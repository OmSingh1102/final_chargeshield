"""The editable template repository.

Three kinds of template live here. Two of them flow through to the rebuttal a
case actually sends; the third is internal procedure text an agent reads but
never attaches.

    cover_letter  -> the representment letter body, one per reason category
    policy        -> the merchant policy documents quoted in the letter
    sop           -> standard operating procedures, repository-only

Nothing in this module stores anything. It describes what is editable and
resolves an override against the built-in text, so the store in ``app.py`` can
stay a plain dict of saved bodies and every consumer keeps working when that
dict is empty.

The built-in text is never migrated into the store. An unedited install has an
empty override dict and renders exactly as it did before this module existed,
which is also what makes "revert to built-in" a delete rather than a restore.
"""

from collections import OrderedDict

from chargeback.engines.cover_letter import COVER_LETTER_BODIES
from chargeback.engines.evidence_documents import DOCUMENTS


def safe_format(text, ctx):
    """``str.format_map`` that survives text a human typed.

    ``ctx`` is a defaultdict, so an unknown *field* already resolves to "N/A".
    An unbalanced brace is the real hazard: a lead writing "we charge {50%" in
    a cover letter would otherwise raise ValueError from deep inside the letter
    builder and take the whole page down. Falling back to the raw string keeps
    the stray brace visible in the output, which is the honest outcome — the
    text is wrong, but it is the text they saved.
    """
    try:
        return text.format_map(ctx)
    except (ValueError, IndexError, KeyError, AttributeError):
        return text


