import uuid
import logging
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Merchant, Payout, IdempotencyRecord, Transaction
from .serializers import (
    MerchantDashboardSerializer,
    CreatePayoutSerializer,
    PayoutSerializer,
)

logger = logging.getLogger(__name__)


@api_view(['GET'])
def merchant_dashboard(request, merchant_id):
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response({'error': 'Merchant not found'}, status=404)

    serializer = MerchantDashboardSerializer(merchant)
    return Response(serializer.data)


@api_view(['GET'])
def list_merchants(request):
    merchants = Merchant.objects.all()
    data = [{'id': str(m.id), 'name': m.name, 'email': m.email} for m in merchants]
    return Response(data)


@api_view(['POST'])
def create_payout(request, merchant_id):
    """
    POST /api/v1/merchants/{merchant_id}/payouts
    Header: Idempotency-Key: <uuid>

    Critical sections:
    1. Idempotency check (return existing if key seen)
    2. SELECT FOR UPDATE to lock merchant's transactions
    3. Balance check and debit atomically
    """
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response({'error': 'Merchant not found'}, status=404)

    # --- Idempotency Key Validation ---
    raw_key = request.headers.get('Idempotency-Key')
    if not raw_key:
        return Response({'error': 'Idempotency-Key header is required'}, status=400)

    try:
        idempotency_key = uuid.UUID(raw_key)
    except ValueError:
        return Response({'error': 'Idempotency-Key must be a valid UUID'}, status=400)

    # Check if we've seen this key before
    try:
        existing = IdempotencyRecord.objects.select_related('payout').get(
            merchant=merchant, key=idempotency_key
        )
        if existing.is_expired():
            existing.delete()
            # Fall through to create new
        else:
            # Return the same response as the first call
            return Response(
                PayoutSerializer(existing.payout).data,
                status=status.HTTP_200_OK,
                headers={'X-Idempotent-Replay': 'true'}
            )
    except IdempotencyRecord.DoesNotExist:
        pass  # First time seeing this key

    # --- Validate request body ---
    serializer = CreatePayoutSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    amount_paise = serializer.validated_data['amount_paise']
    bank_account_id = serializer.validated_data['bank_account_id']

    # --- Atomic: Lock → Check balance → Create payout → Hold funds ---
    try:
        with transaction.atomic():
            # SELECT FOR UPDATE locks ALL of this merchant's transaction rows.
            # No other concurrent request can read or modify them until this
            # transaction commits. This is the database primitive that prevents
            # two simultaneous 60-rupee requests from both seeing 100-rupee balance.
            #
            # We use .select_for_update() on transactions queryset and then
            # compute balance inside the same atomic block.
            txns = merchant.transactions.select_for_update().all()

            # Compute balance at DB level inside the lock
            from django.db.models import Sum, Q
            agg = txns.aggregate(
                credits=Sum('amount_paise', filter=Q(txn_type='credit')),
                debits=Sum('amount_paise', filter=Q(txn_type='debit')),
            )
            total_balance = (agg['credits'] or 0) - (agg['debits'] or 0)

            # Also account for already-held funds in pending/processing payouts
            held = merchant.payouts.filter(
                status__in=['pending', 'processing']
            ).select_for_update().aggregate(
                total=Sum('amount_paise')
            )['total'] or 0

            available = total_balance - held

            if available < amount_paise:
                return Response(
                    {
                        'error': 'Insufficient balance',
                        'available_paise': available,
                        'requested_paise': amount_paise,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            # Create the payout (funds are now "held" by virtue of pending status)
            payout = Payout.objects.create(
                merchant=merchant,
                amount_paise=amount_paise,
                bank_account_id=bank_account_id,
                status='pending',
                idempotency_key=idempotency_key,
            )

            # Record idempotency key
            IdempotencyRecord.objects.create(
                merchant=merchant,
                key=idempotency_key,
                payout=payout,
                expires_at=timezone.now() + timezone.timedelta(hours=24),
            )

        # Enqueue background processing (outside atomic to avoid holding lock during task dispatch)
        from .tasks import process_payout
        process_payout.apply_async(args=[str(payout.id)], countdown=2)

        return Response(PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)

    except IntegrityError:
        # Race condition: another request created this idempotency key between
        # our check and our insert. Fetch and return it.
        try:
            existing = IdempotencyRecord.objects.select_related('payout').get(
                merchant=merchant, key=idempotency_key
            )
            return Response(
                PayoutSerializer(existing.payout).data,
                status=status.HTTP_200_OK,
                headers={'X-Idempotent-Replay': 'true'}
            )
        except IdempotencyRecord.DoesNotExist:
            logger.exception("IntegrityError but no idempotency record found")
            return Response({'error': 'Conflict, please retry'}, status=409)


@api_view(['GET'])
def payout_detail(request, merchant_id, payout_id):
    try:
        payout = Payout.objects.get(id=payout_id, merchant_id=merchant_id)
    except Payout.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    return Response(PayoutSerializer(payout).data)


@api_view(['GET'])
def list_payouts(request, merchant_id):
    payouts = Payout.objects.filter(merchant_id=merchant_id).order_by('-created_at')
    return Response(PayoutSerializer(payouts, many=True).data)
