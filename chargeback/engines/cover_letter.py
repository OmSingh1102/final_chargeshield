from datetime import datetime

from chargeback.utils.datetime_helpers import safe_float, fmt_datetime
from chargeback.engines.reason_code import ReasonCodeInterpreter


class RepositoryEngine:
    """Document repository for reason-code templates and policy artifacts."""

    POLICY_DOCUMENTS = [
        "Terms and Conditions.pdf",
        "Refund and Return Policy.pdf",
        "Checkout Terms Acceptance Snip.png",
    ]

    SAMPLE_REFERENCE_SNIPS = {
        "dispute_notification": "Screenshot 2026-07-22 131304.png",
        "gateway_receipt": "Screenshot 2026-07-22 131333.png",
        "order_confirmation": "Screenshot 2026-07-22 131342.png",
        "pod_proof": "Screenshot 2026-07-22 131350.png",
        "terms": "Screenshot 2026-07-22 131358.png",
        "refund_policy": "Screenshot 2026-07-22 131411.png",
    }

    COVER_TEMPLATES = {
        "10.4": (
            "This representment addresses dispute {case_id} ({reason_code}) for {network} "
            "in the amount of ${amount}. The merchant submits gateway authentication, CRM "
            "order confirmation, shipment proof where available, and policy acknowledgments."
        ),
        "11.3": (
            "This representment addresses dispute {case_id} ({reason_code}) with supporting "
            "authorization records. We provide auth evidence, AVS/CVV outcomes, transaction "
            "copy references, and cardholder order details for transaction {transaction_id}."
        ),
        "13.1": (
            "This representment addresses merchandise-not-received dispute {case_id} "
            "({reason_code}). The packet includes CRM order confirmation, carrier tracking, "
            "and delivery status for transaction {transaction_id}."
        ),
        "13.3": (
            "This representment addresses not-as-described dispute {case_id} ({reason_code}). "
            "The packet includes transaction records, order artifacts, and merchant policy "
            "documents supporting fulfillment and disclosure."
        ),
        "13.6": (
            "This representment addresses credit-not-processed dispute {case_id} ({reason_code}). "
            "The packet includes payment records, customer communication evidence, and refund "
            "policy references tied to transaction {transaction_id}."
        ),
        "13.7": (
            "This representment addresses cancelled-merchandise dispute {case_id} ({reason_code}). "
            "The packet includes refund-policy and fulfillment evidence to validate merchant "
            "compliance with cancellation terms."
        ),
        "default": (
            "This representment addresses dispute {case_id} ({reason_code}) for {network} in "
            "the amount of ${amount}. The merchant submits portal evidence from Gateway, CRM, "
            "Fulfillment, and repository policy records."
        ),
    }

    @classmethod
    def cover_template(cls, reason_code, network=""):
        """Letter template for a code on any network.

        COVER_TEMPLATES is keyed by dispute family, so a Mastercard 4837 or
        Amex F29 has to be resolved first — passed raw, every non-Visa code
        silently fell through to the generic default letter.
        """
        family, _ = ReasonCodeInterpreter.resolve(reason_code, network)
        return cls.COVER_TEMPLATES.get(family or reason_code,
                                       cls.COVER_TEMPLATES["default"])

    @classmethod
    def resolve_documents(cls, reason_code, required_docs, gateway_result, crm_result, pod_result):
        manifest = []
        seen = set()

        def add_doc(document, source, status, notes="", sample_ref=""):
            key = document.strip().lower()
            if key in seen:
                return
            seen.add(key)
            manifest.append({
                "document": document,
                "source": source,
                "status": status,
                "notes": notes,
                "sample_reference": sample_ref,
            })

        for doc in required_docs:
            label = str(doc)
            low = label.lower()
            source = "Repository"
            status = "included"
            notes = ""
            sample_ref = ""

            if any(k in low for k in ["gateway", "auth", "avs", "cvv", "3ds", "transaction copy"]):
                source = "Gateway API"
                status = "included" if gateway_result.get("status") in {"matched", "partial"} else "missing"
                notes = (
                    f"Auth {gateway_result.get('authorization_code', 'N/A')} | "
                    f"AVS {gateway_result.get('avs_status', 'N/A')} | "
                    f"CVV {gateway_result.get('cvv_status', 'N/A')}"
                )
                sample_ref = cls.SAMPLE_REFERENCE_SNIPS["gateway_receipt"]
            elif any(k in low for k in ["order confirmation", "crm", "customer communication"]):
                source = "CRM API"
                status = "included" if crm_result.get("order_confirmation_status") == "Confirmed" else "missing"
                notes = crm_result.get("order_confirmation_email_status", "")
                sample_ref = cls.SAMPLE_REFERENCE_SNIPS["order_confirmation"]
            elif any(k in low for k in ["proof of delivery", "pod", "shipment", "tracking"]):
                source = "Fulfillment/POD API"
                pod_attachment = pod_result.get("pod_attachment", {})
                status = pod_attachment.get("status", "excluded")
                notes = pod_attachment.get("reason", "")
                sample_ref = cls.SAMPLE_REFERENCE_SNIPS["pod_proof"]
            elif "terms" in low:
                source = "Repository"
                status = "included"
                notes = "Checkout acknowledgment and terms snapshot available."
                sample_ref = cls.SAMPLE_REFERENCE_SNIPS["terms"]
            elif "policy" in low or "refund" in low:
                source = "Repository"
                status = "included"
                notes = "Refund/cancellation policy record attached."
                sample_ref = cls.SAMPLE_REFERENCE_SNIPS["refund_policy"]

            add_doc(label, source, status, notes, sample_ref)

        for policy_doc in cls.POLICY_DOCUMENTS:
            if "terms" in policy_doc.lower():
                ref = cls.SAMPLE_REFERENCE_SNIPS["terms"]
            elif "refund" in policy_doc.lower():
                ref = cls.SAMPLE_REFERENCE_SNIPS["refund_policy"]
            else:
                ref = cls.SAMPLE_REFERENCE_SNIPS["refund_policy"]
            add_doc(policy_doc, "Repository", "included", "Policy artifact from central repository.", ref)

        add_doc("Dispute Notification.pdf", "PSP API", "included",
                "Original dispute notice from payment processor.",
                cls.SAMPLE_REFERENCE_SNIPS["dispute_notification"])

        return manifest


