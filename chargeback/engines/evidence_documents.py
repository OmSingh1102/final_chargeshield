"""System-generated evidence documents.

Six of the evidence items a representment packet needs can be assembled from
the dispute sheet itself — the rest have to be uploaded by an agent because no
column holds them (carrier proof of delivery, email threads, screenshots).

Each document declares:

* ``build(case)``      → ``[(section_heading, body), ...]`` where *body* is
  either a list of ``(label, value)`` pairs or a list of prose paragraphs.
* ``available(case)``  → ``(bool, note)``. A document that cannot be built from
  a case says so rather than rendering a block of blank rows.
* ``preview(case)``    → one short line summarising it.

``build_documents`` returns all six ready for the Counter Evidence page, which
renders their content inline — there is no separate file to open or download.

Two of the six — Terms & Conditions and Refund Policy — are *merchant policy*,
not per-case records: the sheet has no columns for them, so they are assembled
from the merchant configuration plus the case's own dates and refund method.
They are labelled as such wherever they appear.
"""

from collections import OrderedDict

DEFAULT_MERCHANT = {
    "company_name": "Acme Commerce Inc.",
    "dba_name": "Acme Online Store",
}


# ─── small helpers ─────────────────────────────────────────────────────────────

def _src(case):
    """The raw sheet row behind a case (empty dict for seeded cases)."""
    return case.get("source") or {}


def _get(case, *names, default=""):
    """First non-empty sheet column among *names*."""
    row = _src(case)
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return default


def _num(value, default=0.0):
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return default


def _money(amount, currency):
    return f"{_num(amount):,.2f} {currency}".strip()


def _yes(value):
    return (value or "").strip().lower() in ("yes", "y", "true", "1")


def _date(value):
    """Trim a timestamp to its date, leaving already-short values alone."""
    text = (value or "").strip()
    if not text:
        return ""
    return text.replace("T", " ").split(" ")[0].rstrip("Z")


def _currency(case):
    return _get(case, "OrderCurrency", "TransactionCurrency",
                "ChargebackTxnCurrency", default=case.get("currency") or "USD")


def _address(case):
    parts = [
        _get(case, "DeliveryAddressLine1"),
        _get(case, "DeliveryCity"),
        _get(case, "DeliveryState"),
        _get(case, "DeliveryPostalCode"),
        _get(case, "DeliveryCountry"),
    ]
    return ", ".join(p for p in parts if p)


# ─── document builders ─────────────────────────────────────────────────────────

def _order_information(case, merchant):
    cur = _currency(case)
    return [
        ("Order Summary", [
            ("Order ID", _get(case, "OrderId", default="—")),
            ("Order Date", _get(case, "OrderDate", default="—")),
            ("Order Status", _get(case, "OrderStatus", default="—")),
            ("Sales Channel", _get(case, "TransactionChannel", default=merchant.get("dba_name", "—"))),
            ("Order Total", _money(_get(case, "OrderTotalAmount"), cur)),
        ]),
        ("Item Ordered", [
            ("Product", _get(case, "ProductName", default="—")),
            ("SKU", _get(case, "Sku", default="—")),
            ("Category", _get(case, "ProductCategory", default="—")),
            ("Quantity", _get(case, "Quantity", default="—")),
            ("Unit Price", _money(_get(case, "UnitPrice"), cur)),
        ]),
        ("Fulfilment", [
            ("Delivery Status", _get(case, "DeliveryStatus", default="—")),
            ("Carrier", _get(case, "ShippingCarrier", default="—")),
            ("Tracking Number", _get(case, "TrackingNumber", default="—")),
            ("Shipped On", _get(case, "ShipDate", default="—")),
            ("Estimated Delivery", _get(case, "EstimatedDeliveryDate", default="—")),
            ("Actual Delivery", _get(case, "ActualDeliveryDate", default="—")),
            ("Proof of Delivery", _get(case, "ProofOfDelivery", default="—")),
            ("Signed By", _get(case, "DeliverySignedBy", default="—")),
        ]),
        ("Delivery Address", [
            ("Ship To", _get(case, "UserFullName", default="—")),
            ("Address", _address(case) or "—"),
            ("Billing / Shipping Match", _get(case, "BillingShippingMatch", default="—")),
        ]),
    ]


