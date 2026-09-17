"""Manager Hub chart data.

Six groups, modelled on the client CB reporting deck:
  1. Card network / processor breakdown
  2. Performance metrics  (won / lost / not fought / pending, fought vs not fought)
  3. CB type              (dispute stage: retrieval, chargeback, pre-arbitration)
  4. Geography            (top delivery regions and countries)
  5. Top reason codes     (per card network)
  6. Volume trends        (daily / weekly / monthly, filterable)

Everything is computed server-side; the template draws with CSS/SVG so the
page needs no external chart library.

Money is never summed across currencies. The working sheet carries IDR, USD and
NGN side by side, so every amount in here is a `{currency: total}` dict rather
than one number — adding them would produce a figure that means nothing.
"""
from collections import Counter, defaultdict, OrderedDict
from datetime import timedelta

from chargeback.utils.datetime_helpers import safe_float, parse_any_datetime

# Stable colours so a network keeps the same colour in every chart.
#
# These are hues, not shades. The previous set was five steps along the brand
# orange, which meant a donut of four networks read as one colour fading out and
# the legend was the only way to tell a slice apart. Categories that carry no
# order should not be encoded as a ramp.
NETWORK_COLORS = OrderedDict([
    ("Visa", "#3b82f6"),
    ("Mastercard", "#f59e0b"),
    ("Amex", "#8b5cf6"),
    ("Discover", "#06b6d4"),
    ("Klarna", "#ec4899"),
    ("Other", "#94a3b8"),
])

# Semantic, not brand: green is a win, red is a loss, amber is waiting. They
# mean the same thing in every theme and are deliberately not tinted with the
# palette above — only refreshed to the same green/red/amber the rest of the
# UI now uses for status.
OUTCOME_COLORS = {
    "Won": "#10b981",
    "Lost": "#ef4444",
    "Not Fought": "#f59e0b",
    "Decision Pending": "#3b82f6",
}

# The deck's four case states, in the order it presents them. This order drives
# the status table's column headers, so it is not free to change.
STATUS_ORDER = ["Decision Pending", "Lost", "Not Fought", "Won"]

# Outcome-first order, for anything that reads as a result rather than a queue.
OUTCOME_ORDER = ["Won", "Lost", "Not Fought", "Decision Pending"]

# Below this many decided cases a win rate says more about the sample than about
# performance, so the bar is muted and labelled instead of stated flatly. The
# same compute() runs over one agent's slice, where a rate off two cases would
# otherwise print as confidently as one off fifty.
MIN_RATE_SAMPLE = 10

# Dispute-stage codes as the deck names them. Anything not listed keeps its raw
# value rather than being folded into an "Other" bucket that hides it.
STAGE_LABELS = {
    "Request for Information": "Retrieval Request",
    "RFI": "Retrieval Request",
    "Chargeback": "1st Chargeback / Dispute",
    "CB": "1st Chargeback / Dispute",
    "Pre-Arbitration": "Second Chargeback / Pre-Arbitration",
    "PRE_ARB": "Second Chargeback / Pre-Arbitration",
}
STAGE_ORDER = ["Retrieval Request", "1st Chargeback / Dispute",
               "Second Chargeback / Pre-Arbitration"]

# Delivery rows with no physical destination.
DIGITAL_REGION = "N/A (Digital)"

TOP_N_REGIONS = 5
TOP_N_REASONS = 5


def _by_currency(cases):
    """Total amount per currency. Never a single cross-currency number."""
    totals = defaultdict(float)
    for c in cases:
        totals[(c.get("currency") or "USD").strip() or "USD"] += safe_float(c.get("amount"))
    return {cur: round(v, 2) for cur, v in sorted(totals.items())}


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


