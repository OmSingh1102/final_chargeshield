import calendar
from collections import Counter, OrderedDict
from datetime import date

from chargeback.analytics.agent_desk import AgentDesk
from chargeback.analytics.manager_charts import ManagerCharts
from chargeback.utils.datetime_helpers import parse_any_datetime


class AgentConsole:
    """Everything one agent may see, and nothing else.

    The spec is explicit that an agent gets no multi-agent overview and no
    master system metrics, so this never hands a template the full case list.
    Every number on the agent pages is computed from the slice of cases
    assigned to that one agent — including the charts, which are the ordinary
    ManagerCharts run over the subset rather than a second implementation.
    """

    # Cases per day an agent is expected to clear. The sheet cannot come close
    # to this (see below), so it lives here as a named constant rather than a
    # literal buried in a template — lowering it is a one-line change.
    DAILY_TARGET = 60

    # Non-overlapping so the four tiles sum to the agent's case count. A case
    # the pipeline auto-represented is not also "pending", and one it conceded
    # is not "represented".
    @staticmethod
    def _bucket(case):
        routing = case.get("ml", {}).get("routing", "")
        if routing == "accept_refund":
            return "accepted"
        if routing == "auto_represent":
            return "auto_represent"
        if (case.get("submission_status") or "") == "Submitted":
            return "represented"
        return "pending"

    @classmethod
    def _rows(cls, tasks, cases_by_id):
        """The chargeback table, one row per assigned case.

        Columns come straight from the sheet. `source` holds the raw CSV row,
        which is where the customer and transaction identifiers live.
        """
        rows = []
        for t in tasks:
            case = cases_by_id.get(t["case_id"], {})
            src = case.get("source", {}) or {}
            submitted = (case.get("submission_status") or "") == "Submitted"
            rows.append({
                "case_id": t["case_id"],
                "card_type": t["network"],
                "reason_code": t["reason_code"],
                "reason_title": t["reason_title"],
                "cb_date": t["dispute_date"],
                "amount": t["amount"],
                "currency": t["currency"],
                "order_id": case.get("order_id", ""),
                "txn_date": (case.get("transaction_date", "") or "")[:10],
                "txn_id": src.get("PaymentTransactionId", ""),
                # No client-name column exists in the data — only an opaque
                # merchant user id. Showing it beats inventing a brand.
                "client": src.get("MerchantUserId", ""),
                "last_four": case.get("card_last_four", ""),
                "customer": src.get("UserFullName", ""),
                "phone": src.get("UserPhone", ""),

                # Filter/search keys and the read-only rule.
                "status": t["status"],
                "submission_status": case.get("submission_status", ""),
                "category": t["category"],
                "stage": t["stage"],
                "due_date": t["due_date"],
                # Agents cannot rework a case they have already submitted unless
                # a team lead has released the lock for them.
                "released": bool(case.get("rework_released")),
                "released_by": (case.get("rework_released") or {}).get("released_by", ""),
                "editable": (not submitted) or bool(case.get("rework_released")),
            })
        return rows

    @classmethod
    def _calendar(cls, tasks, year=None, month=None):
        """Daily case counts laid over a month grid, against DAILY_TARGET.

        Built honestly from the sheet: the dataset covers four days in June
        2026, so most cells are empty and no day reaches the target. The grid
        therefore opens on the month that actually holds data rather than on
        today, which would be blank.
        """
        by_day = Counter()
        for t in tasks:
            dt = parse_any_datetime(t.get("dispute_date"))
            if dt:
                by_day[dt.date()] += 1

        if not by_day:
            # Fall back to the current month rather than passing the caller's
            # None straight back out. The template does arithmetic on these to
            # build its prev/next links, so a None here is a 500 on any agent
            # whose queue is empty -- which is every agent before a lead has
            # allocated anything.
            today = date.today()
            year = year or today.year
            month = month or today.month
            return {"weeks": [], "year": year, "month": month,
                    "month_name": calendar.month_name[month],
                    "target": cls.DAILY_TARGET, "days_with_work": 0,
                    "best_day": 0, "total": 0, "days_on_target": 0}

        # Default to the busiest month in the data, not the current one.
        if year is None or month is None:
            busiest = Counter((d.year, d.month) for d in by_day.elements()).most_common(1)[0][0]
            year, month = busiest

        weeks = []
        for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
            row = []
            for day in week:
                count = by_day.get(day, 0)
                row.append({
                    "day": day.day,
                    "count": count,
                    "in_month": day.month == month,
                    "has_work": count > 0,
                    "on_target": count >= cls.DAILY_TARGET,
                    "pct": min(100, round(count / cls.DAILY_TARGET * 100)) if count else 0,
                })
            weeks.append(row)

        in_month = {d: n for d, n in by_day.items() if (d.year, d.month) == (year, month)}
        return {
            "weeks": weeks,
            "year": year,
            "month": month,
            "month_name": calendar.month_name[month],
            "target": cls.DAILY_TARGET,
            "days_with_work": len(in_month),
            "days_on_target": sum(1 for n in in_month.values() if n >= cls.DAILY_TARGET),
            "best_day": max(in_month.values()) if in_month else 0,
            "total": sum(in_month.values()),
        }

    @classmethod
    def _productivity(cls, tasks):
        """The same cases rolled up three ways for the dashboard filter."""
        daily, weekly, monthly = Counter(), Counter(), Counter()
        for t in tasks:
            dt = parse_any_datetime(t.get("dispute_date"))
            if not dt:
                continue
            daily[dt.strftime("%Y-%m-%d")] += 1
            iso = dt.isocalendar()
            weekly[f"{iso[0]}-W{iso[1]:02d}"] += 1
            monthly[dt.strftime("%Y-%m")] += 1

        def series(counter, target_multiplier):
            rows = []
            for key, count in sorted(counter.items()):
                target = cls.DAILY_TARGET * target_multiplier
                rows.append({
                    "label": key,
                    "count": count,
                    "target": target,
                    "pct": min(100, round(count / target * 100)) if target else 0,
                    "on_target": count >= target,
                })
            return rows

        # A week is five working days, a month twenty-one.
        return OrderedDict([
            ("daily", series(daily, 1)),
            ("weekly", series(weekly, 5)),
            ("monthly", series(monthly, 21)),
        ])

    @classmethod
    def for_agent(cls, cases, ml_stats, evidence_results, agent, year=None, month=None):
        # Reuse the existing queue builder, then keep only this agent's work.
        desk = AgentDesk.build_queue(cases, ml_stats, evidence_results)
        tasks = [t for t in desk["tasks"] if t["assigned_to"] == agent]
        my_ids = {t["case_id"] for t in tasks}

        cases_by_id = {c["case_id"]: c for c in cases}
        mine = [c for c in ml_stats["classified_cases"] if c["case_id"] in my_ids]

        buckets = Counter(cls._bucket(c) for c in mine)
        rows = cls._rows(tasks, cases_by_id)

        return {
            "agent": agent,
            "total_cases": len(tasks),
            "rows": rows,
            "kpis": {
                "pending": buckets.get("pending", 0),
                "represented": buckets.get("represented", 0),
                "accepted": buckets.get("accepted", 0),
                "auto_represent": buckets.get("auto_represent", 0),
            },
            "open_tasks": sum(1 for t in tasks if t["status"] in AgentDesk.OPEN_STATES),
            "actioned": sum(1 for t in tasks if t["status"] not in AgentDesk.OPEN_STATES),
            "calendar": cls._calendar(tasks, year, month),
            "productivity": cls._productivity(tasks),
            # The agent's own cases only — this is what keeps the dashboard
            # personal instead of a copy of the manager's system-wide view.
            "charts": ManagerCharts.compute(mine, []),
            "filters": {
                "networks": sorted({r["card_type"] for r in rows if r["card_type"]}),
                "categories": sorted({r["category"] for r in rows if r["category"]}),
                "statuses": sorted({r["status"] for r in rows if r["status"]}),
                "stages": sorted({r["stage"] for r in rows if r["stage"]}),
            },
        }