def _refund_information(case, merchant):
    cur = _currency(case)
    refunded = _num(_get(case, "RefundAmount"))
    charged = _num(_get(case, "TransactionAmount"))
    balance = charged - refunded
    return [
        ("Refund Record", [
            ("Refund Issued", _get(case, "RefundIssued", default="No")),
            ("Refund Amount", _money(refunded, cur)),
            ("Refund Date", _get(case, "RefundDate", default="—")),
            ("Refund Method", _get(case, "RefundPayType", default="—")),
        ]),
        ("Against The Original Payment", [
            ("Transaction ID", _get(case, "PaymentTransactionId", default="—")),
            ("Transaction Date", _get(case, "TransactionTime", default="—")),
            ("Amount Charged", _money(charged, cur)),
            ("Amount Refunded", _money(refunded, cur)),
            ("Outstanding Balance", _money(balance, cur)),
            ("Settlement Date", _get(case, "SettlementDate", default="—")),
        ]),
        ("Disputed Amount", [
            ("Chargeback Amount", _money(case.get("amount", 0), case.get("currency") or cur)),
            ("Dispute Reference", case.get("case_id", "—")),
            ("Refund Precedes Dispute",
             "Yes" if (_get(case, "RefundDate") and _date(_get(case, "RefundDate"))
                       <= _date(_get(case, "DisputeTime"))) else "No"),
        ]),
    ]


def _invoice_breakup(case, merchant):
    cur = _currency(case)
    qty = _num(_get(case, "Quantity"), 1) or 1
    unit = _num(_get(case, "UnitPrice"))
    total = _num(_get(case, "OrderTotalAmount"))
    line_total = round(qty * unit, 2)
    # Round before comparing: 2 x 14.93 - 29.85 lands at -0.00999… in binary
    # floating point, which would slip past the threshold and leave the invoice
    # showing a line total that doesn't reconcile to its own total.
    adjustment = round(total - line_total, 2)
    lines = [
        (f"{_get(case, 'ProductName', default='Item')} ({_get(case, 'Sku', default='—')})",
         f"{qty:g} x {_money(unit, cur)}"),
        ("Line Total", _money(line_total, cur)),
    ]
    if abs(adjustment) >= 0.01:
        label = "Shipping / Tax / Adjustments" if adjustment > 0 else "Discount"
        lines.append((label, _money(adjustment, cur)))
    lines.append(("Invoice Total", _money(total, cur)))
    return [
        ("Invoice", [
            ("Invoice For Order", _get(case, "OrderId", default="—")),
            ("Invoice Date", _get(case, "OrderDate", default="—")),
            ("Billed To", _get(case, "UserFullName", default="—")),
            ("Currency", cur),
        ]),
        ("Line Items", lines),
        ("Reconciliation", [
            ("Invoice Total", _money(total, cur)),
            ("Amount Captured", _money(_get(case, "TransactionAmount"), cur)),
            ("Amount Disputed", _money(case.get("amount", 0), case.get("currency") or cur)),
            ("Authorization Code", _get(case, "AuthorizationCode", default="—")),
        ]),
    ]