class TemplateRepository:
    """What may be edited, and how an override resolves against the built-ins.

    Named apart from ``cover_letter.RepositoryEngine``, which is an older
    constant holder for the mock dispute platform and unrelated to this.
    """

    # The five cover-letter fields that carry prose. ``heading``,
    # ``subheading`` and ``salutation`` are deliberately not editable: they are
    # structural, and the letter's own layout depends on them being short.
    LETTER_FIELDS = OrderedDict([
        ("intro", "Opening"),
        ("primary_defense_text", "Primary defence"),
        ("secondary_defense_text", "Secondary defence"),
        ("defense_points", "Defence points"),
        ("conclusion", "Closing"),
    ])

    # Substituted through safe_format when the letter is built, so an edited
    # body keeps the same placeholder vocabulary as the built-in one.
    LETTER_PLACEHOLDERS = [
        "{registeredcompany}", "{orderid}", "{chargebackamt}", "{chargebackdate}",
        "{reasoncode}", "{lower_CRT}", "{upper_CRT}", "{specialized_in}",
    ]

    KINDS = OrderedDict([
        ("cover_letter", {
            "label": "Cover Letters",
            "blurb": "The representment letter body, filed by reason category.",
            "flows": True,
            "where": "Sent as the letter on every case in that category.",
        }),
        ("policy", {
            "label": "Policy Documents",
            "blurb": "Merchant policy text quoted back to the issuer as evidence.",
            "flows": True,
            "where": "Rendered into its section of the counter evidence packet.",
        }),
        ("sop", {
            "label": "Standard Operating Procedures",
            "blurb": "Internal procedure notes. Read by agents, never attached to a case.",
            "flows": False,
            "where": "Reference only — no case ever carries an SOP.",
        }),
        ("narrative", {
            "label": "Rebuttal Prose",
            "blurb": "The letter body, section introductions and closing on the counter "
                     "evidence page.",
            "flows": True,
            "where": "Edited in place on a case, saved for that case or for every case "
                     "in its reason category.",
        }),
    ])

    # Starter procedures. Seeded as built-ins so the tile is never empty, and
    # editable like anything else. A lead may add more or delete these.
    SEED_SOPS = OrderedDict([
        ("evidence-intake", {
            "title": "Evidence Intake",
            "reason_codes": [],
            "body": (
                "1. Open the case from Chargeback Management and confirm the reason "
                "code matches the issuer's notice.\n"
                "2. Check which sections the packet already fetched. On a fully "
                "automated account there should be nothing to upload.\n"
                "3. Where a section asks for a file, pull the matching template "
                "from the Repository before writing anything by hand.\n"
                "4. Upload evidence against the named requirement, not as a loose "
                "attachment — a file filed under the wrong requirement does not "
                "count toward the winning ratio.\n"
                "5. Re-read the assembled letter end to end before submitting. "
                "Submission locks the case."
            ),
        }),
        ("reason-code-triage", {
            "title": "Reason Code Triage",
            "reason_codes": [],
            "body": (
                "Sort the queue by deadline, not by amount. A high-value case past "
                "its representment window is worth nothing.\n\n"
                "Fraud codes need the authorisation trail: AVS, CVV and 3DS status "
                "together. One of the three alone rarely holds.\n\n"
                "Goods-not-received needs delivery confirmation. Without a carrier "
                "signature or tracking event, escalate to a team lead rather than "
                "submitting a packet that will lose.\n\n"
                "Credit-not-processed is usually a records question — find the "
                "refund ARN and the date it settled."
            ),
        }),
        ("resubmission-checklist", {
            "title": "Resubmission Checklist",
            "reason_codes": [],
            "body": (
                "A case only reaches you again if a team lead released it for "
                "rework, so start by reading the note on why.\n\n"
                "1. Fix the specific item that was flagged. Do not rebuild the "
                "whole packet.\n"
                "2. Confirm every previously uploaded file is still listed. A file "
                "that vanished means it was filed under a requirement that no "
                "longer exists on this account's tier.\n"
                "3. Re-check the winning ratio. If it did not move, the correction "
                "did not land.\n"
                "4. Resubmit. The lock re-applies immediately and a second rework "
                "needs a fresh approval."
            ),
        }),
    ])

    # ── Introspection ────────────────────────────────────────────────────────

    @classmethod
    def policy_keys(cls):
        """Document keys that are merchant policy text, in registry order."""
        return [k for k, d in DOCUMENTS.items() if d.get("policy")]

    @classmethod
    def valid_key(cls, kind, key):
        """Whether `key` names something this kind can actually render.

        SOP keys are free-form — leads create them — so only shape is checked.
        The other two must name a live built-in, which is what stops a
        hand-edited store file from injecting a template with no render path.
        """
        if kind == "cover_letter":
            return key in COVER_LETTER_BODIES
        if kind == "policy":
            return key in DOCUMENTS and bool(DOCUMENTS[key].get("policy"))
        if kind == "sop":
            return bool(key) and isinstance(key, str) and len(key) <= 64
        if kind == "narrative":
            # "<block_id>:<scope>", scope being a reason category or "default".
            from chargeback.engines.narrative import NarrativeBlocks
            if not isinstance(key, str) or ":" not in key:
                return False
            block_id, scope = key.rsplit(":", 1)
            return (NarrativeBlocks.valid_block(block_id)
                    and (scope == "default" or scope in COVER_LETTER_BODIES))
        return False

    @classmethod
    def store_key(cls, kind, key):
        return f"{kind}:{key}"

    # ── Resolution ───────────────────────────────────────────────────────────

    @classmethod
    def resolve(cls, kind, key, overrides):
        """The saved body for this template, or None to use the built-in.

        Falls back from a reason-code-specific cover letter to `default`, the
        same order `build_cover_letter` already uses for the built-ins.
        """
        if not overrides:
            return None
        entry = overrides.get(cls.store_key(kind, key))
        if entry is None and kind == "cover_letter" and key != "default":
            entry = overrides.get(cls.store_key(kind, "default"))
        return entry

    @classmethod
    def apply_letter(cls, template, overrides, key):
        """Layer an override onto a built-in cover-letter body.

        Returns a new dict — the built-in registry is module-level state shared
        by every request and must never be mutated. Only fields the lead
        actually saved are replaced, so editing the closing paragraph alone
        leaves the rest of the letter built-in.
        """
        entry = cls.resolve("cover_letter", key, overrides)
        if not entry:
            return template
        merged = dict(template)
        for field in cls.LETTER_FIELDS:
            value = entry.get(field)
            if field == "defense_points":
                if isinstance(value, list) and value:
                    merged[field] = value
            elif isinstance(value, str) and value.strip():
                merged[field] = value
        return merged

    # ── The page ─────────────────────────────────────────────────────────────

    @classmethod
    def catalog(cls, overrides, letters, documents, sops):
        """Every template the repository lists, with its edit state.

        `letters` and `documents` arrive already shaped by the caller so this
        stays free of app-level concerns; it adds only what editing introduces.
        """
        overrides = overrides or {}

        def stamp(kind, key, item):
            entry = overrides.get(cls.store_key(kind, key)) or {}
            item = dict(item)
            item["edited"] = bool(entry)
            item["edited_by"] = entry.get("edited_by", "")
            item["edited_at"] = entry.get("edited_at", "")
            item["kind"] = kind
            return item

        return {
            "cover_letters": [stamp("cover_letter", c["key"], c) for c in letters],
            "documents": [stamp("policy", d["key"], d) if d.get("policy")
                          else {**d, "kind": "policy", "edited": False,
                                "edited_by": "", "edited_at": ""}
                          for d in documents],
            "sops": [stamp("sop", s["key"], s) for s in sops],
            "letter_fields": list(cls.LETTER_FIELDS.items()),
            "placeholders": cls.LETTER_PLACEHOLDERS,
        }

    @classmethod
    def sop_list(cls, overrides):
        """Seed SOPs plus any a lead created, minus any they deleted."""
        overrides = overrides or {}
        out = []
        seen = set()
        for key, seed in cls.SEED_SOPS.items():
            entry = overrides.get(cls.store_key("sop", key))
            if entry and entry.get("deleted"):
                continue
            seen.add(key)
            out.append({"key": key,
                        "title": (entry or {}).get("title") or seed["title"],
                        "body": (entry or {}).get("body") or seed["body"],
                        "seeded": True})
        for store_key, entry in overrides.items():
            if not store_key.startswith("sop:") or entry.get("deleted"):
                continue
            key = store_key.split(":", 1)[1]
            if key in seen:
                continue
            out.append({"key": key,
                        "title": entry.get("title") or key.replace("-", " ").title(),
                        "body": entry.get("body", ""),
                        "seeded": False})
        return out
