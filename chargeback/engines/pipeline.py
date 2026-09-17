from chargeback.engines.reason_code import ReasonCodeInterpreter
from chargeback.data.loader import ChargebackCaseLoader


class DatabaseOrchestrator:
    """Coordinates data enrichment from 5 internal databases.
    Each sub-connector simulates a real database/API integration."""

    class PaymentDB:
        """Auth logs, AVS/CVV verification, 3DS authentication results."""
        @staticmethod
        def query(order):
            return {
                "avs_cvv_match_status": order.get("avs_cvv_match", "Pass"),
                "payment_method": order.get("payment_method", "Visa"),
                "card_last_four": order.get("card_last_four", ""),
            }

    class OrderDB:
        """Order history, transaction details, customer aggregates."""
        @staticmethod
        def query(order_id, orders_by_id, cust_order_counts, cust_revenue):
            raw = orders_by_id.get(order_id, {})
            cid = raw.get("customer_id", "")
            return {
                "customer_id": cid,
                "customer_lifetime_value": round(cust_revenue.get(cid, 0), 2),
                "order_history_count": cust_order_counts.get(cid, 0),
                "order_date": raw.get("order_date", ""),
                "product_id": raw.get("product_id", ""),
            }

    class ProductDB:
        """Product catalog, descriptions, return policies."""
        PRODUCTS = {
            "PROD-A1": {"product_name": "Wireless Noise-Cancelling Headphones", "product_type": "Physical", "return_policy_days": 30},
            "PROD-A2": {"product_name": "Smart Watch Ultra Pro", "product_type": "Physical", "return_policy_days": 30},
            "PROD-A3": {"product_name": "LED Desk Lamp with USB Charger", "product_type": "Physical", "return_policy_days": 30},
            "PROD-A4": {"product_name": "65-inch 4K Smart TV", "product_type": "Physical", "return_policy_days": 15},
            "PROD-A5": {"product_name": "Espresso Machine Pro 3000", "product_type": "Physical", "return_policy_days": 30},
            "PROD-A6": {"product_name": "Electric Standing Desk Frame", "product_type": "Physical", "return_policy_days": 30},
            "PROD-A7": {"product_name": "Portable Bluetooth Speaker", "product_type": "Physical", "return_policy_days": 30},
            "PROD-B1": {"product_name": "Silicone Phone Case - Galaxy S24", "product_type": "Physical", "return_policy_days": 14},
            "PROD-B2": {"product_name": "Robot Vacuum Cleaner X500", "product_type": "Physical", "return_policy_days": 30},
            "PROD-B3": {"product_name": "15g Nail Glue Press-On Kit", "product_type": "Physical", "return_policy_days": 0},
        }

        @classmethod
        def query(cls, product_id):
            return cls.PRODUCTS.get(product_id, {
                "product_name": "Unknown Product",
                "product_type": "Physical",
                "return_policy_days": 30,
            })

    class MerchantDB:
        """Merchant info, descriptors, account details."""
        @staticmethod
        def query(case=None):
            return {
                "merchant": "Acme Commerce Inc.",
                "merchant_account": "MID-ACME-0001",
                "descriptor_name": "Acme Online Store",
                "descriptor_url": "acme-store.example.com",
            }

    class ShippingPOD:
        """Carrier tracking, delivery proof, signatures."""
        CARRIER_URLS = {
            "UPS": "https://track.ups.com/",
            "FedEx": "https://track.fedex.com/",
            "USPS": "https://tools.usps.com/",
            "Veho": "https://track.veho.com/",
            "DHL": "https://track.dhl.com/",
        }
        FULFILLMENT_MAP = {
            "Delivered": "Delivered",
            "Shipped": "In Transit",
            "Processing": "Not Shipped",
            "Cancelled": "Not Shipped",
            "Returned": "Delivered",
        }

        @classmethod
        def query(cls, order):
            tn = order.get("tracking_number", "")
            carrier = order.get("shipping_carrier", "")
            tracking_url = (cls.CARRIER_URLS.get(carrier, "https://track.unknown.com/") + tn) if tn else None
            return {
                "shipping_status": cls.FULFILLMENT_MAP.get(order.get("fulfillment_status", ""), "Not Shipped"),
                "carrier_tracking_url": tracking_url,
                "delivery_signature_present": order.get("delivery_signed") == "Yes",
                "delivery_signed_at": order.get("delivery_date") if order.get("delivery_signed") == "Yes" else None,
            }

    @classmethod
    def enrich(cls, order_data, chargeback_data, orders_by_id, cust_counts, cust_revenue):
        """Query all 5 databases and return enriched case data."""
        raw = orders_by_id.get(chargeback_data["order_id"], {})

        order_info = cls.OrderDB.query(
            chargeback_data["order_id"], orders_by_id, cust_counts, cust_revenue)
        product_info = cls.ProductDB.query(order_info.get("product_id", ""))
        payment_info = cls.PaymentDB.query(raw)
        merchant_info = cls.MerchantDB.query()
        shipping_info = cls.ShippingPOD.query(raw)

        return {
            "order": {**order_info, **shipping_info,
                      "customer_ip_address": raw.get("customer_ip", ""),
                      "avs_cvv_match_status": payment_info["avs_cvv_match_status"]},
            "product": product_info,
            "merchant": merchant_info,
            "payment": payment_info,
            "shipping": shipping_info,
        }