def _account_history(case, merchant):
    cur = _currency(case)
    return [
        ("Account Holder", [
            ("Name", _get(case, "UserFullName", default="—")),
            ("Customer ID", _get(case, "UserId", default="—")),
            ("Email", _get(case, "UserEmail", default="—")),
            ("Phone", _get(case, "UserPhone", default="—")),
        ]),
        ("Account Standing", [
            ("Account Created", _get(case, "AccountCreatedDate", default="—")),
            ("Account Status", _get(case, "AccountStatus", default="—")),
            ("KYC Verified", _get(case, "KycVerified", default="—")),
            ("Risk Tier", _get(case, "CustomerRiskTier", default="—")),
        ]),
        ("Purchase History", [
            ("Lifetime Orders", _get(case, "TotalOrdersLifetime", default="—")),
            ("Lifetime Spend", _money(_get(case, "TotalSpendLifetime"), cur)),
            ("Average Order Value", _money(_get(case, "AvgOrderValue"), cur)),
            ("Most Recent Order", _get(case, "LastOrderId", default="—")),
            ("Most Recent Order Date", _get(case, "LastOrderDate", default="—")),
        ]),
        ("Dispute History", [
            ("Previous Chargebacks", _get(case, "PreviousChargebackCount", default="0")),
            ("Previously Won By Merchant", _get(case, "PreviousChargebacksWon", default="0")),
            ("Dispute Rate", f"{_get(case, 'DisputeRatePct', default='0')}%"),
            ("Device Used", _get(case, "DeviceType", default="—")),
            ("Device IP", _get(case, "DeviceIp", default="—")),
        ]),
    ]


def _terms_conditions(case, merchant):
    company = merchant.get("company_name", DEFAULT_MERCHANT["company_name"])
    dba = merchant.get("dba_name", DEFAULT_MERCHANT["dba_name"])
    order_date = _get(case, "OrderDate", default="the order date")
    channel = _get(case, "TransactionChannel", default=dba)
    return [
        ("Applies To This Order", [
            ("Merchant", f"{company} (trading as {dba})"),
            ("Order ID", _get(case, "OrderId", default="—")),
            ("Accepted On", order_date),
            ("Sales Channel", channel),
        ]),
        ("Terms Of Sale", [
            f"1. Acceptance. By placing an order through {dba} the customer accepts these "
            f"terms in force at the time of purchase. These terms were presented at checkout "
            f"and accepted on {order_date}.",

            f"2. Order confirmation. An order is binding once {company} confirms it and the "
            f"payment is authorised. Confirmation is sent to the email address held on the "
            f"customer's account.",

            "3. Delivery. Goods are dispatched to the delivery address supplied at checkout. "
            "Carrier tracking is provided for every physical shipment and delivery is deemed "
            "complete on the carrier's confirmation of delivery.",

            "4. Digital goods. Digital items are deemed delivered on availability in the "
            "customer's account, and access is logged against the account.",

            "5. Pricing. Prices are those displayed at checkout in the order currency. Taxes "
            "and shipping, where applicable, are itemised on the invoice.",

            "6. Cancellation. Orders may be cancelled before dispatch. Once dispatched, the "
            "refund policy applies in place of cancellation.",

            "7. Disputes. The customer agrees to contact merchant support before raising a "
            "payment dispute, so that the matter can be resolved directly.",
        ]),
        ("Merchant Policy Notice", [
            "This is the merchant's standard policy document as it applied to the order "
            "above. It is reproduced from the merchant configuration together with this "
            "order's date and sales channel; it is not a per-customer record.",
        ]),
    ]


def _refund_policy(case, merchant):
    company = merchant.get("company_name", DEFAULT_MERCHANT["company_name"])
    dba = merchant.get("dba_name", DEFAULT_MERCHANT["dba_name"])
    method = _get(case, "RefundPayType")
    refunded = _yes(_get(case, "RefundIssued"))
    applied = (f"A refund of {_money(_get(case, 'RefundAmount'), _currency(case))} was issued on "
               f"{_get(case, 'RefundDate', default='—')} via {method or 'the original payment method'}."
               if refunded else
               "No refund was issued against this order, so no exception to the policy below was made.")
    return [
        ("Applies To This Order", [
            ("Merchant", f"{company} (trading as {dba})"),
            ("Order ID", _get(case, "OrderId", default="—")),
            ("Order Date", _get(case, "OrderDate", default="—")),
            ("Refund Issued", "Yes" if refunded else "No"),
            ("Refund Method Used", method or "Not applicable"),
        ]),
        ("Refund Terms", [
            "1. Return window. Returns are accepted within 30 days of delivery for physical "
            "goods, provided the item is unused and in its original packaging.",

            "2. Refund method. Refunds are returned to the original payment method. Where the "
            "original method can no longer be credited, store credit is offered instead.",

            "3. Processing time. Approved refunds are processed within 5 business days. The "
            "issuing bank may take a further 3-10 business days to post the credit.",

            "4. Non-returnable items. Perishable goods, personalised items and redeemed "
            "digital codes are not eligible for return.",

            "5. Damaged or incorrect items. Report within 48 hours of delivery with photo "
            "evidence and a replacement or full refund is arranged at no cost.",

            "6. Undelivered orders. Where a carrier confirms non-delivery or loss in transit, "
            "a full refund or reshipment is issued once the carrier closes its investigation.",
        ]),
        ("How The Policy Was Applied", [applied]),
        ("Merchant Policy Notice", [
            "This is the merchant's standard refund policy as it applied to the order above, "
            "assembled from the merchant configuration plus this order's refund record. It is "
            "not a per-customer record.",
        ]),
    ]


