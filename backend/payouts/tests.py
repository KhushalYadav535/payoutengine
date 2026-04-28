import uuid
import threading
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient
from .models import Merchant, Transaction, Payout


def create_merchant_with_balance(name, balance_paise):
    merchant = Merchant.objects.create(name=name, email=f"{name}@test.com")
    Transaction.objects.create(
        merchant=merchant,
        amount_paise=balance_paise,
        txn_type='credit',
        description='Test seed credit',
    )
    return merchant


class ConcurrencyTest(TransactionTestCase):
    """
    Test that two simultaneous 60-rupee requests against a 100-rupee balance
    results in exactly one success and one failure.

    Uses TransactionTestCase (not TestCase) because we need real DB transactions
    to test SELECT FOR UPDATE behavior — TestCase wraps everything in a single
    transaction which defeats the locking.
    """

    def test_concurrent_overdraw_rejected(self):
        merchant = create_merchant_with_balance('concurrent_merchant', 10_000)  # 100 rupees
        client = APIClient()
        url = f'/api/v1/merchants/{merchant.id}/payouts/'

        results = []
        errors = []

        def make_request(idempotency_key):
            try:
                response = client.post(
                    url,
                    data={'amount_paise': 6_000, 'bank_account_id': 'HDFC001'},
                    format='json',
                    HTTP_IDEMPOTENCY_KEY=str(idempotency_key),
                )
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))

        key1 = uuid.uuid4()
        key2 = uuid.uuid4()

        t1 = threading.Thread(target=make_request, args=(key1,))
        t2 = threading.Thread(target=make_request, args=(key2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0, f"Unexpected errors: {errors}")
        self.assertEqual(len(results), 2)

        success_count = results.count(201)
        failure_count = results.count(422)

        self.assertEqual(success_count, 1, f"Expected exactly 1 success, got: {results}")
        self.assertEqual(failure_count, 1, f"Expected exactly 1 rejection, got: {results}")

        # Verify balance integrity: only one payout should exist
        pending_payouts = Payout.objects.filter(merchant=merchant, status='pending').count()
        self.assertEqual(pending_payouts, 1)

    def test_balance_invariant_holds(self):
        """credits - debits must always equal balance."""
        merchant = create_merchant_with_balance('invariant_merchant', 50_000)

        # Add some debits
        Transaction.objects.create(
            merchant=merchant,
            amount_paise=10_000,
            txn_type='debit',
            description='Test debit',
        )

        balance = merchant.get_balance()
        self.assertEqual(balance, 40_000)


class IdempotencyTest(TestCase):
    """
    Test that the same Idempotency-Key returns the same response.
    """

    def setUp(self):
        self.merchant = create_merchant_with_balance('idem_merchant', 100_000)
        self.client = APIClient()
        self.url = f'/api/v1/merchants/{self.merchant.id}/payouts/'
        self.idem_key = str(uuid.uuid4())

    def test_same_key_returns_same_payout(self):
        data = {'amount_paise': 5_000, 'bank_account_id': 'ICICI001'}

        response1 = self.client.post(
            self.url, data=data, format='json',
            HTTP_IDEMPOTENCY_KEY=self.idem_key
        )
        self.assertEqual(response1.status_code, 201)
        payout_id_1 = response1.data['id']

        # Second request with same key
        response2 = self.client.post(
            self.url, data=data, format='json',
            HTTP_IDEMPOTENCY_KEY=self.idem_key
        )
        self.assertEqual(response2.status_code, 200)
        payout_id_2 = response2.data['id']

        # Must be the same payout
        self.assertEqual(payout_id_1, payout_id_2)
        self.assertEqual(response2.headers.get('X-Idempotent-Replay'), 'true')

        # Only one payout should exist in DB
        count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(count, 1)

    def test_missing_idempotency_key_rejected(self):
        response = self.client.post(
            self.url,
            data={'amount_paise': 5_000, 'bank_account_id': 'ICICI001'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_different_keys_create_different_payouts(self):
        data = {'amount_paise': 5_000, 'bank_account_id': 'SBI001'}

        r1 = self.client.post(self.url, data=data, format='json',
                              HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        r2 = self.client.post(self.url, data=data, format='json',
                              HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertNotEqual(r1.data['id'], r2.data['id'])


class StateMachineTest(TestCase):

    def setUp(self):
        self.merchant = create_merchant_with_balance('sm_merchant', 100_000)

    def _make_payout(self, status='pending'):
        return Payout.objects.create(
            merchant=self.merchant,
            amount_paise=5_000,
            bank_account_id='TEST001',
            status=status,
            idempotency_key=uuid.uuid4(),
        )

    def test_completed_to_pending_blocked(self):
        payout = self._make_payout('completed')
        with self.assertRaises(ValueError):
            payout.transition_to('pending')

    def test_failed_to_completed_blocked(self):
        payout = self._make_payout('failed')
        with self.assertRaises(ValueError):
            payout.transition_to('completed')

    def test_legal_transitions_work(self):
        payout = self._make_payout('pending')
        payout.transition_to('processing')
        self.assertEqual(payout.status, 'processing')
        payout.transition_to('completed')
        self.assertEqual(payout.status, 'completed')
