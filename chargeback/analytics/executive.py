class ExecutiveAnalytics:
    """C-suite financial impact, ROI, and risk analytics."""

    COST_PER_MANUAL_CASE = 45.00   # avg analyst cost per case
    COST_PER_AUTO_CASE = 1.50      # platform cost per auto case
    WEEKLY_RECOVERY = [
        {"week": "W22", "label": "May 26", "recovered": 1250, "disputed": 2800, "cases": 12},
        {"week": "W23", "label": "Jun 02", "recovered": 1890, "disputed": 3100, "cases": 15},
        {"week": "W24", "label": "Jun 09", "recovered": 2100, "disputed": 2500, "cases": 11},
        {"week": "W25", "label": "Jun 16", "recovered": 1650, "disputed": 3800, "cases": 18},
        {"week": "W26", "label": "Jun 23", "recovered": 1420, "disputed": 2900, "cases": 14},
        {"week": "W27", "label": "Jun 30", "recovered": 927, "disputed": 2787, "cases": 8},
    ]

    @classmethod
    def compute(cls, cases, ml_stats, evidence_stats):
        classified = ml_stats["classified_cases"]
        total = len(classified)

        total_at_risk = sum(c["amount"] for c in classified)
        total_recovered = sum(c["amount"] for c in classified if c["outcome"] == "Win")
        total_lost = sum(c["amount"] for c in classified if c["outcome"] in ["Lost", "Refunded"])
        pending_amount = sum(c["amount"] for c in classified if c["outcome"] == "Pending")

        auto_count = ml_stats["auto_represent"]
        manual_count = total - auto_count
        manual_cost = manual_count * cls.COST_PER_MANUAL_CASE
        auto_cost = auto_count * cls.COST_PER_AUTO_CASE
        total_cost_with_auto = manual_cost + auto_cost
        total_cost_without = total * cls.COST_PER_MANUAL_CASE
        cost_savings = total_cost_without - total_cost_with_auto
        roi_pct = round(cost_savings / total_cost_with_auto * 100) if total_cost_with_auto else 0

        # Funnel
        filed = total
        defended = sum(1 for c in classified if c["submission_status"] in ["Auto-Submitted", "Submitted", "Disputed"])
        won = sum(1 for c in classified if c["outcome"] == "Win")

        # Processor P&L
        proc_pl = {}
        for c in classified:
            p = c["processor"]
            if p not in proc_pl:
                proc_pl[p] = {"disputed": 0, "recovered": 0, "lost": 0, "pending": 0, "cases": 0, "wins": 0}
            proc_pl[p]["cases"] += 1
            proc_pl[p]["disputed"] += c["amount"]
            if c["outcome"] == "Win":
                proc_pl[p]["recovered"] += c["amount"]
                proc_pl[p]["wins"] += 1
            elif c["outcome"] in ["Lost", "Refunded"]:
                proc_pl[p]["lost"] += c["amount"]
            else:
                proc_pl[p]["pending"] += c["amount"]
        for p in proc_pl:
            dec = proc_pl[p]["wins"] + (proc_pl[p]["cases"] - proc_pl[p]["wins"] - (1 if proc_pl[p]["pending"] > 0 else 0))
            proc_pl[p]["recovery_rate"] = round(proc_pl[p]["recovered"] / proc_pl[p]["disputed"] * 100) if proc_pl[p]["disputed"] else 0

        # Risk alerts
        alerts = []
        for p, d in proc_pl.items():
            if d["recovery_rate"] < 20 and d["cases"] > 1:
                alerts.append({"severity": "high", "message": f"{p} recovery rate at {d['recovery_rate']}% - needs investigation", "icon": "&#9888;"})
        low_conf = [c for c in classified if c["ml"]["confidence"] < 40 and c["outcome"] == "Pending"]
        if low_conf:
            alerts.append({"severity": "medium", "message": f"{len(low_conf)} pending case(s) with <40% ML confidence", "icon": "&#128269;"})
        if pending_amount > total_at_risk * 0.3:
            alerts.append({"severity": "medium", "message": f"${pending_amount:,.0f} at risk in pending cases ({round(pending_amount/total_at_risk*100)}% of total)", "icon": "&#128176;"})
        if not alerts:
            alerts.append({"severity": "low", "message": "All systems operating normally", "icon": "&#9989;"})

        annual_savings = round(cost_savings * 52 / 6)  # project 6 weeks to annual

        return {
            "total_at_risk": round(total_at_risk, 2),
            "total_recovered": round(total_recovered, 2),
            "total_lost": round(total_lost, 2),
            "pending_amount": round(pending_amount, 2),
            "cost_savings": round(cost_savings, 2),
            "roi_pct": roi_pct,
            "annual_savings": annual_savings,
            "manual_cost_per_case": cls.COST_PER_MANUAL_CASE,
            "auto_cost_per_case": cls.COST_PER_AUTO_CASE,
            "total_cost_with_auto": round(total_cost_with_auto, 2),
            "total_cost_without": round(total_cost_without, 2),
            "funnel": {"filed": filed, "defended": defended, "won": won},
            "processor_pl": proc_pl,
            "weekly": cls.WEEKLY_RECOVERY,
            "alerts": alerts[:5],
            "auto_count": auto_count,
            "manual_count": manual_count,
        }