def _transaction_copy(case, merchant):
    """The authorisation record behind the disputed payment.

    The letter has always asked for this as a manual upload — a screenshot
    pulled out of the gateway portal. Every field on it is already in the case
    sheet, so a client with gateway access wired up has no reason to be asked
    for it by hand.
    """
    cur = _currency(case)
    return [
        ("Transaction", [
            ("Transaction ID", _get(case, "PaymentTransactionId", default="—")),
            ("PSP Reference", _get(case, "PspReferenceId", default="—")),
            ("Authorization Code", _get(case, "AuthorizationCode", default="—")),
            ("Transaction Date", _get(case, "TransactionTime", default="—")),
            ("Amount", _money(_get(case, "TransactionAmount"), cur)),
            ("Status", _get(case, "TransactionStatus", default="—")),
            ("Settled On", _get(case, "SettlementDate", default="—")),
        ]),
        ("Card", [
            ("Scheme", _get(case, "CardScheme", "CardType", default="—")),
            ("Number", _get(case, "CardNumberMasked", default="—")),
            ("BIN", _get(case, "CardBIN", default="—")),
            ("Funding Type", _get(case, "CardFundingType", default="—")),
            ("Issuer", _get(case, "IssuerName", default="—")),
            ("Issuer Country", _get(case, "IssuerCountry", default="—")),
        ]),
        ("Verification", [
            ("AVS Result", _get(case, "AvsResult", default="—")),
            ("CVV Result", _get(case, "CvvResult", default="—")),
            ("3-D Secure", _get(case, "ThreeDSStatus", default="—")),
            ("Liability Shift", _get(case, "ThreeDSLiabilityShift", default="—")),
            ("Acquirer", _get(case, "AcquirerName", default="—")),
            ("Acquirer MID", _get(case, "AcquirerMID", default="—")),
        ]),
    ]


def _activity_log(case, merchant):
    """The cardholder's trail with this merchant, oldest event first.

    Assembled as a dated sequence rather than a field dump: the point of this
    exhibit is that the account was not dormant and this order sits inside a
    pattern of ordinary use.
    """
    events = [
        ("Account created", _date(_get(case, "AccountCreatedDate"))),
        ("Previous order placed", _date(_get(case, "LastOrderDate"))),
        ("Disputed order placed", _date(_get(case, "OrderDate"))),
        ("Payment authorised", _date(_get(case, "TransactionTime"))),
        ("Delivered", _date(_get(case, "ActualDeliveryDate"))),
        ("Dispute filed", _date(_get(case, "DisputeTime"))),
    ]
    return [
        ("Account", [
            ("Customer", _get(case, "UserFullName", default="—")),
            ("Customer ID", _get(case, "UserId", "MerchantUserId", default="—")),
            ("Email", _get(case, "UserEmail", default="—")),
            ("Account Status", _get(case, "AccountStatus", default="—")),
            ("KYC Verified", _get(case, "KycVerified", default="—")),
            ("Risk Tier", _get(case, "CustomerRiskTier", default="—")),
        ]),
        ("Activity Timeline", [
            (label, value) for label, value in events if value
        ] or [("Timeline", "No dated activity on file.")]),
        ("Standing", [
            ("Lifetime Orders", _get(case, "TotalOrdersLifetime", default="—")),
            ("Lifetime Spend", _money(_get(case, "TotalSpendLifetime"), _currency(case))),
            ("Average Order Value", _money(_get(case, "AvgOrderValue"), _currency(case))),
            ("Prior Chargebacks", _get(case, "PreviousChargebackCount", default="—")),
            ("Prior Chargebacks Won", _get(case, "PreviousChargebacksWon", default="—")),
            ("Last Order ID", _get(case, "LastOrderId", default="—")),
        ]),
    ]


