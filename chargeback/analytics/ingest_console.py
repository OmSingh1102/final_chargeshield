"""The AI Triage view on the ingestion page, built from the loaded book.

The page used to render `IngestionDemo.get_demo_data()` — ten hardcoded cases
in the seed module. That made "Total Cases Ingested" a constant: you could
upload a hundred rows, watch every other page move, and this one still read 10.
Building the same shape from the real case list is what makes an upload visible
on the page you uploaded it from.

The shape is dictated by the template, which reads `processor`, `order` and
`product` blocks per case, so the mapping happens here rather than in the view.
"""


class IngestConsole:

    #: Cases the classifier is confident enough to represent without a human.
    AUTO_ROUTING = "auto_represent"

    #: No merchant-level return policy is carried on a case, and the triage
    #: table only uses it to caption the product block, so one house default
    #: beats inventing a per-case number that nothing can back up.
    DEFAULT_RETURN_DAYS = 30

    @staticmethod
    def _avs_cvv(case):
        """One status string from the two separate response codes.

        The template shows a single AVS/CVV cell, and a reviewer reading it
        wants "do these check out" rather than two raw scheme codes.
        """
        avs = (case.get("avs_response") or "").strip()
        cvv = (case.get("cvv_response") or "").strip()
        if not avs and not cvv:
            return "Not available"
        good = {"Y", "M", "MATCH", "FULL_MATCH", "A", "Z"}
        avs_ok = avs.upper() in good
        cvv_ok = cvv.upper() in good
        if avs_ok and cvv_ok:
            return "Both match"
        if avs_ok or cvv_ok:
            return f"Partial ({'AVS' if avs_ok else 'CVV'} only)"
        return "No match"

    @classmethod
    def _row(cls, classified):
        """Map one classified case onto the blocks the triage table reads."""
        src = classified.get("source") or {}
        ml = classified.get("ml") or {}
        tracking = (src.get("TrackingNumber") or "").strip()

        return {
            "case_id": classified.get("case_id", ""),
            "processor": {
                "processor_case_id": classified.get("case_id", ""),
                "transaction_id": (src.get("PaymentTransactionId")
                                   or classified.get("order_id", "")),
                "chargeback_reason_code": classified.get("reason_code", ""),
                "reason_description": classified.get("reason_description", ""),
                "disputed_amount": classified.get("amount", 0),
                "card_scheme": classified.get("payment_method", ""),
            },
            "order": {
                "customer_id": src.get("MerchantUserId", ""),
                "order_date": (src.get("OrderDate")
                               or classified.get("transaction_date", "")),
                "shipping_status": src.get("DeliveryStatus", ""),
                "delivery_signature_present": bool(
                    (src.get("DeliverySignedBy") or "").strip()),
                "delivery_signed_at": src.get("ActualDeliveryDate", ""),
                # Only build a link when there is something to track, so the
                # table does not render a dead URL for undelivered goods.
                "carrier_tracking_url": (
                    f"https://track.aftership.com/{tracking}" if tracking else ""),
                "avs_cvv_match_status": cls._avs_cvv(classified),
                "customer_ip_address": src.get("DeviceIp", ""),
                "customer_lifetime_value": src.get("TotalSpendLifetime", ""),
                "order_history_count": src.get("TotalOrdersLifetime", ""),
            },
            "product": {
                "product_name": src.get("ProductName", ""),
                "product_type": src.get("ProductCategory", ""),
                "return_policy_days": cls.DEFAULT_RETURN_DAYS,
            },
            # Two lanes, because this page asks the triage question — can the
            # model file this itself, or does a person have to pick it up.
            # Accept/refund cases need a human to accept the loss, so they sit
            # with the review queue rather than being dropped from the count.
            "queue": "ai" if ml.get("routing") == cls.AUTO_ROUTING else "human",
            "ai_reason": ml.get("routing_desc", ""),
            "ai_score": ml.get("confidence", 0),
        }

    @classmethod
    def compute(cls, ml_stats):
        """Triage data for every case currently loaded."""
        classified = ml_stats.get("classified_cases", [])
        cases = [cls._row(c) for c in classified]
        ai = sum(1 for c in cases if c["queue"] == "ai")

        # Precomputed, because the template used to derive this inline by
        # re-scanning every earlier row per row — fine for the ten seeded
        # cases, quadratic once a real book is ingested.
        seen, reason_codes = set(), []
        for c in cases:
            code = c["processor"]["chargeback_reason_code"]
            if code and code not in seen:
                seen.add(code)
                reason_codes.append(
                    {"code": code,
                     "description": c["processor"]["reason_description"]})

        return {
            "cases": cases,
            "reason_codes": reason_codes,
            "summary": {"total": len(cases), "ai": ai, "human": len(cases) - ai},
        }
