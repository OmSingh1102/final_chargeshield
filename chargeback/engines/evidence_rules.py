"""
Evidence rules engine — maps reason categories to required evidence from 4 databases.
Red-highlighted items are PRIMARY (critical/mandatory) evidence for that category.
Non-red items are SECONDARY (supporting) evidence.

Winning ratio = (primary evidence available / total primary evidence) * 100
"""

DATABASES = {
    "db1": {
        "name": "Database I (Order Information)",
        "fields": [
            "Refund information", "Order information", "Invoice Breakup",
            "Communication history", "Logistics Information",
            "Order detailed description", "Return information"
        ]
    },
    "db2": {
        "name": "Database II (Transaction Details)",
        "fields": [
            "Transaction history", "IP information",
            "Customer information (Name and Address)",
            "Geo location"
        ]
    },
    "db3": {
        "name": "Database III",
        "fields": [
            "Payment History", "Binding History", "Account History",
            "3Ds Secure", "Introduction", "Terms and Conditions",
            "Refund Policy"
        ]
    },
    "db4": {
        "name": "Database IV",
        "fields": ["Proof of delivery"]
    }
}

# Evidence rules per reason category
# Each entry: list of {name, critical (red), db_source}
EVIDENCE_RULES = {
    "unauthorized": {
        "title": "Unauthorized Transactions",
        "evidence": [
            {"name": "3D Secure", "critical": True, "db": "db3"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Account History", "critical": False, "db": "db3"},
            {"name": "Binding History", "critical": False, "db": "db3"},
            {"name": "Payment History", "critical": False, "db": "db3"},
            {"name": "Geo location", "critical": False, "db": "db2"},
            {"name": "Undisputed transaction", "critical": True, "db": "db2"},
            {"name": "Highlight the disputed transaction", "critical": False, "db": "db2"},
        ]
    },
    "goods_not_received": {
        "title": "Goods Not Received",
        "sub_scenarios": ["If item delivered", "If item in transit", "If item Lost in Transit",
                          "If item Awaiting collection", "If item Return to Sender"],
        "evidence": [
            {"name": "Proof of delivery", "critical": True, "db": "db4"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
    "product_unsatisfactory": {
        "title": "Product Unacceptable / Unsatisfactory / Not as Described",
        "evidence": [
            {"name": "Order information / Product detailed description", "critical": True, "db": "db1"},
            {"name": "Return information", "critical": True, "db": "db1"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Proof of delivery", "critical": False, "db": "db4"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
    "credit_not_processed": {
        "title": "Credit Not Processed",
        "evidence": [
            {"name": "Reason for not giving the credit", "critical": True, "db": "db1"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Proof of delivery", "critical": False, "db": "db4"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
    "duplicate_payment": {
        "title": "Duplicate Payment",
        "evidence": [
            {"name": "Two transaction details with different timestamps", "critical": True, "db": "db2"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
    "incorrect_amount": {
        "title": "Incorrect Amount",
        "evidence": [
            {"name": "Invoice Breakup", "critical": True, "db": "db1"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
    "cancelled_merchandise": {
        "title": "Cancelled Merchandise",
        "evidence": [
            {"name": "Cancellation Policy", "critical": True, "db": "db3"},
            {"name": "Refund information", "critical": False, "db": "db1"},
            {"name": "Order information", "critical": False, "db": "db1"},
            {"name": "Invoice Breakup", "critical": False, "db": "db1"},
            {"name": "Communication history", "critical": False, "db": "db1"},
            {"name": "Logistics Information", "critical": False, "db": "db1"},
            {"name": "Terms and Conditions", "critical": False, "db": "db3"},
            {"name": "Refund Policy", "critical": False, "db": "db3"},
        ]
    },
}

# Keywords to match reason descriptions to evidence rule categories
CATEGORY_KEYWORDS = {
    "unauthorized": ["fraud", "unauthorized", "ato", "not recognized", "no cardholder", "no authorization",
                     "purchase_unauthorized", "unrecognized", "fraudulent"],
    "goods_not_received": ["not received", "goods and services not received", "item not received",
                           "product not received", "products_not_received", "merchandise/services not received"],
    "product_unsatisfactory": ["not as described", "defective", "unsatisfactory", "damaged", "faulty",
                               "mismatch", "unacceptable", "product_unacceptable", "products_faulty",
                               "misrepresentation", "merchant not as described"],
    "credit_not_processed": ["credit not processed", "credit_not_processed", "refund not", "return was made"],
    "duplicate_payment": ["duplicate", "duplicate processing", "duplicate payment"],
    "incorrect_amount": ["incorrect amount", "incorrect_charge", "amount differs", "capture_amount_incorrect"],
    "cancelled_merchandise": ["cancelled", "cancelation", "cancellation", "subscription_canceled",
                              "recurring", "cancelled merchandise", "cancelled recurring"],
}


def _annotate(rule_key):
    """Copy a rule's evidence list with each item tagged by where it comes from.

    `source` is "system" when one of the generated documents satisfies the item
    and "manual" when an agent has to upload it. Derived from the document
    registry rather than hardcoded here, so adding a document reclassifies the
    matching items automatically. The tables above stay a plain transcription of
    the evidence matrix.
    """
    from chargeback.engines.evidence_documents import document_for_evidence

    annotated = []
    for item in EVIDENCE_RULES[rule_key]["evidence"]:
        doc_key = document_for_evidence(item["name"])
        annotated.append({**item,
                          "source": "system" if doc_key else "manual",
                          "doc_key": doc_key})
    return annotated


def get_evidence_for_case(case):
    """Determine the evidence rule set for a case based on its reason description and category."""
    desc = (case.get("reason_description", "") or case.get("scenario", "") or "").lower()
    cat = (case.get("chargeback_category", "") or "").lower()
    combined = desc + " " + cat

    rule_key = "goods_not_received"  # default: the most common category
    for key, keywords in CATEGORY_KEYWORDS.items():
        if any(k in combined for k in keywords):
            rule_key = key
            break

    return {
        "rule_key": rule_key,
        "title": EVIDENCE_RULES[rule_key]["title"],
        "evidence": _annotate(rule_key),
        "databases": DATABASES,
    }


def calculate_winning_ratio(evidence_list):
    """Calculate winning ratio based on primary and secondary evidence availability.

    Logic:
    - All primary (critical/red) evidence present → 100% winning possibility
    - Each missing primary doc reduces score by (70 / primary_total) points
    - Primary evidence accounts for 70% of the score (base)
    - Secondary evidence accounts for 30% of the score (bonus)
    - Formula: (primary_pct * 0.70) + (secondary_pct * 0.30)

    Example with 2 primary, 7 secondary:
    - All primary + all secondary = 70 + 30 = 100%
    - All primary + 4/7 secondary = 70 + 17 = 87%
    - 1/2 primary + all secondary = 35 + 30 = 65%
    - 0/2 primary + all secondary = 0 + 30 = 30%
    """
    primary_total = 0
    primary_available = 0
    secondary_total = 0
    secondary_available = 0
    primary_items = []
    secondary_items = []

    for item in evidence_list:
        if item.get("critical"):
            primary_total += 1
            if item.get("available"):
                primary_available += 1
            primary_items.append({
                "name": item.get("evidence_type", item.get("name", "")),
                "available": item.get("available", False),
            })
        else:
            secondary_total += 1
            if item.get("available"):
                secondary_available += 1
            secondary_items.append({
                "name": item.get("evidence_type", item.get("name", "")),
                "available": item.get("available", False),
            })

    primary_pct = (primary_available / primary_total * 100) if primary_total > 0 else 0
    secondary_pct = (secondary_available / secondary_total * 100) if secondary_total > 0 else 0

    winning_ratio = round(primary_pct * 0.70 + secondary_pct * 0.30)
    winning_ratio = min(100, max(0, winning_ratio))

    # Assessment levels
    if primary_pct == 100 and secondary_pct >= 80:
        assessment = "Excellent - all primary evidence present, strong secondary support"
        level = "excellent"
    elif primary_pct == 100:
        assessment = "Strong - all primary evidence present, submit additional secondary to strengthen"
        level = "strong"
    elif primary_pct >= 50:
        assessment = "Moderate - some primary evidence missing, case contestable but not guaranteed"
        level = "moderate"
    elif secondary_pct >= 50:
        assessment = "Weak - critical primary evidence missing, secondary evidence alone may not suffice"
        level = "weak"
    else:
        assessment = "Very weak - insufficient evidence to contest, recommend accepting chargeback"
        level = "very_weak"

    # Missing primary items (what's needed to reach 100%)
    missing_primary = [p["name"] for p in primary_items if not p["available"]]
    missing_secondary = [s["name"] for s in secondary_items if not s["available"]]

    return {
        "winning_ratio": winning_ratio,
        "level": level,
        "primary_total": primary_total,
        "primary_available": primary_available,
        "primary_pct": round(primary_pct),
        "secondary_total": secondary_total,
        "secondary_available": secondary_available,
        "secondary_pct": round(secondary_pct),
        "assessment": assessment,
        "missing_primary": missing_primary,
        "missing_secondary": missing_secondary,
        "primary_items": primary_items,
        "secondary_items": secondary_items,
    }
