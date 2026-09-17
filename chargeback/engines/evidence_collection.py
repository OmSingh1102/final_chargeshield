from chargeback.utils.datetime_helpers import safe_float

_safe_float = safe_float


class EvidenceCollectionEngine:
    """Simulates API-based automated evidence retrieval across 5 data sources.
    Returns tier-appropriate synthetic evidence for each chargeback case."""

    APIS = {
        "shipping_delivery": {
            "name": "Shipping & Delivery API",
            "icon": "&#128230;",
            "description": "Carrier tracking, delivery confirmation, proof of delivery photos",
            "source": "Logistics / Carrier Partners",
            "manual_hours": 1.5,
        },
        "payment_gateway": {
            "name": "Payment Gateway API",
            "icon": "&#128179;",
            "description": "Authorization logs, 3DS results, AVS/CVV verification",
            "source": "Adyen / Braintree / Worldpay / Stripe",
            "manual_hours": 0.75,
        },
        "crm_customer": {
            "name": "CRM & Customer API",
            "icon": "&#128100;",
            "description": "Customer history, communication logs, account activity",
            "source": "CRM / Customer Service Platform",
            "manual_hours": 1.0,
        },
        "marketplace_order": {
            "name": "Marketplace Order API",
            "icon": "&#128722;",
            "description": "Order details, product listings, seller records",
            "source": "Marketplace / Storefront Platform",
            "manual_hours": 0.75,
        },
        "threed_secure": {
            "name": "3DS Authentication API",
            "icon": "&#128274;",
            "description": "3D Secure enrollment, authentication results, liability shift",
            "source": "Card Network 3DS Directory Server",
            "manual_hours": 0.5,
        },
    }

    TOTAL_MANUAL_HOURS = sum(a["manual_hours"] for a in APIS.values())  # 4.5h

    @classmethod
    def _latency(cls, api_id, tier):
        """Deterministic simulated latency in ms based on tier."""
        base = hash(api_id) % 100
        if tier == "auto_represent":
            return 150 + (base % 200)
        elif tier == "hitl_review":
            return 250 + (base % 350)
        else:
            return 400 + (base % 800)

    @classmethod
    def _collect_shipping(cls, case, tier):
        oid = case.get("order_id", "ORD-UNKNOWN")
        if tier == "auto_represent":
            return {
                "status": "complete", "completeness_pct": 100,
                "evidence_items": [
                    {"label": "Carrier Tracking Number", "value": f"TTS-TRK-{oid[:12]}-UPS", "confidence": "high"},
                    {"label": "Carrier", "value": "UPS", "confidence": "high"},
                    {"label": "Delivery Status", "value": "Delivered", "confidence": "high"},
                    {"label": "Delivery Date", "value": "Jun 21, 2026, 2:15 PM", "confidence": "high"},
                    {"label": "Delivery Photo", "value": "delivery_photo_verified.jpg", "confidence": "high"},
                    {"label": "Signature", "value": "Left at front door, photo taken", "confidence": "high"},
                    {"label": "Address Match", "value": "Shipping address matches AVS billing address", "confidence": "high"},
                ],
                "gaps": [], "requires_human": False,
            }
        elif tier == "hitl_review":
            return {
                "status": "partial", "completeness_pct": 55,
                "evidence_items": [
                    {"label": "Carrier Tracking Number", "value": f"TTS-TRK-{oid[:12]}-USPS", "confidence": "medium"},
                    {"label": "Carrier", "value": "USPS", "confidence": "medium"},
                    {"label": "Delivery Status", "value": "Delivered", "confidence": "medium"},
                    {"label": "Delivery Date", "value": "Jun 23, 2026, 11:30 AM", "confidence": "medium"},
                ],
                "gaps": ["No delivery photo available", "No signature confirmation", "Address match inconclusive"],
                "requires_human": True,
            }
        else:
            return {
                "status": "unavailable", "completeness_pct": 15,
                "evidence_items": [
                    {"label": "Carrier Tracking Number", "value": f"TTS-TRK-{oid[:12]}-VEHO", "confidence": "low"},
                ],
                "gaps": ["Delivery not confirmed to cardholder address", "No signature", "No delivery photo", "Address mismatch with billing"],
                "requires_human": True,
            }

    @classmethod
    def _collect_payment(cls, case, tier):
        if tier == "auto_represent":
            return {
                "status": "complete", "completeness_pct": 100,
                "evidence_items": [
                    {"label": "Authorization Code", "value": "A08823", "confidence": "high"},
                    {"label": "Authorization Result", "value": "Authorised", "confidence": "high"},
                    {"label": "AVS Result", "value": case.get("avs_response", "N/A"), "confidence": "high"},
                    {"label": "CVV Result", "value": case.get("cvv_response", "N/A"), "confidence": "high"},
                    {"label": "Transaction IP", "value": "104.28.88.21", "confidence": "high"},
                    {"label": "Device Fingerprint", "value": "fp_7k2m9x4bz1q8w3", "confidence": "high"},
                ],
                "gaps": [], "requires_human": False,
            }
        elif tier == "hitl_review":
            return {
                "status": "complete", "completeness_pct": 75,
                "evidence_items": [
                    {"label": "Authorization Code", "value": "A11547", "confidence": "high"},
                    {"label": "Authorization Result", "value": "Authorised", "confidence": "high"},
                    {"label": "AVS Result", "value": case.get("avs_response", "N/A"), "confidence": "medium"},
                    {"label": "CVV Result", "value": case.get("cvv_response", "N/A"), "confidence": "medium"},
                ],
                "gaps": ["Device fingerprint not captured", "IP geolocation mismatch needs review"],
                "requires_human": True,
            }
        else:
            return {
                "status": "unavailable", "completeness_pct": 20,
                "evidence_items": [
                    {"label": "Authorization Code", "value": "115875", "confidence": "low"},
                ],
                "gaps": ["CVV verification bypassed", "AVS street address not provided", "No device fingerprint", "No 3DS authentication"],
                "requires_human": True,
            }

    @classmethod
    def _collect_crm(cls, case, tier):
        if tier == "auto_represent":
            return {
                "status": "complete", "completeness_pct": 95,
                "evidence_items": [
                    {"label": "Customer Since", "value": "Mar 2025", "confidence": "high"},
                    {"label": "Total Orders", "value": "12", "confidence": "high"},
                    {"label": "Prior Disputes", "value": "0", "confidence": "high"},
                    {"label": "Account Status", "value": "Active, Good Standing", "confidence": "high"},
                    {"label": "Last Login", "value": "Jun 20, 2026, 3:45 PM", "confidence": "high"},
                    {"label": "Email Verified", "value": "Yes", "confidence": "high"},
                ],
                "gaps": [], "requires_human": False,
            }
        elif tier == "hitl_review":
            return {
                "status": "partial", "completeness_pct": 50,
                "evidence_items": [
                    {"label": "Customer Since", "value": "Jan 2026", "confidence": "medium"},
                    {"label": "Total Orders", "value": "3", "confidence": "medium"},
                    {"label": "Prior Disputes", "value": "0", "confidence": "medium"},
                ],
                "gaps": ["Communication logs not available from CRM", "Account activity logs incomplete", "No customer service interaction records"],
                "requires_human": True,
            }
        else:
            return {
                "status": "unavailable", "completeness_pct": 10,
                "evidence_items": [
                    {"label": "Account Found", "value": "Yes (limited data)", "confidence": "low"},
                ],
                "gaps": ["No customer communication history", "No prior purchase patterns", "Account flagged - under review", "No customer service records"],
                "requires_human": True,
            }

    @classmethod
    def _collect_marketplace_order(cls, case, tier):
        oid = case.get("order_id", "ORD-UNKNOWN")
        if tier == "auto_represent":
            return {
                "status": "complete", "completeness_pct": 100,
                "evidence_items": [
                    {"label": "Order ID", "value": oid, "confidence": "high"},
                    {"label": "Product", "value": "Wireless Earbuds Pro (SKU: WEP-2026)", "confidence": "high"},
                    {"label": "Order Amount", "value": f"${case.get('amount_settled', 0):.2f}", "confidence": "high"},
                    {"label": "Seller", "value": "TechAudio Official Store (Rating: 4.8)", "confidence": "high"},
                    {"label": "Warehouse", "value": "FCI3_ATL1", "confidence": "high"},
                    {"label": "Product Listing", "value": "Active - matches order description", "confidence": "high"},
                ],
                "gaps": [], "requires_human": False,
            }
        elif tier == "hitl_review":
            return {
                "status": "partial", "completeness_pct": 60,
                "evidence_items": [
                    {"label": "Order ID", "value": oid, "confidence": "high"},
                    {"label": "Product", "value": "Nail Glue Kit (SKU: NGK-1538)", "confidence": "medium"},
                    {"label": "Order Amount", "value": f"${case.get('amount_settled', 0):.2f}", "confidence": "high"},
                    {"label": "Seller", "value": "CurVille (Rating: 4.2)", "confidence": "medium"},
                ],
                "gaps": ["Original product listing has been modified since purchase", "Seller response to dispute pending"],
                "requires_human": True,
            }
        else:
            return {
                "status": "partial", "completeness_pct": 30,
                "evidence_items": [
                    {"label": "Order ID", "value": oid, "confidence": "medium"},
                    {"label": "Order Amount", "value": f"${case.get('amount_settled', 0):.2f}", "confidence": "medium"},
                ],
                "gaps": ["Seller verification pending", "Product listing removed", "No seller dispute response", "Return not initiated"],
                "requires_human": True,
            }

    @classmethod
    def _collect_3ds(cls, case, tier):
        if tier == "auto_represent":
            return {
                "status": "complete", "completeness_pct": 100,
                "evidence_items": [
                    {"label": "3DS Enrollment", "value": "Y (Enrolled)", "confidence": "high"},
                    {"label": "Authentication Result", "value": "Y (Authenticated)", "confidence": "high"},
                    {"label": "CAVV", "value": "AAABBJg0VhI0VniQEjRWAAAAAAA=", "confidence": "high"},
                    {"label": "ECI", "value": "05 (Fully Authenticated)", "confidence": "high"},
                    {"label": "Liability Shift", "value": "Yes - Issuer liable", "confidence": "high"},
                ],
                "gaps": [], "requires_human": False,
            }
        elif tier == "hitl_review":
            return {
                "status": "partial", "completeness_pct": 30,
                "evidence_items": [
                    {"label": "3DS Enrollment", "value": "Y (Enrolled)", "confidence": "medium"},
                    {"label": "Authentication Result", "value": "N (Not Authenticated)", "confidence": "low"},
                ],
                "gaps": ["3DS authentication failed - cardholder did not complete", "No liability shift - merchant liable", "CAVV not generated"],
                "requires_human": True,
            }
        else:
            return {
                "status": "unavailable", "completeness_pct": 0,
                "evidence_items": [],
                "gaps": ["3DS not offered for this transaction", "No enrollment record", "Merchant fully liable", "No liability shift available"],
                "requires_human": True,
            }

    @classmethod
    def collect_for_case(cls, case, ml_result):
        tier = ml_result["routing"]
        collectors = {
            "shipping_delivery": cls._collect_shipping,
            "payment_gateway": cls._collect_payment,
            "crm_customer": cls._collect_crm,
            "marketplace_order": cls._collect_marketplace_order,
            "threed_secure": cls._collect_3ds,
        }
        api_results = {}
        total_time = 0
        total_completeness = 0
        apis_complete = 0
        apis_partial = 0
        apis_unavailable = 0
        all_gaps = []
        human_actions = []

        for api_id, collector in collectors.items():
            result = collector(case, tier)
            latency = cls._latency(api_id, tier)
            result["api_id"] = api_id
            result["api_name"] = cls.APIS[api_id]["name"]
            result["collection_time_ms"] = latency
            result["item_count"] = len(result["evidence_items"])
            api_results[api_id] = result

            total_time += latency
            total_completeness += result["completeness_pct"]
            if result["status"] == "complete":
                apis_complete += 1
            elif result["status"] == "partial":
                apis_partial += 1
            else:
                apis_unavailable += 1
            all_gaps.extend(result["gaps"])
            if result["requires_human"]:
                human_actions.append(f"Review {cls.APIS[api_id]['name']} - {len(result['gaps'])} gap(s)")

        avg_completeness = round(total_completeness / len(collectors))

        if avg_completeness >= 85:
            strength = "strong"
        elif avg_completeness >= 50:
            strength = "moderate"
        else:
            strength = "weak"

        tier_labels = {
            "auto_represent": "Tier 1: Auto-Represent",
            "hitl_review": "Tier 2: HITL Review",
            "accept_refund": "Tier 3: Accept / Refund",
        }

        return {
            "case_id": case["case_id"],
            "tier": tier,
            "tier_label": tier_labels.get(tier, tier),
            "ml_confidence": ml_result["confidence"],
            "total_collection_time_ms": total_time,
            "total_collection_time_sec": round(total_time / 1000, 2),
            "manual_estimate_hours": cls.TOTAL_MANUAL_HOURS,
            "time_saved_hours": round(cls.TOTAL_MANUAL_HOURS - (total_time / 3600000), 2),
            "overall_completeness_pct": avg_completeness,
            "apis_called": len(collectors),
            "apis_complete": apis_complete,
            "apis_partial": apis_partial,
            "apis_unavailable": apis_unavailable,
            "api_results": api_results,
            "evidence_strength": strength,
            "auto_representable": tier == "auto_represent" and avg_completeness >= 85,
            "human_actions_needed": human_actions,
            "all_gaps": all_gaps,
        }

    @classmethod
    def collect_all(cls, classified_cases):
        results = {}
        for c in classified_cases:
            results[c["case_id"]] = cls.collect_for_case(c, c["ml"])
        return results

    @classmethod
    def get_aggregate_stats(cls, all_results):
        cases = list(all_results.values())
        n = len(cases)
        if n == 0:
            return {}
        total_apis = sum(c["apis_called"] for c in cases)
        avg_time_ms = round(sum(c["total_collection_time_ms"] for c in cases) / n)
        avg_completeness = round(sum(c["overall_completeness_pct"] for c in cases) / n)
        total_time_saved = round(sum(c["time_saved_hours"] for c in cases), 1)
        fully_auto = sum(1 for c in cases if c["auto_representable"])
        needs_review = sum(1 for c in cases if len(c["human_actions_needed"]) > 0)

        # Per-API aggregate
        api_stats = {}
        for api_id in cls.APIS:
            times = [c["api_results"][api_id]["collection_time_ms"] for c in cases]
            statuses = [c["api_results"][api_id]["status"] for c in cases]
            api_stats[api_id] = {
                "avg_time_ms": round(sum(times) / n),
                "complete_count": statuses.count("complete"),
                "partial_count": statuses.count("partial"),
                "unavailable_count": statuses.count("unavailable"),
                "success_rate": round((statuses.count("complete") + statuses.count("partial") * 0.5) / n * 100),
            }

        return {
            "total_cases": n,
            "total_apis_called": total_apis,
            "avg_collection_time_ms": avg_time_ms,
            "avg_collection_time_sec": round(avg_time_ms / 1000, 2),
            "avg_completeness": avg_completeness,
            "total_time_saved_hours": total_time_saved,
            "fully_automated": fully_auto,
            "needs_review": needs_review,
            "manual_hours_per_case": cls.TOTAL_MANUAL_HOURS,
            "api_stats": api_stats,
            "speed_improvement_pct": round((1 - (avg_time_ms / 3600000) / cls.TOTAL_MANUAL_HOURS) * 100, 1),
        }
