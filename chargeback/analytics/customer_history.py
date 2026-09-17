"""A customer's other chargebacks in this book.

Chargeback teams work repeat abusers, so the question a case page has to answer
is "have we seen this person before?". The identifiers that can answer it are
the card, the email, the phone and the name — but they are not equally good, and
treating them as if they were is how one customer's dispute record ends up
displayed under another customer's case.

  Card, email, phone are *strong*: sharing one is evidence of the same person.
  A name is *weak*: in the shipped book, 18 of the 24 same-name pairs share no
  card, no email and no phone. Two different Wayan Browns, one on +62 and one
  on +1, with different cards. Linking those would be wrong.

So the two are kept apart. `confirmed` is a match on a strong identifier and
says which one; `same_name` is a name collision with nothing behind it, returned
separately so the page can show it as the unconfirmed thing it is rather than
folding it into the record.

Requiring *all four* to match — the strictest reading — returns nothing at all:
UserPhone and UserId are unique on all 100 rows, so no two cases can ever agree
on them.
"""

STRONG_KEYS = [
    ("CardNumberMasked", "card number"),
    ("UserEmail", "email"),
    ("UserPhone", "phone"),
]

WEAK_KEY = ("UserFullName", "name")


def _src(case):
    """The raw sheet row behind a case — empty for seeded cases that have none."""
    return case.get("source") or {}


def _value(case, column):
    value = (_src(case).get(column) or "").strip()
    # Never match on a placeholder. Two cases both missing an email are not the
    # same customer, and the digital-goods rows carry literal "N/A" strings.
    return "" if value.upper().startswith("N/A") else value


class CustomerHistory:
    """Other cases belonging to the same customer as a given case."""

    @classmethod
    def _row(cls, case, matched_on):
        return {
            "case_id": case.get("case_id", ""),
            "matched_on": matched_on,
            "dispute_date": (case.get("dispute_creation_date", "") or "")[:10],
            "network": case.get("payment_method", ""),
            "reason_code": case.get("reason_code", ""),
            "reason_description": case.get("reason_description", "") or case.get("scenario", ""),
            "amount": case.get("amount", 0),
            "currency": case.get("currency", "USD"),
            "outcome": case.get("case_status") or case.get("outcome", ""),
            "customer": _value(case, "UserFullName"),
        }

    @classmethod
    def profile(cls, case):
        """What the issuer says about this customer, straight off the row.

        Populated on every row of the sheet, so the pane still says something
        useful about a customer with no other case in the book — and "0 prior
        chargebacks" is a real answer, not an empty one.
        """
        src = _src(case)

        def num(column):
            try:
                return float(src.get(column) or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "name": _value(case, "UserFullName"),
            "customer_id": _value(case, "UserId"),
            "email": _value(case, "UserEmail"),
            "phone": _value(case, "UserPhone"),
            "card": _value(case, "CardNumberMasked"),
            "account_created": _value(case, "AccountCreatedDate"),
            "account_status": _value(case, "AccountStatus"),
            "kyc_verified": _value(case, "KycVerified"),
            "risk_tier": _value(case, "CustomerRiskTier"),
            "lifetime_orders": int(num("TotalOrdersLifetime")),
            "lifetime_spend": num("TotalSpendLifetime"),
            "prior_chargebacks": int(num("PreviousChargebackCount")),
            "prior_won": int(num("PreviousChargebacksWon")),
            "dispute_rate_pct": num("DisputeRatePct"),
            "has_sheet_row": bool(src),
        }

    @classmethod
    def for_case(cls, case, all_cases):
        """{confirmed, same_name, profile, searched} for one case.

        `searched` names the identifiers actually available on this case, so an
        empty result reads as an answer rather than as a broken feature.
        """
        this_id = case.get("case_id")
        mine = {column: _value(case, column) for column, _label in STRONG_KEYS}
        my_name = _value(case, WEAK_KEY[0])

        confirmed, same_name = [], []
        for other in all_cases or []:
            if other.get("case_id") == this_id:
                continue
            matched = [label for column, label in STRONG_KEYS
                       if mine[column] and _value(other, column) == mine[column]]
            if matched:
                confirmed.append(cls._row(other, matched))
            elif my_name and _value(other, WEAK_KEY[0]) == my_name:
                same_name.append(cls._row(other, [WEAK_KEY[1]]))

        confirmed.sort(key=lambda r: (r["dispute_date"], r["case_id"]), reverse=True)
        same_name.sort(key=lambda r: (r["dispute_date"], r["case_id"]), reverse=True)

        searched = [label for column, label in STRONG_KEYS if mine[column]]
        if my_name:
            searched.append(WEAK_KEY[1])

        return {
            "confirmed": confirmed,
            "same_name": same_name,
            "profile": cls.profile(case),
            "searched": searched,
            "total": len(confirmed) + len(same_name),
        }
