from typing import List, Optional

from chargeback.adapters.base import BaseCRMAdapter
from chargeback.utils.datetime_helpers import safe_float
from chargeback.utils.hashing import deterministic_seed


class MockCRMAdapter(BaseCRMAdapter):
    """Mock CRM adapter. Wraps the original CRMOrderAPI logic."""

    def fetch_order(self, dispute: dict, order_data: dict) -> dict:
        order_id = dispute.get("order_id", "")
        seed = deterministic_seed(order_id) if order_id else 0
        customer_email = order_data.get("customer_email", "")

        return {
            "order_id": order_id,
            "transaction_id": dispute.get("transaction_id", ""),
            "customer_email": customer_email,
            "customer_phone": f"+1-{200 + seed % 700:03d}-{100 + seed % 900:03d}-{1000 + seed % 9000:04d}",
            "product_purchased": order_data.get("product_name", ""),
            "transaction_amount": round(safe_float(order_data.get("order_amount")), 2),
            "date_of_purchase": order_data.get("order_date", ""),
            "quantity": order_data.get("quantity", "1"),
            "delivery_status": order_data.get("fulfillment_status", "Unknown"),
            "tracking_number": order_data.get("tracking_number", ""),
            "ip_address": order_data.get("customer_ip", ""),
            "order_confirmation_status": "Confirmed" if order_data else "Not Found",
            "order_confirmation_email_status": f"Sent to {customer_email}" if customer_email else "No email record",
        }

    def search_orders(self, transaction_id: str) -> List[dict]:
        return []

    def get_communication_history(self, customer_email: str) -> List[dict]:
        return []