# ─── Full Cover Letter Templates Per Category ────────────────────────────────

COVER_LETTER_BODIES = {
    "unauthorized": {
        "heading": "UNAUTHORIZED CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment & Legal Credit Proof",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. All our programs are sold online using our secure "
            "website. On {chargebackdate}, we received a {lower_CRT} under RC {reasoncode} in the amount of "
            "${chargebackamt}.\n\n"
            "We strongly believe the {lower_CRT} filed by the Cardholder for the above case number is not valid "
            "because the compelling evidence attached with this letter shows that the transaction is valid, and the "
            "Cardholder is well aware of the transaction and its terms prior to purchase."
        ),
        "primary_defense_label": "Primary Defense (Transaction Authentication)",
        "primary_defense_text": (
            "The transaction was completed with verified authentication. The attached transaction copy with a "
            "positive AVS code ({avscode}) and CVV match ({cvvcode}) with Authorization code {authcode} proves "
            "this is a valid transaction. This copy was taken from the Payment Gateway."
        ),
        "secondary_defense_label": "Secondary Defense (Cardholder Verification)",
        "secondary_defense_text": (
            "The Cardholder placed an online order on our website for purchasing our program in the amount of "
            "${transactionamt} on {transactiondate} with authorization code {authcode} pertaining to transaction "
            "ID {transactionid}. Accurate credit card, name: {customername}, email address: {customeremail}, "
            "phone number: {phonenumber} and valid billing information was provided at the time of the purchase, "
            "all of which proves the Cardholder willingly engaged in the transaction."
        ),
        "defense_points": [
            "Transaction passed AVS/CVV verification at the point of sale.",
            "IP address and geolocation match the cardholder's billing jurisdiction.",
            "Cardholder's account history shows prior undisputed transactions from the same card and device.",
        ],
        "conclusion": (
            "All charges are accurate. The above evidence supports that the Cardholder willingly engaged in the "
            "transaction and accessed the program, therefore we are asking for your consideration to reverse this "
            "{lower_CRT} in our favor."
        ),
    },
    "goods_not_received": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Merchandise Not Received",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. All our products are sold online using our secure "
            "website. On {chargebackdate}, we received a {lower_CRT} under RC {reasoncode} in the amount of "
            "${chargebackamt}.\n\n"
            "We strongly believe the {lower_CRT} filed by the Cardholder for the above case number is not valid "
            "because the compelling evidence attached with this letter shows that the transaction is valid, and the "
            "Cardholder is well aware of the transaction and its terms prior to purchase.\n\n"
            "The Cardholder is claiming that they did not receive their order. Our delivery records confirm that "
            "the merchandise was shipped and delivered to the customer's verified address."
        ),
        "primary_defense_label": "Primary Defense (Proof of Delivery)",
        "primary_defense_text": (
            "The order ({orderid}) was fulfilled and shipped via carrier with tracking number provided. "
            "Delivery was confirmed to the customer's address. The attached Proof of Delivery document shows "
            "the delivery status, date, and carrier confirmation."
        ),
        "secondary_defense_label": "Secondary Defense (Transaction Verification)",
        "secondary_defense_text": (
            "The attached transaction copy with a positive AVS code ({avscode}) and CVV match ({cvvcode}) "
            "with Authorization code {authcode} proves this is a valid transaction. The Cardholder provided "
            "accurate billing and shipping information at the time of purchase."
        ),
        "defense_points": [
            "Goods delivered successfully to the customer's verified address.",
            "The cardholder did not attempt to cancel or return goods.",
            "The cardholder did not attempt to reach out to the seller or customer support for a refund.",
            "Refund is available only when a customer follows the Refund Policy as disclosed on our website.",
        ],
        "conclusion": (
            "Based on the confirmed delivery evidence, carrier tracking records, and verified transaction "
            "authentication, we respectfully request that this chargeback be reversed in favor of the merchant."
        ),
    },
    "product_unsatisfactory": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Product Not as Described",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We contest this chargeback. The product delivered matches the description listed on our website "
            "at the time of purchase. The Cardholder did not initiate a return or contact customer support "
            "prior to filing this dispute."
        ),
        "primary_defense_label": "Primary Defense (Product Description Accuracy)",
        "primary_defense_text": (
            "The order ({orderid}) was fulfilled as described. The product listing accurately described the "
            "item, including specifications, images, and pricing. The attached order information and product "
            "detailed description confirm the accuracy of what was delivered."
        ),
        "secondary_defense_label": "Secondary Defense (Return Policy Compliance)",
        "secondary_defense_text": (
            "The Cardholder did not follow the return procedure outlined in our Return Policy, which was "
            "accepted at checkout. No return request was initiated, and no communication was received from "
            "the Cardholder regarding product dissatisfaction."
        ),
        "defense_points": [
            "Product listing accurately described the item delivered.",
            "Customer did not initiate a return within the policy window.",
            "No customer service complaint was received prior to the chargeback.",
            "Return information confirms no return was processed.",
        ],
        "conclusion": (
            "Based on the accurate product description, fulfillment records, and the cardholder's failure to "
            "follow the established return process, we respectfully request reversal of this chargeback."
        ),
    },
    "credit_not_processed": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Credit Not Processed",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We contest this chargeback. Our records show that a credit/refund has been processed for this "
            "transaction or was not applicable based on our refund policy terms."
        ),
        "primary_defense_label": "Primary Defense (Refund/Credit Evidence)",
        "primary_defense_text": (
            "A formal credit/refund was processed and settled through the card network channel. This is supported "
            "by the Acquirer Reference Number (ARN): {arnnumber}, which provides network-level settlement "
            "traceability. The refund was completed on {refund_date} for the amount of ${refundamt}."
        ),
        "secondary_defense_label": "Secondary Defense (Reason for Credit Status)",
        "secondary_defense_text": (
            "If a credit was not issued, it was because the transaction did not meet the criteria outlined "
            "in our Refund Policy, which was accepted by the Cardholder at checkout. The attached policy "
            "document and order information detail the specific reason."
        ),
        "defense_points": [
            "Refund was already processed with verifiable ARN tracking.",
            "Credit settlement has been confirmed through the acquiring bank.",
            "Cardholder's issuing bank can verify funds receipt via the ARN.",
            "Continuing this chargeback would constitute a double-debit against the merchant.",
        ],
        "conclusion": (
            "Based on the refund transaction records confirming that credit was issued and settled via ARN "
            "{arnnumber}, we respectfully request that this chargeback be reversed in favor of the merchant."
        ),
    },
    "duplicate_payment": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Duplicate Processing",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We contest this chargeback. Our payment records confirm that each transaction processed "
            "corresponds to a separate and distinct order."
        ),
        "primary_defense_label": "Primary Defense (Distinct Transactions)",
        "primary_defense_text": (
            "The attached transaction details show two separate transactions with different timestamps, "
            "order IDs, and authorization codes. Each transaction corresponds to a unique purchase made "
            "by the Cardholder at different times."
        ),
        "secondary_defense_label": "Secondary Defense (Order Verification)",
        "secondary_defense_text": (
            "Each transaction has a corresponding order confirmation with distinct order details. "
            "The Cardholder received confirmation emails for each separate purchase."
        ),
        "defense_points": [
            "Two transaction details with different timestamps confirm separate purchases.",
            "Each transaction has a unique order ID and authorization code.",
            "Order confirmations were sent for each individual purchase.",
            "Invoice breakup shows distinct items/services for each transaction.",
        ],
        "conclusion": (
            "Based on the distinct transaction timestamps, separate order records, and individual "
            "authorization codes, we respectfully request that this chargeback be reversed in favor of the merchant."
        ),
    },
    "incorrect_amount": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Incorrect Amount",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We contest this chargeback. Our invoice records confirm that the amount charged matches "
            "the order total agreed upon by the Cardholder at the time of purchase."
        ),
        "primary_defense_label": "Primary Defense (Invoice Verification)",
        "primary_defense_text": (
            "The attached invoice breakup confirms the exact amount of ${transactionamt} charged to the "
            "Cardholder's card. This amount includes the base product price, applicable taxes, and "
            "shipping charges as displayed and accepted during checkout."
        ),
        "secondary_defense_label": "Secondary Defense (Checkout Acceptance)",
        "secondary_defense_text": (
            "The Cardholder reviewed and accepted the total amount at checkout before completing the "
            "purchase. The checkout page screenshot shows the exact pricing breakdown that the Cardholder "
            "agreed to before placing the order."
        ),
        "defense_points": [
            "Invoice breakup confirms the correct amount was charged.",
            "Cardholder accepted the total amount at checkout.",
            "Pricing was clearly displayed before order confirmation.",
            "No pricing discrepancy exists between the order and the charge.",
        ],
        "conclusion": (
            "Based on the invoice breakdown, checkout acceptance records, and customer-accepted pricing, "
            "we respectfully request that this chargeback be reversed in favor of the merchant."
        ),
    },
    "cancelled_merchandise": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment - Cancelled Merchandise/Services",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We contest this chargeback. The Cardholder's cancellation request was either processed in "
            "accordance with our cancellation policy or did not meet the cancellation criteria."
        ),
        "primary_defense_label": "Primary Defense (Cancellation Policy Compliance)",
        "primary_defense_text": (
            "The Cardholder agreed to our cancellation policy at the time of purchase. The attached "
            "cancellation policy document outlines the terms and conditions for cancellations, including "
            "applicable timeframes and fees."
        ),
        "secondary_defense_label": "Secondary Defense (Service/Product Delivered)",
        "secondary_defense_text": (
            "The merchandise/service was delivered or provided to the Cardholder prior to the "
            "cancellation request. The Cardholder received the benefit of the transaction."
        ),
        "defense_points": [
            "Cancellation policy was clearly disclosed and accepted at checkout.",
            "Cardholder did not cancel within the eligible cancellation window.",
            "Merchandise/service was already delivered or provided.",
            "Refund is available only per the terms of the cancellation policy.",
        ],
        "conclusion": (
            "Based on the cancellation policy terms accepted at checkout and the fulfillment of the "
            "order, we respectfully request that this chargeback be reversed in favor of the merchant."
        ),
    },
    "default": {
        "heading": "CHARGEBACK REBUTTAL",
        "subheading": "Defensive Representment & Legal Credit Proof",
        "salutation": "Dear {upper_CRT} Processing Team,",
        "intro": (
            "{registeredcompany} specializes in selling {specialized_in}. On {chargebackdate}, we received a "
            "{lower_CRT} under RC {reasoncode} in the amount of ${chargebackamt}.\n\n"
            "We strongly believe this chargeback is not valid based on the compelling evidence attached."
        ),
        "primary_defense_label": "Primary Defense (Transaction Evidence)",
        "primary_defense_text": (
            "The attached transaction copy with AVS code ({avscode}) and CVV match ({cvvcode}) "
            "with Authorization code {authcode} proves this is a valid transaction."
        ),
        "secondary_defense_label": "Secondary Defense (Order Verification)",
        "secondary_defense_text": (
            "The Cardholder placed an order on our website and provided valid billing information "
            "at the time of purchase. Order confirmation was sent to the registered email."
        ),
        "defense_points": [
            "Transaction was verified with AVS/CVV authentication.",
            "Order confirmation was sent to the cardholder.",
            "Cardholder agreed to Terms and Conditions at checkout.",
        ],
        "conclusion": (
            "Based on the evidence submitted herein, we respectfully request that this chargeback "
            "be reversed in favor of the merchant."
        ),
    },
}


