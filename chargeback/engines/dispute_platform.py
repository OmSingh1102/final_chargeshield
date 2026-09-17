from chargeback.data.loader import ChargebackCaseLoader
from chargeback.engines.reason_code import ReasonCodeRulebook, REASON_CODES
from chargeback.engines.cover_letter import RepositoryEngine, CoverLetterAIEngine
from chargeback.engines.pdf_converter import PDFPacketConverter
from chargeback.utils.datetime_helpers import safe_float, parse_any_datetime, fmt_datetime

from chargeback.adapters.psp.mock import MockPSPAdapter
from chargeback.adapters.gateway.mock import MockGatewayAdapter
from chargeback.adapters.crm.mock import MockCRMAdapter
from chargeback.adapters.carrier.mock import MockCarrierAdapter

import hashlib
from datetime import datetime, timedelta


class PSPDisputeAPI:
    """Pull disputes from PSP feed (CSV-backed in this demo)."""

    POLL_INTERVAL_SECONDS = 30
    _last_sync_utc = None

    @classmethod
    def pull_disputes(cls, limit=None):
        rows = ChargebackCaseLoader.load_chargebacks()
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

        cls._last_sync_utc = fmt_datetime(datetime.utcnow())
        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 0
            if limit > 0:
                disputes = disputes[:limit]
        return disputes

    @classmethod
    def get_sync_status(cls):
        if not cls._last_sync_utc:
            cls._last_sync_utc = fmt_datetime(datetime.utcnow())
        return {
            "mode": "real-time polling",
            "poll_interval_seconds": cls.POLL_INTERVAL_SECONDS,
            "last_sync_utc": cls._last_sync_utc,
        }