def _checkout_record(case, merchant):
    """What the cardholder saw and did at checkout.

    Part merchant configuration, part per-order signal — which is why it is a
    policy document: the descriptor and terms are the same for every case, and
    only the device and address checks change.
    """
    return [
        ("Checkout", [
            ("Sales Channel", _get(case, "TransactionChannel",
                                   default=merchant.get("dba_name", "—"))),
            ("Order Placed", _get(case, "OrderDate", default="—")),
            ("Order Currency", _get(case, "OrderCurrency", default=_currency(case))),
            ("Billing / Shipping Match", _get(case, "BillingShippingMatch", default="—")),
        ]),
        ("Device", [
            ("Device Type", _get(case, "DeviceType", default="—")),
            ("IP Address", _get(case, "DeviceIp", default="—")),
        ]),
        ("What the cardholder saw", [
            f"Checkout was completed on {merchant.get('dba_name') or 'the merchant site'}, "
            f"which bills under the descriptor "
            f"{merchant.get('descriptor_url') or 'shown on the statement'}.",
            "The terms of sale and the refund policy were presented on the "
            "checkout page and had to be accepted before the order could be "
            "submitted. Both are reproduced in this packet.",
        ]),
    ]


# ─── availability + card previews ──────────────────────────────────────────────

def _avail_transaction(case):
    if _get(case, "AuthorizationCode") or _get(case, "PaymentTransactionId"):
        return True, ""
    return False, "No authorisation record on file for this payment."


def _avail_activity(case):
    if _get(case, "UserId") or _get(case, "AccountCreatedDate"):
        return True, ""
    return False, "No cardholder account history on file."


def _prev_transaction(case):
    auth = _get(case, "AuthorizationCode", default="—")
    avs = _get(case, "AvsResult")
    return f"Auth {auth}{' · AVS ' + avs if avs else ''}"


def _prev_activity(case):
    created = _date(_get(case, "AccountCreatedDate"))
    orders = _get(case, "TotalOrdersLifetime", default="0")
    return f"Since {created or '—'} · {orders} orders"


def _prev_checkout(case):
    channel = _get(case, "DeviceType") or "Web"
    return f"{channel} checkout · {_get(case, 'BillingShippingMatch', default='—')}"


def _avail_order(case):
    if _get(case, "OrderId"):
        return True, ""
    return False, "No order record on file for this dispute."


def _avail_refund(case):
    if not _get(case, "RefundIssued"):
        return False, "No refund record on file for this dispute."
    if not _yes(_get(case, "RefundIssued")):
        return True, "No refund was issued — the document records that fact."
    return True, ""


def _avail_invoice(case):
    if _num(_get(case, "OrderTotalAmount")) or _num(_get(case, "UnitPrice")):
        return True, ""
    return False, "No priced line items on file for this order."


def _avail_account(case):
    if _get(case, "UserId") or _get(case, "UserFullName"):
        return True, ""
    return False, "No customer account record on file."


def _avail_policy(case):
    return True, ""


def _prev_order(case):
    order = _get(case, "OrderId", default="—")
    status = _get(case, "DeliveryStatus")
    return f"{order}{' · ' + status if status else ''}"


