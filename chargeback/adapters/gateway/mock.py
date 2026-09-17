from typing import Optional

from chargeback.adapters.base import BaseGatewayAdapter
from chargeback.utils.datetime_helpers import safe_float, parse_any_datetime
from chargeback.utils.hashing import deterministic_seed


class MockGatewayAdapter(BaseGatewayAdapter):
    """Mock gateway adapter. Wraps the original GatewayEvidenceAPI logic."""

    def fetch_transaction_evidence(self, dispute: dict, order_data: dict) -> dict:
        seed_input = f"{dispute.get('chargeback_case_id', '')}:{dispute.get('transaction_id', '')}"
        seed = deterministic_seed(seed_input)

        order_amount = safe_float(order_data.get("order_amount"))
        dispute_amount = safe_float(dispute.get("transaction_amount"))
        order_date = parse_any_datetime(order_data.get("order_date", ""))
        txn_date = parse_any_datetime(dispute.get("transaction_date", ""))
        order_network = order_data.get("payment_method", "").strip().lower()
        dispute_network = dispute.get("card_network", "").strip().lower()

        match_flags = {
            "transaction_date_match": bool(order_date and txn_date and order_date.date() == txn_date.date()),
            "transaction_amount_match": abs(order_amount - dispute_amount) < 0.01,
            "card_network_match": bool(order_network and order_network == dispute_network),
            "card_last4_match": str(order_data.get("card_last_four", "")) == str(dispute.get("last4_card_number", "")),
            "transaction_id_match": bool(dispute.get("transaction_id", "")),
        }

        if not order_data:
            status = "unmatched"
        elif all(match_flags.values()):
            status = "matched"
        elif any(match_flags.values()):
            status = "partial"
        else:
            status = "unmatched"

        avs_pass = order_data.get("avs_cvv_match") == "Pass"
        avs_status = "Address and ZIP match (Y)" if avs_pass else "Address or ZIP mismatch (N)"
        cvv_status = "CVV2 Match" if avs_pass else "CVV2 No Match"

        return {
            "status": status,
            "match_flags": match_flags,
            "ip_address": order_data.get("customer_ip", ""),
            "authorization_code": f"{100000 + seed % 900000}",
            "avs_status": avs_status,
            "cvv_status": cvv_status,
            "three_ds_status": "Authenticated" if seed % 4 else "Attempted/Unavailable",
            "transaction_copy_reference": f"TXCOPY-{dispute.get('transaction_id', 'UNKNOWN')}",
            "previous_undisputed_transaction": f"HIST-{seed % 1000000:06d}",
            "card_expiration_date": f"{(seed % 12) + 1:02d}/{2027 + (seed % 4)}",
            "receipt_snip": {
                "transaction_id": dispute.get("transaction_id", ""),
                "auth_code": f"{100000 + seed % 900000}",
                "avs_status": avs_status,
                "cvv_status": cvv_status,
                "three_ds_status": "Authenticated" if seed % 4 else "Attempted/Unavailable",
                "card_expiration_date": f"{(seed % 12) + 1:02d}/{2027 + (seed % 4)}",
            },
        }

    def get_transaction_copy(self, transaction_id: str) -> Optional[bytes]:
        return None