def letter_context(case, order_row=None):
    """Every placeholder a rebuttal template can use, filled from one case.

    Extracted from ``build_cover_letter`` so the counter evidence page's
    narrative blocks resolve their tokens from the same vocabulary rather than
    a parallel one that could drift on what ``{chargebackamt}`` means.

    A defaultdict, so a token nobody has defined renders "N/A" instead of
    raising. The keys below the divider were added for the counter page and
    exist because its prose used a different fallback from the letter's for the
    same field — ``{customername}`` redacts, ``{cardholdername}`` does not — and
    collapsing the two would have quietly changed what one of the pages says.
    """
    from collections import defaultdict

    order_row = order_row or {}
    amt = safe_float(case.get("amount", 0))
    auth_amt = safe_float(case.get("amount_authorized", amt))
    settled_amt = safe_float(case.get("amount_settled", amt))

    return defaultdict(lambda: "N/A", {
        "merchantaccno": case.get("merchant_account", "") or "N/A",
        "registeredcompany": case.get("merchant", "") or "Acme Commerce Inc.",
        "orderid": case.get("order_id", "") or "N/A",
        "casenumber": case.get("dispute_psp_ref", case.get("case_id", "")),
        "arnnumber": case.get("acquirer_ref", "") or "N/A",
        "reasoncode": case.get("reason_code", ""),
        "chargebackamt": f"{amt:.2f}",
        "upper_CRT": case.get("payment_method", "Visa"),
        "lower_CRT": (case.get("payment_method", "Visa") or "Visa").lower(),
        "customername": case.get("cardholder", "") or "***REDACTED***",
        "customeremail": order_row.get("customer_email", "") or case.get("customer_email", "") or "N/A",
        "phonenumber": order_row.get("customer_phone", "") or case.get("customer_phone", "") or "N/A",
        "cardtype": case.get("payment_method", "Visa"),
        "avscode": case.get("avs_response", "") or "N/A",
        "cvvcode": case.get("cvv_response", "") or "N/A",
        "authcode": case.get("auth_code", "") or "N/A",
        "transactionamt": f"{auth_amt:.2f}",
        "transactiondate": case.get("transaction_date", "") or "N/A",
        "transactionid": case.get("payment_psp_ref", case.get("order_id", "")) or "N/A",
        "chargebackdate": case.get("dispute_creation_date", case.get("submission_date", "")) or "N/A",
        "specialized_in": "e-commerce marketplace services",
        "refund_date": case.get("submission_date", "") or "N/A",
        "refundamt": f"{settled_amt:.2f}",
        "date": fmt_datetime(datetime.now()),

        # ── Counter evidence page ────────────────────────────────────────────
        # Each mirrors exactly what that page's Jinja resolved to before the
        # prose moved into the narrative registry, fallbacks included.
        "currency": case.get("currency", "USD"),
        "merchantname": case.get("merchant") or "Merchant",
        "disputedate": case.get("dispute_creation_date", "") or "N/A",
        "reasondescription": case.get("reason_description", "") or case.get("scenario", ""),
        "cardholdername": case.get("cardholder", "") or "N/A",
        "cardholderemail": case.get("cardholder_email", "") or "N/A",
        "cardholderphone": case.get("cardholder_phone", "") or "N/A",
        "paymentref": case.get("payment_psp_ref", "") or "N/A",
        "threedsecure": case.get("threed_secure", "") or "N/A",
    })


