from abc import ABC, abstractmethod
from typing import List, Optional


class BasePSPAdapter(ABC):
    """Abstract interface for Payment Service Provider dispute ingestion."""

    @abstractmethod
    def pull_disputes(self, limit: Optional[int] = None) -> List[dict]:
        """Poll for new disputes from the PSP.
        Returns list of dispute dicts with standard fields:
        chargeback_case_id, transaction_id, transaction_date, transaction_amount,
        card_network, last4_card_number, reason_code, reason_description,
        dispute_filed_date, dispute_response_date, order_id, processor."""
        ...

    @abstractmethod
    def get_dispute_detail(self, chargeback_case_id: str) -> Optional[dict]:
        """Fetch full detail for a single dispute by its case ID."""
        ...

    @abstractmethod
    def submit_evidence(self, chargeback_case_id: str, evidence_packet: dict) -> dict:
        """Submit defense evidence packet back to the PSP.
        Returns submission status dict."""
        ...

    @abstractmethod
    def get_sync_status(self) -> dict:
        """Return current sync state: {mode, poll_interval_seconds, last_sync_utc}."""
        ...

    def supports_webhooks(self) -> bool:
        """Whether this provider supports webhook-based real-time notifications."""
        return False

    def register_webhook(self, callback_url: str) -> dict:
        """Register a webhook endpoint with the provider. Optional override."""
        raise NotImplementedError("This provider does not support webhooks")


class BaseGatewayAdapter(ABC):
    """Abstract interface for payment gateway transaction evidence retrieval."""

    @abstractmethod
    def fetch_transaction_evidence(self, dispute: dict, order_data: dict) -> dict:
        """Fetch gateway evidence for a dispute. Performs match validation
        (date, amount, network, last4, transaction ID) and returns auth details.
        Must return: status, match_flags, ip_address, authorization_code,
        avs_status, cvv_status, three_ds_status, receipt_snip, etc."""
        ...

    @abstractmethod
    def get_transaction_copy(self, transaction_id: str) -> Optional[bytes]:
        """Download transaction receipt/screenshot as bytes (for PDF inclusion).
        Returns None if not available."""
        ...

    def get_authorization_log(self, transaction_id: str) -> Optional[dict]:
        """Retrieve full authorization log. Optional override."""
        return None


class BaseCRMAdapter(ABC):
    """Abstract interface for CRM/order management system integration."""

    @abstractmethod
    def fetch_order(self, dispute: dict, order_data: dict) -> dict:
        """Look up order by transaction_id or order_id.
        Must return: order_id, customer_email, customer_phone, product_purchased,
        transaction_amount, date_of_purchase, quantity, delivery_status,
        tracking_number, ip_address, order_confirmation_status, etc."""
        ...

    @abstractmethod
    def search_orders(self, transaction_id: str) -> List[dict]:
        """Search for orders matching a transaction ID."""
        ...

    def get_communication_history(self, customer_email: str) -> List[dict]:
        """Retrieve customer communication logs. Optional override."""
        return []


class BaseCarrierAdapter(ABC):
    """Abstract interface for carrier tracking and proof of delivery."""

    @abstractmethod
    def track_shipment(self, tracking_number: str, carrier: str = "",
                       order_data: dict = None) -> dict:
        """Track a shipment and return delivery status.
        Must return: tracking_number, carrier, delivery_status,
        delivery_date, pod_attachment (status, reason, document).
        order_data is provided for mock adapter compatibility."""
        ...

    @abstractmethod
    def download_pod(self, tracking_number: str) -> Optional[bytes]:
        """Download proof of delivery document as bytes.
        Returns None if POD is not available."""
        ...

    def get_signature_image(self, tracking_number: str) -> Optional[bytes]:
        """Download delivery signature image. Optional override."""
        return None


class BaseRepositoryAdapter(ABC):
    """Abstract interface for document repository (templates, policies)."""

    @abstractmethod
    def get_cover_template(self, reason_code: str) -> str:
        """Retrieve cover letter template for a reason code."""
        ...

    @abstractmethod
    def resolve_documents(self, reason_code: str, required_docs: list,
                          gateway_result: dict, crm_result: dict,
                          pod_result: dict) -> list:
        """Build document manifest based on available evidence.
        Returns list of dicts: {document, source, status, notes, sample_reference}."""
        ...

    @abstractmethod
    def get_policy_documents(self) -> list:
        """Return list of available policy document names."""
        ...