class DecisionPackageBuilder:
    """Generates rebuttal and defense evidence packages for cases."""

    @classmethod
    def build(cls, case, reason_code_info=None):
        """Build a defense package for a case."""
        if reason_code_info is None:
            reason_code_info = ReasonCodeInterpreter.interpret(
                case.get("reason_code", ""))

        return {
            "case_id": case.get("case_id", ""),
            "reason_code": case.get("reason_code", ""),
            "defense_goals": reason_code_info.get("defense_goals", []),
            "supporting_docs_platform": reason_code_info.get("supporting_docs_platform", []),
            "supporting_docs_general": reason_code_info.get("supporting_docs_general", []),
            "portals": reason_code_info.get("portals", []),
            "merchant_challenge": reason_code_info.get("merchant_challenge", ""),
        }


class ChargebackPipeline:
    """End-to-end chargeback defense pipeline.
    Orchestrates all stages from CSV upload to decision package."""

    @classmethod
    def run(cls):
        """Execute the full pipeline and return classified cases."""
        from collections import Counter, defaultdict
        from chargeback.data.seed import IngestionDemo

        # Stage 1: CSV Upload -> Chargeback Case Loader
        orders, chargebacks, orders_by_id = ChargebackCaseLoader.load()
        cust_order_counts = Counter(o["customer_id"] for o in orders)
        cust_revenue = defaultdict(float)
        for o in orders:
            cust_revenue[o["customer_id"]] += float(o["order_amount"])

        # Stage 2-3: Reason Code Interpretation + Database Enrichment
        enriched_cases = []
        for cb in chargebacks:
            # Stage 2: Interpret reason code
            reason_info = ReasonCodeInterpreter.interpret(cb["reason_code"])

            # Stage 3: Enrich from 5 databases
            enrichment = DatabaseOrchestrator.enrich(
                None, cb, orders_by_id, cust_order_counts, cust_revenue)

            # Build processor case object
            processor_case = {
                "processor_case_id": cb["dispute_ref"],
                "chargeback_reason_code": cb["reason_code"],
                "reason_description": cb["reason_description"],
                "card_scheme": cb["card_scheme"],
                "disputed_amount": float(cb["disputed_amount"]),
                "currency": "USD",
                "transaction_id": cb["order_id"],
            }

            # Stage 4: AI triage (rule-based)
            queue, ai_reason, score = IngestionDemo.triage(
                processor_case, enrichment["order"], enrichment["product"])

            enriched_cases.append({
                "processor": processor_case,
                "order": enrichment["order"],
                "product": enrichment["product"],
                "queue": queue,
                "ai_reason": ai_reason,
                "ai_score": score,
                "reason_info": reason_info,
            })

        return enriched_cases, orders, cust_order_counts, cust_revenue

    @classmethod
    def get_pipeline_summary(cls):
        """Return pipeline stage metadata for visualization."""
        return [
            {"stage": 1, "name": "CSV Upload", "icon": "&#128196;",
             "description": "Raw chargeback data ingested from processor CSV files"},
            {"stage": 2, "name": "Chargeback Case Loader", "icon": "&#128230;",
             "description": "Parse and validate dispute records, link to order IDs"},
            {"stage": 3, "name": "Reason Code Interpreter", "icon": "&#128209;",
             "description": "Map reason codes to defense strategies and network rules"},
            {"stage": 4, "name": "Database Connector Orchestrator", "icon": "&#128451;",
             "description": "Enrich cases from 5 internal databases",
             "sub_stages": ["Payment DB", "Order DB", "Product DB", "Merchant DB", "Shipping/POD"]},
            {"stage": 5, "name": "AI Validation Engine", "icon": "&#129302;",
             "description": "Rule-based scoring + LLM reasoning for case assessment"},
            {"stage": 6, "name": "Auto/Human Decision", "icon": "&#9878;",
             "description": "80% auto-represent, 20% routed to human review"},
            {"stage": 7, "name": "Rebuttal / Decision Package", "icon": "&#128220;",
             "description": "Generate defense evidence packets and rebuttal documents"},
        ]
