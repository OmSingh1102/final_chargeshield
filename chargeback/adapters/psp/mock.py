import hashlib
from datetime import datetime, timedelta
from typing import List, Optional

from chargeback.adapters.base import BasePSPAdapter
from chargeback.utils.datetime_helpers import safe_float, parse_any_datetime, fmt_datetime


class MockPSPAdapter(BasePSPAdapter):
    """Mock PSP adapter backed by CSV data. Wraps the original PSPDisputeAPI logic."""

    POLL_INTERVAL_SECONDS = 30

    def __init__(self, loader_class=None):
        self._last_sync_utc = None
        self._loader_class = loader_class

    def _get_loader(self):
        if self._loader_class is None:
            from chargeback.data.loader import ChargebackCaseLoader
            self._loader_class = ChargebackCaseLoader
        return self._loader_class

    def pull_disputes(self, limit: Optional[int] = None) -> List[dict]:
        rows = self._get_loader().load_chargebacks()
        disputes = []

        for row in rows:
            filed_dt = parse_any_datetime(row.get("dispute_date", ""))
            response_dt = filed_dt + timedelta(days=20) if filed_dt else None
            disputes.append({
                "chargeback_case_id": row.get("dispute_ref", ""),
                "transaction_id": row.get("payment_ref", ""),
                "transaction_date": row.get("transaction_date", ""),
                "transaction_amount": round(safe_float(row.get("disputed_amount")), 2),
                "card_network": row.get("card_scheme", ""),
                "last4_card_number": row.get("card_last_four", ""),
                "reason_code": row.get("reason_code", ""),
                "reason_description": row.get("reason_description", ""),
                "dispute_filed_date": row.get("dispute_date", ""),
                "dispute_response_date": fmt_datetime(response_dt) if response_dt else "",
                "order_id": row.get("order_id", ""),
                "processor": row.get("processor", ""),
            })

        disputes.sort(
            key=lambda d: parse_any_datetime(d.get("dispute_filed_date")) or datetime.min,
            reverse=True,
        )

        self._last_sync_utc = fmt_datetime(datetime.utcnow())
        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 0
            if limit > 0:
                disputes = disputes[:limit]
        return disputes

    def get_dispute_detail(self, chargeback_case_id: str) -> Optional[dict]:
        disputes = self.pull_disputes()
        for d in disputes:
            if d["chargeback_case_id"] == chargeback_case_id:
                return d
        return None

    def submit_evidence(self, chargeback_case_id: str, evidence_packet: dict) -> dict:
        return {
            "status": "submitted",
            "case_id": chargeback_case_id,
            "message": "Evidence submitted (mock mode)",
            "submitted_at": fmt_datetime(datetime.utcnow()),
        }

    def get_sync_status(self) -> dict:
        if not self._last_sync_utc:
            self._last_sync_utc = fmt_datetime(datetime.utcnow())
        return {
            "mode": "real-time polling",
            "poll_interval_seconds": self.POLL_INTERVAL_SECONDS,
            "last_sync_utc": self._last_sync_utc,
        }
