from collections import Counter

from chargeback.analytics.agent_desk import AgentDesk
from chargeback.analytics.team_console import TeamConsole
from chargeback.utils.hashing import deterministic_seed


class ManagerConsole:
    """The management view: everything, plus the controls only a manager gets.

    This is aggregation rather than new analysis — DashboardAnalytics and
    ManagerCharts already compute the numbers, so the job here is to answer the
    questions the management hub asks that nothing else does: how much of the
    book arrived automatically versus by hand, what work is still outstanding,
    and who owns which client and which agents.
    """

    @staticmethod
    def _sources(cases):
        """How much is in the book.

        This used to split the total into automated and manually ingested. That
        split is gone because it was never real: no path feeds cases in without
        a person, so "automated" could only ever have counted cases whose tag
        had been lost. Every case now carries "manual" and the pages report one
        number instead of a bar with an empty half.
        """
        return {"total": len(cases)}

    @classmethod
    def _history(cls, all_cases, cases_by_id, mapping):
        """Every case, with the fields the history view filters on."""
        rows = []
        for c in all_cases:
            case = cases_by_id.get(c["case_id"], {})
            rows.append({
                **c,
                "bucket": TeamConsole._bucket_of(case, mapping),
                "ingest_source": case.get("ingest_source") or "manual",
                # Same resolver the rest of the app uses: a lead's allocation,
                # or "" while nobody owns it. Deliberately not read from
                # DashboardAnalytics, which only names an agent on HITL rows and
                # would leave the lead totals not summing to the book.
                "assigned_agent": case.get("assigned_agent") or "",
                "customer": (case.get("source", {}) or {}).get("UserFullName", ""),
                "dispute_date": (case.get("dispute_creation_date", "") or "")[:10],
                "outstanding": c.get("outcome") == "Pending",
            })
        return rows

    @classmethod
    def compute(cls, cases, analytics, charts, lead_agents, client_routing,
                team_leads):
        cases_by_id = {c["case_id"]: c for c in cases}
        mapping = TeamConsole._bucket_map(cases)
        history = cls._history(analytics.get("all_cases", []), cases_by_id, mapping)
        outstanding = [r for r in history if r["outstanding"]]

        # ── Which lead owns which agents and which client books ──
        leads = []
        for lead in team_leads:
            agents = lead_agents.get(lead, [])
            clients = [b for b, owner in client_routing.items() if owner == lead]
            owned = [r for r in history if r["assigned_agent"] in agents]
            leads.append({
                "name": lead,
                "agents": agents,
                "clients": clients,
                "cases": len(owned),
                "outstanding": sum(1 for r in owned if r["outstanding"]),
            })

        unassigned = [a for a in TeamConsole.BUCKET_LABELS
                      if a not in client_routing]

        return {
            "sources": cls._sources(cases),
            "history": history,
            "outstanding": outstanding,
            "leads": leads,
            "team_leads": team_leads,
            "client_routing": dict(client_routing),
            "lead_agents": {k: list(v) for k, v in lead_agents.items()},
            "unrouted_clients": unassigned,
            "bucket_labels": TeamConsole.BUCKET_LABELS,
            "filters": {
                "buckets": TeamConsole.BUCKET_LABELS,
                "agents": sorted({r["assigned_agent"] for r in history
                                  if r["assigned_agent"]}),
                "handlings": sorted({r["handling"] for r in history
                                     if r.get("handling")}),
                "outcomes": sorted({r["outcome"] for r in history
                                    if r.get("outcome")}),
                "processors": sorted({r["processor"] for r in history
                                      if r.get("processor")}),
                "networks": sorted({r["network"] for r in history
                                    if r.get("network")}),
                "submissions": sorted({r["submission_status"] for r in history
                                       if r.get("submission_status")}),
            },
            # Handling is one field with mutually exclusive values, so these do
            # partition the book — unlike outstanding/submitted, which are two
            # independent flags and overlap. Counting it here lets the page show
            # a strip of chips that add up to the total.
            "handling_counts": dict(Counter(r["handling"] for r in history
                                            if r.get("handling"))),
            "totals": {
                "cases": len(history),
                "outstanding": len(outstanding),
                "submitted": sum(1 for r in history
                                 if r.get("submission_status") == "Submitted"),
                # "avg_resolution" is gone with the hardcoded 3.2 it read —
                # nothing in the book records when a case was resolved.
                "unassigned": sum(1 for r in history if not r.get("assigned_agent")),
                "networks": len(charts.get("networks", [])),
                "processors": len(analytics.get("processor_perf", {})),
            },
        }