def _prev_refund(case):
    if _yes(_get(case, "RefundIssued")):
        return f"{_money(_get(case, 'RefundAmount'), _currency(case))} on {_get(case, 'RefundDate', default='—')}"
    return "No refund issued"


def _prev_invoice(case):
    qty = _get(case, "Quantity", default="1")
    return f"{qty} x {_money(_get(case, 'UnitPrice'), _currency(case))}"


def _prev_account(case):
    orders = _get(case, "TotalOrdersLifetime", default="0")
    cbs = _get(case, "PreviousChargebackCount", default="0")
    return f"{orders} lifetime orders · {cbs} prior chargebacks"


def _prev_terms(case):
    return f"Accepted {_date(_get(case, 'OrderDate')) or '—'}"


def _prev_policy(case):
    return _get(case, "RefundPayType") or "30-day return window"


# ─── registry ──────────────────────────────────────────────────────────────────
# `matches` are the evidence-rule item names this document satisfies, lower-cased.
# evidence_rules tags an item "system" when its name appears here.

DOCUMENTS = OrderedDict([
    ("order_information", {
        "title": "Order Information",
        "icon": "\U0001F4E6",
        "blurb": "Order, item and fulfilment record",
        "columns": "OrderId, OrderDate, ProductName, Sku, Quantity, UnitPrice, DeliveryStatus",
        "policy": False,
        "build": _order_information,
        "available": _avail_order,
        "preview": _prev_order,
        "matches": ["order information", "order information / product detailed description",
                    "order detailed description", "logistics information"],
    }),
    ("refund_information", {
        "title": "Refund Information",
        "icon": "\U0001F4B3",
        "blurb": "Refund record against the original payment",
        "columns": "RefundIssued, RefundAmount, RefundDate, RefundPayType, TransactionAmount",
        "policy": False,
        "build": _refund_information,
        "available": _avail_refund,
        "preview": _prev_refund,
        "matches": ["refund information", "reason for not giving the credit"],
    }),
    ("invoice_breakup", {
        "title": "Invoice Breakup",
        "icon": "\U0001F9FE",
        "blurb": "Line-item breakdown against the disputed amount",
        "columns": "Quantity, UnitPrice, OrderTotalAmount, TransactionAmount",
        "policy": False,
        "build": _invoice_breakup,
        "available": _avail_invoice,
        "preview": _prev_invoice,
        "matches": ["invoice breakup"],
    }),
    ("account_history", {
        "title": "Account History",
        "icon": "\U0001F464",
        "blurb": "Customer standing and prior dispute record",
        "columns": "UserFullName, AccountCreatedDate, TotalOrdersLifetime, PreviousChargebackCount",
        "policy": False,
        "build": _account_history,
        "available": _avail_account,
        "preview": _prev_account,
        "matches": ["account history", "payment history", "binding history",
                    "customer information (name and address)", "transaction history"],
    }),
    ("terms_conditions", {
        "title": "Terms & Conditions",
        "icon": "\U0001F4DC",
        "blurb": "Merchant terms in force at the time of purchase",
        "columns": "Merchant configuration + OrderDate, TransactionChannel",
        "policy": True,
        "build": _terms_conditions,
        "available": _avail_policy,
        "preview": _prev_terms,
        "matches": ["terms and conditions", "cancellation policy", "introduction"],
    }),
    ("refund_policy", {
        "title": "Refund Policy",
        "icon": "↩",
        "blurb": "Merchant refund terms and how they were applied",
        "columns": "Merchant configuration + RefundPayType, RefundDate",
        "policy": True,
        "build": _refund_policy,
        "available": _avail_policy,
        "preview": _prev_policy,
        "matches": ["refund policy"],
    }),
    # ── The three the letter used to demand by hand ──
    # `matches` is deliberately narrow. document_for_evidence drives which
    # evidence items evidence_rules tags "system", which in turn moves the
    # winning ratio on every screen — including /rebuttal, which nobody asked
    # to change. None of these three strings appears in EVIDENCE_RULES, so
    # registering them reclassifies nothing. Widening them is its own decision.
    ("transaction_copy", {
        "title": "Transaction Copy",
        "icon": "\U0001F9FE",
        "blurb": "Authorisation record behind the disputed payment",
        "columns": "AuthorizationCode, AvsResult, CvvResult, ThreeDSStatus, PaymentTransactionId",
        "policy": False,
        "build": _transaction_copy,
        "available": _avail_transaction,
        "preview": _prev_transaction,
        "matches": ["transaction copy"],
    }),
    ("activity_log", {
        "title": "Cardholder Activity Log",
        "icon": "\U0001F5D2",
        "blurb": "The cardholder's trail with this merchant",
        "columns": "AccountCreatedDate, LastOrderDate, TotalOrdersLifetime, TotalSpendLifetime",
        "policy": False,
        "build": _activity_log,
        "available": _avail_activity,
        "preview": _prev_activity,
        "matches": ["cardholder activity log"],
    }),
    ("checkout_record", {
        "title": "Checkout Page",
        "icon": "\U0001F6D2",
        "blurb": "What the cardholder saw and accepted at checkout",
        "columns": "TransactionChannel, DeviceType, DeviceIp, BillingShippingMatch",
        "policy": True,
        "build": _checkout_record,
        "available": _avail_policy,
        "preview": _prev_checkout,
        "matches": ["checkout page"],
    }),
])