def build_cover_letter(case, order_row=None, overrides=None):
    """Build a dynamic cover letter based on case category with populated variables.

    `overrides` is the repository's edited-template store. Passing None — which
    every caller that has no opinion does — yields the built-in letter, so this
    function behaves exactly as it did before the repository became editable.
    """
    from collections import defaultdict
    from chargeback.engines.evidence_rules import get_evidence_for_case
    # Imported here rather than at module scope: repository.py reads
    # COVER_LETTER_BODIES from this module, so a top-level import would be
    # circular. The two lines above already establish the local-import style.
    from chargeback.engines.repository import TemplateRepository, safe_format

    ev_info = get_evidence_for_case(case)
    category = ev_info["rule_key"]
    template = COVER_LETTER_BODIES.get(category, COVER_LETTER_BODIES["default"])
    # A team lead's edit layers onto the built-in, field by field, so editing
    # one paragraph leaves the rest of the letter untouched.
    template = TemplateRepository.apply_letter(template, overrides, category)

    order_row = order_row or {}
    ctx = letter_context(case, order_row)

    return {
        "category": category,
        "category_title": ev_info["title"],
        "heading": template["heading"],
        "subheading": template["subheading"],
        # safe_format, not .format_map: these five fields are editable from the
        # repository, and a lead typing an unbalanced brace must not be able to
        # raise ValueError out of here and take the whole counter page down.
        "salutation": safe_format(template["salutation"], ctx),
        "intro": safe_format(template["intro"], ctx),
        "primary_defense_label": template["primary_defense_label"],
        "primary_defense_text": safe_format(template["primary_defense_text"], ctx),
        "secondary_defense_label": template["secondary_defense_label"],
        "secondary_defense_text": safe_format(template["secondary_defense_text"], ctx),
        "defense_points": template["defense_points"],
        "conclusion": safe_format(template["conclusion"], ctx),
    }


