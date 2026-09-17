from collections import Counter, OrderedDict

from chargeback.analytics.agent_console import AgentConsole
from chargeback.analytics.agent_desk import AgentDesk
from chargeback.analytics.manager_charts import ManagerCharts
from chargeback.analytics.team_console import TeamConsole


class ClientConsole:
    """Everything one client may see, and the tier that governs their rebuttals.

    Where AgentConsole narrows to one person's queue, this narrows to one
    brand's book. A client is a customer of the platform rather than a member of
    the team, so nothing this returns carries an agent or team-lead name.

    The tier is the part with teeth: it decides how a representment packet is
    built, not merely how it is labelled. Evidence is described as "fetched from
    the case record" only where it genuinely was, and anything else is asked for
    as an upload.
    """

    # One tier. The platform is semi-automated by definition: it assembles what
    # the case record covers and asks a human for the rest, because evidence
    # like proof of delivery cannot be derived from the data at all. A
    # fully-automated tier would have to badge those items as "fetched" or drop
    # them silently, and a manual tier would throw away the documents that do
    # build. Kept as a dict rather than a constant so the shape the templates,
    # tier_of and manager_client_tier read is unchanged.
    TIERS = OrderedDict([
        ("semi_automated", {
            "label": "Semi-Automated",
            "blurb": "Assembled from the case record where the data is there; "
                     "an upload is asked for only where it is missing.",
        }),
    ])

    #: The merchant account record, in display order. Keys are stored; values
    #: are the column headings the client page and the client portal both use.
    ACCOUNT_FIELDS = OrderedDict([
        ("corp_name", "Corp Name"),
        ("signer_name", "Signer Name"),
        ("processor_name", "Processor Name"),
        ("dba_name", "DBA Name"),
        ("mid_no", "MID No"),
        ("approved_mv", "Approved MV"),
        ("descriptor", "Descriptor"),
        ("processor_id", "Processor ID"),
        ("status", "Status"),
        ("pending_with", "Pending with"),
        ("updates", "Updates"),
    ])

    STATUSES = ["Active", "WIP"]

    #: The nine sections of the representment letter, in the order they appear,
    #: each naming the document that satisfies it and the requirement label its
    #: uploads are filed under. The labels are byte-identical to the strings the
    #: letter has always used, so files already on disk keep being found when a
    #: client moves between tiers.
    LETTER_SECTIONS = [
        ("transaction_copy", "Transaction Copy"),
        ("order_information", "Order Information"),
        ("invoice_breakup", "Invoice Breakup"),
        ("refund_information", "Refund Information"),
        ("account_history", "Account History"),
        ("activity_log", "{payment_method} Cardholder Activity Log"),
        ("checkout_record", "Checkout Page"),
        ("terms_conditions", "Terms and Conditions"),
        ("refund_policy", "Refund Policy"),
    ]

    DEFAULT_TIER = "semi_automated"

    # ── Resolution ────────────────────────────────────────────────────────────

    @classmethod
    def client_of(cls, case, mapping):
        """Which client book a case belongs to.

        Delegates rather than reimplements: the bucket rule lives in one place
        so the client portal, the manager console and the rebuttal builder can
        never disagree about who owns a case.
        """
        return TeamConsole._bucket_of(case, mapping)

    @classmethod
    def tier_of(cls, case, profiles, mapping):
        """The service tier governing this case's rebuttal.

        A case whose channel is not in the map lands on "Unassigned", which no
        client owns, and falls back to DEFAULT_TIER. Every seeded case takes
        this path — they carry no source row. With one tier defined the fallback
        and the answer are the same value, but the lookup stays so that a stored
        profile naming a tier that no longer exists resolves to a real one
        rather than to whatever the file happened to say.
        """
        profile = (profiles or {}).get(cls.client_of(case, mapping))
        tier = (profile or {}).get("tier", cls.DEFAULT_TIER)
        return tier if tier in cls.TIERS else cls.DEFAULT_TIER

    @classmethod
    def section_plan(cls, tier, documents, case):
        """How each letter section renders, and the label its uploads file under.

        Returns (modes, labels) where a mode is "system" (assemble it from the
        case record) or "manual" (ask for an upload).
        """
        payment_method = case.get("payment_method") or "Card"
        modes, labels = {}, {}
        for key, label in cls.LETTER_SECTIONS:
            labels[key] = label.format(payment_method=payment_method)
            # A document counts as fetched only when it actually built from the
            # data on the case; everything else is asked for as an upload. That
            # is the whole of semi-automated, and with one tier it is the whole
            # of the plan. `tier` stays in the signature: _packet_doc passes it
            # positionally, and a second tier would branch here again.
            doc = (documents or {}).get(key) or {}
            modes[key] = "system" if doc.get("available") else "manual"
        return modes, labels

    # ── The client's own view ─────────────────────────────────────────────────

    @classmethod
    def _kpis(cls, classified):
        """Pending / represented / accepted / auto-represent, in the merchant's
        words.

        Delegates the split to AgentConsole._bucket rather than repeating it:
        the four buckets are already mutually exclusive there, which is what
        makes the tiles add up to the client's caseload instead of overlapping.
        """
        buckets = Counter(AgentConsole._bucket(c) for c in classified)
        return {
            "pending": buckets.get("pending", 0),
            "represented": buckets.get("represented", 0),
            "accepted": buckets.get("accepted", 0),
            "auto_represent": buckets.get("auto_represent", 0),
            "total": len(classified),
        }

    @classmethod
    def for_client(cls, cases, ml_stats, evidence_results, client, profile):
        """One brand's book, and nothing else.

        Deliberately omits every internal name — which agent holds a case and
        which lead owns the book are Straive's business, not the merchant's.
        """
        mapping = TeamConsole._bucket_map(cases)
        mine = [c for c in cases if cls.client_of(c, mapping) == client]
        my_ids = {c["case_id"] for c in mine}

        desk = AgentDesk.build_queue(cases, ml_stats, evidence_results)
        task_by_id = {t["case_id"]: t for t in desk["tasks"]
                      if t["case_id"] in my_ids}

        # The charts read the `ml` dict, which only the classified copies carry,
        # so they are built from that list rather than from `mine`.
        classified = [c for c in ml_stats["classified_cases"]
                      if c["case_id"] in my_ids]

        rows = []
        for case in mine:
            task = task_by_id.get(case["case_id"], {})
            rows.append({
                "case_id": case["case_id"],
                "network": case.get("payment_method", ""),
                "processor": case.get("processor", ""),
                "reason_code": case.get("reason_code", ""),
                "reason_title": task.get("reason_title")
                or case.get("chargeback_category", ""),
                "scenario": case.get("scenario", ""),
                "amount": case.get("amount", 0),
                "currency": case.get("currency", "USD"),
                "dispute_date": (case.get("dispute_creation_date", "") or "")[:10],
                "due_date": (case.get("due_date", "") or "")[:10],
                "outcome": case.get("outcome", ""),
                "submission_status": case.get("submission_status", ""),
                "case_status": case.get("case_status", ""),
                "win_probability": case.get("win_probability", 0),
                "outstanding": case.get("outcome") == "Pending",
            })
        rows.sort(key=lambda r: r["dispute_date"], reverse=True)

        outcomes = Counter(r["outcome"] for r in rows)
        value = sum(r["amount"] for r in rows)
        at_risk = sum(r["amount"] for r in rows if r["outstanding"])
        tier = (profile or {}).get("tier", cls.DEFAULT_TIER)
        if tier not in cls.TIERS:
            tier = cls.DEFAULT_TIER

        return {
            "client": client,
            "tier": tier,
            "tier_label": cls.TIERS[tier]["label"],
            "tier_blurb": cls.TIERS[tier]["blurb"],
            "account": (profile or {}).get("account", {}),
            "account_fields": cls.ACCOUNT_FIELDS,
            "rows": rows,
            # This brand's book only — the same charts Manager Hub draws, run
            # over one client's slice rather than a second implementation.
            "charts": ManagerCharts.compute(classified, []),
            # Where the work stands, borrowed from the agent console so the
            # four tiles stay non-overlapping and sum to the caseload.
            "kpis": cls._kpis(classified),
            "totals": {
                "cases": len(rows),
                "outstanding": sum(1 for r in rows if r["outstanding"]),
                "submitted": sum(1 for r in rows
                                 if r["submission_status"] == "Submitted"),
                "won": outcomes.get("Win", 0),
                "lost": outcomes.get("Lost", 0),
                "refunded": outcomes.get("Refunded", 0),
                "value": round(value, 2),
                "at_risk": round(at_risk, 2),
            },
            "filters": {
                "networks": sorted({r["network"] for r in rows if r["network"]}),
                "outcomes": sorted({r["outcome"] for r in rows if r["outcome"]}),
                "submissions": sorted({r["submission_status"] for r in rows
                                       if r["submission_status"]}),
            },
        }