class ManagerCharts:

    @classmethod
    def compute(cls, classified, orders=None):
        """classified: cases carrying an `ml` dict (from AIValidationEngine).

        `orders` is accepted but unused since risk monitoring was removed; the
        caller still passes the order book, so the parameter stays rather than
        breaking that call site.
        """
        if not classified:
            return {"has_data": False}

        total = len(classified)

        # ── 1. Card network / processor breakdown ───────────────────────────
        # Cases are bucketed rather than counted so each bucket's money can be
        # split by currency afterwards.
        net_cases, proc_cases = defaultdict(list), defaultdict(list)
        proc_by_net = defaultdict(Counter)

        for c in classified:
            net = cls._network(c)
            proc = c.get("processor") or "Unknown"
            net_cases[net].append(c)
            proc_cases[proc].append(c)
            proc_by_net[proc][net] += 1

        net_count = Counter({n: len(v) for n, v in net_cases.items()})
        networks = [n for n in NETWORK_COLORS if n in net_count]
        networks += sorted(n for n in net_count if n not in NETWORK_COLORS)

        network_rows = [{
            "name": n,
            "color": NETWORK_COLORS.get(n, "#c9a898"),
            "count": net_count[n],
            "amounts": _by_currency(net_cases[n]),
            "pct": _pct(net_count[n], total),
        } for n in networks]

        # Pie slices need cumulative angles for the CSS conic-gradient.
        cls._add_arcs(network_rows)

        processor_rows = []
        for p, cases in sorted(proc_cases.items(), key=lambda kv: -len(kv[1])):
            cnt = len(cases)
            mix = [{
                "name": n,
                "color": NETWORK_COLORS.get(n, "#c9a898"),
                "count": proc_by_net[p][n],
                "pct": _pct(proc_by_net[p][n], cnt),
            } for n in networks if proc_by_net[p][n]]
            processor_rows.append({
                "name": p,
                "count": cnt,
                "amounts": _by_currency(cases),
                "pct": _pct(cnt, total),
                "mix": mix,
            })

        # ── 2. Performance metrics ──────────────────────────────────────────
        # "Fought" = the case was represented. "Not fought" = conceded to the
        # cardholder — a decision in its own right, so it stays separate from
        # Lost rather than being folded into it.
        status_cases = defaultdict(list)
        status_by_net = defaultdict(Counter)
        fought_cases, not_fought_cases = [], []

        for c in classified:
            status = cls._status(c)
            status_cases[status].append(c)
            status_by_net[status][cls._network(c)] += 1
            (fought_cases if cls._is_fought(c) else not_fought_cases).append(c)

        won = len(status_cases["Won"])
        lost = len(status_cases["Lost"])
        conceded = len(status_cases["Not Fought"])
        pending = len(status_cases["Decision Pending"])
        decided = won + lost + conceded

        status_stacks = []
        for s in STATUS_ORDER:
            col_total = sum(status_by_net[s].values())
            status_stacks.append({
                "name": s,
                "total": col_total,
                "color": OUTCOME_COLORS[s],
                "segments": [{
                    "name": n,
                    "color": NETWORK_COLORS.get(n, "#c9a898"),
                    "count": status_by_net[s][n],
                    "pct": _pct(status_by_net[s][n], col_total),
                } for n in networks if status_by_net[s][n]],
            })

        # Per-network rows for the table under the stacked columns.
        status_table = [{
            "name": n,
            "color": NETWORK_COLORS.get(n, "#c9a898"),
            "cells": [status_by_net[s][n] for s in STATUS_ORDER],
            "total": sum(status_by_net[s][n] for s in STATUS_ORDER),
        } for n in networks]

        recovered_rows = [
            {"name": s, "color": OUTCOME_COLORS[s], "count": len(status_cases[s]),
             "amounts": _by_currency(status_cases[s]), "pct": _pct(len(status_cases[s]), total)}
            for s in ("Won", "Lost", "Not Fought", "Decision Pending")
        ]
        cls._add_arcs(recovered_rows)

        fought_rows = [
            {"name": "Fought", "color": "#f4611a", "count": len(fought_cases),
             "amounts": _by_currency(fought_cases), "pct": _pct(len(fought_cases), total)},
            {"name": "Not Fought", "color": "#e8dad0", "count": len(not_fought_cases),
             "amounts": _by_currency(not_fought_cases), "pct": _pct(len(not_fought_cases), total)},
        ]
        cls._add_arcs(fought_rows)

        # ── 3. CB type (dispute stage) ──────────────────────────────────────
        stages = cls._build_stages(classified, total)

        # ── 4. Geography ────────────────────────────────────────────────────
        geography = cls._build_geography(classified, networks, total)

        # ── 5. Top reason codes per network ─────────────────────────────────
        reason_panels = cls._build_reason_panels(net_cases, networks)

        # ── 6. Volume trends ────────────────────────────────────────────────
        trend = cls._build_trend(classified, networks)

        return {
            "has_data": True,
            "total": total,
            "networks": networks,
            "network_colors": {n: NETWORK_COLORS.get(n, "#c9a898") for n in networks},
            "currencies": sorted({(c.get("currency") or "USD").strip() or "USD"
                                  for c in classified}),
            "breakdown": {
                "network_rows": network_rows,
                "processor_rows": processor_rows,
                "total_amounts": _by_currency(classified),
            },
            "performance": {
                "status_stacks": status_stacks,
                "status_order": STATUS_ORDER,
                "status_table": status_table,
                "recovered_rows": recovered_rows,
                "fought_rows": fought_rows,
                "won": won, "lost": lost, "conceded": conceded, "pending": pending,
                "decided": decided,
                "win_rate": _pct(won, decided),
                "amounts_won": _by_currency(status_cases["Won"]),
                "amounts_lost": _by_currency(status_cases["Lost"]),
                "amounts_pending": _by_currency(status_cases["Decision Pending"]),
                "fought": len(fought_cases), "not_fought": len(not_fought_cases),
                # Win rate cut two ways: by the network that raised the dispute,
                # and by the kind of dispute it is.
                "win_by_network": cls._build_win_by_network(net_cases, networks),
                "win_by_category": cls._build_win_by_category(classified),
                "min_rate_sample": MIN_RATE_SAMPLE,
                # The sheet's outcome columns are simulated; say so on the page.
                "simulated": True,
            },
            "stages": stages,
            "geography": geography,
            "reason_panels": reason_panels,
            "trend": trend,
        }

    @classmethod
    def representment(cls, classified):
        """How the disputes we actually contested have landed, and for how much.

        `classified`: cases carrying an `ml` dict, same contract as compute().
        Taking them pre-classified rather than importing AIValidationEngine here
        keeps this module free of a dependency on the engine.

        A different question from the rest of the dashboard, which describes the
        whole book. This describes only the *representment pool* -- cases where
        a rebuttal has been filed, either because an agent submitted one or
        because the engine auto-represented it. Everything else is excluded and
        counted separately, because a case nobody has fought yet says nothing
        about how well we fight.

        Outcomes are read, never modelled. `case_status` is the only source; a
        book with no decisions in it reports no decisions rather than projecting
        any, which is what `has_decisions` is for.

        Deliberately narrower than `_is_fought`, which treats a pending case as
        fought. That is the right call for the Fought-vs-Not-Fought split (it
        asks "did we concede?"), and the wrong one here (this asks "did we
        file?").
        """
        pool, outside_hitl, outside_accept, outside_other = [], 0, 0, 0
        for c in classified:
            routing = (c.get("ml") or {}).get("routing", "")
            submitted = (c.get("submission_status") or "").strip() == "Submitted"
            if submitted or routing == "auto_represent":
                pool.append(c)
            elif routing == "hitl_review":
                outside_hitl += 1
            elif routing == "accept_refund":
                outside_accept += 1
            else:
                outside_other += 1

        buckets = {"Won": [], "Lost": [], "Decision Pending": []}
        for c in pool:
            status = cls._status(c)
            # A conceded case cannot be in the pool -- conceding is the decision
            # not to file -- but map it rather than dropping it silently if some
            # future action leaves that combination behind.
            buckets.setdefault("Decision Pending" if status == "Not Fought"
                               else status, []).append(c)

        rows = [{"name": s, "color": OUTCOME_COLORS[s], "count": len(buckets[s]),
                 "pct": _pct(len(buckets[s]), len(pool)),
                 "amounts": _by_currency(buckets[s])}
                for s in ("Won", "Lost", "Decision Pending")]
        cls._add_arcs(rows)

        total_amounts = _by_currency(pool)
        won_amounts = _by_currency(buckets["Won"])
        # Per currency, never one figure: recovered ÷ disputed across IDR, NGN
        # and USD would be a ratio of incompatible units.
        recovery = {cur: _pct(won_amounts.get(cur, 0), amt)
                    for cur, amt in total_amounts.items()}

        won, lost = len(buckets["Won"]), len(buckets["Lost"])
        decided = won + lost
        outside = outside_hitl + outside_accept + outside_other

        reasons = []
        if outside_hitl:
            reasons.append(f"{outside_hitl} awaiting human review")
        if outside_accept:
            reasons.append(f"{outside_accept} recommended for acceptance")
        if outside_other:
            reasons.append(f"{outside_other} not yet routed")

        return {
            "pool": len(pool),
            "outside": outside,
            "outside_reasons": reasons,
            "rows": rows,
            "amounts": {"total": total_amounts, "won": won_amounts,
                        "lost": _by_currency(buckets["Lost"]),
                        "pending": _by_currency(buckets["Decision Pending"])},
            "recovery": recovery,
            "won": won, "lost": lost, "decided": decided,
            "pending": len(buckets["Decision Pending"]),
            "win_rate": _pct(won, decided),
            "has_decisions": decided > 0,
        }

    @staticmethod
    def _rca_checks():
        """The weaknesses a lost case can honestly be tested for.

        (key, label, matrix item name or None, predicate). Every predicate
        reads a field the case genuinely carries; the delivery ones read
        case["source"] raw rather than through _order_view, whose placeholder
        strings ("—", "Not applicable") would land in a histogram as if they
        were data. Order here is only the tie-break — the page sorts by lift.
        """
        def src(c):
            return c.get("source") or {}

        def absent(v):
            v = (v or "").strip()
            return not v or v.upper().startswith("N/A")

        def threed_weak(c):
            v = (c.get("threed_secure") or "").lower()
            # "not authenticated" is tested first because "authenticated" is a
            # substring of it — the trap extract_signals fell into once.
            return bool(v) and ("not authenticated" in v
                                or "authenticated" not in v)

        return [
            ("threed", "3DS not fully authenticated", "3d secure", threed_weak),
            ("avs", "AVS no-match", None,
             lambda c: "no match" in (c.get("avs_response") or "").lower()),
            ("cvv", "CVV no-match", None,
             lambda c: "no match" in (c.get("cvv_response") or "").lower()),
            ("liability", "No liability shift", None,
             lambda c: not c.get("liability_shift")),
            ("pod", "No proof of delivery", "proof of delivery",
             lambda c: (src(c).get("ProofOfDelivery") or "").strip().lower() == "no"),
            ("signature", "Delivery not signed for", "proof of delivery",
             lambda c: absent(src(c).get("DeliverySignedBy"))),
            ("undelivered", "Item never delivered", None,
             lambda c: ("return" in (src(c).get("DeliveryStatus") or "").lower()
                        or "transit" in (src(c).get("DeliveryStatus") or "").lower())),
            ("ai_accept", "Engine had recommended accepting", None,
             lambda c: (c.get("ml") or {}).get("routing") == "accept_refund"),
        ]

    @classmethod
    def root_cause(cls, classified, matrix_notes=None, family_labels=None):
        """Why decided cases were lost, and where the losses concentrate.

        `classified`: cases carrying `ml`, same contract as representment().
        `matrix_notes` / `family_labels` come from the evidence matrix via
        app.py, so the ontology stays single-sourced — this module never
        duplicates a row of the management workbook.

        Decided = Won + Lost only, matching representment() next door and
        deliberately narrower than _outcome_split(), which counts Not Fought
        as decided. A concession is a choice we made; root-cause analysis asks
        about rulings that went against us.

        Outcomes are read, never modelled: a book with no CaseOutcome column
        reports has_decisions False and the page explains itself instead of
        rendering a table of zeros. With few losses every rate is returned
        beside its count and rows under MIN_RATE_SAMPLE are marked thin —
        eight losses is a lead to investigate, not a statistic.
        """
        notes = matrix_notes or {}
        fams = family_labels or {}

        order = ("Won", "Lost", "Not Fought", "Decision Pending")
        buckets = {s: [] for s in order}
        for c in classified:
            buckets[cls._status(c)].append(c)

        statuses = [{"name": s, "color": OUTCOME_COLORS[s],
                     "count": len(buckets[s]),
                     "pct": _pct(len(buckets[s]), len(classified)),
                     "amounts": _by_currency(buckets[s])}
                    for s in order]
        cls._add_arcs(statuses)

        won_cases, lost_cases = buckets["Won"], buckets["Lost"]
        decided_cases = won_cases + lost_cases
        won, lost = len(won_cases), len(lost_cases)
        decided = won + lost

        weaknesses = []
        for key, label, item, test in cls._rca_checks():
            with_w = [c for c in decided_cases if test(c)]
            lost_with = sum(1 for c in with_w if cls._status(c) == "Lost")
            without_n = decided - len(with_w)
            rate_with = _pct(lost_with, len(with_w))
            rate_without = _pct(lost - lost_with, without_n)
            measurable = len(with_w) > 0
            weaknesses.append({
                "key": key, "label": label,
                "matrix": notes.get(item, "") if item else "",
                "decided_with": len(with_w), "lost_with": lost_with,
                "loss_rate_with": rate_with,
                "loss_rate_without": rate_without,
                "lift": round(rate_with - rate_without, 1) if measurable else 0.0,
                "thin": 0 < len(with_w) < MIN_RATE_SAMPLE,
                "measurable": measurable,
            })
        weaknesses.sort(key=lambda r: (r["measurable"], r["lift"]), reverse=True)

        def breakdown(label_of):
            groups = {}
            for c in decided_cases:
                groups.setdefault(label_of(c), []).append(c)
            rows = []
            for lab, cs in groups.items():
                lost_here = [x for x in cs if cls._status(x) == "Lost"]
                rows.append({"label": lab, "lost": len(lost_here),
                             "decided": len(cs),
                             "loss_rate": _pct(len(lost_here), len(cs)),
                             "amounts": _by_currency(lost_here)})
            rows.sort(key=lambda r: (r["lost"], r["decided"]), reverse=True)
            return rows

        loss_by = {
            "family": breakdown(
                lambda c: fams.get(c.get("reason_code_canonical") or "")
                or (c.get("reason_code_canonical") or "Unresolved family")),
            "network": breakdown(lambda c: c.get("payment_method") or "Unknown"),
            "processor": breakdown(lambda c: c.get("processor") or "Unknown"),
        }

        # Insight sentences: each asserts only what its numbers support, and
        # carries the counts — a rate over eight losses must never travel
        # without its denominator.
        insights = []
        if lost:
            best = (next((w for w in weaknesses
                          if w["measurable"] and not w["thin"] and w["lift"] > 0
                          and w["lost_with"]), None)
                    or next((w for w in weaknesses
                             if w["measurable"] and w["lift"] > 0
                             and w["lost_with"]), None))
            if best:
                caveat = (" — a small sample, treat as a lead"
                          if best["thin"] else "")
                insights.append(
                    f"{best['lost_with']} of {lost} losses carry "
                    f"\"{best['label']}\": decided cases with it lose at "
                    f"{best['loss_rate_with']}% against "
                    f"{best['loss_rate_without']}% without it{caveat}.")

            top_fam = next((r for r in loss_by["family"] if r["lost"]), None)
            if top_fam:
                insights.append(
                    f"{top_fam['label']} disputes account for "
                    f"{top_fam['lost']} of {lost} losses "
                    f"({top_fam['loss_rate']}% of their {top_fam['decided']} "
                    f"decided cases).")

            top_proc = next((r for r in loss_by["processor"] if r["lost"]), None)
            if top_proc:
                insights.append(
                    f"{top_proc['label']} carries the most lost cases: "
                    f"{top_proc['lost']} of {lost}.")

            # Skipped when the lift line above already named this weakness —
            # two sentences about the same eight losses read as padding.
            ai_row = next(w for w in weaknesses if w["key"] == "ai_accept")
            if ai_row["lost_with"] and (not best or best["key"] != "ai_accept"):
                insights.append(
                    f"{ai_row['lost_with']} of {lost} losses were cases the "
                    f"engine had recommended accepting rather than fighting.")

            amounts = _by_currency(lost_cases)
            if amounts:
                pretty = " · ".join(f"{cur} {val:,.2f}"
                                    for cur, val in amounts.items())
                insights.append(
                    f"Value lost across {lost} "
                    f"case{'' if lost == 1 else 's'}: {pretty}.")

        return {
            "total": len(classified),
            "statuses": statuses,
            "won": won, "lost": lost, "decided": decided,
            "win_rate": _pct(won, decided),
            "won_amounts": _by_currency(won_cases),
            "lost_amounts": _by_currency(lost_cases),
            "has_decisions": decided > 0,
            "has_losses": lost > 0,
            "weaknesses": weaknesses,
            "loss_by": loss_by,
            "insights": insights[:5],
            "min_sample": MIN_RATE_SAMPLE,
        }

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _network(case):
        raw = (case.get("payment_method") or case.get("card_network") or "").strip()
        if not raw:
            return "Other"
        low = raw.lower()
        if low.startswith("visa"):
            return "Visa"
        if low.startswith("master") or low == "mc":
            return "Mastercard"
        if "amex" in low or "american" in low:
            return "Amex"
        if low.startswith("discover"):
            return "Discover"
        if low.startswith("klarna"):
            return "Klarna"
        return raw

    @staticmethod
    def _status(case):
        """The deck's four case states.

        Prefers `case_status`, which the sheet supplies directly and which keeps
        "Not Fought" distinct. Falls back to the app's older outcome vocabulary,
        where a conceded case is recorded as a refund.
        """
        status = (case.get("case_status") or "").strip()
        if status in OUTCOME_COLORS:
            return status

        outcome = (case.get("outcome") or "").strip().lower()
        if outcome == "win":
            return "Won"
        if outcome == "lost":
            return "Lost"
        if outcome == "refunded":
            return "Not Fought"
        return "Decision Pending"

    @classmethod
    def _is_fought(cls, case):
        """Was the case defended rather than conceded?

        A recorded status settles it. Without one, fall back to the ML routing.
        """
        status = (case.get("case_status") or "").strip()
        if status in OUTCOME_COLORS:
            return status != "Not Fought"

        routing = (case.get("ml") or {}).get("routing", "")
        if routing:
            return routing != "accept_refund"
        return (case.get("outcome") or "") != "Refunded"

    @classmethod
    def _build_stages(cls, classified, total):
        """Dispute stage — the deck's "CB Type" chart.

        Stages the label map doesn't know keep their raw code, so an unexpected
        value shows up on the chart instead of vanishing into an Other bucket.
        """
        counts = Counter()
        for c in classified:
            raw = (c.get("dispute_stage") or "").strip() or "Unspecified"
            counts[STAGE_LABELS.get(raw, raw)] += 1

        ordered = [s for s in STAGE_ORDER if s in counts]
        ordered += sorted(s for s in counts if s not in STAGE_ORDER)

        peak = max(counts.values(), default=0)
        rows = [{
            "name": s,
            "count": counts[s],
            "pct": _pct(counts[s], total),
            # Bar height relative to the tallest, so a short bar stays visible.
            "bar_pct": round(counts[s] / peak * 100, 1) if peak else 0,
            "known": s in STAGE_ORDER,
        } for s in ordered]
        return {"rows": rows, "total": sum(counts.values()),
                "unmapped": [r["name"] for r in rows if not r["known"]]}

    @classmethod
    def _build_geography(cls, classified, networks, total):
        """Top delivery regions, each split by card network, plus countries.

        The region column mixes US state codes with worldwide regions and marks
        digital orders as having no destination, so this is labelled by region
        rather than by state, and digital keeps its own bar instead of being
        dropped.
        """
        region_counts = Counter()
        region_by_net = defaultdict(Counter)
        country_counts = Counter()

        for c in classified:
            src = c.get("source") or {}
            region = (src.get("DeliveryState") or "").strip() or "Unknown"
            country = (src.get("DeliveryCountry") or "").strip() or "Unknown"
            region_counts[region] += 1
            region_by_net[region][cls._network(c)] += 1
            country_counts[country] += 1

        top = [r for r, _ in region_counts.most_common(TOP_N_REGIONS)]
        # Bars are per network, so they scale against the tallest single bar —
        # scaling against the region total would squash every bar to a stub.
        peak = max((region_by_net[r][n] for r in top for n in networks), default=0)
        region_rows = [{
            "name": r,
            "count": region_counts[r],
            "pct": _pct(region_counts[r], total),
            "digital": r == DIGITAL_REGION,
            "bars": [{
                "name": n,
                "color": NETWORK_COLORS.get(n, "#c9a898"),
                "count": region_by_net[r][n],
                "bar_pct": round(region_by_net[r][n] / peak * 100, 1) if peak else 0,
            } for n in networks],
        } for r in top]

        covered = sum(region_counts[r] for r in top)
        country_peak = max(country_counts.values(), default=0)
        country_rows = [{
            "name": name,
            "count": cnt,
            "pct": _pct(cnt, total),
            "bar_pct": round(cnt / country_peak * 100, 1) if country_peak else 0,
        } for name, cnt in country_counts.most_common()]

        return {
            "region_rows": region_rows,
            "country_rows": country_rows,
            "covered": covered,
            "other": total - covered,
            "distinct_regions": len(region_counts),
            "peak": peak,
        }

    @classmethod
    def _build_reason_panels(cls, net_cases, networks):
        """Top reason codes within each card network.

        Each panel reports its own case count: on a sheet where reason codes are
        nearly unique, the bars are short because the sample is small, and the
        reader should be able to see that rather than guess.
        """
        panels = []
        for n in networks:
            cases = net_cases.get(n, [])
            counts = Counter()
            labels = {}
            for c in cases:
                code = (c.get("reason_code") or "").strip() or "Unspecified"
                counts[code] += 1
                labels.setdefault(code, (c.get("source") or {}).get("ReasonMsg", "")
                                  or c.get("reason_description", "") or code)
            top = counts.most_common(TOP_N_REASONS)
            peak = top[0][1] if top else 0
            panels.append({
                "network": n,
                "color": NETWORK_COLORS.get(n, "#c9a898"),
                "cases": len(cases),
                "distinct": len(counts),
                "covered": sum(cnt for _, cnt in top),
                "rows": [{
                    "code": code,
                    "label": labels[code],
                    "count": cnt,
                    "pct": _pct(cnt, len(cases)),
                    "bar_pct": round(cnt / peak * 100, 1) if peak else 0,
                } for code, cnt in top],
            })
        return panels

    @classmethod
    def _outcome_split(cls, cases):
        """Won / lost / conceded / pending counts for one slice of the book.

        `decided` deliberately counts a conceded case: choosing not to fight is
        a decision, and leaving it out of the denominator would flatter the win
        rate by hiding every case we gave up on.
        """
        counts = Counter(cls._status(c) for c in cases)
        won = counts["Won"]
        lost = counts["Lost"]
        not_fought = counts["Not Fought"]
        decided = won + lost + not_fought
        return {
            "won": won, "lost": lost, "not_fought": not_fought,
            "pending": counts["Decision Pending"],
            "decided": decided,
            "total": len(cases),
            "win_rate": _pct(won, decided),
            "loss_rate": _pct(lost + not_fought, decided),
            # A rate off a handful of cases is noise wearing a percent sign.
            "thin": decided < MIN_RATE_SAMPLE,
        }

    @classmethod
    def _build_win_by_network(cls, net_cases, networks):
        """Win rate per card network, in the same order the pie above it uses.

        Every row carries its own `decided` count so the reader can see the
        denominator the rate was taken over, rather than trusting a bare
        percentage drawn from eight cases.
        """
        rows = []
        for n in networks:
            row = cls._outcome_split(net_cases.get(n, []))
            row["name"] = n
            row["color"] = NETWORK_COLORS.get(n, "#c9a898")
            row["bar_pct"] = row["win_rate"]
            rows.append(row)
        return rows

    @classmethod
    def _build_win_by_category(cls, classified):
        """How each dispute family resolves, as counts rather than as a rate.

        Reported as a stacked count bar on purpose. Processing Error decides
        three won and none lost on the current sheet; as "75%" that reads as the
        strongest family in the book, while a stubby four-case bar shows the
        reader exactly how little is behind it. The rate is still returned, but
        `thin` marks the ones the page should not state flatly.

        Groups on the sheet's own category wording. Cases with none -- seeded
        cases carry no sheet row -- are kept under "Unspecified" rather than
        dropped, so the bars always account for the whole book.
        """
        buckets = defaultdict(list)
        for c in classified:
            label = (c.get("reason_category_label") or "").strip() or "Unspecified"
            buckets[label].append(c)

        rows = []
        for label, cases in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            row = cls._outcome_split(cases)
            row["name"] = label
            row["segments"] = [{
                "name": s,
                "color": OUTCOME_COLORS[s],
                "count": row[key],
                "pct": _pct(row[key], row["total"]),
            } for s, key in zip(OUTCOME_ORDER,
                                ("won", "lost", "not_fought", "pending"))
                if row[key]]
            rows.append(row)
        return rows

    @staticmethod
    def _add_arcs(rows):
        """Attach cumulative start/end degrees for a CSS conic-gradient pie."""
        total = sum(r["count"] for r in rows)
        cursor = 0.0
        for r in rows:
            span = (r["count"] / total * 360) if total else 0
            r["start_deg"] = round(cursor, 2)
            cursor += span
            r["end_deg"] = round(cursor, 2)
        if rows:
            rows[-1]["end_deg"] = 360

    @classmethod
    def _case_date(cls, case):
        for field in ("dispute_creation_date", "submission_date", "transaction_date"):
            dt = parse_any_datetime(case.get(field))
            if dt:
                return dt
        return None

    @classmethod
    def _build_trend(cls, classified, networks):
        """Bucket cases by day / week / month, stacked by card network."""
        buckets = {"daily": defaultdict(Counter), "weekly": defaultdict(Counter),
                   "monthly": defaultdict(Counter)}
        amounts = {"daily": defaultdict(float), "weekly": defaultdict(float),
                   "monthly": defaultdict(float)}
        undated = 0

        for c in classified:
            dt = cls._case_date(c)
            if not dt:
                undated += 1
                continue
            net = cls._network(c)
            amt = safe_float(c.get("amount"))
            keys = {
                "daily": dt.strftime("%Y-%m-%d"),
                "weekly": (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d"),
                "monthly": dt.strftime("%Y-%m"),
            }
            for gran, key in keys.items():
                buckets[gran][key][net] += 1
                amounts[gran][key] += amt

        series = {}
        for gran in ("daily", "weekly", "monthly"):
            points = []
            for key in sorted(buckets[gran]):
                counts = buckets[gran][key]
                points.append({
                    "key": key,
                    "label": cls._trend_label(gran, key),
                    "total": sum(counts.values()),
                    "amount": round(amounts[gran][key], 2),
                    "by_network": {n: counts[n] for n in networks},
                })
            series[gran] = points

        peak = max((p["total"] for p in series["daily"]), default=0)
        return {
            "series": series,
            "undated": undated,
            "peak_daily": peak,
            "span": {
                "start": series["daily"][0]["key"] if series["daily"] else "",
                "end": series["daily"][-1]["key"] if series["daily"] else "",
                "days": len(series["daily"]),
            },
        }

    @staticmethod
    def _trend_label(gran, key):
        dt = parse_any_datetime(key if gran != "monthly" else key + "-01")
        if not dt:
            return key
        if gran == "monthly":
            return dt.strftime("%b %Y")
        if gran == "weekly":
            return "w/c " + dt.strftime("%d %b")
        return dt.strftime("%d %b")