def build_evidence_list(case, order_row=None):
    """Build dynamic evidence exhibit list based on what's actually available."""
    from chargeback.engines.evidence_rules import get_evidence_for_case

    ev_info = get_evidence_for_case(case)
    order_row = order_row or {}
    exhibits = []
    exhibit_letters = "ABCDEFGHIJKLMNOP"
    idx = 0

    for item in ev_info["evidence"]:
        name = item["name"]
        low = name.lower()
        available = False
        details = ""

        if "3d secure" in low or "3ds" in low:
            val = case.get("threed_secure", "")
            available = val and val != "Not Offered"
            details = f"3DS Status: {val}" if available else "3DS not triggered"
        elif "proof of delivery" in low or "pod" in low:
            fs = order_row.get("fulfillment_status", case.get("fulfillment_status", ""))
            tn = order_row.get("tracking_number", case.get("tracking_number", ""))
            available = fs == "Delivered" and bool(tn)
            details = f"Carrier: {order_row.get('shipping_carrier', 'N/A')}, Tracking: {tn}" if available else "Delivery not confirmed"
        elif "refund" in low:
            arn = case.get("acquirer_ref", "")
            amt = safe_float(case.get("amount_settled", 0))
            available = bool(arn and arn != "N/A") or amt > 0
            details = f"ARN: {arn}, Amount: ${amt:.2f}" if available else "No refund on record"
        elif "order info" in low or "order confirmation" in low:
            available = bool(order_row.get("order_id") or case.get("order_id"))
            details = f"Order ID: {order_row.get('order_id', case.get('order_id', 'N/A'))}"
        elif "invoice" in low:
            available = safe_float(case.get("amount_authorized", 0)) > 0
            details = f"Amount: ${safe_float(case.get('amount_authorized', 0)):.2f}"
        elif "communication" in low:
            email = order_row.get("customer_email", case.get("customer_email", ""))
            available = bool(email and email != "N/A")
            details = f"Customer email: {email}" if available else "No email on file"
        elif "logistics" in low or "tracking" in low:
            tn = order_row.get("tracking_number", case.get("tracking_number", ""))
            available = bool(tn)
            details = f"Tracking: {tn}" if available else "No tracking info"
        elif "account history" in low or "binding" in low or "payment history" in low:
            available = True
            details = "Account and payment records available in system"
        elif "geo" in low or "ip" in low:
            ip = order_row.get("customer_ip", case.get("customer_ip", ""))
            available = bool(ip and ip != "N/A")
            details = f"IP: {ip}" if available else "No IP data"
        elif "terms" in low or "conditions" in low:
            available = True
            details = "Terms and Conditions accepted at checkout"
        elif "refund policy" in low or "cancellation" in low:
            available = True
            details = "Policy document on file"
        elif "return" in low:
            available = True
            details = "Return policy and records available"
        elif "undisputed" in low:
            available = True
            details = "Prior undisputed transaction history on file"
        elif "transaction" in low and "two" in low:
            available = True
            details = "Transaction records with timestamps available"
        elif "highlight" in low:
            available = True
            details = "Disputed transaction highlighted in records"
        elif "reason for not giving" in low:
            available = True
            details = "Credit decision rationale documented"
        else:
            available = True
            details = "Document available"

        exhibit_id = f"Exhibit {exhibit_letters[idx]}" if idx < len(exhibit_letters) else f"Exhibit {idx+1}"
        exhibits.append({
            "exhibit_id": exhibit_id,
            "evidence_type": name,
            "details": details,
            "status": "Included" if available else "Missing",
            "critical": item.get("critical", False),
            "available": available,
        })
        idx += 1

    return exhibits


