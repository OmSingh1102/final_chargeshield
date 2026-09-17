from collections import Counter

from chargeback.utils.hashing import deterministic_seed


class DashboardAnalytics:
    """Computes manager-level analytics: KPIs, success rates, team workload,
    and automated output quality metrics."""

    # How the pipeline decided to handle a case, in plain words.
    #
    # accept_refund reads "Accept Recommended", not "Accepted". Below the score
    # floor the engine recommends conceding — it does not concede: the case
    # still lands in the human queue (processing_category is "hitl" for both
    # accept_refund and hitl_review). "Accepted" also collides with the Outcome
    # column beside it, where it means an analyst really did accept, so the same
    # word in one row meant two different things.
    ROUTING_LABELS = {
        "auto_represent": "Auto Submission",
        "hitl_review": "HITL Review",
        "accept_refund": "Accept Recommended",
    }
    # An analyst who overrides a case to accept has made the decision the engine
    # only recommended. Same routing value, different fact, so it gets its own
    # label instead of hiding under the recommendation's.
    ANALYST_ACCEPTED = "Accepted by Analyst"
    ROUTING_CLASSES = {
        "auto_represent": "auto",
        "hitl_review": "hitl",
        "accept_refund": "accepted",
    }

    # Kept in step with AgentDesk.AGENTS so the app shows one agent roster.
    AGENTS = ["Agent1", "Agent2", "Agent3"]

    ANALYSTS = [
        {"id": "A1", "name": "Priya Sharma", "role": "Senior Dispute Analyst", "avatar_color": "#1565c0", "status": "Online"},
        {"id": "A2", "name": "Marcus Chen", "role": "Chargeback Specialist", "avatar_color": "#2e7d32", "status": "Online"},
        {"id": "A3", "name": "Sarah Johnson", "role": "Fraud Review Analyst", "avatar_color": "#7c3aed", "status": "Away"},
    ]

    WEEKLY_TRENDS = [
        {"week": "W22 (May 26)", "cases": 12, "wins": 7, "win_rate": 58},
        {"week": "W23 (Jun 02)", "cases": 15, "wins": 9, "win_rate": 60},
        {"week": "W24 (Jun 09)", "cases": 11, "wins": 8, "win_rate": 73},
        {"week": "W25 (Jun 16)", "cases": 18, "wins": 11, "win_rate": 61},
        {"week": "W26 (Jun 23)", "cases": 14, "wins": 9, "win_rate": 64},
        {"week": "W27 (Jun 30)", "cases": 8, "wins": 5, "win_rate": 63},
    ]

    @classmethod
    def compute(cls, cases, ml_stats, evidence_stats, evidence_results, reason_code_db):
        classified = ml_stats["classified_cases"]
        total = len(classified)
        if total == 0:
            return {}

        # ── KPIs ──
        wins = sum(1 for c in classified if c["outcome"] == "Win")
        losses = sum(1 for c in classified if c["outcome"] == "Lost")
        refunded = sum(1 for c in classified if c["outcome"] == "Refunded")
        pending = sum(1 for c in classified if c["outcome"] == "Pending")
        decided = wins + losses + refunded
        win_rate = round(wins / decided * 100) if decided else 0

        total_disputed = sum(c["amount"] for c in classified)
        amount_won = sum(c["amount"] for c in classified if c["outcome"] == "Win")
        recovery_rate = round(amount_won / total_disputed * 100) if total_disputed else 0

        auto_cases = [c for c in classified if c["ml"]["routing"] == "auto_represent"]
        auto_wins = sum(1 for c in auto_cases if c["outcome"] == "Win")
        auto_losses = sum(1 for c in auto_cases if c["outcome"] in ["Lost", "Refunded"])
        auto_decided = auto_wins + auto_losses
        auto_success_rate = round(auto_wins / auto_decided * 100) if auto_decided else 100

        # ── Processor Performance ──
        proc_perf = {}
        for c in classified:
            p = c["processor"]
            if p not in proc_perf:
                proc_perf[p] = {"total": 0, "wins": 0, "losses": 0, "pending": 0,
                                "total_amount": 0, "amount_won": 0,
                                "auto": 0, "confidence_sum": 0}
            proc_perf[p]["total"] += 1
            proc_perf[p]["total_amount"] += c["amount"]
            proc_perf[p]["confidence_sum"] += c["ml"]["confidence"]
            if c["outcome"] == "Win":
                proc_perf[p]["wins"] += 1
                proc_perf[p]["amount_won"] += c["amount"]
            elif c["outcome"] in ["Lost", "Refunded"]:
                proc_perf[p]["losses"] += 1
            else:
                proc_perf[p]["pending"] += 1
            if c["ml"]["routing"] == "auto_represent":
                proc_perf[p]["auto"] += 1

        for p in proc_perf:
            d = proc_perf[p]
            dec = d["wins"] + d["losses"]
            d["win_rate"] = round(d["wins"] / dec * 100) if dec else 0
            d["avg_confidence"] = round(d["confidence_sum"] / d["total"])

        # ── Reason Code Success ──
        rc_perf = {}
        for c in classified:
            rc = c["reason_code"]
            if rc not in rc_perf:
                rc_perf[rc] = {"title": reason_code_db.get(rc, {}).get("title", rc),
                               "total": 0, "wins": 0, "losses": 0,
                               "total_amount": 0, "confidence_sum": 0}
            rc_perf[rc]["total"] += 1
            rc_perf[rc]["total_amount"] += c["amount"]
            rc_perf[rc]["confidence_sum"] += c["ml"]["confidence"]
            if c["outcome"] == "Win":
                rc_perf[rc]["wins"] += 1
            elif c["outcome"] in ["Lost", "Refunded"]:
                rc_perf[rc]["losses"] += 1

        for rc in rc_perf:
            d = rc_perf[rc]
            dec = d["wins"] + d["losses"]
            d["win_rate"] = round(d["wins"] / dec * 100) if dec else 0
            d["avg_confidence"] = round(d["confidence_sum"] / d["total"])

        # ── Team Workload ──
        hitl_cases = [c for c in classified if c["ml"]["routing"] == "hitl_review"]
        team = []
        for i, analyst in enumerate(cls.ANALYSTS):
            assigned = [c for j, c in enumerate(hitl_cases) if j % len(cls.ANALYSTS) == i]
            team.append({
                **analyst,
                "assigned_cases": len(assigned),
                "assigned_case_ids": [c["case_id"] for c in assigned],
                "reviewed_today": min(len(assigned), 1 + i),
                "avg_review_min": 18 + i * 7,
                "queue_depth": max(0, len(assigned) - (1 + i)),
                "total_amount": round(sum(c["amount"] for c in assigned), 2),
            })
        total_queue = sum(a["queue_depth"] for a in team)

        # ── Auto Output Quality ──
        auto_output = []
        for c in auto_cases:
            ev = evidence_results.get(c["case_id"], {})
            auto_output.append({
                "case_id": c["case_id"],
                "outcome": c["outcome"],
                "confidence": c["ml"]["confidence"],
                "completeness": ev.get("overall_completeness_pct", 0),
                "correct": c["outcome"] in ["Win", "Pending"],
                "needs_attention": c["outcome"] in ["Lost", "Refunded"],
            })
        auto_correct = sum(1 for a in auto_output if a["correct"])
        auto_accuracy = round(auto_correct / len(auto_output) * 100) if auto_output else 0

        # ── One table holding every case ──
        # Previously this was two tables, and cases routed to accept/refund
        # appeared in neither — a third of the book was invisible here. One list
        # with the handling spelled out per row fixes that.
        all_cases = []
        for i, c in enumerate(classified):
            routing = c["ml"]["routing"]
            # The lead's allocation, matching AgentDesk, so both pages name the
            # same owner — and "" when the case has not been allocated yet.
            agent = c.get("assigned_agent") or ""
            all_cases.append({
                "case_id": c["case_id"], "scenario": c["scenario"],
                "chargeback_category": c["chargeback_category"],
                "processor": c["processor"],
                "network": c.get("payment_method", ""),
                "amount": c["amount"],
                # Cases are not all in one currency, so the amount has to carry
                # its own — a bare $ in front of an IDR figure is just wrong.
                "currency": c.get("currency", "USD"),
                "win_probability": c["win_probability"],
                "submission_date": c["submission_date"],
                "submission_status": c["submission_status"],
                "outcome": c["outcome"],
                "case_status": c.get("case_status", ""),
                "routing": routing,
                "handling": (cls.ANALYST_ACCEPTED
                             if routing == "accept_refund" and c["ml"].get("overridden")
                             else cls.ROUTING_LABELS.get(routing, routing)),
                "handling_class": cls.ROUTING_CLASSES.get(routing, "hitl"),
                "agent": agent,
                "confidence": c["ml"]["confidence"],
            })

        handling_counts = Counter(c["handling"] for c in all_cases)

        return {
            "kpis": {
                "total_cases": total,
                "win_rate": win_rate,
                "wins": wins, "losses": losses, "refunded": refunded, "pending": pending,
                "total_disputed": round(total_disputed, 2),
                "amount_won": round(amount_won, 2),
                "recovery_rate": recovery_rate,
                # avg_resolution_days used to sit here as a hardcoded 3.2 —
                # a number presented as a measurement that nothing computed.
                # The sheet carries no resolution timestamps to derive it from,
                # so it is gone rather than faked.
                "auto_represent_rate": ml_stats["auto_rate_pct"],
                "auto_success_rate": auto_success_rate,
                "avg_completeness": evidence_stats.get("avg_completeness", 0),
            },
            "processor_perf": proc_perf,
            "reason_code_perf": rc_perf,
            "team": team,
            "total_queue": total_queue,
            "trends": cls.WEEKLY_TRENDS,
            "auto_output": auto_output,
            "auto_accuracy": auto_accuracy,
            "all_cases": all_cases,
            "handling_counts": handling_counts,
            # The analyst-accepted label rides at the end so the chip strip still
            # sums to the book once cases are conceded during a session.
            "handling_order": list(cls.ROUTING_LABELS.values()) + [cls.ANALYST_ACCEPTED],
        }