class GatewayEvidenceAPI:
    """Gateway connector: matching logic + auth evidence details."""

    @classmethod
    def fetch(cls, dispute, order_row):
        seed_input = f"{dispute.get('chargeback_case_id', '')}:{dispute.get('transaction_id', '')}"
        seed = int(hashlib.md5(seed_input.encode("utf-8")).hexdigest(), 16)

        order_amount = safe_float(order_row.get("order_amount"))
        dispute_amount = safe_float(dispute.get("transaction_amount"))
        order_date = parse_any_datetime(order_row.get("order_date", ""))
        txn_date = parse_any_datetime(dispute.get("transaction_date", ""))
        order_network = order_row.get("payment_method", "").strip().lower()
        dispute_network = dispute.get("card_network", "").strip().lower()

        match_flags = {
            "transaction_date_match": bool(order_date and txn_date and order_date.date() == txn_date.date()),
            "transaction_amount_match": abs(order_amount - dispute_amount) < 0.01,
            "card_network_match": bool(order_network and order_network == dispute_network),
            "card_last4_match": str(order_row.get("card_last_four", "")) == str(dispute.get("last4_card_number", "")),
            "transaction_id_match": bool(dispute.get("transaction_id", "")),
        }

        if not order_row:
            status = "unmatched"
        elif all(match_flags.values()):
            status = "matched"
        elif any(match_flags.values()):
            status = "partial"
        else:
            status = "unmatched"

        avs_pass = order_row.get("avs_cvv_match") == "Pass"
        avs_status = "Address and ZIP match (Y)" if avs_pass else "Address or ZIP mismatch (N)"
        cvv_status = "CVV2 Match" if avs_pass else "CVV2 No Match"

        return {
            "status": status,
            "match_flags": match_flags,
            "ip_address": order_row.get("customer_ip", ""),
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


class CRMOrderAPI:
    """CRM connector for order confirmation and customer details."""

    @classmethod
    def fetch(cls, dispute, order_row):
        order_id = dispute.get("order_id", "")
        seed = int(hashlib.md5(order_id.encode("utf-8")).hexdigest(), 16) if order_id else 0
        customer_email = order_row.get("customer_email", "")

        return {
            "order_id": order_id,
            "transaction_id": dispute.get("transaction_id", ""),
            "customer_email": customer_email,
            "customer_phone": f"+1-{200 + seed % 700:03d}-{100 + seed % 900:03d}-{1000 + seed % 9000:04d}",
            "product_purchased": order_row.get("product_name", ""),
            "transaction_amount": round(safe_float(order_row.get("order_amount")), 2),
            "date_of_purchase": order_row.get("order_date", ""),
            "quantity": order_row.get("quantity", "1"),
            "delivery_status": order_row.get("fulfillment_status", "Unknown"),
            "tracking_number": order_row.get("tracking_number", ""),
            "ip_address": order_row.get("customer_ip", ""),
            "order_confirmation_status": "Confirmed" if order_row else "Not Found",
            "order_confirmation_email_status": f"Sent to {customer_email}" if customer_email else "No email record",
        }


class PODTrackingAPI:
    """Shipment/POD connector and attachment gating logic."""

    STATUS_MAP = {
        "Delivered": "Delivered",
        "Shipped": "Pending Delivery",
        "Processing": "Pending Delivery",
        "Cancelled": "Returned",
        "Returned": "Returned",
    }

    @classmethod
    def fetch(cls, order_row):
        raw_status = order_row.get("fulfillment_status", "")
        normalized_status = cls.STATUS_MAP.get(raw_status, "Pending Delivery")
        tracking_number = order_row.get("tracking_number", "")
        carrier = order_row.get("shipping_carrier", "")
        delivery_date = order_row.get("delivery_date", "")

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


class DisputeAutomationPlatform:
    """API integration orchestration across PSP, CRM, Gateway, POD, and repository."""

    WORKFLOW = [
        "Consumer raises dispute with issuer bank.",
        "Issuer raises chargeback under a network reason code.",
        "PSP API receives dispute notification and syncs to platform.",
        "Automation fetches minimal dispute metadata in real time.",
        "Gateway API match logic validates date/amount/network/last4/transaction ID.",
        "CRM API fetches order confirmation, customer details, and communication records.",
        "Fulfillment API checks shipment tracking and POD inclusion rules.",
        "Reason-code rule engine assembles required evidence checklist.",
        "Repository selects template + policy documents by reason code.",
        "AI modifies cover letter based on available evidence.",
        "PDF converter builds the final representment packet for submission.",
    ]

    PORTALS = [
        {"id": "psp", "name": "PSP Portal API", "purpose": "Dispute ingestion", "status": "active"},
        {"id": "gateway", "name": "Gateway API", "purpose": "Auth/AVS/CVV/3DS/receipt", "status": "active"},
        {"id": "crm", "name": "CRM API", "purpose": "Order and customer confirmation", "status": "active"},
        {"id": "pod", "name": "Fulfillment/POD API", "purpose": "Shipment tracking + delivery proof", "status": "active"},
        {"id": "repo", "name": "Repository API", "purpose": "Templates and policy docs", "status": "active"},
        {"id": "ai", "name": "AI Cover Letter Engine", "purpose": "Evidence-aware cover letter edits", "status": "active"},
        {"id": "pdf", "name": "PDF Converter", "purpose": "Packet formatting and export", "status": "active"},
    ]

    @classmethod
    def _orders_by_id(cls):
        orders = ChargebackCaseLoader.load_orders()
        return {o["order_id"]: o for o in orders}

    @classmethod
    def get_disputes(cls, limit=12):
        return PSPDisputeAPI.pull_disputes(limit=limit)

    @classmethod
    def compile_dispute_packet(cls, dispute, orders_by_id=None):
        if orders_by_id is None:
            orders_by_id = cls._orders_by_id()

        order_row = orders_by_id.get(dispute.get("order_id", ""), {})
        reason_code = dispute.get("reason_code", "")
        reason_info = REASON_CODES.get(reason_code, {})
        required_docs = ReasonCodeRulebook.required_evidence(reason_code)

        gateway = GatewayEvidenceAPI.fetch(dispute, order_row)
        crm = CRMOrderAPI.fetch(dispute, order_row)
        pod = PODTrackingAPI.fetch(order_row)
        document_manifest = RepositoryEngine.resolve_documents(
            reason_code, required_docs, gateway, crm, pod
        )
        ai_cover_letter = CoverLetterAIEngine.generate(
            dispute, gateway, crm, pod, document_manifest
        )
        pdf_packet = PDFPacketConverter.build_packet(
            dispute, ai_cover_letter, document_manifest
        )

        readiness = cls._readiness_score(gateway, crm, pod, document_manifest)
        network_codes = ReasonCodeRulebook.network_reason_matrix(reason_code)

        return {
            "dispute": dispute,
            "reason": {
                "code": reason_code,
                "title": reason_info.get("title", "Unknown reason code"),
                "description": reason_info.get("definition", ""),
                "network_reason_codes": network_codes,
            },
            "required_evidence": required_docs,
            "gateway": gateway,
            "crm": crm,
            "pod": pod,
            "document_manifest": document_manifest,
            "ai_cover_letter": ai_cover_letter,
            "pdf_packet": pdf_packet,
            "readiness": readiness,
        }

    @classmethod
    def _readiness_score(cls, gateway, crm, pod, document_manifest):
        score = 0
        if gateway.get("status") == "matched":
            score += 40
        elif gateway.get("status") == "partial":
            score += 25
        elif gateway.get("status") == "unmatched":
            score += 5

        if crm.get("order_confirmation_status") == "Confirmed":
            score += 25

        if pod.get("pod_attachment", {}).get("status") == "included":
            score += 20
        else:
            score += 5

        total_docs = max(len(document_manifest), 1)
        included_docs = sum(1 for d in document_manifest if d.get("status") == "included")
        score += int((included_docs / total_docs) * 15)
        score = min(score, 100)

        recommended_action = "Auto-Represent" if score >= 75 else "Manual Review"
        return {"score": score, "recommended_action": recommended_action}

    @classmethod
    def build_case_packet(cls, chargeback_case_id):
        disputes = PSPDisputeAPI.pull_disputes(limit=None)
        match = next((d for d in disputes if d["chargeback_case_id"] == chargeback_case_id), None)
        if not match:
            return None
        return cls.compile_dispute_packet(match)

    @classmethod
    def framework_summary(cls, disputes):
        networks = {}
        auto_ready = 0
        manual_review = 0
        orders_by_id = cls._orders_by_id()

        for dispute in disputes:
            network = dispute.get("card_network", "Unknown")
            networks[network] = networks.get(network, 0) + 1
            packet = cls.compile_dispute_packet(dispute, orders_by_id)
            if packet["readiness"]["recommended_action"] == "Auto-Represent":
                auto_ready += 1
            else:
                manual_review += 1

        return {
            "total_disputes": len(disputes),
            "auto_ready": auto_ready,
            "manual_review": manual_review,
            "network_mix": networks,
        }