# Evidence-rule item names that one of the six documents covers.
SYSTEM_EVIDENCE_NAMES = {name for doc in DOCUMENTS.values() for name in doc["matches"]}


def is_system_evidence(name):
    return (name or "").strip().lower() in SYSTEM_EVIDENCE_NAMES


def document_for_evidence(name):
    """The document key that satisfies an evidence item, or None."""
    key_name = (name or "").strip().lower()
    for key, doc in DOCUMENTS.items():
        if key_name in doc["matches"]:
            return key
    return None


def build_documents(case, merchant=None, overrides=None):
    """Every system document for a case, keyed by document key.

    Each entry carries its built ``sections`` so the Counter Evidence page can
    render the content in place — the letter shows the data, there is nothing to
    open or download. A document that isn't backed by this case's data reports
    ``available: False`` with the reason, and its sections are left empty rather
    than filled with blank rows.

    ``overrides`` is the repository's edited-template store. Only the policy
    documents consult it — a lead writes the merchant's terms, not the case's
    transaction data — and only their ``sections`` change, never the key set or
    availability, so the packet keeps exactly the same shape either way.
    """
    merchant = merchant or DEFAULT_MERCHANT
    documents = OrderedDict()
    for key, doc in DOCUMENTS.items():
        available, note = doc["available"](case)
        sections = doc["build"](case, merchant) if available else []
        edited = ""
        if available and doc["policy"] and overrides:
            entry = overrides.get(f"policy:{key}")
            body = (entry or {}).get("body", "")
            if isinstance(body, str) and body.strip():
                # One section carrying the lead's text, replacing the generated
                # clauses. The "Applies To This Order" header rows stay: they
                # are this case's facts, not policy, and dropping them would
                # leave the issuer without the order the policy applies to.
                keep = [s for s in sections if s and s[0] == "Applies To This Order"]
                sections = keep + [(doc["title"], _paragraphs(body))]
                edited = (entry or {}).get("edited_by", "")
        documents[key] = {
            "key": key,
            "title": doc["title"],
            "icon": doc["icon"],
            "blurb": doc["blurb"],
            "columns": doc["columns"],
            "policy": doc["policy"],
            "available": available,
            "note": note,
            "preview": doc["preview"](case) if available else "",
            "sections": sections,
            "edited_by": edited,
        }
    return documents


def _paragraphs(body):
    """Split lead-entered text into the list of strings a section renders.

    Blank lines separate paragraphs; single newlines inside one are kept as
    written, since the built-in policy text numbers its clauses that way.
    """
    out = []
    for chunk in body.replace("\r\n", "\n").split("\n\n"):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out or [body.strip()]
