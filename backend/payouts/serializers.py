from rest_framework import serializers
from .models import Merchant, Transaction, Payout


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ['id', 'amount_paise', 'txn_type', 'description', 'created_at']


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ['id', 'amount_paise', 'bank_account_id', 'status',
                  'idempotency_key', 'attempt_count', 'created_at', 'updated_at']


class MerchantDashboardSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()
    held_balance = serializers.SerializerMethodField()
    total_balance = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()
    recent_payouts = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = ['id', 'name', 'email', 'available_balance', 'held_balance',
                  'total_balance', 'recent_transactions', 'recent_payouts']

    def get_total_balance(self, obj):
        return obj.get_balance()

    def get_available_balance(self, obj):
        return obj.get_available_balance()

    def get_held_balance(self, obj):
        return obj.get_held_balance()

    def get_recent_transactions(self, obj):
        txns = obj.transactions.all()[:20]
        return TransactionSerializer(txns, many=True).data

    def get_recent_payouts(self, obj):
        payouts = obj.payouts.all()[:20]
        return PayoutSerializer(payouts, many=True).data


class CreatePayoutSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.CharField(max_length=255)
