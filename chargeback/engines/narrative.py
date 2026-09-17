"""The prose blocks of the counter evidence rebuttal.

These eleven strings were hardcoded Jinja inside ``counter_evidence.html``. They
rendered into ``<textarea>`` boxes that anyone could type in and nothing ever
saved — reloading the page discarded every edit.

They live here now as templates with ``{placeholder}`` tokens so an edit is
portable: text captured from a rendered box would have this case's order id and
amount baked into it, which is wrong for anything meant to apply to other cases.
Tokens resolve through ``cover_letter.letter_context``, the same vocabulary the
representment letter uses.

BUILT_IN is a faithful transcription of what the page said before, token for
token and fallback for fallback. It is the bottom of the resolution cascade and
is never written to, which is what makes "reset to built-in" a delete.
"""

from collections import OrderedDict


class NarrativeBlocks:
    """What is editable on the counter evidence page, and what it falls back to."""

    # Page order. `section` names the evidence section the block introduces, or
    # None for the two blocks that stand on their own.
    BLOCKS = OrderedDict([
        ("letter_body", {
            "label": "Letter body",
            "rows": 17,
            "section": None,
        }),
        ("intro_transaction_copy", {
            "label": "Transaction Copy",
            "rows": 3,
            "section": "transaction_copy",
        }),
        ("intro_order_confirmation", {
            "label": "Order Confirmation",
            "rows": 2,
            "section": "order_information",
        }),
        ("intro_invoice_breakup", {
            "label": "Invoice Breakup",
            "rows": 2,
            "section": "invoice_breakup",
        }),
        ("intro_refund_information", {
            "label": "Refund Information",
            "rows": 2,
            "section": "refund_information",
        }),
        ("intro_account_history", {
            "label": "Cardholder Registration and Order History",
            "rows": 2,
            "section": "account_history",
        }),
        ("intro_activity_log", {
            "label": "Cardholder Activity Log",
            "rows": 2,
            "section": "activity_log",
        }),
        ("intro_checkout_record", {
            "label": "Checkout Page",
            "rows": 2,
            "section": "checkout_record",
        }),
        ("intro_terms_conditions", {
            "label": "Terms & Conditions",
            "rows": 2,
            "section": "terms_conditions",
        }),
        ("intro_refund_policy", {
            "label": "Refund Policy",
            "rows": 2,
            "section": "refund_policy",
        }),
        ("conclusion", {
            "label": "Conclusion",
            "rows": 3,
            "section": None,
        }),
    ])

    BUILT_IN = {
        "letter_body": (
            "Dear {upper_CRT} Processing Team,\n"
            "\n"
            "{merchantname} specializes in selling {specialized_in}. All our programs are sold "
            "online using our secure website. On {disputedate}, we received a {lower_CRT} under "
            "RC {reasoncode} in the amount of {chargebackamt} {currency}.\n"
            "\n"
            "We strongly believe the {lower_CRT} filed by the Cardholder for the above case "
            "number is not valid because the compelling evidence attached with this letter shows "
            "that the transaction is valid, and the Cardholder is well aware of the transaction "
            "and its terms prior to purchase.\n"
            "\n"
            "{reasondescription}. Our records show order {orderid} placed on {transactiondate}.\n"
            "\n"
            "Below are the Cardholder's details recorded in our system:\n"
            "\n"
            "{upper_CRT} Cardholder Name: {cardholdername}\n"
            "Email Address: {cardholderemail}\n"
            "Phone Number: {cardholderphone}"
        ),
        "intro_transaction_copy": (
            "The Cardholder placed an online order on our website for purchasing our program in "
            "the amount of {transactionamt} {currency} on {transactiondate} with authorization "
            "code {authcode} pertaining to transaction ID {paymentref}. Accurate credit card, "
            "name: {cardholdername}, and valid billing information was provided at the time of "
            "the purchase, all of which proves the Cardholder willingly engaged in the "
            "transaction.\n"
            "\n"
            "The attached transaction copy shows AVS as {avscode}, CVV as {cvvcode} and 3D "
            "Secure as {threedsecure}. This copy was taken from the Payment Gateway."
        ),
        "intro_order_confirmation": (
            "The copy of order confirmation for Order ID: {orderid} is provided below that "
            "outlines the program purchased, the delivery record and the billing address."
        ),
        "intro_invoice_breakup": (
            "The invoice below itemises what the Cardholder was billed and reconciles the "
            "invoice total against the amount captured and the amount now disputed."
        ),
        "intro_refund_information": (
            "Our refund record for this order is set out below, showing what was returned to "
            "the Cardholder, when, and by which method, against the original payment."
        ),
        "intro_account_history": (
            "The Cardholder holds a registered account with us. Their registration details, "
            "purchase history and prior dispute record are set out below."
        ),
        "intro_activity_log": (
            "The Cardholder has logged into our membership portal at various times and the "
            "detailed activity log history with date and time stamp is attached which proves "
            "that the Cardholder has used our service."
        ),
        "intro_checkout_record": (
            "The Cardholder has also agreed at the time of purchase to all our terms clearly "
            "outlined in our website."
        ),
        "intro_terms_conditions": (
            "The Cardholder accepted the terms below at the time of purchase. They are "
            "reproduced in full as they stood on the order date."
        ),
        "intro_refund_policy": (
            "The Cardholder has also agreed at the time of purchase to all the refund and "
            "cancellation policies clearly outlined in our website, reproduced below with a "
            "note on how they were applied to this order."
        ),
        "conclusion": (
            "All charges are accurate. The above evidence supports that the Cardholder "
            "willingly engaged in the transaction and received what was purchased, therefore "
            "we are asking for your consideration to reverse this {lower_CRT} in our favor."
        ),
    }

    # The tokens offered in the editor. Not the full context — that carries
    # keys only the representment letter uses, and listing those here would
    # invite them into prose that has no business with them.
    PLACEHOLDERS = [
        "{upper_CRT}", "{lower_CRT}", "{merchantname}", "{orderid}", "{reasoncode}",
        "{chargebackamt}", "{currency}", "{disputedate}", "{transactiondate}",
        "{transactionamt}", "{authcode}", "{paymentref}", "{avscode}", "{cvvcode}",
        "{threedsecure}", "{cardholdername}", "{cardholderemail}", "{cardholderphone}",
    ]

    @classmethod
    def store_key(cls, block_id, scope):
        """Template store key. `scope` is a reason category or "default"."""
        return f"narrative:{block_id}:{scope}"

    @classmethod
    def valid_block(cls, block_id):
        return block_id in cls.BLOCKS

    @classmethod
    def raw(cls, block_id, category, case_text, overrides):
        """The unrendered text for a block, and which level it came from.

        The cascade, most specific first. Level 4 is the built-in, which is
        never stored, so clearing any level falls through to the one below it
        rather than leaving a hole.
        """
        if case_text:
            return case_text, "case"
        overrides = overrides or {}
        if category:
            entry = overrides.get(cls.store_key(block_id, category))
            if entry and entry.get("text"):
                return entry["text"], "category"
        entry = overrides.get(cls.store_key(block_id, "default"))
        if entry and entry.get("text"):
            return entry["text"], "default"
        return cls.BUILT_IN.get(block_id, ""), "builtin"

    @classmethod
    def resolve(cls, block_id, ctx, category=None, case_text=None, overrides=None):
        """Rendered text for a block, plus where it came from and who set it."""
        from chargeback.engines.repository import safe_format

        text, level = cls.raw(block_id, category, case_text, overrides)
        entry = {}
        if level in ("category", "default"):
            entry = (overrides or {}).get(cls.store_key(block_id, category if level == "category"
                                                        else "default")) or {}
        return {
            "id": block_id,
            "label": cls.BLOCKS[block_id]["label"],
            "rows": cls.BLOCKS[block_id]["rows"],
            "text": safe_format(text, ctx),
            "raw": text,
            "level": level,
            "edited_by": entry.get("edited_by", ""),
            "edited_at": entry.get("edited_at", ""),
        }

    @classmethod
    def resolve_all(cls, ctx, category=None, case_texts=None, overrides=None):
        """Every block for one case, keyed by block id, in page order."""
        case_texts = case_texts or {}
        return OrderedDict(
            (block_id, cls.resolve(block_id, ctx, category,
                                   case_texts.get(block_id), overrides))
            for block_id in cls.BLOCKS)
