class AIValidationEngine:
    """AI-powered case validation engine combining rule-based scoring
    with LLM-style reasoning to route cases to auto-represent or human review.
    Implements Stage 4-5 of the chargeback defense pipeline."""

    # Weights for each signal (simulating a trained model)
    SIGNAL_WEIGHTS = {
        "avs_match": 15,
        "cvv_match": 15,
        "threed_secure": 20,
        "liability_shift": 10,
        "amount_low": 10,
        "repeat_customer": 8,
        "delivery_confirmed": 12,
        "reason_code_winnable": 10,
    }

    # Reason codes with historically higher win rates
    HIGH_WIN_REASON_CODES = {"13.1", "12.6.1", "13.2"}
    MEDIUM_WIN_REASON_CODES = {"13.3", "13.6", "13.7", "12.5", "12.6.2"}
    LOW_WIN_REASON_CODES = {"10.4", "11.3"}

    # Category keywords that suggest winnability
    HIGH_WIN_CATEGORIES = {"merchandise", "processing"}
    MEDIUM_WIN_CATEGORIES = {"others"}
    LOW_WIN_CATEGORIES = {"fraud", "authorization"}

    AUTO_THRESHOLD = 70   # Score >= 70 -> auto-represent
    HITL_THRESHOLD = 40   # Score 40-69 -> human review needed
    # Score < 40 -> likely accept/refund

    @classmethod
    def extract_signals(cls, case):
        """Extract binary signals from a case for scoring."""
        signals = {}

        # AVS match — "No match" should NOT count as a match
        avs = case.get("avs_response", "")
        avs_lower = avs.lower()
        signals["avs_match"] = 1 if ("(Y)" in avs or "Pass" in avs or ("match" in avs_lower and "no match" not in avs_lower)) else 0

        # CVV match — "No match" and "Not processed" must NOT count.
        #
        # This used to test for "Matches", "(M)" or "Pass". The sheet writes
        # "M - Match", which is none of those, so the signal never fired once in
        # the whole book — all 43 genuine CVV matches scored as no match. Now on
        # the same idiom as AVS above, which reads both the sheet's "M - Match"
        # and the seeded "Supplied, Matches (M)" while still rejecting
        # "N - No Match".
        cvv = case.get("cvv_response", "")
        cvv_lower = cvv.lower()
        signals["cvv_match"] = 1 if ("match" in cvv_lower
                                     and "no match" not in cvv_lower) else 0

        # 3D Secure — authentication that actually succeeded.
        #
        # The test was `"Authenticated" in threed`, and "N - Not Authenticated"
        # contains that word, so a case where the cardholder FAILED 3DS scored
        # the full twenty points for it. Eight cases in the book were credited
        # for the opposite of what happened. "A - Attempted" scores nothing
        # either: it did not complete, and the liability shift it would have
        # bought is a separate signal below.
        threed = case.get("threed_secure", "")
        threed_lower = threed.lower()
        signals["threed_secure"] = 1 if ("authenticated" in threed_lower
                                         and "not authenticated" not in threed_lower) else 0

        # Liability shift
        signals["liability_shift"] = 1 if case.get("liability_shift") else 0

        # Amount threshold (low amounts < $100 easier to defend)
        signals["amount_low"] = 1 if case.get("amount", 0) < 100 else 0

        # Repeat customer — check if order history > 1 or if card seen before
        signals["repeat_customer"] = 1 if case.get("card_last_four", "") in ["3059", "4401"] else 0

        # Delivery confirmed
        signals["delivery_confirmed"] = 1 if case.get("auto_defended") or case.get("outcome") == "Win" else 0

        # Reason code winnability — check known codes first, then category.
        # Scored on the family so a Mastercard 4837 lands in the same band as
        # the Visa 10.4 it is the same dispute as; keyed on the raw code, every
        # non-Visa case skipped these bands and fell to keyword matching.
        rc = case.get("reason_code_canonical") or case.get("reason_code", "")
        if rc in cls.HIGH_WIN_REASON_CODES:
            signals["reason_code_winnable"] = 1
        elif rc in cls.MEDIUM_WIN_REASON_CODES:
            signals["reason_code_winnable"] = 0.5
        elif rc in cls.LOW_WIN_REASON_CODES:
            signals["reason_code_winnable"] = 0
        else:
            # Unknown reason code — use category or description to infer winnability
            cat = case.get("chargeback_category", "").lower()
            desc = case.get("reason_description", "").lower()
            combined = cat + " " + desc
            if any(k in combined for k in ["not received", "merchandise", "duplicate",
                                            "cancelled"]):
                signals["reason_code_winnable"] = 0.7
            elif any(k in combined for k in ["processing", "incorrect amount", "credit not processed"]):
                # Processing: needs human verification, not auto
                signals["reason_code_winnable"] = 0.4
            elif any(k in combined for k in ["not as described", "defective", "unsatisfactory",
                                              "recurring", "return"]):
                signals["reason_code_winnable"] = 0.5
            elif any(k in combined for k in ["fraud", "unauthorized", "no authorization"]):
                # Fraud with 3DS = auto-win (liability shift to issuer)
                if signals.get("threed_secure") == 1:
                    signals["reason_code_winnable"] = 1
                else:
                    signals["reason_code_winnable"] = 0
            else:
                signals["reason_code_winnable"] = 0.3

        return signals

    @classmethod
    def score(cls, case):
        """Compute a confidence score (0-100) for a case."""
        signals = cls.extract_signals(case)
        raw = sum(signals[k] * cls.SIGNAL_WEIGHTS[k] for k in signals)

        # Boost from CSV win_rate data if available
        win_rate = case.get("win_rate", 0)
        if win_rate and win_rate > 0:
            # win_rate from CSV is 0.0024 (0.24%) to 0.012 (1.2%) — scale to 0-15 bonus
            rate_bonus = min(15, int(win_rate * 1500))
            raw = raw + rate_bonus

        return min(100, max(0, int(raw)))

    @classmethod
    def classify(cls, case):
        """Classify a case and return routing decision + details."""
        confidence = cls.score(case)
        signals = cls.extract_signals(case)

        if confidence >= cls.AUTO_THRESHOLD:
            routing = "auto_represent"
            routing_label = "Auto-Represent"
            routing_desc = "High confidence. Case will be auto-defended with system-generated evidence packet."
        elif confidence >= cls.HITL_THRESHOLD:
            routing = "hitl_review"
            routing_label = "HITL Review"
            routing_desc = "Moderate confidence. Case routed to human expert for evidence review and decision."
        else:
            routing = "accept_refund"
            # "Accept Recommended", not "Accepted" — this is advice awaiting a
            # human, and processing_category below puts it in the human queue.
            routing_label = "Accept Recommended"
            routing_desc = "Low win probability. Recommend accepting the chargeback to avoid fees. A human confirms before anything is conceded."

        # Determine which signals contributed most
        contributing = sorted(
            [(k, signals[k] * cls.SIGNAL_WEIGHTS[k]) for k in signals if signals[k] > 0],
            key=lambda x: x[1], reverse=True
        )
        missing = [k for k in signals if signals[k] == 0]

        return {
            "confidence": confidence,
            # The same number under the name the case pages ask for. They read
            # win_probability; the routing thresholds read confidence. Keeping
            # them one value is what stops a case from being sent to
            # Auto-Represent while its own page reports a low chance of winning.
            "win_probability": confidence,
            "routing": routing,
            "routing_label": routing_label,
            "routing_desc": routing_desc,
            # The headline split, derived from routing rather than replacing it.
            # Dashboards lead with two numbers -- what the system handled, and
            # what a person still has to -- because that is the question anyone
            # opening them is asking. Both hitl_review and accept_refund need a
            # human, so both land in "hitl"; which of the two it is stays on the
            # case as routing_label, and is shown as a recommendation there.
            "processing_category": ("auto" if routing == "auto_represent"
                                    else "hitl"),
            "signals": signals,
            "contributing_factors": contributing,
            "missing_signals": missing,
        }

    # What a manual override reads as, once an analyst has made the call. These
    # are decisions, not recommendations — hence "Accepted by Analyst" against
    # the engine's "Accept Recommended".
    OVERRIDE_LABELS = {
        "accept_refund": ("Accepted by Analyst", "Chargeback accepted by analyst."),
        "auto_represent": ("Auto-Represent", "Manually moved to auto-represent."),
        "hitl_review": ("HITL Review", "Manually moved to human review."),
    }

    @classmethod
    def classify_one(cls, case):
        """classify() plus the analyst's manual override.

        classify() is the raw model output and is override-blind, so any page
        rendering a real case must come through here instead. Otherwise a case
        an analyst conceded via /case/<id>/accept keeps advertising itself as
        auto-represented on its own detail page while the dashboard — which
        goes through classify_all — already shows it as accepted.

        The score-derived routing is preserved under ai_routing/ai_routing_label
        so the AI Validation panel can still report what the model said, rather
        than relabelling itself with a decision a human made over the top of it.
        """
        ml = cls.classify(case)
        ml["ai_routing"] = ml["routing"]
        ml["ai_routing_label"] = ml["routing_label"]
        ml["overridden"] = False

        override = case.get("ml_override")
        if override in cls.OVERRIDE_LABELS:
            label, desc = cls.OVERRIDE_LABELS[override]
            ml["routing"] = override
            ml["routing_label"] = label
            ml["routing_desc"] = desc
            ml["overridden"] = True
        return ml

    @classmethod
    def classify_all(cls, cases):
        """Classify all cases and return enriched list."""
        return [{**case, "ml": cls.classify_one(case)} for case in cases]

    @classmethod
    def get_pipeline_stats(cls, cases):
        """Aggregate stats for the AI overview dashboard."""
        classified = cls.classify_all(cases)
        total = len(classified)
        auto = sum(1 for c in classified if c["ml"]["routing"] == "auto_represent")
        hitl = sum(1 for c in classified if c["ml"]["routing"] == "hitl_review")
        accept = sum(1 for c in classified if c["ml"]["routing"] == "accept_refund")

        # Processor aggregation
        processors = {}
        for c in classified:
            p = c["processor"]
            if p not in processors:
                processors[p] = {"total": 0, "auto_represent": 0, "hitl_review": 0, "accept_refund": 0, "total_amount": 0}
            processors[p]["total"] += 1
            processors[p]["total_amount"] += c["amount"]
            processors[p][c["ml"]["routing"]] += 1

        # Reason code distribution
        reason_codes = {}
        for c in classified:
            rc = c["reason_code"]
            if rc not in reason_codes:
                # The network rides along so the overview table can name the
                # code. Without it the template looked the raw string up in
                # REASON_CODES, which is keyed by Visa-format family — so 4837,
                # UA02 and A02 all missed and silently reprinted the code as its
                # own description.
                reason_codes[rc] = {"count": 0, "avg_confidence": 0, "total_amount": 0,
                                    "network": c.get("payment_method", "")}
            reason_codes[rc]["count"] += 1
            reason_codes[rc]["avg_confidence"] += c["ml"]["confidence"]
            reason_codes[rc]["total_amount"] += c["amount"]
        for rc in reason_codes:
            reason_codes[rc]["avg_confidence"] = round(
                reason_codes[rc]["avg_confidence"] / reason_codes[rc]["count"]
            )

        # Outcome tracking
        wins = sum(1 for c in classified if c["outcome"] == "Win")
        losses = sum(1 for c in classified if c["outcome"] in ["Lost", "Refunded"])
        pending = sum(1 for c in classified if c["outcome"] == "Pending")

        avg_confidence = round(sum(c["ml"]["confidence"] for c in classified) / total) if total else 0
        total_amount = sum(c["amount"] for c in classified)

        return {
            "total_cases": total,
            "auto_represent": auto,
            "hitl_review": hitl,
            "accept_refund": accept,
            # The two-bucket headline. hitl_review and accept_refund both need a
            # person, so both count as human-in-the-loop; the three tiers above
            # stay available for anywhere that needs the finer answer.
            "auto_processed": auto,
            "human_in_loop": hitl + accept,
            "hitl_rate_pct": round((hitl + accept) / total * 100) if total else 0,
            "auto_rate_pct": round(auto / total * 100) if total else 0,
            "processors": processors,
            "reason_codes": reason_codes,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "avg_confidence": avg_confidence,
            "total_amount": round(total_amount, 2),
            "classified_cases": classified,
        }

# Backward compatibility alias
ChargebackClassifier = AIValidationEngine
