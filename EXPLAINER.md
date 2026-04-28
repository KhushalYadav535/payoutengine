# EXPLAINER.md

This document explains the critical engineering decisions in the Playto Payout Engine.

---

## 1. The Ledger

**Balance calculation query (from `models.py`):**

```python
def get_balance(self):
    from django.db.models import Sum, Q
    result = self.transactions.aggregate(
        credits=Sum('amount_paise', filter=Q(txn_type='credit')),
        debits=Sum('amount_paise', filter=Q(txn_type='debit')),
    )
    credits = result['credits'] or 0
    debits = result['debits'] or 0
    return credits - debits
```

**SQL generated:**
```sql
SELECT
  SUM(amount_paise) FILTER (WHERE txn_type = 'credit') AS credits,
  SUM(amount_paise) FILTER (WHERE txn_type = 'debit') AS debits
FROM payouts_transaction
WHERE merchant_id = '<uuid>';
```

**Why this model:**

Credits and debits are stored as separate rows in a `Transaction` table rather than as a single mutable balance column. This is a double-entry bookkeeping approach — it gives us a complete, immutable audit trail. Every rupee that entered or left is a record in the ledger.

The alternative (a single `balance` column on Merchant) creates concurrency problems: two processes read balance=100, both see they can deduct 60, both write 40. You end up with -20. Our immutable ledger + SELECT FOR UPDATE (see section 2) avoids this.

All amounts are `BigIntegerField` in paise. No floats, no decimals. `0.1 + 0.2 = 0.30000000000000004` in floating point — unacceptable for money. Integer paise arithmetic is exact.

The available balance accounts for held funds:
```python
def get_available_balance(self):
    return self.get_balance() - self.get_held_balance()

def get_held_balance(self):
    result = self.payouts.filter(
        status__in=['pending', 'processing']
    ).aggregate(total=Sum('amount_paise'))
    return result['total'] or 0
```

Funds are "held" simply by virtue of a pending payout existing. When a payout completes, we create a debit transaction. When a payout fails, no debit is created — the held balance disappears when the payout leaves pending/processing, and the ledger balance is unchanged.

---

## 2. The Lock

**Exact code that prevents concurrent overdraw (`views.py`):**

```python
with transaction.atomic():
    # SELECT FOR UPDATE — the database primitive that prevents the race
    txns = merchant.transactions.select_for_update().all()

    # Balance computed inside the same lock
    from django.db.models import Sum, Q
    agg = txns.aggregate(
        credits=Sum('amount_paise', filter=Q(txn_type='credit')),
        debits=Sum('amount_paise', filter=Q(txn_type='debit')),
    )
    total_balance = (agg['credits'] or 0) - (agg['debits'] or 0)

    held = merchant.payouts.filter(
        status__in=['pending', 'processing']
    ).select_for_update().aggregate(
        total=Sum('amount_paise')
    )['total'] or 0

    available = total_balance - held

    if available < amount_paise:
        return Response({'error': 'Insufficient balance', ...}, status=422)

    # Create payout inside the same transaction
    payout = Payout.objects.create(...)
```

**Database primitive: `SELECT FOR UPDATE`**

PostgreSQL's `SELECT FOR UPDATE` acquires row-level exclusive locks on all matching rows. Any other transaction attempting to `SELECT FOR UPDATE` on the same rows will block until the first transaction commits or rolls back.

Scenario — two simultaneous 60-rupee requests against 100-rupee balance:

1. Request A acquires `SELECT FOR UPDATE` on merchant's transaction rows
2. Request B attempts `SELECT FOR UPDATE` — **blocks at the database level**
3. Request A computes available=10000, deducts 6000, creates payout, commits
4. Request B unblocks, re-computes available=4000 (updated), rejects with 422

This is database-level serialization, not Python-level locking. Python-level (`threading.Lock`) would fail across multiple Gunicorn workers or separate containers. The DB lock works regardless of how many processes or machines are running.

We also lock pending/processing payouts with `select_for_update()` to prevent stale reads of the held amount.

---

## 3. The Idempotency

**How the system knows it has seen a key before:**

We store idempotency keys in an `IdempotencyRecord` table with a `unique_together` constraint on `(merchant, key)`. On every request, we query this table before creating a payout:

```python
try:
    existing = IdempotencyRecord.objects.select_related('payout').get(
        merchant=merchant, key=idempotency_key
    )
    if existing.is_expired():
        existing.delete()
        # Fall through to create new
    else:
        return Response(
            PayoutSerializer(existing.payout).data,
            status=200,
            headers={'X-Idempotent-Replay': 'true'}
        )
except IdempotencyRecord.DoesNotExist:
    pass
```

