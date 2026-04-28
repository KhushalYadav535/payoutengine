import random
import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
PROCESSING_TIMEOUT_SECONDS = 30


@shared_task(bind=True, max_retries=MAX_ATTEMPTS)
def process_payout(self, payout_id: str):
    """
    Background worker that simulates bank settlement.
    Outcomes: 70% success, 20% failure, 10% hang (timeout handled by retry_stuck_payouts)
    """
    from .models import Payout, Transaction

    try:
        with transaction.atomic():
            # Lock this payout row for update
            try:
                payout = Payout.objects.select_for_update(nowait=True).get(id=payout_id)
            except Payout.DoesNotExist:
                logger.error(f"Payout {payout_id} not found")
                return

            # Only process pending payouts
            if payout.status != 'pending':
                logger.info(f"Payout {payout_id} is {payout.status}, skipping")
                return

            # Transition to processing
            payout.transition_to('processing')
            payout.attempt_count += 1
            payout.processing_started_at = timezone.now()
            payout.save()

    except Exception as e:
        logger.exception(f"Failed to transition payout {payout_id} to processing: {e}")
        return

    # Simulate bank API call (outside the lock, this takes time)
    outcome = _simulate_bank_settlement()

    if outcome == 'hang':
        # Don't do anything — retry_stuck_payouts will handle this
        logger.info(f"Payout {payout_id} is hanging (simulated)")
        return

    # Apply outcome
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            return

        if payout.status != 'processing':
            logger.warning(f"Payout {payout_id} status changed unexpectedly to {payout.status}")
            return

        if outcome == 'success':
            _complete_payout(payout)
        elif outcome == 'failure':
            _fail_payout(payout)


def _simulate_bank_settlement():
    roll = random.random()
    if roll < 0.70:
        return 'success'
    elif roll < 0.90:
        return 'failure'
    else:
        return 'hang'


def _complete_payout(payout):
    """Mark payout completed. Funds were already held (deducted conceptually via pending status)."""
    from .models import Transaction

    payout.transition_to('completed')
    payout.save()

    # Record the debit transaction to make the ledger accurate
    Transaction.objects.create(
        merchant=payout.merchant,
        amount_paise=payout.amount_paise,
        txn_type='debit',
        description=f'Payout to bank account {payout.bank_account_id}',
        payout=payout,
    )
    logger.info(f"Payout {payout.id} completed successfully")


def _fail_payout(payout):
    """
    Mark payout failed. Funds return to merchant balance automatically
    because we never created a debit transaction — held balance was just
    the pending payout existing. Now that it's failed, get_held_balance()
    won't count it, so available balance returns to normal.

    This is atomic with the state transition (same transaction).
    """
    payout.transition_to('failed')
    payout.save()
    logger.info(f"Payout {payout.id} failed. Funds returned to merchant balance.")


@shared_task
def retry_stuck_payouts():
    """
    Periodic task: find payouts stuck in 'processing' for > 30 seconds.
    Retry up to MAX_ATTEMPTS times, then fail them.
    """
    from .models import Payout

    cutoff = timezone.now() - timezone.timedelta(seconds=PROCESSING_TIMEOUT_SECONDS)
    stuck = Payout.objects.filter(
        status='processing',
        processing_started_at__lt=cutoff,
    )

    for payout in stuck:
        logger.info(f"Found stuck payout {payout.id}, attempt {payout.attempt_count}")

        with transaction.atomic():
            payout_locked = Payout.objects.select_for_update().get(id=payout.id)

            if payout_locked.status != 'processing':
                continue  # Changed since we queried

            if payout_locked.attempt_count >= MAX_ATTEMPTS:
                logger.info(f"Payout {payout.id} exceeded max attempts, failing")
                _fail_payout(payout_locked)
            else:
                # Reset to pending for retry
                payout_locked.status = 'pending'
                payout_locked.processing_started_at = None
                payout_locked.save()
                # Re-enqueue with exponential backoff
                delay = 2 ** payout_locked.attempt_count  # 2, 4, 8 seconds
                process_payout.apply_async(args=[str(payout_locked.id)], countdown=delay)
