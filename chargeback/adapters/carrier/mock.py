from typing import Optional

from chargeback.adapters.base import BaseCarrierAdapter


class MockCarrierAdapter(BaseCarrierAdapter):
    """Mock carrier adapter. Wraps the original PODTrackingAPI logic."""

    STATUS_MAP = {
        "Delivered": "Delivered",
        "Shipped": "Pending Delivery",
        "Processing": "Pending Delivery",
        "Cancelled": "Returned",
        "Returned": "Returned",
    }

    def track_shipment(self, tracking_number: str, carrier: str = "",
                       order_data: dict = None) -> dict:
        if order_data is None:
            order_data = {}

        raw_status = order_data.get("fulfillment_status", "")
        normalized_status = self.STATUS_MAP.get(raw_status, "Pending Delivery")
        tracking_number = order_data.get("tracking_number", tracking_number or "")
        carrier = order_data.get("shipping_carrier", carrier or "")
        delivery_date = order_data.get("delivery_date", "")

        include_attachment = normalized_status == "Delivered" and bool(tracking_number)
        if include_attachment:
            reason = "Delivered status matched. POD attachment included."
        elif normalized_status == "Pending Delivery":
            reason = "Pending delivery. POD attachment excluded per rules."
        else:
            reason = "Shipment returned/cancelled. POD attachment excluded per rules."

        return {
            "tracking_number": tracking_number,
            "carrier": carrier,
            "delivery_status": normalized_status,
            "delivery_date": delivery_date,
            "pod_attachment": {
                "status": "included" if include_attachment else "excluded",
                "reason": reason,
                "document": f"{carrier} POD - {tracking_number}.pdf" if include_attachment else "",
            },
        }

    def download_pod(self, tracking_number: str) -> Optional[bytes]:
        return None

    def get_signature_image(self, tracking_number: str) -> Optional[bytes]:
        return None
