"""
Seed script: python manage.py seed_merchants

Creates 3 merchants with varied credit histories.
Run once after migrations.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from payouts.models import Merchant, Transaction
import random


MERCHANTS = [
    {
        'name': 'Arjun Sharma Design Studio',
        'email': 'arjun@designstudio.in',
        'credits': [
            (120_000, 'Client payment - Acme Corp USA'),
            (85_000, 'Client payment - TechStart Inc'),
            (200_000, 'Client payment - GlobalBrand LLC'),
        ],
    },
    {
        'name': 'Priya Digital Marketing',
        'email': 'priya@pdm.in',
        'credits': [
            (300_000, 'Campaign fee - NovaCo'),
            (150_000, 'Monthly retainer - StartupXYZ'),
        ],
    },
    {
        'name': 'CodeCraft Solutions',
        'email': 'hello@codecraft.in',
        'credits': [
            (500_000, 'Project milestone 1 - FinTech client'),
            (250_000, 'Project milestone 2 - FinTech client'),
            (100_000, 'Maintenance contract Q1'),
            (75_000, 'Consulting - DevOps setup'),
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed database with test merchants and credit history'

    def handle(self, *args, **options):
        with transaction.atomic():
            for m_data in MERCHANTS:
                merchant, created = Merchant.objects.get_or_create(
                    email=m_data['email'],
                    defaults={'name': m_data['name']}
                )
                if created:
                    self.stdout.write(f"Created merchant: {merchant.name}")
                    for amount, desc in m_data['credits']:
                        Transaction.objects.create(
                            merchant=merchant,
                            amount_paise=amount,
                            txn_type='credit',
                            description=desc,
                        )
                    self.stdout.write(
                        f"  Balance: ₹{merchant.get_balance() / 100:.2f}"
                    )
                else:
                    self.stdout.write(f"Merchant already exists: {merchant.name}")

        self.stdout.write(self.style.SUCCESS('\nSeeding complete!'))