class CoverLetterAIEngine:
    """AI-style cover letter generation based on available evidence."""

    @classmethod
    def generate(cls, dispute, gateway_result, crm_result, pod_result, document_manifest):
        base_template = RepositoryEngine.cover_template(
            dispute.get("reason_code", "default"), dispute.get("card_network", ""))
        letter = base_template.format(
            case_id=dispute.get("chargeback_case_id", ""),
            reason_code=dispute.get("reason_code", ""),
            network=dispute.get("card_network", ""),
            amount=f"{safe_float(dispute.get('transaction_amount')):.2f}",
            transaction_id=dispute.get("transaction_id", ""),
        )

        highlights = []
        open_items = []

        if gateway_result.get("status") == "matched":
            highlights.append(
                "Gateway data fully matched (date, amount, card network, last4, transaction ID)."
            )
        elif gateway_result.get("status") == "partial":
            highlights.append("Gateway data partially matched; strongest available auth evidence attached.")
            open_items.append("Analyst should validate mismatched gateway fields before submission.")
        else:
            open_items.append("Gateway match failed. Manual review is required.")

        if crm_result.get("order_confirmation_status") == "Confirmed":
            highlights.append("CRM confirms order placement and customer notification email.")
        else:
            open_items.append("CRM order confirmation record missing.")

        pod_attachment = pod_result.get("pod_attachment", {})
        if pod_attachment.get("status") == "included":
            highlights.append(
                f"POD attached from {pod_result.get('carrier', '')} tracking {pod_result.get('tracking_number', '')}."
            )
        else:
            open_items.append(pod_attachment.get("reason", "POD evidence unavailable."))

        included_docs = sum(1 for d in document_manifest if d.get("status") == "included")
        highlights.append(f"Repository attached {included_docs}/{len(document_manifest)} required artifacts.")

        if highlights:
            letter += "\n\nEvidence Highlights:\n" + "\n".join(f"- {item}" for item in highlights)
        if open_items:
            letter += "\n\nOpen Items:\n" + "\n".join(f"- {item}" for item in open_items)

        return {
            "content": letter,
            "highlights": highlights,
            "open_items": open_items,
            "generated_at_utc": fmt_datetime(datetime.utcnow()),
        }
