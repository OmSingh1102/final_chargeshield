from collections import Counter, defaultdict

from chargeback.engines.reason_code import REASON_CODES
from chargeback.utils.datetime_helpers import safe_float, parse_any_datetime, fmt_datetime
from chargeback.utils.hashing import deterministic_seed


class AgentDesk:
    """Builds the agent working queue: every case, assigned to an agent, with
    per-agent productivity computed from the loaded sheet.

    Agent assignment is derived from a hash of the case id — no data source
    carries an agent column, and per-agent productivity is meaningless without
    one. Hashing rather than round-robin matters here: the sheet cycles card
    networks every 5 rows, so `index % 10` would hand each agent a single
    network and make the network filter useless. Every other field on the queue
    comes from the sheet.
    """

    AGENTS = ["Agent1", "Agent2", "Agent3"]

    # An agent's decision on a case. "Pending" is the default for untouched work.
    OPEN_STATES = {"", "Pending", "Select Action"}

    EVIDENCE_BUNDLES = {
        "fraud": ["GatewayAuthLog.pdf", "AVS_CVV_Report.csv", "DeviceFingerprint.json"],
        "merchandise": ["CarrierTracking.pdf", "DeliveryPhoto.jpg", "SupportEmail.eml"],
        "processing": ["GatewayVoidLog.pdf", "SettlementReport.csv", "CustomerNotification.eml"],
        "authorization": ["AuthorizationLog.pdf", "3DS_Result.json", "IssuerResponse.txt"],
        "others": ["EvidencePacket.pdf", "CustomerCorrespondence.eml"],
    }

    @classmethod
    def build_queue(cls, cases, ml_stats, evidence_results):
        classified = ml_stats["classified_cases"]

        tasks = []
        for c in classified:
            ev = evidence_results.get(c["case_id"], {})
            amount = safe_float(c.get("amount"))
            category = (c.get("reason_category") or "others").strip().lower()
            rc = c.get("reason_code", "")
            # By family, not by the raw code — otherwise every non-Visa case in
            # the queue shows a blank reason title.
            rc_db = REASON_CODES.get(c.get("reason_code_canonical") or rc, {})

            due_dt = parse_any_datetime(c.get("due_date"))
            dispute_dt = parse_any_datetime(c.get("dispute_creation_date"))

            tasks.append({
                "case_id": c["case_id"],
                # "" means nobody owns this yet. Everything downstream reads
                # assigned_to, so this one line is what makes an unassigned
                # case unassigned everywhere -- queues, counts and filters.
                # There is deliberately no hash fallback: inventing an owner
                # made every ingested case look like somebody's work.
                "assigned_to": c.get("assigned_agent") or "",
                "status": c.get("agent_action") or "Pending",
                "actioned_at": c.get("agent_action_at", ""),

                # ── straight from the sheet ──
                "stage": c.get("dispute_stage", ""),
                "network": c.get("payment_method", ""),
                "category": category,
                "reason_code": rc,
                "reason_title": rc_db.get("title", ""),
                "reason_description": c.get("reason_description", "") or c.get("scenario", ""),
                "amount": round(amount, 2),
                "currency": c.get("currency", "USD"),
                "merchant_ref": c.get("payment_psp_ref", ""),
                "refund_type": c.get("refund_type", ""),
                "dispute_date": fmt_datetime(dispute_dt) if dispute_dt else "",
                "due_date": due_dt.strftime("%Y-%m-%d") if due_dt else "",
                "transaction_date": c.get("transaction_date", ""),
                "win_probability": c.get("win_probability", 0),

                # ── derived ──
                # "priority" used to be here: High/Medium/Low bucketed straight
                # off the amount. It was an amount threshold wearing an urgency
                # label, and the amount is already its own column.
                "evidence_pct": ev.get("overall_completeness_pct", 0),
                "suggested_evidence": cls.EVIDENCE_BUNDLES.get(
                    category, cls.EVIDENCE_BUNDLES["others"]),
                "manual_evidence": c.get("manual_evidence", []),
                # Sortable ISO date; blank sorts last.
                "due_sort": due_dt.strftime("%Y-%m-%d") if due_dt else "9999-12-31",
            })

        # Soonest deadline first, then biggest money.
        tasks.sort(key=lambda t: (t["due_sort"], -t["amount"]))

        # ── Per-agent productivity, computed from the queue itself ──
        per_agent = {}
        for agent in cls.AGENTS:
            mine = [t for t in tasks if t["assigned_to"] == agent]
            if not mine:
                continue
            status_counts = Counter(t["status"] for t in mine)
            open_count = sum(n for s, n in status_counts.items() if s in cls.OPEN_STATES)
            total_value = sum(t["amount"] for t in mine)
            per_agent[agent] = {
                "assigned": len(mine),
                "open": open_count,
                "actioned": len(mine) - open_count,
                "contested": status_counts.get("Contested", 0),
                "not_fought": status_counts.get("Not Fought", 0),
                "waiting_pod": status_counts.get("Waiting for POD", 0),
                "total_value": round(total_value, 2),
                "avg_value": round(total_value / len(mine), 2),
                "avg_win_prob": round(sum(t["win_probability"] for t in mine) / len(mine)),
                "by_stage": dict(Counter(t["stage"] for t in mine)),
                "by_network": dict(Counter(t["network"] for t in mine)),
                "evidence_uploaded": sum(len(t["manual_evidence"]) for t in mine),
            }

        return {
            "tasks": tasks,
            "per_agent": per_agent,
            "agents": [a for a in cls.AGENTS if a in per_agent],
            "networks": sorted({t["network"] for t in tasks if t["network"]}),
            "categories": sorted({t["category"] for t in tasks if t["category"]}),
            "reason_codes": sorted({t["reason_code"] for t in tasks if t["reason_code"]}),
            "stages": sorted({t["stage"] for t in tasks if t["stage"]}),
            "statuses": ["Pending", "Contested", "Not Fought", "Waiting for POD"],
            "total_cases": len(tasks),
        }