**What if the first request is in-flight when the second arrives?**

The `unique_together` constraint on `IdempotencyRecord(merchant, key)` is the safety net. If request A is still inside the `atomic()` block (hasn't committed the IdempotencyRecord yet), request B will:

1. Check the DB, not find the record (A hasn't committed)
2. Proceed to the `atomic()` block itself
3. Try to `INSERT` an IdempotencyRecord with the same key
4. Hit an `IntegrityError` from the unique constraint

We catch this `IntegrityError` explicitly:

```python
except IntegrityError:
    # Race condition: fetch and return the record created by the other request
    existing = IdempotencyRecord.objects.select_related('payout').get(
        merchant=merchant, key=idempotency_key
    )
    return Response(PayoutSerializer(existing.payout).data, status=200,
                    headers={'X-Idempotent-Replay': 'true'})
```

This is the correct pattern: optimistic check → DB constraint as final guarantee → handle the collision gracefully.

Keys are scoped per merchant (`unique_together = [('merchant', 'key')]`), so the same UUID can be used by different merchants without conflict. Keys expire after 24 hours via `expires_at`.

---

## 4. The State Machine

**Where `failed → completed` is blocked (`models.py`):**

```python
VALID_TRANSITIONS = {
    'pending':    ['processing'],
    'processing': ['completed', 'failed'],
    'completed':  [],   # Terminal — no transitions allowed
    'failed':     [],   # Terminal — no transitions allowed
}

def transition_to(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Illegal transition: {self.status} → {new_status}. "
            f"Allowed from {self.status}: {allowed}"
        )
    self.status = new_status
```

`completed` and `failed` map to empty lists — no outgoing transitions. Any call to `payout.transition_to('completed')` on a failed payout will raise `ValueError` before any database write happens.

Every state change in `tasks.py` goes through `transition_to()`, so this check cannot be bypassed. There is no direct `payout.status = 'completed'` anywhere except through this method.

**Fund return on failure is atomic:**

In `_fail_payout()` (called inside `with transaction.atomic()`):
```python
def _fail_payout(payout):
    payout.transition_to('failed')
    payout.save()
    # No debit transaction created — held balance disappears automatically
```

The state change and the implicit fund return (no debit created = balance stays) happen in the same database transaction. There is no window where the payout is failed but the funds are still held.

---

## 5. The AI Audit

**What AI wrote (subtle bug in balance check):**

When I asked Claude to write the concurrent balance check, it initially generated this:

```python
# WRONG — what AI first suggested
merchant.refresh_from_db()
available_balance = merchant.available_balance  # Hypothetical field

if available_balance < amount_paise:
    return insufficient_error()

payout = Payout.objects.create(...)
```

This has a classic TOCTOU (Time-of-Check to Time-of-Use) race condition. Between `refresh_from_db()` and `Payout.objects.create()`, another request can read the same balance, see sufficient funds, and also create a payout. Both would succeed, overdrawing the balance.

**What I caught:**
The check and the write are not atomic. Even if `refresh_from_db()` reads the latest data, there's no lock held — another transaction can do the same read between our check and our create.

**What I replaced it with:**

```python
with transaction.atomic():
    txns = merchant.transactions.select_for_update().all()
    agg = txns.aggregate(...)
    available = (agg['credits'] or 0) - (agg['debits'] or 0) - held

    if available < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=422)

    # Create happens inside the same atomic block, under the same lock
    payout = Payout.objects.create(...)
```

The `SELECT FOR UPDATE` acquires row-level locks before we compute the balance. The lock is held until the transaction commits. No other transaction can read or modify these rows while we're checking and creating. The check and the create are now truly atomic from the database's perspective.

---

## Design Decisions Summary

| Decision | Choice | Reason |
|---|---|---|
| Money storage | BigIntegerField paise | Float imprecision is unacceptable for money |
| Balance computation | DB aggregation inside SELECT FOR UPDATE | Python arithmetic on fetched rows races |
| Concurrency | Row-level locking (SELECT FOR UPDATE) | Works across multiple processes/containers |
| Idempotency | DB table + unique constraint + IntegrityError catch | Handles in-flight race correctly |
| Fund holding | Implicit (pending payout exists) | No risk of fund "escaping" on failure |
| State machine | Whitelist VALID_TRANSITIONS dict | Single source of truth, illegal transitions raise before any DB write |
| Background jobs | Real Celery + Redis | Task spec prohibits fake sync code |
| Retry | Periodic beat task scanning processing > 30s | Decoupled from the original task, exponential backoff |
