"""
Thin client around Pesapal API v3.

Flow used by this platform:
  1. get_access_token()          — auth, cached in-process per request cycle
  2. register_ipn()               — one-time setup (see register_ipn management command)
  3. submit_order()                — called at checkout, returns a redirect_url
  4. get_transaction_status()      — called from the IPN callback view to confirm payment
"""
import requests
from django.conf import settings


class PesapalError(Exception):
    pass


class PesapalClient:
    def __init__(self):
        self.base_url = settings.PESAPAL_BASE_URL
        self.consumer_key = settings.PESAPAL_CONSUMER_KEY
        self.consumer_secret = settings.PESAPAL_CONSUMER_SECRET

    def get_access_token(self) -> str:
        resp = requests.post(
            f"{self.base_url}/api/Auth/RequestToken",
            json={
                "consumer_key": self.consumer_key,
                "consumer_secret": self.consumer_secret,
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if not token:
            raise PesapalError(f"No token in Pesapal response: {data}")
        return token

    def register_ipn(self, ipn_url: str, notification_type: str = "GET") -> str:
        """Returns the ipn_id to store and reuse in order submissions."""
        token = self.get_access_token()
        resp = requests.post(
            f"{self.base_url}/api/URLSetup/RegisterIPN",
            json={"url": ipn_url, "ipn_notification_type": notification_type},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["ipn_id"]

    def submit_order(
        self,
        *,
        merchant_reference: str,
        amount: float,
        description: str,
        callback_url: str,
        ipn_id: str,
        email: str,
        phone_number: str = "",
        first_name: str = "",
        last_name: str = "",
    ) -> dict:
        """
        Returns Pesapal's response containing `order_tracking_id` and
        `redirect_url` — redirect the user's browser to redirect_url to
        complete payment.
        """
        token = self.get_access_token()
        payload = {
            "id": merchant_reference,
            "currency": "UGX",
            "amount": amount,
            "description": description,
            "callback_url": callback_url,
            "notification_id": ipn_id,
            "billing_address": {
                "email_address": email,
                "phone_number": phone_number,
                "first_name": first_name,
                "last_name": last_name,
                "country_code": "UG",
            },
        }
        resp = requests.post(
            f"{self.base_url}/api/Transactions/SubmitOrderRequest",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def get_transaction_status(self, order_tracking_id: str) -> dict:
        token = self.get_access_token()
        resp = requests.get(
            f"{self.base_url}/api/Transactions/GetTransactionStatus",
            params={"orderTrackingId": order_tracking_id},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


# Pesapal status codes → our internal PesapalTransaction.status values
PESAPAL_STATUS_MAP = {
    "COMPLETED": "completed",
    "FAILED": "failed",
    "INVALID": "failed",
    "REVERSED": "cancelled",
    "PENDING": "pending",
}
