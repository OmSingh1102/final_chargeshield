"""Runtime case state, in SQLite, so it outlives the process.

Everything a user does to a case lives in a module-level list that dies with the
worker. Three JSON files used to carry part of it across a restart -- the agent
action, the allocation, the rework release -- and the rest was simply lost:
accepting a case, the evidence attached to it, and every timeline entry written
while working it.

This is one store for all of it. A snapshot per case rather than a log of
events, matching the _save_/_restore_ idiom this app already uses, and for one
concrete reason: dispute_history and manual_evidence are appended to, so an
event log would have to be replayed exactly once or it would double them.
Snapshotting the whole list makes a second replay a no-op, which matters because
_apply_cases runs again on every sheet re-upload.

Only case state is kept here. Passwords, credential ciphertext, client routing
and authored prose stay in their own files -- they are settings, not case
actions, and nothing in a rebuild path should be near a password hash.
"""
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "chargeback_state.db")

# The keys a user can change on a case. Everything else is rebuilt from the
# sheet on every boot, so storing it would only create a way for the two to
# disagree.
#
# ingest_source and win_probability are deliberately absent: both are derived
# during the load and would go stale the moment the sheet or the model changed.
RUNTIME_KEYS = (
    "agent_action",
    "agent_action_at",
    # Who took the action — provenance for a concession the same way
    # issuer_decision carries recorded_by for a ruling.
    "agent_action_by",
    "case_status",
    "outcome",
    "submission_status",
    "assigned_agent",
    "rework_released",
    "ml_override",
    "manual_evidence",
    "dispute_history",
    # An issuer ruling recorded in the app rather than read from the sheet.
    # outcome_date rides along with case_status/outcome: without it here, the
    # ruling date a lead typed would be lost on the next restart while the
    # decision it belongs to survived.
    "outcome_date",
    "issuer_decision",
    # The system's own filing of an auto-represent case: when it filed, and
    # the evidence completeness / model confidence it filed on. Written once
    # by _auto_submit_filed_cases at book load; rides with submission_status
    # the same way issuer_decision rides with case_status — without it the
    # filing date would shift on every restart.
    "auto_submitted",
    # The system's own allocation of a case at book load. Rides with
    # assigned_agent the way auto_submitted rides with submission_status;
    # /admin/allocate pops it the moment a person chooses, so provenance
    # stays true.
    "auto_assigned",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_state (
    case_id    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS added_case (
    case_id    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# The uploaded sheet the app is currently working from. The case list itself is
# a module-level Python list that dies with the process, so without this pointer
# an ingest would survive exactly until the next restart.
ACTIVE_DATASET_KEY = "active_dataset"

# The backend sheet the case list is joined against, under data/reference/.
# An ingested sheet may be a thin case list -- dispute id, stage, amount -- and
# this is where the rest of the case comes from: authentication results, card
# and cardholder, delivery proof. Joined on DisputeId.
REFERENCE_DATASET_KEY = "reference_dataset"


class StateStore:
    """Case state that survives a restart. Never raises at the caller.

    Every method swallows sqlite and JSON errors and reports through `on_error`,
    because the restore runs at import: an exception here would take the whole
    app down rather than merely losing a decision.
    """

    path = DB_PATH
    on_error = None          # set by the app to its logger

    # ── plumbing ────────────────────────────────────────────────────────────

    @classmethod
    def _warn(cls, message, exc):
        if cls.on_error:
            cls.on_error("%s: %s", message, exc)

    @classmethod
    def _connect(cls):
        # A connection per operation: the dev server is threaded and a sqlite3
        # connection may not cross threads. At a few hundred rows the cost of
        # opening one is not worth a pool.
        conn = sqlite3.connect(cls.path, timeout=5)
        # WAL lets a reader and a writer overlap, which a threaded server does.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        return conn

    # ── writing ─────────────────────────────────────────────────────────────

    @classmethod
    def save(cls, cases, baseline=None):
        """Store what a user changed, and only that.

        `baseline` is what each case looked like straight off the sheet. Four of
        the runtime keys -- the three status fields and dispute_history -- are
        also set during the load, so storing them unconditionally would put the
        sheet's own values in the database and then replay them over the top of
        the next sheet, freezing the book at whatever was loaded first. Anything
        equal to the baseline is therefore left out.

        A case whose state has been undone back to the baseline is deleted
        rather than stored empty, so the table holds only real differences.

        The test is presence-and-difference, not truthiness. Emptying a field is
        itself a change: clearing a recorded ruling sets outcome_date back to
        "", and a truthiness test dropped that write, so the case reloaded as
        Decision Pending while still carrying the sheet's ruling date. The
        baseline is captured with the same rule, so a field the sheet already
        left empty still compares equal and stores nothing.
        """
        baseline = baseline or {}
        now = datetime.now().isoformat(timespec="seconds")
        rows, empty = [], []
        for case in cases:
            case_id = case.get("case_id")
            if not case_id:
                continue
            was = baseline.get(case_id, {})
            state = {k: case[k] for k in RUNTIME_KEYS
                     if k in case and case[k] != was.get(k)}
            if state:
                rows.append((case_id, json.dumps(state), now))
            else:
                empty.append((case_id,))

        try:
            with cls._connect() as conn:
                conn.executemany(
                    "INSERT INTO case_state (case_id, data, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(case_id) DO UPDATE SET "
                    "data=excluded.data, updated_at=excluded.updated_at", rows)
                conn.executemany("DELETE FROM case_state WHERE case_id = ?", empty)
        except (sqlite3.Error, ValueError, TypeError) as exc:
            cls._warn("Could not save case state", exc)
            return 0
        return len(rows)

    @classmethod
    def save_added_case(cls, case):
        """Keep a manually entered case. Without this it lives only in memory
        and the next restart drops it, sheet-loaded cases being rebuilt from
        the CSV and this one having no CSV row to come from."""
        case_id = case.get("case_id")
        if not case_id:
            return False
        try:
            with cls._connect() as conn:
                conn.execute(
                    "INSERT INTO added_case (case_id, data, created_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(case_id) DO UPDATE SET "
                    "data=excluded.data",
                    (case_id, json.dumps(case, default=str),
                     datetime.now().isoformat(timespec="seconds")))
        except (sqlite3.Error, ValueError, TypeError) as exc:
            cls._warn("Could not save the added case", exc)
            return False
        return True

    # ── settings ────────────────────────────────────────────────────────────
    #
    # app_setting is a plain key/value table. These three carry every setting;
    # the named wrappers below them exist so callers read as what they mean
    # rather than as a string key, and so a typo cannot silently create a new
    # setting nobody reads.

    @classmethod
    def _set_setting(cls, key, value, what):
        try:
            with cls._connect() as conn:
                conn.execute(
                    "INSERT INTO app_setting (key, value, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "value=excluded.value, updated_at=excluded.updated_at",
                    (key, value,
                     datetime.now().isoformat(timespec="seconds")))
        except (sqlite3.Error, ValueError, TypeError) as exc:
            cls._warn(f"Could not record the {what}", exc)
            return False
        return True

    @classmethod
    def _get_setting(cls, key, what):
        try:
            with cls._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM app_setting WHERE key = ?",
                    (key,)).fetchone()
        except sqlite3.Error as exc:
            cls._warn(f"Could not read the {what}", exc)
            return ""
        return (row[0] if row else "") or ""

    @classmethod
    def _clear_setting(cls, key, what):
        try:
            with cls._connect() as conn:
                conn.execute("DELETE FROM app_setting WHERE key = ?", (key,))
        except sqlite3.Error as exc:
            cls._warn(f"Could not clear the {what}", exc)
            return False
        return True

    # ── the active dataset ──────────────────────────────────────────────────

    @classmethod
    def set_active_dataset(cls, filename):
        """Record which uploaded sheet the app should load at boot.

        Only the filename is stored, never the rows: the CSV itself stays on
        disk under data/, so the sheet remains the single source of truth for
        case fields and case_state keeps holding only what a user changed.
        """
        return cls._set_setting(ACTIVE_DATASET_KEY, filename, "active dataset")

    @classmethod
    def active_dataset(cls):
        """The recorded sheet filename, or "" when nothing has been ingested.

        An empty return is a normal state, not an error: a fresh install has no
        dataset and every page is expected to render its empty state.
        """
        return cls._get_setting(ACTIVE_DATASET_KEY, "active dataset")

    @classmethod
    def clear_active_dataset(cls):
        """Forget the current sheet, returning the app to its empty state."""
        return cls._clear_setting(ACTIVE_DATASET_KEY, "active dataset")

    # ── the backend reference sheet ─────────────────────────────────────────
    #
    # Separate from the active dataset and deliberately so. The active dataset
    # is the case list -- which disputes exist. This is the detail behind them:
    # authentication results, card and cardholder, delivery proof. An ingested
    # sheet may carry only dispute ids and amounts, and is joined to this on
    # DisputeId to become a full case. Replacing it changes what the app knows
    # about cases; it never changes which cases there are.

    @classmethod
    def set_reference_dataset(cls, filename):
        """Record which sheet under data/reference/ backs the case detail."""
        return cls._set_setting(REFERENCE_DATASET_KEY, filename,
                                "reference dataset")

    @classmethod
    def reference_dataset(cls):
        """The reference sheet filename, or "" when none is configured.

        Empty is a supported state: ingest still works, the cases just carry
        only what the uploaded sheet itself holds.
        """
        return cls._get_setting(REFERENCE_DATASET_KEY, "reference dataset")

    @classmethod
    def clear_reference_dataset(cls):
        """Forget the backend sheet. Ingest keeps working, unenriched."""
        return cls._clear_setting(REFERENCE_DATASET_KEY, "reference dataset")

    # ── reading ─────────────────────────────────────────────────────────────

    @classmethod
    def added_cases(cls):
        """Manually entered cases, oldest first."""
        try:
            with cls._connect() as conn:
                rows = conn.execute(
                    "SELECT data FROM added_case ORDER BY created_at, case_id").fetchall()
        except sqlite3.Error as exc:
            cls._warn("Could not read added cases", exc)
            return []

        out = []
        for (blob,) in rows:
            try:
                case = json.loads(blob)
            except ValueError:
                continue
            if isinstance(case, dict) and case.get("case_id"):
                out.append(case)
        return out

    @classmethod
    def restore(cls, cases, valid_actions=(), valid_agents=()):
        """Re-apply stored state onto the current case set.

        Skips a case id the sheet no longer carries, an action the app no longer
        defines and an agent no longer on the roster, rather than trusting the
        file -- the same guards the JSON restores used, kept because a stored
        row outlives the code that wrote it.

        Assignment rather than merge: the stored list *is* the history, so a
        second call replaces it instead of appending to it.
        """
        try:
            with cls._connect() as conn:
                rows = conn.execute("SELECT case_id, data FROM case_state").fetchall()
        except sqlite3.Error as exc:
            cls._warn("Could not read case state", exc)
            return 0

        by_id = {c.get("case_id"): c for c in cases}
        restored = 0
        for case_id, blob in rows:
            case = by_id.get(case_id)
            if case is None:
                continue
            try:
                state = json.loads(blob)
            except ValueError:
                continue
            if not isinstance(state, dict):
                continue

            action = state.get("agent_action")
            if action and valid_actions and action not in valid_actions:
                state.pop("agent_action", None)
                state.pop("agent_action_at", None)
            agent = state.get("assigned_agent")
            if agent and valid_agents and agent not in valid_agents:
                state.pop("assigned_agent", None)
                # A stamp must not outlive the owner it describes.
                state.pop("auto_assigned", None)

            if not state:
                continue
            case.update({k: v for k, v in state.items() if k in RUNTIME_KEYS})
            restored += 1
        return restored

    # ── maintenance ─────────────────────────────────────────────────────────

    @classmethod
    def migrate_json(cls, agent_actions_file, allocations_file, rework_file):
        """Fold the three superseded JSON stores in, once.

        A deployment that has been running already has these files; without this
        its agents would find their decisions gone the first time the new code
        booted. The files are read and left alone -- deleting them would remove
        the fallback if this change is reverted.
        """
        if cls._count() or not any(os.path.exists(p) for p in
                                   (agent_actions_file, allocations_file, rework_file)):
            return 0

        def _load(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}

        merged = {}
        for case_id, entry in _load(agent_actions_file).items():
            if isinstance(entry, dict) and entry.get("action"):
                merged.setdefault(case_id, {}).update(
                    {"agent_action": entry["action"],
                     "agent_action_at": entry.get("at", "")})
        for case_id, agent in _load(allocations_file).items():
            if agent:
                merged.setdefault(case_id, {})["assigned_agent"] = agent
        for case_id, entry in _load(rework_file).items():
            if entry:
                merged.setdefault(case_id, {})["rework_released"] = entry

        if not merged:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with cls._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO case_state (case_id, data, updated_at) "
                    "VALUES (?, ?, ?)",
                    [(cid, json.dumps(state), now) for cid, state in merged.items()])
        except (sqlite3.Error, ValueError, TypeError) as exc:
            cls._warn("Could not migrate the JSON stores", exc)
            return 0
        return len(merged)

    @classmethod
    def _count(cls):
        try:
            with cls._connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM case_state").fetchone()[0]
        except sqlite3.Error:
            return 0

    @classmethod
    def clear(cls):
        """Drop every stored action. Not wired to logout -- state is meant to
        stay -- but a demo needs a way back to the sheet."""
        try:
            with cls._connect() as conn:
                conn.execute("DELETE FROM case_state")
                conn.execute("DELETE FROM added_case")
        except sqlite3.Error as exc:
            cls._warn("Could not clear case state", exc)
            return False
        return True
