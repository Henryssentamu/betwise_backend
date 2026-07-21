"""
Run once per environment (and again whenever PESAPAL_IPN_URL changes):

    python manage.py register_pesapal_ipn

Prints the ipn_id — copy it into your .env as PESAPAL_IPN_ID so checkout
requests can reference it.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from recommendations.pesapal import PesapalClient


class Command(BaseCommand):
    help = "Registers the IPN callback URL with Pesapal and prints the ipn_id"

    def handle(self, *args, **options):
        client = PesapalClient()
        ipn_id = client.register_ipn(settings.PESAPAL_IPN_URL)
        self.stdout.write(self.style.SUCCESS(f"Registered IPN. ipn_id = {ipn_id}"))
        self.stdout.write("Add this to your .env as PESAPAL_IPN_ID and restart the server.")
