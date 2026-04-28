import uuid
from django.db import models
from django.db import transaction
from django.utils import timezone


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_balance(self):
        """
        Balance = SUM of credits - SUM of debits
        Done at DB level with aggregation — never Python arithmetic on fetched rows.
        """
        from django.db.models import Sum, Q
        result = self.transactions.aggregate(
            credits=Sum('amount_paise', filter=Q(txn_type='credit')),
            debits=Sum('amount_paise', filter=Q(txn_type='debit')),
        )
        credits = result['credits'] or 0
        debits = result['debits'] or 0
        return credits - debits

    def get_held_balance(self):
        """Funds locked in pending/processing payouts."""
        from django.db.models import Sum, Q
        result = self.payouts.filter(
            status__in=['pending', 'processing']
        ).aggregate(total=Sum('amount_paise'))
        return result['total'] or 0

    def get_available_balance(self):
        return self.get_balance() - self.get_held_balance()

    def __str__(self):
        return self.name


class Transaction(models.Model):
    TXN_TYPES = [('credit', 'Credit'), ('debit', 'Debit')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name='transactions')
    amount_paise = models.BigIntegerField()  # Always paise, always integer
    txn_type = models.CharField(max_length=10, choices=TXN_TYPES)
    description = models.CharField(max_length=500, blank=True)
    payout = models.ForeignKey('Payout', null=True, blank=True, on_delete=models.SET_NULL, related_name='txns')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.txn_type} {self.amount_paise} paise for {self.merchant.name}"


class Payout(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    # Legal transitions only
    VALID_TRANSITIONS = {
        'pending': ['processing'],
        'processing': ['completed', 'failed'],
        'completed': [],   # Terminal
        'failed': [],      # Terminal
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name='payouts')
    amount_paise = models.BigIntegerField()
    bank_account_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    idempotency_key = models.UUIDField()
    attempt_count = models.IntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One idempotency key per merchant
        unique_together = [('merchant', 'idempotency_key')]
        ordering = ['-created_at']

    def transition_to(self, new_status):
        """
        Enforce state machine. Raises ValueError on illegal transitions.
        This is the single place where bad transitions are blocked.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {self.status} → {new_status}. "
                f"Allowed from {self.status}: {allowed}"
            )
        self.status = new_status

    def __str__(self):
        return f"Payout {self.id} | {self.status} | {self.amount_paise} paise"


class IdempotencyRecord(models.Model):
    """
    Stores idempotency keys with the response so second call gets same response.
    Expires after 24 hours.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE)
    key = models.UUIDField()
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = [('merchant', 'key')]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=24)
        super().save(*args, **kwargs)
