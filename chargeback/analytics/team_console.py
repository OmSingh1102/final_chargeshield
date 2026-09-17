from collections import Counter, OrderedDict

from chargeback.analytics.agent_desk import AgentDesk
from chargeback.utils.datetime_helpers import parse_any_datetime


class TeamConsole:
    """The team lead's view: every agent under them, and the work to distribute.

    Where AgentConsole narrows to one person, this widens to the whole team —
    but deliberately stays narrower than Manager Hub. The spec asks for
    "limited graphical images focused on team productivity", not a second copy
    of the management dashboard, so there are no win-rate or recovery charts
    here. Distribution, approvals and output are the job.
    """

    DAILY_TARGET = 60

    # One client book. There is no client column in the sheet, and the two-way
    # TransactionChannel split this used to be keyed on was never a real
    # division — every case carries the same merchant, MERCHANT_CONFIG's
    # "Acme Commerce Inc." with DBA "Acme Online Store". The label and the data
    # agree now.
    BUCKET_LABELS = ["Acme Online Store"]

    @classmethod
    def _bucket_map(cls, cases):
        """Map every raw channel value onto a client label.

        Sorted so the same raw value always lands on the same label across
        restarts, rather than following dict order. The modulo is what makes
        this hold for one label as well as many: every channel folds onto the
        single book instead of half the cases going Unassigned.
        """
        raw = sorted({(c.get("source", {}) or {}).get("TransactionChannel", "")
                      for c in cases} - {""})
        return {value: cls.BUCKET_LABELS[i % len(cls.BUCKET_LABELS)]
                for i, value in enumerate(raw)}

    @classmethod
    def _bucket_of(cls, case, mapping):
        raw = (case.get("source", {}) or {}).get("TransactionChannel", "")
        return mapping.get(raw, "Unassigned")

    @classmethod
    def for_lead(cls, cases, ml_stats, evidence_results, my_agents=None,
                 my_clients=None):
        """`my_agents` limits the view to the agents reporting to this lead.

        The spec is explicit that a lead sees the agents assigned to them and
        no further, so passing None (every agent) is only for a manager
        inspecting the whole team.
        """
        desk = AgentDesk.build_queue(cases, ml_stats, evidence_results)
        roster = [a for a in AgentDesk.AGENTS
                  if my_agents is None or a in my_agents]
        # Unassigned cases ("" owner) belong in the lead's view even though no
        # agent on the roster holds them — allocating them is the lead's job,
        # and filtering them out would hide every freshly ingested case from
        # the one person who can act on it.
        tasks = [t for t in desk["tasks"]
                 if t["assigned_to"] in roster or not t["assigned_to"]]
        cases_by_id = {c["case_id"]: c for c in cases}
        classified_by_id = {c["case_id"]: c for c in ml_stats["classified_cases"]}
        mapping = cls._bucket_map(cases)

        # ── Per-agent rows: assigned / open / actioned / submitted / value ──
        agents = []
        for name in AgentDesk.AGENTS:
            mine = [t for t in tasks if t["assigned_to"] == name]
            if not mine:
                continue
            stats = desk["per_agent"].get(name, {})
            submitted = sum(
                1 for t in mine
                if (cases_by_id.get(t["case_id"], {}).get("submission_status") or "")
                == "Submitted")
            agents.append({
                "name": name,
                "assigned": len(mine),
                "open": stats.get("open", 0),
                "actioned": stats.get("actioned", 0),
                "submitted": submitted,
                "total_value": stats.get("total_value", 0),
                "avg_win_prob": stats.get("avg_win_prob", 0),
                "contested": stats.get("contested", 0),
                "not_fought": stats.get("not_fought", 0),
                "waiting_pod": stats.get("waiting_pod", 0),
            })

        team_total = sum(a["assigned"] for a in agents) or 1
        for a in agents:
            a["share_pct"] = round(a["assigned"] / team_total * 100)
            a["done_pct"] = (round(a["actioned"] / a["assigned"] * 100)
                             if a["assigned"] else 0)

        # ── Client buckets ──
        buckets = []
        for label in cls.BUCKET_LABELS:
            in_bucket = [t for t in tasks
                         if cls._bucket_of(cases_by_id.get(t["case_id"], {}), mapping) == label]
            if not in_bucket:
                continue
            buckets.append({
                "name": label,
                "count": len(in_bucket),
                "pending": sum(1 for t in in_bucket
                               if t["status"] in AgentDesk.OPEN_STATES),
                "value": round(sum(t["amount"] for t in in_bucket), 2),
                "by_agent": dict(Counter(t["assigned_to"] for t in in_bucket)),
                "pct": round(len(in_bucket) / len(tasks) * 100) if tasks else 0,
            })

        # ── Every unactioned case in the team's scope ──
        def row(t):
            case = cases_by_id.get(t["case_id"], {})
            return {
                "case_id": t["case_id"],
                "assigned_to": t["assigned_to"],
                "bucket": cls._bucket_of(case, mapping),
                "network": t["network"],
                "reason_code": t["reason_code"],
                "reason_title": t["reason_title"],
                "amount": t["amount"],
                "currency": t["currency"],
                "due_date": t["due_date"],
                "status": t["status"],
                "stage": t["stage"],
                "submission_status": case.get("submission_status", ""),
                "customer": (case.get("source", {}) or {}).get("UserFullName", ""),
                "released": bool(case.get("rework_released")),
                "released_by": (case.get("rework_released") or {}).get("released_by", ""),
                "released_at": (case.get("rework_released") or {}).get("at", ""),
                # What the lead said needs fixing. Shown back on the approvals
                # page so a second lead can see why a case was reopened.
                "released_note": (case.get("rework_released") or {}).get("note", ""),
                "win_probability": classified_by_id.get(t["case_id"], {}).get(
                    "win_probability", t.get("win_probability", 0)),
            }

        pending = [row(t) for t in tasks if t["status"] in AgentDesk.OPEN_STATES]
        submitted_rows = [
            row(t) for t in tasks
            if (cases_by_id.get(t["case_id"], {}).get("submission_status") or "")
            == "Submitted"]

        # ── Team output per day, against the per-agent target ──
        by_day = Counter()
        for t in tasks:
            dt = parse_any_datetime(t.get("dispute_date"))
            if dt:
                by_day[dt.strftime("%Y-%m-%d")] += 1
        team_target = cls.DAILY_TARGET * len(agents)
        daily = [{
            "label": day,
            "count": count,
            "target": team_target,
            "pct": min(100, round(count / team_target * 100)) if team_target else 0,
            "on_target": count >= team_target,
        } for day, count in sorted(by_day.items())]

        return {
            "agents": agents,
            "agent_names": [a["name"] for a in agents],
            "roster": roster,
            "buckets": buckets,
            "bucket_labels": cls.BUCKET_LABELS,
            # The client books management has routed to this lead.
            "my_clients": list(my_clients) if my_clients else [],
            "pending": pending,
            "submitted": submitted_rows,
            "awaiting_release": [r for r in submitted_rows if not r["released"]],
            "released": [r for r in submitted_rows if r["released"]],
            "daily": daily,
            "team_target": team_target,
            "totals": {
                "cases": len(tasks),
                "pending": len(pending),
                "submitted": len(submitted_rows),
                "released": sum(1 for r in submitted_rows if r["released"]),
                "actioned": sum(a["actioned"] for a in agents),
                # Counted over the unactioned rows the allocation page shows,
                # so the segmented filter's three numbers add up to what is on
                # screen rather than to the whole book.
                "unassigned": sum(1 for r in pending if not r["assigned_to"]),
                "assigned": sum(1 for r in pending if r["assigned_to"]),
            },
            "filters": {
                "agents": [a["name"] for a in agents],
                "buckets": [b["name"] for b in buckets],
                "networks": sorted({t["network"] for t in tasks if t["network"]}),
            },
        }
