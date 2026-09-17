from flask import (Flask, render_template, jsonify, request, redirect, url_for,
                   flash, session, send_file, send_from_directory, abort)
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet, InvalidToken
import hashlib
import hmac
import json
import os
import re
import secrets
import csv as _csv
import copy
import io
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from functools import wraps

# ─── Modular imports ───────────────────────────────────────────────────────────
from chargeback.utils.datetime_helpers import safe_float as _safe_float, parse_any_datetime as _parse_any_datetime, fmt_datetime as _fmt_datetime
from chargeback.utils.hashing import deterministic_seed
from chargeback.data.loader import ChargebackCaseLoader
from chargeback.data.seed import CASES, IngestionDemo
from chargeback.data.state_store import StateStore, RUNTIME_KEYS
from chargeback.engines.reason_code import REASON_CODES, SCENARIO_CATEGORIES, ReasonCodeInterpreter, ReasonCodeRulebook
from chargeback.engines.pipeline import DatabaseOrchestrator, DecisionPackageBuilder, ChargebackPipeline
from chargeback.engines.ai_validation import AIValidationEngine, ChargebackClassifier
from chargeback.engines.evidence_collection import EvidenceCollectionEngine
from chargeback.engines.evidence_matrix import (DATABASES, EVIDENCE_MATRIX,
                                                SECTION_BY_FAMILY)
from chargeback.engines.provider_registry import (CATEGORY_ORDER, GENERIC_SCHEMA,
                                                  PENDING_NOTES, PROVIDERS,
                                                  SCHEMAS, panel_allowed_fields,
                                                  schema_for, secret_fields_for)
from chargeback.engines.cover_letter import RepositoryEngine, CoverLetterAIEngine, COVER_LETTER_BODIES
from chargeback.engines.evidence_documents import DOCUMENTS
from chargeback.engines.repository import TemplateRepository
from chargeback.engines.narrative import NarrativeBlocks
from chargeback.engines.pdf_converter import PDFPacketConverter
from chargeback.engines.packet_pdf import render_packet_pdf
from chargeback.engines.dispute_platform import DisputeAutomationPlatform, PSPDisputeAPI, GatewayEvidenceAPI, CRMOrderAPI, PODTrackingAPI
from chargeback.analytics.dashboard import DashboardAnalytics
from chargeback.analytics.manager_charts import ManagerCharts
from chargeback.analytics.executive import ExecutiveAnalytics
from chargeback.analytics.qa_review import QAReviewEngine
from chargeback.analytics.agent_desk import AgentDesk
from chargeback.analytics.agent_console import AgentConsole
from chargeback.analytics.team_console import TeamConsole
from chargeback.analytics.manager_console import ManagerConsole
from chargeback.analytics.ingest_console import IngestConsole
from chargeback.analytics.client_console import ClientConsole
from chargeback.analytics.customer_history import CustomerHistory
from chargeback.adapters.registry import register_default_adapters

# ─── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "chargeback-dev-key"

# The ingest page tells the user ".csv up to 25 MB". Nothing enforced that
# before, so the label was a claim rather than a limit; this makes it true.
# Werkzeug raises 413 past it, handled below so the user gets the page back
# with an explanation instead of a bare error.
MAX_UPLOAD_MB = 25
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# The state store must never raise — its restore runs at import, so an
# unwritable or locked database would take the app down rather than merely
# losing a decision. It reports here instead.
StateStore.on_error = app.logger.warning
register_default_adapters()


# ─── Sign-in and role routing ─────────────────────────────────────────────────
# Demo gate only: a hardcoded user table, no password hashing, and the session
# cookie is signed with the dev secret above. It decides which profile page a
# user lands on — it is not a security control.
#
# The Straive door lets you pick your profile from a dropdown (see
# STRAIVE_LOGIN_PROFILES). That would be a privilege-escalation hole in a real
# system; here the passwords are printed on the card beside it, so choosing a
# profile gives away nothing that reading the page did not. The client door at
# /login/client still derives its role from the credential, because a merchant
# picking their own book would be a different thing entirely.
_DEMO_USERS = {
    # One login per agent, so each signs in to their own queue. All three hold
    # the same role — the queue they own is what differs, via AGENT_LOGIN_MAP.
    "agent":   {"password": "agent123",   "role": "agent"},
    "agent2":  {"password": "agent2123",  "role": "agent"},
    "agent3":  {"password": "agent3123",  "role": "agent"},
    # One team lead over the whole book. The second lead existed to give the
    # client-to-lead routing somewhere to route to; with a single client there
    # is nowhere else to route. Which agents report to them lives in LEAD_AGENTS.
    "admin":   {"password": "admin123",   "role": "admin"},
    "manager": {"password": "manager123", "role": "manager"},
    # One login per client book. A merchant signs in to their own brand and
    # sees nothing else — which book a login owns lives in CLIENT_LOGIN_MAP.
    "acme":      {"password": "acme123",      "role": "client"},
}
STRAIVE_USERS = {name: dict(rec) for name, rec in _DEMO_USERS.items()}

# Optional overrides: AGENT_PASSWORD / AGENT2_PASSWORD / ADMIN_PASSWORD / …
_ENV_OVERRIDDEN = False
for _name in STRAIVE_USERS:
    _env_pw = os.environ.get(f"{_name.upper()}_PASSWORD")
    if _env_pw:
        STRAIVE_USERS[_name]["password"] = _env_pw
        _ENV_OVERRIDDEN = True

# The one password the Straive door accepts for every profile, printed on the
# card. Shorter than MIN_PASSWORD_LENGTH on purpose: that floor governs a
# password a user chooses for themselves and might reuse elsewhere, and this is
# a demo fixture nobody is trusting with anything.
DEMO_PASSWORD = os.environ.get("STRAIVE_DEMO_PASSWORD", "1234")
STRAIVE_EMAIL_DOMAIN = "@straive.com"

# Only advertise credentials on the login card while they are the built-in demo
# set — never print a password someone set through the environment.
_SHOW_DEMO_HINT = not (_ENV_OVERRIDDEN or "STRAIVE_DEMO_PASSWORD" in os.environ)

# Which of the hash-assigned queues (Agent1/2/3) a login owns. Cases are split
# by deterministic_seed(case_id) % 3, so this one mapping is all that is needed
# to scope every agent page to a single person's work.
AGENT_LOGIN_MAP = {"agent": "Agent1", "agent2": "Agent2", "agent3": "Agent3"}
DEFAULT_AGENT = "Agent1"

# The profiles the Straive door offers, in the order they are listed.
#
# The *value* is the login key the rest of the app is built around: session
# ["user"] must stay one of these, because _current_agent, LEAD_AGENTS,
# USER_PROFILES and the password-expiry gate all key off it. The *label* is what
# a person sees, and for agents that is the queue they own rather than their
# login name — the queue is the only thing that differs between the three.
#
# So there is no "agent1" login. Agent1 is `agent`, and reading the labels as
# usernames is the one mistake this table exists to prevent.
STRAIVE_LOGIN_PROFILES = [
    ("manager", "Manager"),
    ("admin",   "Admin"),
    ("agent",   AGENT_LOGIN_MAP["agent"]),
    ("agent2",  AGENT_LOGIN_MAP["agent2"]),
    ("agent3",  AGENT_LOGIN_MAP["agent3"]),
]

# The client-side mirror. Deliberately no DEFAULT_CLIENT: an agent login with no
# queue can fall back to Agent1 because a manager inspecting a queue is
# legitimate, but nobody may fall back into a brand's book. An unmapped client
# login sees nothing at all.
CLIENT_LOGIN_MAP = {"acme": "Acme Online Store"}

# Which login the merchant door signs a demo email in as. Derived from the map
# above rather than written twice, so it cannot drift from it.
#
# There is no picker on that form, unlike the Straive door: with one book there
# is nothing to choose between. A second book would need one — this would then
# be picking a brand for the user, which is the one thing CLIENT_LOGIN_MAP's
# note above says must never happen by fallback.
CLIENT_DEMO_LOGIN = next(iter(CLIENT_LOGIN_MAP), "")

# The team hierarchy the manager owns: which agents report to which lead, and
# which client book each lead is responsible for. Both are editable from the
# management console and persisted beside the other override stores.
#
# One lead over all three agents, because there is one book to be accountable
# for. This is what scopes Rework Approvals and _role_switch's reopenable_here —
# with a single lead those stop being a per-team subset and show everything.
LEAD_AGENTS = {"admin": ["Agent1", "Agent2", "Agent3"]}
CLIENT_ROUTING = {"Acme Online Store": "admin"}
TEAM_LEADS = ["admin"]

# What we know about each client book as a customer rather than as a workload:
# the service tier their contract puts them on, and the merchant account record
# behind it. Keyed by the same labels the routing above uses, so a client has
# one identity across the manager console, the rebuttal builder and the portal.
#
# The tier is not a label. It decides how a representment packet is built —
# see ClientConsole.section_plan and counter_evidence().
CLIENT_PROFILES = {
    label: {"tier": ClientConsole.DEFAULT_TIER,
            "account": {key: "" for key in ClientConsole.ACCOUNT_FIELDS}}
    for label in TeamConsole.BUCKET_LABELS
}
CLIENT_PROFILES["Acme Online Store"].update({
    # No "tier" key on purpose. The comprehension above already supplies
    # ClientConsole.DEFAULT_TIER, so app.py names no tier at all — which is what
    # stops this file from being the one place a deleted tier could come back.
    "account": {"corp_name": "Acme Commerce Inc.", "signer_name": "R. Halloran",
                "processor_name": "Cybersource", "dba_name": "Acme Online Store",
                "mid_no": "8412200917", "approved_mv": "$75,000",
                "descriptor": "acme-store.example.com",
                "processor_id": "CYB-4471", "status": "Active",
                "pending_with": "", "updates": ""},
})

# Bumped every time shared state changes — routing, allocations, rework
# releases, agent actions, ingestion. Every page stamps the value it rendered
# with; the browser polls /state/version and offers a refresh when the two
# diverge. That is what stops one user's screen sitting stale after another
# user changes something underneath it.
#
# A plain int is enough: CPython guarantees `+= 1` under the GIL is not going
# to lose an increment badly enough to matter here, and the only thing anyone
# does with the number is compare it for equality.
STATE_VERSION = 0


def _bump_state():
    """Mark shared state as changed so open pages know to refresh."""
    global STATE_VERSION
    STATE_VERSION += 1

# Where each role lands after signing in, and what the header chip calls them.
ROLE_HOME = {"agent": "agent_dashboard", "admin": "admin_dashboard",
             "manager": "manager_hub", "client": "client_dashboard"}
ROLE_LABEL = {"agent": "Agent", "admin": "Admin (Team Lead)",
              "manager": "Management", "client": "Client"}

# The case list each role actually works from. Distinct from ROLE_HOME because a
# "back to the cases" link means the queue, not the landing page. Exists because
# chargeback_detail's "Back to Cases" pointed at the legacy /dashboard, which is
# in no role's sidebar — following it dropped an agent outside their own console
# with nothing to click back.
ROLE_CASES = {"agent": "agent_chargebacks", "admin": "admin_allocation",
              "manager": "manager_history", "client": "client_chargebacks"}

# Which roles may open each profile page. Anything not listed is shared by every
# signed-in user — case detail, counter evidence, rebuttal and so on.
PAGE_ROLES = {
    "manager_hub":      {"manager"},
    "agent_desk":       {"admin", "manager"},
    # QA Review is an audit tool over everyone's work, so it is not an agent
    # page any more — agents get the console below instead.
    "qa_review":        {"manager"},
    # Nav only — the route keeps @role_required("agent", "manager"), and this
    # dict has one functional reader, the NAV_PAGES filter below. Dropping
    # "manager" takes the "Agent Page" button out of the manager's top nav
    # without closing the page to them; the View-as toggle is how a manager
    # reaches the agent console now.
    "agent_dashboard":  {"agent"},
    "agent_chargebacks": {"agent", "manager"},
    "agent_repository": {"agent", "manager"},
    "agent_settings":   {"agent", "manager"},
    # The evidence-requirements matrix, one page per console shell. Reference
    # material, so every staff role may read its own console's copy.
    "agent_evidence":   {"agent", "manager"},
    "admin_evidence":   {"admin", "manager"},
    "manager_evidence": {"manager"},
    "admin_dashboard":  {"admin", "manager"},
    "admin_allocation": {"admin", "manager"},
    "admin_approvals":  {"admin", "manager"},
    "admin_repository": {"admin", "manager"},
    "admin_settings":   {"admin", "manager"},
    # Manual ingestion is a lead's fallback when the portal API fails, never an
    # agent's. The nav already omitted it for agents; now the route agrees.
    "ingest":           {"admin", "manager"},
    # Management only — onboarding and client-to-lead routing are meant to be
    # invisible to team leads and agents, not merely unlinked.
    "manager_history":  {"manager"},
    "manager_rca":      {"manager"},
    "manager_onboarding": {"manager"},
    "manager_settings": {"manager"},
    # The client portal. A merchant sees their own book and nothing else.
    "client_dashboard":   {"client"},
    "client_chargebacks": {"client"},
    "client_case":        {"client"},
    "client_processor":   {"client"},
    "client_letter":      {"client"},
    "client_letter_pdf":  {"client"},
    "client_packet_file": {"client"},
    "client_repository":  {"client"},
    "client_settings":    {"client"},
    "client_credentials": {"client"},
}

# The side pane on the management console. Data Ingestion appears here and on
# the team-lead console, but never on an agent's.
MANAGER_NAV = [
    {"endpoint": "manager_hub",        "label": "Data Dashboard",      "icon": "trending-up"},
    {"endpoint": "manager_history",    "label": "Chargeback History",  "icon": "file-text"},
    {"endpoint": "manager_operations", "label": "Operations",          "icon": "alert-circle"},
    {"endpoint": "manager_rca",        "label": "Root Cause Analysis", "icon": "search"},
    {"endpoint": "manager_evidence",   "label": "Evidence Requirements", "icon": "clipboard"},
    {"endpoint": "manager_onboarding", "label": "Onboarding & Clients", "icon": "building"},
    {"endpoint": "manager_settings",   "label": "System Settings",     "icon": "settings"},
    {"endpoint": "ingest",             "label": "Data Ingestion",      "icon": "upload"},
]

# The sidebar on the team-lead console, in display order. Data Ingestion points
# at the existing /ingest screen — manually uploading a case dump when the
# portal API fails is exactly a team lead's job.
#
# An entry carrying "children" is a collapsible group rather than a link. It has
# a "key" instead of an "endpoint" because a group has no URL of its own — give
# it a fake one and url_for raises at render time. Leaves keep their original
# shape, so the other three navs below need no change and the same loop renders
# all four.
ADMIN_NAV = [
    {"endpoint": "admin_dashboard",   "label": "Dashboard",        "icon": "grid"},
    # Allocation and rework approvals are one job — moving work to the right
    # agent and letting them fix it — so they sit under one heading rather than
    # as two unrelated siblings.
    {"key": "chargeback_management", "label": "Chargeback Management",
     "icon": "credit-card", "children": [
         {"endpoint": "admin_allocation", "label": "Case Allocation",  "icon": "users"},
         {"endpoint": "admin_approvals",  "label": "Rework Approvals", "icon": "check-circle"},
     ]},
    {"endpoint": "admin_evidence",    "label": "Evidence Requirements", "icon": "clipboard"},
    # Team Queue removed from the sidebar. The page itself stays reachable at
    # /agent-desk — its POST sibling /agent-desk/action is what the agent's own
    # Chargeback Management page calls to record an action, so the endpoint is
    # load-bearing even with nothing linking to the view.
    # Repository removed from the sidebar. /admin/repository still renders, and
    # its two POST siblings are what the page's own editors call, so the
    # endpoints stay live with nothing linking to the view.
    {"endpoint": "ingest",            "label": "Data Ingestion",   "icon": "upload"},
    {"endpoint": "admin_settings",    "label": "Settings",         "icon": "settings"},
]

# The sidebar on the agent console, in display order.
AGENT_NAV = [
    {"endpoint": "agent_dashboard",   "label": "Dashboard",             "icon": "grid"},
    {"endpoint": "agent_chargebacks", "label": "Chargeback Management", "icon": "credit-card"},
    {"endpoint": "agent_evidence",    "label": "Evidence Requirements", "icon": "clipboard"},
    # Repository removed from the sidebar; /agent/repository still renders.
    {"endpoint": "agent_settings",    "label": "Settings",              "icon": "settings"},
]

# The sidebar on the client portal. Kept out of NAV_PAGES deliberately — the
# top nav subscripts PAGE_ROLES directly, and the per-role sidebars do not.
CLIENT_NAV = [
    {"endpoint": "client_dashboard",   "label": "Dashboard",             "icon": "grid"},
    {"endpoint": "client_chargebacks", "label": "Chargeback Management", "icon": "credit-card"},
    # Repository removed from the sidebar. client_repository stays in
    # CLIENT_ENDPOINTS so the route keeps working for a merchant who has the
    # URL — dropping it from the allow-list would 302 them to sign-in instead.
    {"endpoint": "client_credentials", "label": "Credentials",           "icon": "key"},
    {"endpoint": "client_settings",    "label": "Settings",              "icon": "settings"},
]

# The top nav, in display order. Filtered per role by _inject_nav below, so the
# bar can never offer a page the signed-in user would be bounced off.
NAV_PAGES = [
    {"endpoint": "manager_hub",     "label": "Manager Hub", "icon": "trending-up"},
    # "Admin Page" (agent_desk) is deliberately not offered here. The route and
    # its two POST endpoints stay live — agent_chargebacks posts to
    # agent_desk_action — but the page is no longer linked from the top nav.
    {"endpoint": "agent_dashboard", "label": "Agent Page",  "icon": "user"},
]

# Reachable without signing in. Everything else is gated by _require_sign_in.
PUBLIC_ENDPOINTS = {"portal", "login", "client_login", "logout", "static"}

# Reachable while a password is past its change-by date. Deliberately tiny: the
# screen that fixes the problem, the stylesheet that makes it legible, the way
# out, and the state poll every console runs so it does not error in a loop.
PASSWORD_EXEMPT_ENDPOINTS = {"password_expired", "settings_password",
                             "logout", "static", "state_version"}

# Everything a signed-in client may reach. state_version keeps the live-refresh
# poll working; counter_evidence is deliberately absent — it carries upload and
# delete controls that belong to staff.
CLIENT_ENDPOINTS = {"client_dashboard", "client_chargebacks", "client_case",
                    # The processor screen for one of their own cases, and the
                    # letter we filed on it. The first is built from a
                    # projection, not the case dict — see _client_processor_view.
                    "client_processor", "client_letter", "client_letter_pdf",
                    # Attachments in that packet. counter_upload_download is
                    # deliberately still absent — it checks no ownership, so
                    # allow-listing it would open every case to every merchant.
                    "client_packet_file",
                    "client_repository", "client_settings",
                    "client_credentials", "client_credentials_save",
                    "client_credentials_mid", "client_credentials_reveal",
                    # The two the settings cards post to. settings_theme is
                    # deliberately absent — the portal is not themed, so the
                    # card is not rendered and the route stays closed to it.
                    "settings_profile", "settings_password",
                    "state_version", "logout", "static"}


def _login_page(error=None, email="", selected="", next_url="", status=200):
    return render_template(
        "login.html", next=next_url, error=error, email=email,
        # Carried back so a rejected attempt re-renders the form as it was
        # typed, rather than making the user fill it in again.
        selected=selected, profiles=STRAIVE_LOGIN_PROFILES,
        domain=STRAIVE_EMAIL_DOMAIN,
        # Staff door: only the shared password. The client credential is never
        # printed here — it would advertise a merchant's login to everyone who
        # opens the page.
        demo_password=DEMO_PASSWORD if _SHOW_DEMO_HINT else None,
    ), status


def _client_login_page(error=None, email="", status=200):
    return render_template(
        "client_login.html", error=error, email=email,
        demo_password=DEMO_PASSWORD if _SHOW_DEMO_HINT else None,
    ), status


_PBKDF2_ROUNDS = 120_000


def _hash_password(password: str, salt: str) -> str:
    """PBKDF2-SHA256 of a password, hex encoded.

    The built-in demo logins stay plaintext — they are printed on the login card
    and there is nothing to protect. This exists so a password a *user* chooses
    is not written to user_profiles.json in the clear, which is a different
    thing: they may well reuse it somewhere that matters.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()


def _password_record(username):
    """(hash, salt) for a user who has set their own password, else (None, None)."""
    rec = USER_PROFILES.get(username) or {}
    if rec.get("pw_hash") and rec.get("pw_salt"):
        return rec["pw_hash"], rec["pw_salt"]
    return None, None


def _authenticate(username: str, password: str):
    """Return (username, role) for valid credentials, else (None, None).

    Compares bytes, not str: compare_digest rejects non-ASCII strings, and a
    typed accent would otherwise raise instead of simply failing the check.
    Every known user is checked even after a match, and `&` is used rather than
    `and`, so the time taken does not depend on which name was typed.

    A user who has changed their password is checked against the stored PBKDF2
    hash instead of the built-in table. The loop shape is unchanged: the hash
    branch also runs for every user and also compares with compare_digest, so
    the timing property above still holds for the name.
    """
    typed_user = (username or "").encode("utf-8")
    typed_pw = (password or "").encode("utf-8")
    matched = (None, None)
    for name, rec in STRAIVE_USERS.items():
        stored_hash, salt = _password_record(name)
        if stored_hash:
            candidate = _hash_password(password or "", salt).encode("utf-8")
            expected = stored_hash.encode("utf-8")
        else:
            candidate = typed_pw
            expected = rec["password"].encode("utf-8")
        if (hmac.compare_digest(typed_user, name.encode("utf-8"))
                & hmac.compare_digest(candidate, expected)):
            matched = (name, rec["role"])
    return matched


def _valid_email(value: str):
    """The typed address lowercased, or "" if it does not look like one.

    Deliberately loose, for the reason settings_profile already gives about the
    email field it stores: rejecting a valid-but-unusual local part would be
    worse than accepting a malformed one. A local part, one @, and a dotted
    domain is as far as this goes.
    """
    email = (value or "").strip().lower()
    if len(email) > 120 or email.count("@") != 1:
        return ""
    local, _, domain = email.partition("@")
    ok = local and domain and "." in domain[1:-1]
    return email if ok else ""


def _straive_email(value: str):
    """A _valid_email that is also on the Straive domain, else "".

    The merchant door takes any address — a client is not on our domain — so the
    domain check lives here rather than in _valid_email.
    """
    email = _valid_email(value)
    return email if email.endswith(STRAIVE_EMAIL_DOMAIN) else ""


def _check_password(username: str, password: str) -> bool:
    """Whether this password opens `username`'s profile.

    Two things open it. The shared demo password, which is what the sign-in card
    tells people to use. And the profile's own credential — built-in,
    env-overridden, or a PBKDF2 hash the user set for themselves — which is what
    keeps the change-password card at /settings from becoming a write-only
    store, and what keeps an AGENT2_PASSWORD-style override meaning something.

    Accepting the demo password is also what makes the forced-change wall
    passable: _change_password asks for your current password, and for anyone
    who signed in through the dropdown that is the only password they hold.

    Both branches always run and combine with `|` rather than `or`, so the time
    taken does not reveal which one matched — the discipline _authenticate keeps
    for the username.
    """
    demo_ok = hmac.compare_digest((password or "").encode("utf-8"),
                                  DEMO_PASSWORD.encode("utf-8"))
    own_ok = _authenticate(username, password or "") != (None, None)
    return bool(demo_ok | own_ok)


def _password_age_days(username):
    """Whole days since this user last changed their password, or None."""
    changed = (USER_PROFILES.get(username) or {}).get("pw_changed_at", "")
    if not changed:
        return None
    try:
        when = datetime.strptime(changed[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return (datetime.now() - when).days


def _password_expired(username):
    """Whether this user is past the change-by date.

    An unparseable or missing date reads as *not* expired. A malformed store
    file should not lock every account out of the app.
    """
    age = _password_age_days(username)
    return age is not None and age > PASSWORD_MAX_AGE_DAYS


def _role_home_url(role=None):
    """The page this role owns; the portal if there is no usable role."""
    endpoint = ROLE_HOME.get(role or session.get("role"))
    return url_for(endpoint) if endpoint else url_for("portal")


def _role_cases_url(role=None):
    """This role's case queue, falling back to their home page.

    Same shape as _role_home_url deliberately: both are read by _inject_nav on
    every render, and neither may return a dead link for a roleless session.
    """
    endpoint = ROLE_CASES.get(role or session.get("role"))
    return url_for(endpoint) if endpoint else _role_home_url(role)


def _safe_next(target: str) -> str:
    """Only follow same-site paths.

    Rejects absolute URLs and protocol-relative ones. Browsers normalise
    backslashes to slashes, so '/\\host' is as dangerous as '//host'.
    """
    if target and target.startswith("/") and target[1:2] not in ("/", "\\"):
        return target
    return _role_home_url()


def role_required(*roles):
    """Restrict a view to the given roles.

    A signed-out visitor goes to the login form with their destination
    remembered. A signed-in user holding the wrong role is sent to their own
    page rather than shown an error — the nav never offers them the link, so
    reaching here means a hand-typed URL.
    """
    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if not role:
                return redirect(url_for("login", next=request.path))
            if role not in allowed:
                return redirect(_role_home_url(role))
            return view(*args, **kwargs)
        return wrapper
    return decorator


# Kept so the existing decorator site reads the same as before.
manager_required = role_required("manager")


@app.before_request
def _require_sign_in():
    """Everything outside PUBLIC_ENDPOINTS needs a session.

    One hook rather than a decorator on each of the thirty-odd routes: easier to
    audit, and impossible to forget when a route is added. `endpoint is None`
    means the URL matched nothing — let it fall through to the 404.
    """
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session.get("role"):
        return redirect(url_for("portal"))
    # A client is a customer, not staff. Allow-listing here rather than
    # decorating thirty routes means anything added later is closed to them
    # until it is named — the safe direction to fail in.
    if (session.get("role") == "client"
            and request.endpoint not in CLIENT_ENDPOINTS):
        return redirect(_role_home_url("client"))
    # Past the 45-day policy, nothing opens until the password is changed. The
    # three exemptions are what stop this being a lockout: without the change
    # screen itself the user cannot reach the page that fixes it, without static
    # it renders unstyled, and without logout they cannot even leave.
    if (request.endpoint not in PASSWORD_EXEMPT_ENDPOINTS
            and _password_expired(session.get("user", ""))):
        return redirect(url_for("password_expired"))
    return None


@app.context_processor
def _inject_nav():
    """Give every template the nav its role is allowed to see."""
    role = session.get("role")
    return {
        # .get, not [] — a NAV_PAGES entry with no PAGE_ROLES key used to raise
        # KeyError on every page render for every role.
        "nav_pages": [p for p in NAV_PAGES
                      if role in PAGE_ROLES.get(p["endpoint"], set())],
        "agent_nav": AGENT_NAV,
        "admin_nav": ADMIN_NAV,
        "manager_nav": MANAGER_NAV,
        "client_nav": CLIENT_NAV,
        "role_label": ROLE_LABEL.get(role, ""),
        # The Home button and the "back to cases" links read these. A context
        # processor is the whole delivery mechanism: it runs before every
        # render_template, so the five shells, all their children and the two
        # standalone documents get them without a single route changing.
        # _role_home_url falls through to the portal for a roleless session, so
        # neither key is ever a dead link.
        "home_url": _role_home_url(),
        "cases_url": _role_cases_url(),
        # Empty list in any build with real passwords set — see
        # _role_switch_options.
        "role_switch": _role_switch_options() if role else [],
        # The signed-in user's colour choice, stamped on <html> by the staff
        # shells. Every colour in the templates is written as
        # var(--token, #original), so "default" needs no theme block at all —
        # the fallbacks are the shipped palette.
        #
        # Coerced against UI_THEMES rather than read straight through: the
        # "blue" theme was retired, and a profile still holding it would stamp
        # data-theme="blue" with no rules behind it — a half-painted page
        # rather than a clean fall back to light.
        "ui_theme": _stored_theme(),
        # Stamped into every page so the browser can tell when the server has
        # moved on without it.
        "state_version": STATE_VERSION,
        # The line-icon macro, delivered the same way and for the same reason as
        # home_url above. A {% from "_icon.html" import icon %} in a shell does
        # not reach inside a {% block %} its children fill, so every page that
        # wanted an icon would need its own import; this reaches all of them.
        #
        # Fetched per render rather than cached at import: get_template honours
        # the loader's auto-reload, so editing _icon.html shows up without
        # restarting, the same as editing any other template.
        "icon": app.jinja_env.get_template("_icon.html").module.icon,
    }


# ─── Demo role switcher ────────────────────────────────────────────────────────
# Which login each console is demoed from. One per role, so the switch lands on
# a real account: plenty of code keys off session["user"] — _current_agent,
# LEAD_AGENTS, CLIENT_LOGIN_MAP — and a role without a matching user would break
# those rather than merely look odd.
ROLE_SWITCH_USERS = [
    ("manager", "manager", "Manager"),
    ("agent", "agent", "Agent"),
]


def _role_switch_options():
    """The View-as buttons, or [] when the switcher is off.

    Gated on _SHOW_DEMO_HINT, the same flag that decides whether the login page
    prints the built-in passwords. If those are advertised, this hands out
    nothing a visitor could not get by typing them; set any *_PASSWORD env var
    and both the hint and this disappear together.
    """
    if not _SHOW_DEMO_HINT:
        return []
    current = session.get("role")
    # The manager's own tool, so it shows on the manager console — and on the
    # agent console only for someone who got there through it. An agent who
    # signed in as an agent never sees it, which keeps the switch from being a
    # way up: the only role that can reach "Manager" is the one already there.
    if current != "manager" and not (current == "agent"
                                     and session.get("view_as_from") == "manager"):
        return []
    return [{"key": role, "label": label, "current": role == current,
             "title": f"Switch to the {label.lower()} console as '{user}'"}
            for role, user, label in ROLE_SWITCH_USERS]


@app.route("/switch-role", methods=["POST"])
def switch_role():
    """Jump between consoles without signing out. Demo builds only."""
    # Re-checked here, not just in the template — a hidden button is not a rule.
    if not _SHOW_DEMO_HINT:
        return redirect(_role_home_url() if session.get("role")
                        else url_for("portal"))
    # Only the manager may drive it, and only someone the manager sent to the
    # agent console may drive it back. Without this the button's absence would
    # be the whole rule, and an agent could POST their way to manager.
    if not _role_switch_options():
        return redirect(_role_home_url() if session.get("role")
                        else url_for("portal"))
    wanted = (request.form.get("as") or "").strip()
    match = next((u for u in ROLE_SWITCH_USERS if u[0] == wanted), None)
    if not match:
        return redirect(_role_home_url() if session.get("role")
                        else url_for("portal"))
    role, user, _label = match
    session["role"] = role
    session["user"] = user
    session["is_manager"] = (role == "manager")
    # Remembers that this agent seat is a manager looking around, which is what
    # keeps the way back visible. Cleared on the way home so a later sign-in as
    # a real agent inherits nothing.
    if role == "manager":
        session.pop("view_as_from", None)
    else:
        session["view_as_from"] = "manager"
    return redirect(_role_home_url(role))


@app.route("/state/version")
def state_version():
    """Cheap staleness probe polled by every open console.

    Deliberately does no analytics — it reads one integer, so polling it every
    few seconds costs nothing even with every role signed in at once.
    """
    return jsonify({"v": STATE_VERSION})


@app.route("/")
def portal():
    """Front door: choose Straive or Client sign-in."""
    if session.get("role"):
        return redirect(_role_home_url())
    return render_template("portal.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Straive sign-in — a Straive address, the demo password, and a profile."""
    next_url = request.values.get("next", "")
    if request.method == "POST":
        email = _straive_email(request.form.get("email", ""))
        name = request.form.get("role", "")
        # flash() is never rendered on this page, so errors are surfaced inline.
        # The domain rule and the profile list are both printed on the card, so
        # naming those two failures gives nothing away. A wrong password stays
        # generic below, and keeps its 401.
        typed = (request.form.get("email", "") or "").strip()
        if not email:
            return _login_page(error=f"Use your {STRAIVE_EMAIL_DOMAIN} email address.",
                               email=typed, selected=name, next_url=next_url,
                               status=400)
        if name not in dict(STRAIVE_LOGIN_PROFILES):
            return _login_page(error="Choose a profile to sign in as.",
                               email=typed, selected="", next_url=next_url,
                               status=400)
        if not _check_password(name, request.form.get("password", "")):
            return _login_page(error="Incorrect email or password.",
                               email=typed, selected=name, next_url=next_url,
                               status=401)

        session["role"] = STRAIVE_USERS[name]["role"]
        # The bare login key, never the email. _current_agent, LEAD_AGENTS,
        # USER_PROFILES and the expiry gate all key off this, and _current_agent
        # in particular falls back silently — an email here would put all three
        # agents on Agent1's queue with nothing to show it had gone wrong.
        session["user"] = name
        session["email"] = email
        # Still set for anything that reads the old flag.
        session["is_manager"] = (session["role"] == "manager")
        # A real sign-in is never a manager looking around, even if the
        # browser still carries the flag from an earlier switch.
        session.pop("view_as_from", None)
        return redirect(_safe_next(next_url) if next_url
                        else _role_home_url(session["role"]))
    if session.get("role"):
        return redirect(_safe_next(next_url) if next_url else _role_home_url())
    return _login_page(next_url=next_url)


@app.route("/login/client", methods=["GET", "POST"])
def client_login():
    """Merchant sign-in — an email address and the demo password.

    No profile picker, unlike the Straive door: CLIENT_DEMO_LOGIN explains why.
    Any address is accepted because a merchant is not on the Straive domain, so
    the address identifies a person to greet rather than an account to open —
    the book comes from the login this resolves to.
    """
    if request.method == "POST":
        email = _valid_email(request.form.get("email", ""))
        typed = (request.form.get("email", "") or "").strip()
        # What a valid address looks like is not a secret, so saying so is more
        # use than a blanket rejection. A wrong password stays generic below.
        if not email:
            return _client_login_page(error="Enter a valid email address.",
                                      email=typed, status=400)
        if not CLIENT_DEMO_LOGIN or not _check_password(
                CLIENT_DEMO_LOGIN, request.form.get("password", "")):
            return _client_login_page(error="Incorrect email or password.",
                                      email=typed, status=401)

        session["role"] = "client"
        # The login key, never the email — _current_client maps this through
        # CLIENT_LOGIN_MAP to decide whose book opens, and returns None for
        # anything it does not recognise, which signs the user straight out.
        session["user"] = CLIENT_DEMO_LOGIN
        session["email"] = email
        session["is_manager"] = False
        session.pop("view_as_from", None)
        return redirect(_role_home_url("client"))
    if session.get("role") == "client":
        return redirect(_role_home_url())
    return _client_login_page()


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("portal"))

# Working data set loaded at boot (see _load_startup_cases below).
#
# The previous sheet paired reason codes with card networks at random — Visa
# rows carrying Mastercard's 4837/4868, Amex rows carrying Discover's RG/RM,
# codes belonging to no network at all (1040, 3000, 6000), free text used as a
# code ("Goods not received"), and Klarna listed as a card scheme on a fifth of
# the book. This one is internally consistent: 19 (scheme, code) pairs, each
# code owned by the network it sits under, and four real reason categories.
# The old file is left on disk, so switching back is this one line.
#
# Nothing is loaded from here at boot any more. The app starts with an empty
# book and the sheet a user ingests becomes the active dataset — see
# UPLOAD_DIR, _load_startup_cases() and StateStore.active_dataset(). The two
# CSVs under static/ are sample data somebody can upload, not startup state.
SAMPLE_DATASET = "Chargeback_case_data_100.csv"

# Ingested sheets live here rather than under static/, which Flask serves
# publicly — this is a customer's dispute book, not an asset.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# The backend sheet an ingested case list is joined against, on DisputeId. Kept
# apart from UPLOAD_DIR because the two answer different questions: a file in
# data/ says which disputes exist, a file in here says what is known about them.
REFERENCE_DIR = os.path.join(UPLOAD_DIR, "reference")

# Actions an agent can record against a case from the Agent Desk, and what each
# one means for the fields the rest of the app reads.
#
# Manager Hub, the dashboard and QA Review all read `case_status` / `outcome`,
# never `agent_action` — so an action has to rewrite those to be visible
# anywhere else. An agent's decision overrides whatever the sheet recorded.
#
# "Contested" stays Decision Pending on purpose: defending a case is not the
# same as winning it. It still moves the fought/not-fought split, because
# `_is_fought()` keys off `case_status != "Not Fought"`.
AGENT_ACTION_EFFECTS = {
    "Contested":       {"case_status": "Decision Pending", "outcome": "Pending",
                        "submission_status": "Submitted"},
    "Not Fought":      {"case_status": "Not Fought", "outcome": "Refunded",
                        "submission_status": "Not Submitted"},
    "Waiting for POD": {"case_status": "Decision Pending", "outcome": "Pending",
                        "submission_status": "Awaiting Evidence"},
    "Pending":         {"case_status": "Decision Pending", "outcome": "Pending",
                        "submission_status": "Pending"},
}
AGENT_ACTIONS = list(AGENT_ACTION_EFFECTS)

# The two vocabularies for one fact, in one place. `case_status` is the
# reporting deck's wording ("Won"); `outcome` is what the rest of the app and
# the badge CSS speak ("Win" — .status-badge.win exists, .won does not). Both
# the sheet loader and the manual decision route derive from this map, so an
# issuer ruling typed into the app and one read from a CSV cannot disagree.
OUTCOME_BY_STATUS = {"Won": "Win", "Lost": "Lost", "Not Fought": "Refunded"}

# What a lead may record as having come back from the network. Deliberately not
# in AGENT_ACTION_EFFECTS: that dict is the ungated /agent-desk/action surface,
# and a ruling is not an agent's to make.
ISSUER_DECISIONS = ("Won", "Lost")

# Agent decisions outlive the process here. Kept out of static/, which is served
# to the browser.
AGENT_ACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "agent_actions.json")


def _apply_agent_action(case, action, at=None, by=None):
    """Record an agent's decision and push it onto the reporting fields.

    One code path for both a live action and a restore at boot, so the two
    cannot drift.
    """
    case["agent_action"] = action
    case["agent_action_at"] = at or datetime.now().strftime("%b %d, %Y, %H:%M:%S")
    if by is not None:
        # Who conceded (or contested) is provenance the same way a ruling's
        # recorder is. None means "caller does not know" — a legacy replay —
        # and must not blank out a name a live action already recorded.
        case["agent_action_by"] = by
    case.update(AGENT_ACTION_EFFECTS[action])
    # A concession IS the analyst accepting: route the case's handling through
    # the same override the legacy Accept button sets, so both concede paths
    # read "Accepted by Analyst" everywhere. Fighting again (or resetting to
    # Pending) takes that reading back — a case being contested must not keep
    # claiming an analyst accepted it.
    if action == "Not Fought":
        case["ml_override"] = "accept_refund"
    elif action in ("Contested", "Pending") and case.get("ml_override") == "accept_refund":
        case.pop("ml_override", None)
    return case["agent_action_at"]


def _record_agent_action(case, action, event=None):
    """Apply a decision, consume any rework release, and persist both.

    Shared by the Agent Page dropdown and the Submit button on the counter
    evidence page so the two cannot drift on what submitting means. A release is
    a one-shot: the agent fixes the case and resubmits, and it locks again —
    reopening it a second time needs a second approval.
    """
    at = _apply_agent_action(case, action, by=session.get("user", ""))
    if session.get("role") == "agent" and case.pop("rework_released", None):
        _save_rework_releases()
    case.setdefault("dispute_history", []).append(
        {"event": event or f"AgentAction: {action}", "date": at})
    _save_agent_actions()
    return at


# What each case looked like straight off the sheet, captured during the load.
# Without it the store cannot tell an agent's "Not Fought" from the sheet's own
# case_status, and would replay the sheet over the top of itself.
CASE_BASELINE = {}


def _capture_baseline():
    """Remember the sheet's own values for the keys a user can also set.

    Deep-copied on purpose. dispute_history and manual_evidence are lists the
    routes append to in place, so a shallow copy would hand the baseline the
    same list object and every later comparison would say "unchanged" — the
    appended timeline entries would then never be stored.
    """
    CASE_BASELINE.clear()
    for case in CASES:
        # Keyed on presence, not truthiness, and StateStore.save compares the
        # same way: a field the sheet left empty has to be in here, or emptying
        # it later would read as a difference and store on every save.
        CASE_BASELINE[case["case_id"]] = {
            k: copy.deepcopy(case[k]) for k in RUNTIME_KEYS if k in case}


def _save_case_state():
    """Persist everything a user has changed on a case, to SQLite.

    One call covers the lot. StateStore snapshots every runtime key on every
    case, so a route does not have to know which of them it touched -- which is
    how accepting a case, attaching evidence and appending to the timeline went
    unpersisted for so long: each had its own partial saver, or none.

    Bumps the state version, so the three superseded savers below keep that
    behaviour for their callers and every open console still learns to refresh.
    """
    _bump_state()
    StateStore.save(CASES, CASE_BASELINE)


# The three names the routes already call. Each now writes the whole snapshot,
# which is a superset of what it used to write on its own.
_save_agent_actions = _save_case_state
_save_allocations = _save_case_state
_save_rework_releases = _save_case_state


def _save_agent_actions_json():
    """The superseded JSON writer, kept only so the format is documented beside
    the importer that reads it. Nothing calls this."""
    stored = {c["case_id"]: {"action": c["agent_action"], "at": c.get("agent_action_at", "")}
              for c in CASES if c.get("agent_action")}
    try:
        with open(AGENT_ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(stored, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save agent actions: %s", exc)


def _restore_agent_actions():
    """Re-apply stored decisions onto the current case set.

    A missing or unreadable file just means nothing has been actioned yet — it
    must never stop the app booting. Unknown actions and case ids that are not
    in the current sheet are skipped rather than trusted.
    """
    try:
        with open(AGENT_ACTIONS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    by_id = {c["case_id"]: c for c in CASES}
    restored = 0
    for case_id, entry in stored.items():
        case = by_id.get(case_id)
        action = (entry or {}).get("action") if isinstance(entry, dict) else None
        if case is None or action not in AGENT_ACTION_EFFECTS:
            continue
        _apply_agent_action(case, action, entry.get("at"))
        restored += 1
    return restored


# ─── Team-lead overrides: who owns a case, and what may be reworked ────────────
# Both follow the agent_actions.json pattern above: a JSON file at the project
# root (never under static/, which is web-served), restored inside _apply_cases
# so an override survives a restart and a sheet re-upload alike.
ALLOCATIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "case_allocations.json")
REWORK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "rework_releases.json")


def _restore_allocations():
    """Re-apply a team lead's re-assignments.

    Sets `assigned_agent`, which AgentDesk prefers over its hash. An unreadable
    file, an unknown case id or an agent name that is not on the roster are all
    skipped rather than trusted.
    """
    try:
        with open(ALLOCATIONS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    by_id = {c["case_id"]: c for c in CASES}
    restored = 0
    for case_id, agent in stored.items():
        case = by_id.get(case_id)
        if case is None or agent not in AgentDesk.AGENTS:
            continue
        case["assigned_agent"] = agent
        restored += 1
    return restored


# _save_allocations and _save_rework_releases used to live here, each writing
# its own JSON file. Both are now aliases of _save_case_state, defined with it
# above: one snapshot covers what all three used to write separately, and picks
# up the accept, the attachments and the timeline entries none of them did.


ROUTING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "client_routing.json")


def _save_routing():
    """Persist the team hierarchy the manager controls."""
    _bump_state()
    try:
        with open(ROUTING_FILE, "w", encoding="utf-8") as f:
            json.dump({"lead_agents": LEAD_AGENTS,
                       "client_routing": CLIENT_ROUTING}, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save routing: %s", exc)


def _restore_routing():
    """Re-apply the manager's agent and client assignments.

    Entries naming a lead or agent that no longer exists are skipped, so an
    edited file can never strand a queue with an owner nobody can sign in as.
    """
    try:
        with open(ROUTING_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    restored = 0
    leads = stored.get("lead_agents")
    if isinstance(leads, dict):
        cleaned = {lead: [a for a in agents if a in AgentDesk.AGENTS]
                   for lead, agents in leads.items()
                   if lead in TEAM_LEADS and isinstance(agents, list)}
        if cleaned:
            LEAD_AGENTS.clear()
            LEAD_AGENTS.update(cleaned)
            restored += 1

    routing = stored.get("client_routing")
    if isinstance(routing, dict):
        # The bucket is checked as well as the lead, the way
        # _restore_client_profiles checks its client key. Without it a routing
        # file written when there were two books would put the dropped one back
        # as a phantom chip on a lead card that no case can ever belong to.
        cleaned = {bucket: lead for bucket, lead in routing.items()
                   if lead in TEAM_LEADS
                   and bucket in TeamConsole.BUCKET_LABELS}
        if cleaned:
            CLIENT_ROUTING.clear()
            CLIENT_ROUTING.update(cleaned)
            restored += 1
    return restored


CLIENT_PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "client_profiles.json")


def _save_client_profiles():
    """Persist each client's service tier and merchant account record."""
    _bump_state()
    try:
        with open(CLIENT_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(CLIENT_PROFILES, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save client profiles: %s", exc)


def _restore_client_profiles():
    """Re-apply the tier and account record the manager has set per client.

    Updates in place rather than swapping the dict wholesale: the key set is
    the client roster, so a stored file that has lost a client must not be able
    to delete that client's defaults. A tier the rebuttal builder does not
    implement is skipped, which means a hand-edited file can never put a client
    into a mode with no code behind it.
    """
    try:
        with open(CLIENT_PROFILES_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    restored = 0
    for client, entry in stored.items():
        if client not in CLIENT_PROFILES or not isinstance(entry, dict):
            continue
        if entry.get("tier") in ClientConsole.TIERS:
            CLIENT_PROFILES[client]["tier"] = entry["tier"]
        account = entry.get("account")
        if isinstance(account, dict):
            CLIENT_PROFILES[client]["account"].update(
                {k: str(v) for k, v in account.items()
                 if k in ClientConsole.ACCOUNT_FIELDS
                 and isinstance(v, (str, int, float))})
        restored += 1
    return restored


REPOSITORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "repository_templates.json")

# Templates a team lead has edited, keyed "<kind>:<key>". Empty on a fresh
# install and never seeded: an absent entry means "use the built-in text", so
# reverting a template is a delete rather than a restore, and every page
# renders as it did before this store existed.
TEMPLATE_OVERRIDES = {}


def _save_template_overrides():
    """Persist the repository templates a team lead has edited."""
    _bump_state()
    try:
        with open(REPOSITORY_FILE, "w", encoding="utf-8") as f:
            json.dump(TEMPLATE_OVERRIDES, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save repository templates: %s", exc)


def _restore_template_overrides():
    """Re-apply edited templates, skipping any that have no render path.

    Unlike the other stores this one starts empty, so it replaces its dict
    wholesale rather than updating in place — there are no defaults to protect.
    Each key is validated against the live registries: a cover letter must name
    a real reason category and a policy must name a real policy document, which
    means a hand-edited file cannot introduce a template that nothing renders.
    SOP keys are free-form because leads create them.
    """
    try:
        with open(REPOSITORY_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    TEMPLATE_OVERRIDES.clear()
    restored = 0
    for store_key, entry in stored.items():
        if not isinstance(store_key, str) or ":" not in store_key:
            continue
        kind, key = store_key.split(":", 1)
        if kind not in TemplateRepository.KINDS or not isinstance(entry, dict):
            continue
        if not TemplateRepository.valid_key(kind, key):
            continue
        TEMPLATE_OVERRIDES[store_key] = entry
        restored += 1
    return restored


USER_PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "user_profiles.json")

# How long a password may go unchanged before sign-in insists on a new one.
PASSWORD_MAX_AGE_DAYS = 45

# Themes a user may pick. "default" is the shipped palette; "dark" overrides
# the tokens in static/css/style.css. Semantic colours — green for a win, red
# for a loss, amber for a warning — are deliberately not themed.
#
# A third option, "blue", was retired when the palette was reworked: it was a
# slate-and-indigo variant with no counterpart in the design it now follows,
# and keeping it meant maintaining a third set of ~140 generated tokens.
# _stored_theme() below folds any profile still holding it back to default.
UI_THEMES = OrderedDict([
    ("default", {"label": "Light", "blurb": "The shipped light palette."}),
    ("dark", {"label": "Dark", "blurb": "Dark layout for low-light work."}),
])


def _stored_theme():
    """The signed-in user's theme, or "default" if they have none or it is one
    the app no longer ships."""
    stored = (USER_PROFILES.get(session.get("user", "")) or {}).get("theme", "default")
    return stored if stored in UI_THEMES else "default"


def _seed_user_profile(username):
    """A profile record for a login that has never been edited.

    `pw_changed_at` is left empty here and stamped on first restore rather than
    at epoch — dating it to 1970 would expire every account immediately and open
    the demo onto a forced-change screen.
    """
    return {"display_name": username.title(), "email": "",
            "theme": "default", "pw_hash": "", "pw_salt": "",
            "pw_changed_at": ""}


USER_PROFILES = {name: _seed_user_profile(name) for name in STRAIVE_USERS}


def _save_user_profiles():
    """Persist per-user display name, email, theme and password record."""
    _bump_state()
    try:
        with open(USER_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(USER_PROFILES, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save user profiles: %s", exc)


def _restore_user_profiles():
    """Re-apply saved profiles, and start the password clock for new logins.

    Updates in place rather than swapping, so a stored file that has lost a user
    cannot delete that user's defaults. Only usernames in STRAIVE_USERS are
    accepted, so a hand-edited file cannot invent a login — it would be a record
    with no credentials behind it, which nothing could sign in as, but it would
    still show up wherever profiles are listed.
    """
    stamped = False
    try:
        with open(USER_PROFILES_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}

    restored = 0
    for name, entry in stored.items():
        if name not in USER_PROFILES or not isinstance(entry, dict):
            continue
        for field in ("display_name", "email", "pw_hash", "pw_salt", "pw_changed_at"):
            value = entry.get(field)
            if isinstance(value, str):
                USER_PROFILES[name][field] = value
        if entry.get("theme") in UI_THEMES:
            USER_PROFILES[name]["theme"] = entry["theme"]
        restored += 1

    # Anyone without a change date gets today's, so the 45-day clock runs from
    # first boot rather than from a date that has already passed.
    today = datetime.now().strftime("%Y-%m-%d")
    for rec in USER_PROFILES.values():
        if not rec.get("pw_changed_at"):
            rec["pw_changed_at"] = today
            stamped = True
    if stamped:
        _save_user_profiles()
    return restored


# ─── Merchant credentials: the third-party logins a client stores with us ─────
# The one store in this app holding secrets that must be readable again, so it
# is the one store that is encrypted rather than written as plain JSON. Password
# hashing is no use here: an API key has to come back out to be worth keeping.
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "credentials.json")
CREDENTIAL_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   ".credential_key")

# The five panels a merchant fills in, and which fields each carries. Order is
# display order. `choices` renders a dropdown; the rest are text.
CREDENTIAL_PANELS = OrderedDict([
    ("crm", {
        "label": "CRM",
        "choose": ("crm_name", "Select CRM",
                   ["Konnektive CRM", "Sticky.io", "Response CRM", "Checkout Champ",
                    "Salesforce", "HubSpot", "Other"]),
        "fields": ["url", "login_id", "password", "api_key"],
    }),
    ("gateway", {
        "label": "Gateway",
        "choose": ("gateway_name", "Select Gateway",
                   ["NMI Gateway", "Authorize.Net", "Braintree", "Stripe",
                    "Checkout.com", "Other"]),
        "fields": ["url", "login_id", "password", "api_key"],
    }),
    ("processor", {
        "label": "Processor Portal",
        "choose": ("psp_name", "Select PSP",
                   ["PayPal", "Adyen", "Cybersource", "Worldpay", "Stripe",
                    "Nuvei", "PayU", "Braintree", "Other"]),
        "fields": ["url", "login_id", "password", "api_key"],
    }),
    ("shipment", {
        "label": "Shipment",
        "choose": ("carrier_name", "Select Shipment",
                   ["USPS", "UPS", "FedEx", "DHL", "Royal Mail", "Other"]),
        "fields": ["url", "login_id", "password", "api_key"],
    }),
    ("other", {
        "label": "Other URLs",
        "choose": None,
        "fields": ["url", "login_id", "password"],
    }),
])

# Fields never written in the clear and never sent back to the browser. Anything
# not listed here is shown as typed, because a URL or a login id has to be
# readable for the page to be worth opening.
CREDENTIAL_SECRETS = {"password", "api_key"}

# Ontology database -> the credential panel that connects it. This is the join
# the architecture feedback asked for: Database I-IV is what the evidence
# matrix calls the merchant's systems, and these panels are where the merchant
# supplies the credentials that connect them. The matrix's own legend backs
# each pairing — I holds order/communication records (a CRM), II transaction
# details (the processor portal), III payment/3DS/policy records (the
# gateway), IV proof of delivery (the shipment carrier).
DATABASE_CONNECTORS = {"I": "crm", "II": "processor", "III": "gateway", "IV": "shipment"}

MAX_CREDENTIAL_MIDS = 20

# client label -> {"mids": [ {mid_no, panels: {...}, updated_at} ]}
CREDENTIALS = {}


def _credential_key():
    """The Fernet key, from the environment or a generated one beside the data.

    `CREDENTIAL_KEY` is the real answer: the key lives wherever the deployment
    keeps its secrets and the file on disk is useless on its own. Without it a
    key is generated once and written next to the store, which keeps the demo
    working across restarts but protects nothing against anyone holding the
    disk — the page says exactly that rather than implying otherwise.
    """
    from_env = os.environ.get("CREDENTIAL_KEY", "").strip()
    if from_env:
        try:
            Fernet(from_env.encode())
            return from_env.encode(), True
        except (ValueError, TypeError):
            app.logger.warning("CREDENTIAL_KEY is not a valid Fernet key; "
                               "falling back to the local key file.")
    try:
        with open(CREDENTIAL_KEY_FILE, "rb") as f:
            key = f.read().strip()
        Fernet(key)
        return key, False
    except (OSError, ValueError, TypeError):
        pass

    key = Fernet.generate_key()
    try:
        with open(CREDENTIAL_KEY_FILE, "wb") as f:
            f.write(key)
    except OSError as exc:
        app.logger.warning("Could not write the credential key: %s", exc)
    return key, False


def _credential_cipher():
    key, _ = _credential_key()
    return Fernet(key)


def _credential_key_is_managed():
    return _credential_key()[1]


def _encrypt_secret(value):
    return _credential_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_secret(token):
    """Plaintext behind a stored token, or "" if it cannot be read.

    A token encrypted under a key that has since changed is unreadable, not a
    crash: the merchant re-enters the value and moves on.
    """
    if not token:
        return ""
    try:
        return _credential_cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def _blank_mid(mid_no=""):
    return {
        "mid_no": mid_no,
        "panels": {key: {} for key in CREDENTIAL_PANELS},
        "updated_at": "",
    }


def _save_credentials():
    """Persist every merchant's credential records.

    Secrets are already ciphertext by the time they reach here — encryption
    happens at the point of entry, so a value is never held in the clear in
    CREDENTIALS either, only on its way through the request that set it.
    """
    _bump_state()
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(CREDENTIALS, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save credentials: %s", exc)


def _restore_credentials():
    """Re-apply stored credentials, skipping anything the app does not know.

    A hand-edited file cannot invent a merchant, a panel or a field: every key
    is checked against CLIENT_PROFILES and CREDENTIAL_PANELS before it lands.
    """
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    CREDENTIALS.clear()
    restored = 0
    for client, entry in stored.items():
        if client not in CLIENT_PROFILES or not isinstance(entry, dict):
            continue
        mids = []
        for raw in (entry.get("mids") or [])[:MAX_CREDENTIAL_MIDS]:
            if not isinstance(raw, dict):
                continue
            rec = _blank_mid(str(raw.get("mid_no", ""))[:60])
            rec["updated_at"] = str(raw.get("updated_at", ""))[:40]
            for panel, values in (raw.get("panels") or {}).items():
                if panel not in CREDENTIAL_PANELS or not isinstance(values, dict):
                    continue
                # The registry's field names must be in this filter too, or a
                # provider-specific credential saves fine and then silently
                # vanishes on the next restart.
                allowed = (set(CREDENTIAL_PANELS[panel]["fields"])
                           | panel_allowed_fields(panel))
                choose = CREDENTIAL_PANELS[panel]["choose"]
                if choose:
                    allowed.add(choose[0])
                rec["panels"][panel] = {k: str(v) for k, v in values.items()
                                        if k in allowed and isinstance(v, str)}
            mids.append(rec)
        if mids:
            CREDENTIALS[client] = {"mids": mids}
            restored += 1
    return restored


def _client_mids(client):
    """This merchant's MID records, seeding an empty first one on demand."""
    entry = CREDENTIALS.setdefault(client, {"mids": []})
    if not entry["mids"]:
        entry["mids"].append(_blank_mid())
    return entry["mids"]


def _mid_for_display(record):
    """One MID record shaped for the page, with every secret withheld.

    A stored secret becomes {"set": True, "value": ""} — the ciphertext does not
    go to the browser either. There is no path from rendering this page to
    seeing a password; that takes the explicit reveal route.
    """
    out = {"mid_no": record.get("mid_no", ""),
           "updated_at": record.get("updated_at", ""), "panels": {}}
    for panel, spec in CREDENTIAL_PANELS.items():
        values = record.get("panels", {}).get(panel, {})
        shown = {}
        if spec["choose"]:
            shown[spec["choose"][0]] = values.get(spec["choose"][0], "")
        # The record's own adapter decides which stored names are secrets; the
        # shown field set is that adapter's schema plus the legacy fields, so a
        # record saved before the provider registry existed still renders.
        adapter = str(values.get("adapter") or "").strip()
        shown["adapter"] = adapter
        shown["environment"] = values.get("environment", "")
        secret_names = secret_fields_for(adapter) | CREDENTIAL_SECRETS
        field_names = [f["key"] for f in schema_for(adapter)["fields"]]
        field_names += [f for f in spec["fields"] if f not in field_names]
        for field in field_names:
            if field in secret_names:
                shown[field] = {"set": bool(values.get(field))}
            else:
                shown[field] = values.get(field, "")
        out["panels"][panel] = shown
    return out


CASE_NARRATIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "case_narrative.json")

# Rebuttal prose a team lead has rewritten for one case only, keyed case id ->
# {block_id: text}. Kept apart from TEMPLATE_OVERRIDES because the two have
# different lifetimes: a template outlives the case list, this does not.
CASE_NARRATIVE = {}


def _save_case_narrative():
    """Persist per-case rebuttal prose."""
    _bump_state()
    try:
        with open(CASE_NARRATIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(CASE_NARRATIVE, f, indent=2)
    except OSError as exc:
        app.logger.warning("Could not save case narrative: %s", exc)


def _restore_case_narrative():
    """Re-apply per-case prose, dropping anything whose case is gone.

    Runs after the case list is rebuilt, so a re-ingest that drops a case takes
    its prose with it rather than leaving text stranded against an id nothing
    renders.
    """
    try:
        with open(CASE_NARRATIVE_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    known = {c["case_id"] for c in CASES}
    CASE_NARRATIVE.clear()
    restored = 0
    for case_id, blocks in stored.items():
        if case_id not in known or not isinstance(blocks, dict):
            continue
        cleaned = {b: t for b, t in blocks.items()
                   if NarrativeBlocks.valid_block(b) and isinstance(t, str) and t.strip()}
        if cleaned:
            CASE_NARRATIVE[case_id] = cleaned
            restored += 1
    return restored


def _restore_rework_releases():
    """Re-apply locks a team lead has released for rework."""
    try:
        with open(REWORK_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(stored, dict):
        return 0

    by_id = {c["case_id"]: c for c in CASES}
    restored = 0
    for case_id, entry in stored.items():
        case = by_id.get(case_id)
        if case is None or not isinstance(entry, dict):
            continue
        case["rework_released"] = entry
        restored += 1
    return restored

# ─── Pre-computed Evidence Collection ──────────────────────────────────────────
_classified_for_evidence = AIValidationEngine.classify_all(CASES)
EVIDENCE_RESULTS = EvidenceCollectionEngine.collect_all(_classified_for_evidence)
EVIDENCE_STATS = EvidenceCollectionEngine.get_aggregate_stats(EVIDENCE_RESULTS)


def _get_reason(case):
    """Get reason code info with safe defaults for unknown codes.

    The fallback used to claim `{"Visa": rc, "Mastercard": rc, "Amex": rc,
    "Discover": rc}` — every network using the case's own code. That is where
    "Mastercard codes appearing under Visa" came from: a 4837 case rendered a
    badge reading "Visa: 4837". Now the code is resolved through its own network
    first, and an unresolvable code is attributed to that network alone rather
    than to all four.
    """
    rc = case.get("reason_code", "")
    network = case.get("payment_method", "")
    reason = ReasonCodeInterpreter.interpret(rc, network)
    if not reason:
        desc = case.get("reason_description", "") or case.get("scenario", "")
        reason = {
            "title": desc or f"Reason Code {rc}",
            "definition": desc,
            "network_codes": {network: rc} if network and rc else {},
            "scenarios": [desc] if desc else [],
            "merchant_challenge": "",
            "defense_goals": [],
            "supporting_docs_general": [],
            "supporting_docs_platform": [],
            "portals": [],
        }
    return reason


# ─── Merchant Configuration ────────────────────────────────────────────────────
# Placeholder identity for a generic install. Everything here is editable at
# /merchant-config, and the case builders read these values rather than carrying
# their own copies, so changing it once re-brands the whole app.
MERCHANT_CONFIG = {
    "customer_id": "CUST-001",
    "company_name": "Acme Commerce Inc.",
    "dba_name": "Acme Online Store",
    "descriptor_url": "acme-store.example.com",
    "services": "Chargeback",
    "merchant_account_number": "",
    "mid_alias_name": "",
    "status": "Active",
    "notes": "",
    "gateway_name": "Cybersource",
    "gateway_url": "",
    "gateway_username": "",
    "gateway_password": "",
    "gateway_api_login_id": "",
    "gateway_transaction_key": "",
    "processor_name": "American Express",
    "processor_url": "",
    "processor_username": "",
    "processor_password": "",
    "crm_name": "Konnektive",
    "crm_url": "",
    "crm_username": "",
    "crm_password": "",
    "crm_api_username": "",
    "crm_api_password": "",
}

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/merchant-config", methods=["GET", "POST"])
def merchant_config():
    if request.method == "POST":
        for key in MERCHANT_CONFIG:
            val = request.form.get(key, "")
            if val:
                MERCHANT_CONFIG[key] = val
        return redirect(url_for("merchant_config"))
    return render_template("merchant_config.html", config=MERCHANT_CONFIG)


@app.route("/api-integration")
def api_integration():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Pairs, not bare strings: a `set()` of codes throws away the network, and
    # without the network the chips cannot be named.
    reason_codes = _distinct_reason_codes(CASES) or [
        {"code": rc, "label": _reason_label(rc, "Visa")} for rc in REASON_CODES]
    return render_template("api_integration.html", now=now, total_cases=len(CASES), reason_codes=reason_codes)


# Unlinked, not removed. Nothing in the app points here any more — the nine
# links that did now use home_url or cases_url, which resolve per role — but the
# route stays so the URL keeps working for anyone who has it bookmarked. It
# belongs to no role: absent from every sidebar and from NAV_PAGES, which is why
# landing on it left the user with no way back.
@app.route("/dashboard")
def dashboard():
    scenarios = sorted(set(c["scenario"] for c in CASES))
    processors = sorted(set(c["processor"] for c in CASES))
    outcomes = sorted(set(c["outcome"] for c in CASES))
    classified = AIValidationEngine.classify_all(CASES)
    return render_template("dashboard.html", cases=classified, scenarios=scenarios,
                           processors=processors, outcomes=outcomes,
                           reason_options=_distinct_reason_codes(CASES))


@app.route("/ai-overview")
def ai_overview():
    stats = AIValidationEngine.get_pipeline_stats(CASES)
    return render_template("ai_overview.html", stats=stats, reason_codes=REASON_CODES)


@app.route("/evidence-collection")
def evidence_collection():
    classified = AIValidationEngine.classify_all(CASES)
    return render_template("evidence_collection.html",
                           cases=classified,
                           evidence=EVIDENCE_RESULTS,
                           stats=EVIDENCE_STATS,
                           apis=EvidenceCollectionEngine.APIS)


def _manager_context(cases=None):
    """The three analytics bundles every management page renders from.

    `cases` narrows the whole bundle to a subset — the Data Dashboard passes
    its filtered view so the charts below the filter bar describe exactly what
    the bar says is in view. Every other management page omits it and gets the
    full book. Nothing in the analytics layer needed changing for this:
    ManagerCharts.compute already takes whatever case list it is handed.
    """
    cases = CASES if cases is None else cases
    ml_stats = AIValidationEngine.get_pipeline_stats(cases)
    analytics = DashboardAnalytics.compute(
        cases, ml_stats, EVIDENCE_STATS, EVIDENCE_RESULTS, REASON_CODES)
    charts = ManagerCharts.compute(
        ml_stats["classified_cases"], ChargebackCaseLoader.load_orders())
    console = ManagerConsole.compute(cases, analytics, charts, LEAD_AGENTS,
                                     CLIENT_ROUTING, TEAM_LEADS)
    return {"a": analytics, "ml": ml_stats, "ev": EVIDENCE_STATS,
            "ch": charts, "m": console}


# The four states the Executive Overview counts. Derived rather than stored:
# `submission_status` says whether a representment has gone to the network, and
# `case_status` says whether the dispute is finished. A case is Pending until it
# is submitted, and Closed once the network has ruled either way.
def _exec_status(case):
    # Keyed on case_status, not on the old outcome=="Accepted" marker. Accepting
    # a chargeback IS not fighting it, and the two used to be counted apart:
    # a case conceded from the Agent Desk fell through to "closed" while one
    # conceded from the legacy page landed here.
    if (case.get("case_status") or "") == "Not Fought":
        return "accepted"
    if (case.get("case_status") or "Decision Pending") != "Decision Pending":
        return "closed"
    if (case.get("submission_status") or "") == "Submitted":
        return "submitted"
    return "pending"


def _hub_filters(cases):
    """Read the Data Dashboard's filter bar off the query string.

    Returns (filtered cases, the state the bar needs to render itself). Options
    are always built from the FULL book, never the filtered view — a filter that
    removes its own value from the dropdown cannot be undone.
    """
    def opts(key):
        return sorted({(c.get(key) or "").strip() for c in cases} - {""})

    args = request.args
    picked = {
        "processor": args.get("processor", ""),
        "network": args.get("network", ""),
        "reason": args.get("reason", ""),
        "method": args.get("method", ""),
        "status": args.get("status", ""),
        "start": args.get("start", ""),
        "end": args.get("end", ""),
    }

    # Routing drives the "processing method" filter. Classified per case rather
    # than read off a stored field: routing is derived from the score and an
    # analyst override, and classify_one is the one place that resolves both.
    routing = {c["case_id"]: AIValidationEngine.classify_one(c)["routing"]
               for c in cases}
    method_of = {"auto": "auto_represent", "hitl": "hitl_review",
                 "accept": "accept_refund"}

    def keep(c):
        if picked["processor"] and c.get("processor") != picked["processor"]:
            return False
        if picked["network"] and c.get("payment_method") != picked["network"]:
            return False
        if picked["reason"] and c.get("reason_code") != picked["reason"]:
            return False
        if picked["method"] and routing.get(c["case_id"]) != method_of.get(picked["method"]):
            return False
        if picked["status"] and _exec_status(c) != picked["status"]:
            return False
        # Dates are compared as ISO strings, which sorts correctly and avoids
        # parsing a column that is already normalised to YYYY-MM-DD.
        day = (c.get("dispute_creation_date") or "")[:10]
        if picked["start"] and (not day or day < picked["start"]):
            return False
        if picked["end"] and (not day or day > picked["end"]):
            return False
        return True

    view = [c for c in cases if keep(c)]
    days = sorted({(c.get("dispute_creation_date") or "")[:10] for c in cases} - {""})
    return view, {
        "picked": picked,
        "active": any(picked.values()),
        "in_view": len(view),
        "total": len(cases),
        "processors": opts("processor"),
        "networks": opts("payment_method"),
        "reasons": opts("reason_code"),
        "span": {"min": days[0] if days else "", "max": days[-1] if days else ""},
        "dataset": StateStore.active_dataset(),
    }


def _executive_overview(view):
    """The headline cards above the Data Dashboard's charts.

    Amounts stay split by currency. The book runs in IDR, NGN and USD, and one
    summed figure across them would be arithmetic on incompatible units — the
    same reason the charts below use the money() macro rather than a total.
    """
    total = len(view)
    ml = AIValidationEngine.get_pipeline_stats(view) if view else {}
    counts = Counter(_exec_status(c) for c in view)
    amounts = defaultdict(float)
    for c in view:
        amounts[c.get("currency") or "USD"] += c.get("amount") or 0
    return {
        "total": total,
        "auto": ml.get("auto_processed", 0),
        "hitl": ml.get("human_in_loop", 0),
        "auto_rate": ml.get("auto_rate_pct", 0),
        "amounts": {k: round(v, 2) for k, v in sorted(amounts.items())},
        "avg": {k: round(v / total, 2) for k, v in sorted(amounts.items())} if total else {},
        "statuses": [
            {"key": "pending",   "label": "Pending",     "n": counts.get("pending", 0)},
            {"key": "submitted", "label": "Submitted",   "n": counts.get("submitted", 0)},
            {"key": "accepted",  "label": "Accepted",    "n": counts.get("accepted", 0)},
            {"key": "closed",    "label": "Case Closed", "n": counts.get("closed", 0)},
        ],
        "pct": (lambda n: round(n / total * 100, 1) if total else 0.0),
    }


@app.route("/manager-hub")
@manager_required
def manager_hub():
    # Filtering happens on the server rather than in the browser: everything
    # below the bar is server-rendered SVG and tables computed by ManagerCharts,
    # so there is nothing for client-side JS to re-derive without shipping the
    # whole book to the page and reimplementing the analytics in JavaScript.
    view, bar = _hub_filters(CASES)
    return render_template("manager_hub.html", flt=bar,
                           ex=_executive_overview(view),
                           **_manager_context(view))


@app.route("/manager/history")
@role_required("manager")
def manager_history():
    return render_template("manager_history.html", **_manager_context())


# What a case is waiting on, as one value. The app stores four status-shaped
# fields -- outcome, case_status, submission_status and the ML routing -- and a
# queue needs a single answer. Read in priority order: a recorded human decision
# beats a pipeline state, and a pipeline state beats a recommendation.
WORKFLOW_STATUS = {
    "chargeback_accepted":   "Chargeback accepted",
    "case_closed":           "Case closed",
    "rebuttal_submitted":    "Rebuttal submitted",
    "awaiting_evidence":     "Awaiting evidence",
    "rebuttal_generated":    "Rebuttal generated",
    "human_review_required": "Human review required",
    "accept_recommended":    "Accept recommended",
}


def _workflow_status(case, routing):
    # Same correction as _exec_status: a conceded case is a conceded case,
    # whichever page it was conceded from.
    if (case.get("case_status") or "") == "Not Fought":
        return "chargeback_accepted"
    if (case.get("case_status") or "Decision Pending") != "Decision Pending":
        return "case_closed"
    submission = (case.get("submission_status") or "").strip()
    if submission == "Submitted":
        return "rebuttal_submitted"
    if submission == "Awaiting Evidence":
        return "awaiting_evidence"
    if routing == "auto_represent":
        return "rebuttal_generated"
    if routing == "accept_refund":
        return "accept_recommended"
    return "human_review_required"


def _operations_rows():
    """One row per case for the Operations queue.

    Missing evidence is read from EVIDENCE_RESULTS rather than invented: each
    collection source reports `status` and a `gaps` list, so a row can name the
    sources that came back short and say how many gaps they left. A fully
    collected case shows nothing, which is the point of the column.
    """
    today = datetime.now().date()
    rows = []
    for case in CASES:
        ml = AIValidationEngine.classify_one(case)
        routing = ml["routing"]

        ev = EVIDENCE_RESULTS.get(case["case_id"]) or {}
        missing, gap_count = [], 0
        for src in (ev.get("api_results") or {}).values():
            gaps = src.get("gaps") or []
            gap_count += len(gaps)
            if src.get("status") != "complete":
                missing.append({
                    # "Shipping & Delivery API" is the column header's worth of
                    # width on its own; the chip drops the redundant suffix.
                    "name": (src.get("api_name") or "").replace(" API", ""),
                    "status": src.get("status", ""),
                    "gaps": len(gaps),
                })

        day = (case.get("dispute_creation_date") or "")[:10]
        age = ""
        if day:
            try:
                age = (today - datetime.strptime(day, "%Y-%m-%d").date()).days
            except ValueError:
                age = ""

        status = _workflow_status(case, routing)
        rows.append({
            "case_id": case["case_id"],
            "date": (case.get("dispute_creation_date") or "")[:16].replace("T", " "),
            "network": case.get("payment_method", ""),
            "processor": case.get("processor", ""),
            "currency": case.get("currency") or "USD",
            "amount": case.get("amount") or 0,
            "reason_code": case.get("reason_code", ""),
            # The two-bucket split the tabs filter on. The finer three-tier
            # label rides alongside it so "recommend accept" stays visible
            # rather than being flattened into "needs a human".
            "bucket": ml.get("processing_category", "hitl"),
            "routing_label": ml.get("routing_label", ""),
            "missing": missing,
            "gap_count": gap_count,
            "completeness": ev.get("overall_completeness_pct", 0),
            "age": age,
            "status": status,
            "status_label": WORKFLOW_STATUS.get(status, status),
        })
    rows.sort(key=lambda r: (r["bucket"] != "hitl", -(r["age"] or 0)))
    return rows


@app.route("/manager/operations")
@role_required("manager")
def manager_operations():
    # `ml` comes from _manager_context() -- it is already
    # AIValidationEngine.get_pipeline_stats(CASES), so computing a second copy
    # here only collided with it.
    return render_template("manager_operations.html", rows=_operations_rows(),
                           statuses=WORKFLOW_STATUS, **_manager_context())


# ─── Evidence Requirements: the management matrix, one page per console ───────
# The same reference content in all three staff shells, the way the repository
# is served: thin per-role routes around one body partial, because each shell
# needs its own context (manager_base reads `m`, admin_base `t`, agent_base
# `a`) and a shared route could satisfy only one of them.
def _client_connections(label):
    """Which of the four ontology databases have credentials on file.

    {db_key: {"panel": panel label, "system": chosen product name,
              "connected": bool}} for one client book, from the credentials the
    merchant stored. Set-or-not only: secrets are held as ciphertext and a
    cleared one is popped from the record, so plain truthiness answers the
    question without a single decrypt — no secret value ever leaves here.

    Reads CREDENTIALS raw, never through _client_mids: that helper seeds a
    blank MID via setdefault, and a staff page looking at connection state
    must not write to a merchant's credential store.
    """
    mids = (CREDENTIALS.get(label) or {}).get("mids") or []
    out = {}
    for db_key, panel_key in DATABASE_CONNECTORS.items():
        spec = CREDENTIAL_PANELS[panel_key]
        chooser = (spec.get("choose") or ("",))[0]
        connected, system = False, ""
        for mid in mids:
            panel = (mid.get("panels") or {}).get(panel_key) or {}
            # Legacy secrets plus whatever this record's own provider schema
            # calls a secret — a saved Adyen apiKey counts exactly like a
            # saved legacy api_key. Still no decryption.
            adapter = str(panel.get("adapter") or "").strip()
            if any(panel.get(f)
                   for f in (CREDENTIAL_SECRETS | secret_fields_for(adapter))):
                connected = True
            if not system and chooser:
                system = (panel.get(chooser) or "").strip()
        out[db_key] = {"panel": spec["label"], "system": system,
                       "connected": connected}
    return out


def _case_connections(case):
    """_client_connections for the book this case belongs to.

    Same bucket resolution the packet uses: TransactionChannel -> book label.
    A case with no channel buckets to "Unassigned", which owns no credential
    record, so every database correctly reads as not connected.
    """
    mapping = TeamConsole._bucket_map(CASES)
    return _client_connections(ClientConsole.client_of(case, mapping))


def _case_evidence_checklist(case, order):
    """This case's row of the evidence matrix, or an honest absence.

    Resolution is reason_code_canonical -> SECTION_BY_FAMILY. The live book
    carries 11.3 and 13.2 cases — about a fifth of it — and the management
    workbook has no row for either, so {"missing": True} is a first-class
    outcome the page must render as a statement, never as silence.

    For Goods not received the workbook splits requirements by where the item
    physically is; the scenario is picked from the fulfilment status with the
    same fail-first matching the source cards use, so "Returned To Origin"
    cannot be caught by the "deliver" test. An unmatched status shows every
    item with its applies-to label rather than guessing a scenario.
    """
    fam = case.get("reason_code_canonical") or ""
    sec = SECTION_BY_FAMILY.get(fam)
    if not sec:
        return {"family": fam, "missing": True,
                "reason": REASON_CODES.get(fam, {})}

    variant, note = "", ""
    if sec.get("variants"):
        fs = (order.get("fulfillment_status") or "").lower()
        picked = ("If item returned to sender" if "return" in fs
                  else "If item lost in transit" if "lost" in fs
                  else "If item awaiting collection" if "await" in fs or "collect" in fs
                  else "If item in transit" if "transit" in fs
                  else "If item delivered" if "deliver" in fs or "complete" in fs
                  else "")
        if picked in sec["variants"]:
            variant = picked
            note = f'from the fulfilment status "{order.get("fulfillment_status")}"'

    items = [it for it in sec["items"]
             if not variant or variant in it.get("variants_for", sec.get("variants", []))]
    return {"family": fam, "section": sec, "variant": variant,
            "variant_note": note, "items": items,
            "reason": REASON_CODES.get(fam, {})}


def _evidence_matrix_context():
    """The matrix, the four databases, and the live reason-code families.

    `families` resolves each section's reason_families against REASON_CODES so
    the page can print the network codes a section governs (Visa 13.1,
    Mastercard 4855, ...) without the template importing anything. A family
    missing from REASON_CODES simply renders no chip — the matrix is the
    manager's sheet and must not fail on our code table's gaps.

    `connections` is the credential state of the one live book, so the page
    can say which of the four databases a merchant has actually connected.
    """
    fams = {f for sec in EVIDENCE_MATRIX for f in sec["reason_families"]}
    return {"matrix": EVIDENCE_MATRIX, "dbs": DATABASES,
            "families": {f: REASON_CODES[f] for f in fams if f in REASON_CODES},
            "connections": _client_connections(TeamConsole.BUCKET_LABELS[0])}


def _matrix_primary_notes():
    """{item name lower: which dispute types it is primary evidence for}.

    Walks EVIDENCE_MATRIX so the RCA page's ontology chips have one source —
    the transcribed workbook — and manager_charts never carries a copy of it.
    """
    notes = {}
    for sec in EVIDENCE_MATRIX:
        for it in sec["items"]:
            if it["primary"]:
                notes.setdefault(
                    it["name"].strip().lower(),
                    f"Primary evidence for {' / '.join(sec['labels'])} (#{sec['num']})")
    return notes


def _matrix_family_labels():
    """{reason family: the workbook's dispute-type label(s)} for breakdowns."""
    return {fam: " / ".join(sec["labels"])
            for fam, sec in SECTION_BY_FAMILY.items()}


@app.route("/manager/root-cause")
@role_required("manager")
def manager_rca():
    """Root cause analysis: why decided cases were lost.

    Recomputing pipeline stats beside _manager_context's copy matches the
    admin_dashboard precedent and is cheap at this book size.
    """
    classified = AIValidationEngine.get_pipeline_stats(CASES)["classified_cases"]
    return render_template("manager_rca.html",
                           rca=ManagerCharts.root_cause(classified,
                                                        _matrix_primary_notes(),
                                                        _matrix_family_labels()),
                           dataset=StateStore.active_dataset(),
                           **_manager_context())


@app.route("/manager/evidence")
@role_required("manager")
def manager_evidence():
    return render_template("manager_evidence.html",
                           **_evidence_matrix_context(), **_manager_context())


@app.route("/admin/evidence")
@role_required("admin", "manager")
def admin_evidence():
    return render_template("admin_evidence.html", t=_team_console(),
                           **_evidence_matrix_context())


@app.route("/agent/evidence")
@role_required("agent", "manager")
def agent_evidence():
    return render_template("agent_evidence.html", a=_agent_console(),
                           **_evidence_matrix_context())


@app.route("/manager/onboarding")
@role_required("manager")
def manager_onboarding():
    # Passed to this page only — _manager_context feeds four pages and none of
    # the others render a client profile.
    #
    # Connection state per client is read-only here: _client_connections reads
    # CREDENTIALS raw (never _client_mids, which setdefaults a blank record),
    # so a manager LOOKING at a merchant's connections cannot write to them.
    # updated_at comes the same raw way. No secret value is in this context.
    connections_by_client = {}
    cred_updated = {}
    for name in CLIENT_PROFILES:
        connections_by_client[name] = _client_connections(name)
        stamps = [m.get("updated_at", "")
                  for m in (CREDENTIALS.get(name) or {}).get("mids") or []]
        cred_updated[name] = max((s for s in stamps if s), default="")
    return render_template("manager_onboarding.html", agents=AgentDesk.AGENTS,
                           profiles=CLIENT_PROFILES, tiers=ClientConsole.TIERS,
                           account_fields=ClientConsole.ACCOUNT_FIELDS,
                           statuses=ClientConsole.STATUSES,
                           connections_by_client=connections_by_client,
                           cred_updated=cred_updated, dbs=DATABASES,
                           **_manager_context())


@app.route("/manager/settings")
@role_required("manager")
def manager_settings():
    # active_dataset is passed here rather than added to _settings_context(),
    # which client_settings also renders from and has no use for it.
    return render_template("manager_settings.html",
                           active_dataset=StateStore.active_dataset(),
                           reference_dataset=StateStore.reference_dataset(),
                           reference_count=len(_reference_rows_by_dispute_id()),
                           **_manager_context(), **_settings_context())


@app.route("/manager/route", methods=["POST"])
@role_required("manager")
def manager_route():
    """Assign a client book to a team lead, or an agent to a team lead."""
    payload = request.get_json(silent=True) or request.form
    lead = (payload.get("lead") or "").strip()
    if lead not in TEAM_LEADS:
        return jsonify({"ok": False, "error": f"Unknown team lead '{lead}'"}), 400

    client = (payload.get("client") or "").strip()
    agent = (payload.get("agent") or "").strip()

    if client:
        if client not in TeamConsole.BUCKET_LABELS:
            return jsonify({"ok": False, "error": f"Unknown client '{client}'"}), 404
        CLIENT_ROUTING[client] = lead
    elif agent:
        if agent not in AgentDesk.AGENTS:
            return jsonify({"ok": False, "error": f"Unknown agent '{agent}'"}), 404
        # An agent reports to exactly one lead, so take them off the others.
        for name in TEAM_LEADS:
            LEAD_AGENTS.setdefault(name, [])
            if agent in LEAD_AGENTS[name]:
                LEAD_AGENTS[name].remove(agent)
        LEAD_AGENTS[lead].append(agent)
        LEAD_AGENTS[lead].sort()
    else:
        return jsonify({"ok": False, "error": "Nothing to assign."}), 400

    _save_routing()
    return jsonify({"ok": True, "lead": lead, "client": client, "agent": agent,
                    "lead_agents": LEAD_AGENTS,
                    "client_routing": CLIENT_ROUTING})


# Separate from manager_route rather than another branch inside it: that route
# rejects a payload with no team lead as its first statement, so a tier change
# would be turned away before it was ever read.
@app.route("/manager/client/tier", methods=["POST"])
@role_required("manager")
def manager_client_tier():
    """Move a client book onto a different service tier."""
    payload = request.get_json(silent=True) or request.form
    client = (payload.get("client") or "").strip()
    tier = (payload.get("tier") or "").strip()

    if tier not in ClientConsole.TIERS:
        return jsonify({"ok": False, "error": f"Unknown tier '{tier}'"}), 400
    if client not in CLIENT_PROFILES:
        return jsonify({"ok": False, "error": f"Unknown client '{client}'"}), 404

    CLIENT_PROFILES[client]["tier"] = tier
    _save_client_profiles()
    return jsonify({"ok": True, "client": client, "tier": tier,
                    "label": ClientConsole.TIERS[tier]["label"]})


@app.route("/manager/client/account", methods=["POST"])
@role_required("manager")
def manager_client_account():
    """Update a client's merchant account record."""
    payload = request.get_json(silent=True) or request.form
    client = (payload.get("client") or "").strip()
    if client not in CLIENT_PROFILES:
        return jsonify({"ok": False, "error": f"Unknown client '{client}'"}), 404

    fields = payload.get("account")
    if not isinstance(fields, dict):
        fields = {k: payload.get(k) for k in ClientConsole.ACCOUNT_FIELDS
                  if payload.get(k) is not None}
    fields = {k: str(v).strip() for k, v in fields.items()
              if k in ClientConsole.ACCOUNT_FIELDS}
    if not fields:
        return jsonify({"ok": False, "error": "Nothing to update."}), 400

    # Unlike /merchant-config, a blank value clears the field. An account that
    # is no longer pending with anyone has to be able to say so.
    CLIENT_PROFILES[client]["account"].update(fields)
    _save_client_profiles()
    return jsonify({"ok": True, "client": client,
                    "account": CLIENT_PROFILES[client]["account"]})


@app.route("/ingest")
@role_required("admin", "manager")
def ingest():
    # Quick mode only. The 1,000-orders + 12-chargebacks pipeline demo used to
    # live behind ?mode=full; it cleared CASES and replaced the working set with
    # 12 fabricated cases, which silently wiped whatever had been ingested.
    #
    # Built from the loaded book rather than IngestionDemo's ten hardcoded
    # cases: this is the page an upload is made from, so it has to be the page
    # that shows the upload landing. It used to report 10 no matter what.
    data = IngestConsole.compute(AIValidationEngine.get_pipeline_stats(CASES))
    data["orders_meta"] = None
    # The backend reference sheet is deliberately not surfaced on this page. It
    # still backs every ingest — see _enriched_rows — the page just does not
    # describe it or offer to replace it.
    return render_template("ingest.html", d=data, mode="quick",
                           merchant=MERCHANT_CONFIG,
                           max_upload_mb=MAX_UPLOAD_MB)


def _first(row, *names, default=""):
    """First non-empty value among `names`.

    The dispute sheets have shipped under two spellings: an early export
    truncated its headers (`ReasonCategor`, `ChargebackAm`, `ChannelName`),
    the current one spells them out. Trying each name in turn lets one
    normalizer read both instead of silently returning blanks for whichever
    file it wasn't written against.
    """
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return default


def _last_four(masked):
    """Trailing digits of a masked PAN like '413278XXXXXX5506'."""
    digits = [ch for ch in (masked or "") if ch.isdigit()]
    return "".join(digits[-4:]) if len(digits) >= 4 else ""


def _normalize_chargeback_row(row):
    """Auto-detect CSV format and normalize to standard fields."""
    headers = set(row.keys())

    # Format B: DisputeId / ReasonCode / CardType / ProcessorName columns
    if "DisputeId" in headers or "ChannelName" in headers or "DisputeStage" in headers:
        card_type = _first(row, "CardScheme", "CardType", default="Visa")
        network = card_type.title() if card_type.isupper() else card_type
        # NetworkReasonCode is the scheme's own code and is the authoritative
        # one; ReasonCode is the merchant-side copy. They agree on every row of
        # the current sheet, so preferring it changes nothing today and is
        # correct for any sheet where they diverge.
        reason_code = _first(row, "NetworkReasonCode", "ReasonCode")
        category = _first(row, "ReasonCategory", "ReasonCategor")
        # The family this code belongs to, whichever network wrote it. The raw
        # code stays on the case — that is what the sheet says and what the
        # agent sees — while every knowledge-base lookup goes through the family
        # so a Mastercard 4837 gets the same packet as a Visa 10.4.
        family, _family_entry = ReasonCodeInterpreter.resolve(reason_code, network)
        stage = _first(row, "DisputeStage", default="CB")
        win_rate = _safe_float(_first(row, "WinRate", default="0"))

        # The sheet's ReasonCategory vocabulary is "Fraud / Authorization /
        # Processing Error / Consumer Dispute"; the app's internal buckets —
        # what EVIDENCE_BUNDLES and cat_map below are keyed on — are
        # "fraud / authorization / merchandise / processing / others". Left
        # unmapped, the 63 Consumer Dispute and Processing Error rows would all
        # fall through to the generic "others" evidence bundle. Take the bucket
        # from the resolved family where there is one, and fall back to the
        # label only when the code resolves nothing.
        bucket = ReasonCodeInterpreter.bucket(reason_code, network)
        if not bucket:
            bucket = {
                "processing error": "processing",
                "consumer dispute": "merchandise",
            }.get(category.lower(), category.lower())

        # Map category to scenario
        cat_map = {
            "fraud": "Fraud - Card Not Present (CNP)",
            "authorization": "Fraud - No Authorization",
            "merchandise": "Merchandise - Item Not Received",
            "processing": "Processing - Incorrect Amount",
            "others": "Other Dispute",
        }
        scenario = cat_map.get(bucket, category.title() if category else "Unknown")

        # Stage label
        stage_map = {"CB": "Chargeback", "PRE_ARB": "Pre-Arbitration", "RFI": "Request for Information"}
        stage_label = stage_map.get(stage, stage)

        due_date = _first(row, "DueDate", "RepresentmentDeadline")

        return {
            "dispute_ref": _first(row, "DisputeId"),
            "reason_code": reason_code,
            "reason_code_canonical": family,
            "reason_description": _first(row, "ReasonMsg"),
            "card_scheme": card_type.title() if card_type.isupper() else card_type,
            "card_last_four": _last_four(_first(row, "CardNumberMasked")),
            # ChargebackTxnAmount, not ChargebackAmount. The two disagree on
            # every row of the sheet, and ChargebackAmount is a recycled column
            # unrelated to the transaction — 449.42 against a 162.17 order —
            # so the case page printed "Disputed Amount 449.42" directly above
            # "Amount Authorized 162.17" on all 100 cases. ChargebackTxnAmount
            # agrees with TransactionAmount and OrderTotalAmount. The older
            # truncated exports are kept as fallbacks.
            "disputed_amount": _safe_float(_first(row, "ChargebackTxnAmount", "ChargebackAmount",
                                                  "ChargebackAm", default="0")),
            "txn_original_amount": _safe_float(_first(row, "ChargebackTxnAmount", default="0")),
            "transaction_date": _first(row, "TransactionTime", "TransactionTim"),
            "dispute_date": _first(row, "DisputeTime"),
            "due_date": due_date.split(" ")[0] if due_date else "",
            "arn": _first(row, "ARN"),
            "processor": _first(row, "ProcessorName", "ChannelName", default="Unknown"),
            # The current sheet carries a real order reference; the older one only
            # had the opaque TransactionChannel token.
            "order_id": _first(row, "OrderId", "TransactionChannel", "TransactionCha"),
            "payment_ref": _first(row, "PspReferenceId", "MerchantUserId"),
            "scenario": scenario,
            # The internal bucket, which is what EVIDENCE_BUNDLES, the routing
            # heuristic and the category filters are keyed on. The sheet's own
            # label is kept beside it for anywhere that wants to quote it.
            "category": bucket,
            "category_label": category,
            "stage": stage_label,
            "currency": _first(row, "ChargebackTxnCurrency", "ChargebackTxn", default="USD"),
            "txn_amount": _safe_float(_first(row, "ChargebackTxnAmount", default="0")),
            "refund_type": _first(row, "RefundPayType"),
            "win_rate": win_rate,
            "status": _first(row, "DisputeStatus", default="NEED_RESPONSE"),
            # Sheets without these columns fall back to an undecided case.
            "case_outcome": _first(row, "CaseOutcome", default="Decision Pending"),
            "outcome_date": _first(row, "OutcomeDate"),
            # Everything else the sheet carries. Kept whole rather than flattened
            # into ~40 more keys: the evidence documents read straight from it.
            "source": dict(row),
        }

    # Format A: dispute_ref / reason_code / card_scheme columns (original)
    return {
        "dispute_ref": row.get("dispute_ref", ""),
        "reason_code": row.get("reason_code", "13.1"),
        "reason_code_canonical": ReasonCodeInterpreter.resolve(
            row.get("reason_code", "13.1"), row.get("card_scheme", "Visa"))[0],
        "reason_description": row.get("reason_description", ""),
        "card_scheme": row.get("card_scheme", "Visa"),
        "card_last_four": row.get("card_last_four", ""),
        "disputed_amount": _safe_float(row.get("disputed_amount", 0)),
        "transaction_date": row.get("transaction_date", ""),
        "dispute_date": row.get("dispute_date", ""),
        "due_date": "",
        "arn": row.get("arn", ""),
        "processor": row.get("processor", "Unknown"),
        "order_id": row.get("order_id", ""),
        "payment_ref": row.get("payment_ref", ""),
        "scenario": "",
        "category": "",
        "stage": "Chargeback",
        "currency": "USD",
        "txn_amount": _safe_float(row.get("disputed_amount", 0)),
        "txn_original_amount": _safe_float(row.get("disputed_amount", 0)),
        "refund_type": "",
        "win_rate": 0,
        "status": "NEED_RESPONSE",
        "case_outcome": "Decision Pending",
        "outcome_date": "",
        "source": dict(row),
    }


def _reference_rows_by_dispute_id():
    """The backend sheet, keyed on DisputeId. {} when none is configured.

    Empty is a supported state, not a failure: with no reference sheet an
    ingest still works, the cases just carry only what the uploaded file holds.
    """
    name = StateStore.reference_dataset()
    if not name:
        return {}
    rows = _read_csv_rows(os.path.join(REFERENCE_DIR, name))
    return {key: row for row in rows
            if (key := (row.get("DisputeId") or "").strip())}


def _enriched_rows(chargebacks):
    """Fill each uploaded row from the backend sheet. Returns (rows, matched).

    The uploaded sheet wins wherever it actually carries a value and the
    reference fills the rest, so re-uploading a corrected amount overrides the
    backend rather than being overwritten by it.

    The filter is on truthiness rather than key presence, deliberately: the
    trimmed export writes empty cells for columns it does not track, and
    letting those through would blank out real backend data — the merge would
    then be worse than no merge at all.
    """
    reference = _reference_rows_by_dispute_id()
    if not reference:
        return list(chargebacks), 0

    merged, matched = [], 0
    for row in chargebacks:
        base = reference.get((row.get("DisputeId") or "").strip())
        if base is None:
            merged.append(row)
            continue
        matched += 1
        merged.append({**base,
                       **{k: v for k, v in row.items() if v not in ("", None)}})
    return merged, matched


def _build_cases_from_rows(chargebacks):
    """Turn raw chargeback CSV rows into case dicts.

    Shared by the startup loader and the /ingest/upload route so the two
    ingestion paths cannot drift apart.

    An uploaded sheet may be a thin case list -- the trimmed export carries
    eleven columns, essentially "which disputes exist". The rest of the case
    comes from the backend reference sheet, joined on DisputeId below. Without
    that join a thin row does not degrade politely: _normalize_chargeback_row
    fills the missing authentication columns with defaults ("No match", "Not
    Offered"), those defaults score in AIValidationEngine, and the same hundred
    disputes route differently depending on which file was uploaded.

    `_enriched_rows` also reports how many rows matched, which /ingest/upload
    puts in its flash message -- partial enrichment is worth saying out loud,
    because an unmatched row falls back to exactly those invented defaults.
    """
    # Use existing orders data for enrichment (if order_id matches)
    all_orders = ChargebackCaseLoader.load_orders()
    orders_by_id = {o["order_id"]: o for o in all_orders}

    chargebacks, _enriched = _enriched_rows(chargebacks)

    new_cases = []
    for idx, raw_row in enumerate(chargebacks):
        cb = _normalize_chargeback_row(raw_row)

        order_id = cb["order_id"]
        raw = orders_by_id.get(order_id, {})
        reason_code = cb["reason_code"]
        # Look the knowledge base up by family, not by the raw string. Keyed on
        # the raw code this missed on 87 of 100 rows of the outgoing sheet and
        # would still miss on ~80 of the corrected one, because 14 of its 19
        # codes are not Visa-format.
        reason_info = REASON_CODES.get(cb.get("reason_code_canonical") or reason_code, {})
        disputed_amount = cb["disputed_amount"]
        desc = cb["reason_description"]
        scenario = desc or cb["scenario"] or (reason_info.get("scenarios", ["Unknown"])[0] if reason_info.get("scenarios") else "Unknown")

        case_id = cb["dispute_ref"] or f"CSV-{idx + 1:04d}"
        card_last4 = cb["card_last_four"] or raw.get("card_last_four", "0000")

        src = cb.get("source") or {}

        # Determine authentication signals. Preference order: the dispute sheet
        # itself (the current export carries AVS/CVV/3DS and delivery columns),
        # then the orders file, then inference from the reason category for the
        # older sheets that carry neither.
        has_order = bool(raw)
        if src.get("AvsResult") or src.get("ThreeDSStatus"):
            avs_pass = (src.get("AvsResult", "").startswith("Y")
                        and src.get("CvvResult", "").startswith("M"))
            delivered = src.get("DeliveryStatus", "").lower().startswith(
                ("delivered", "digital delivery"))
        elif has_order:
            avs_pass = raw.get("avs_cvv_match", "") == "Pass"
            delivered = raw.get("fulfillment_status", "") == "Delivered"
        else:
            # Infer from category and reason description for uploaded cases
            cat = (cb.get("category", "") or "").lower()
            desc_lower = desc.lower()

            if cat == "fraud" or any(k in desc_lower for k in ["fraud", "unauthorized", "ato", "not recognized"]):
                # Fraud: only winnable if 3DS was used (liability shift to issuer)
                avs_pass = False
                delivered = False
            elif cat == "authorization" or any(k in desc_lower for k in ["no authorization", "purchase_unauthorized"]):
                avs_pass = False
                delivered = False
            elif cat == "others" or any(k in desc_lower for k in ["other", "unknown", "inquiry", "noncompliant", "unrecognizable"]):
                avs_pass = False
                delivered = False
            elif cat == "merchandise" or any(k in desc_lower for k in [
                "not received", "not as described", "defective", "unsatisfactory",
                "damaged", "cancelled", "return", "faulty"
            ]):
                avs_pass = True
                delivered = "not received" not in desc_lower and "cancelled" not in desc_lower
            elif cat == "processing" or any(k in desc_lower for k in [
                "incorrect amount", "duplicate", "credit not processed", "processing error"
            ]):
                # Processing: AVS may pass but needs human verification (HITL)
                avs_pass = True
                delivered = False  # No auto-delivery, forces HITL not Auto
            else:
                avs_pass = False
                delivered = False

        # Two vocabularies for the same fact. `case_status` is the reporting
        # deck's wording, which keeps "Not Fought" distinct; `outcome` is what
        # the rest of the app already speaks, where a conceded case is a refund.
        case_status = cb["case_outcome"] or "Decision Pending"
        outcome = OUTCOME_BY_STATUS.get(case_status, "Pending")

        new_case = {
            "case_id": case_id,
            "scenario": scenario,
            "chargeback_category": desc or reason_info.get("title", cb["category"] or "Unknown"),
            # Internal bucket (fraud / merchandise / processing / authorization /
            # others) — drives the Agent Desk category filter and the evidence
            # bundle. Derived from the resolved family, so it no longer depends
            # on the sheet happening to use the app's own vocabulary.
            "reason_category": cb["category"] or "Unknown",
            "reason_category_label": cb.get("category_label", ""),
            "reason_code": reason_code,
            # The dispute family the code belongs to on any network. The raw
            # code above is what the sheet says and what the agent sees; this is
            # what every knowledge-base lookup keys on.
            "reason_code_canonical": cb.get("reason_code_canonical", ""),
            "processor": cb["processor"],
            "amount": disputed_amount,
            # Filled in below from AIValidationEngine.score once the case dict
            # is whole — the scorer reads AVS, CVV, 3DS, amount and reason code,
            # none of which are assembled yet at this point.
            "win_probability": 0,
            "submission_date": cb["dispute_date"],
            # A ruling implies a representment was filed; a concession means
            # nothing was ever sent — the same "Not Submitted" the Agent Desk's
            # own Not Fought action writes. Stamping every decided case as
            # Submitted produced impossible "Submitted + Refunded" rows.
            "submission_status": ("Submitted" if case_status in ("Won", "Lost")
                                  else "Not Submitted" if case_status == "Not Fought"
                                  else "Pending"),
            "outcome": outcome,
            "case_status": case_status,
            "outcome_date": cb["outcome_date"],
            "merchant": MERCHANT_CONFIG["company_name"],
            # MERCHANT_CONFIG's account number is blank on a fresh install, and
            # the sheet carries the real acquirer MID per case. Prefer the
            # configured value when someone has set one at /merchant-config.
            "merchant_account": (MERCHANT_CONFIG["merchant_account_number"]
                                 or src.get("AcquirerMID", "")),
            "descriptor_name": MERCHANT_CONFIG["dba_name"],
            "descriptor_url": MERCHANT_CONFIG["descriptor_url"],
            "payment_method": cb["card_scheme"],
            "card_last_four": card_last4,
            "card_expiry": "",
            "cardholder": src.get("UserFullName") or "***REDACTED***",
            "issuer_country": src.get("IssuerCountry") or "United States",
            "issuer_name": src.get("IssuerName", ""),
            "avs_response": src.get("AvsResult") or (
                "Both postal code and address match (Y)" if avs_pass else "No match"),
            "cvv_response": src.get("CvvResult") or (
                "Supplied, Matches (M)" if avs_pass else "Not provided"),
            "threed_secure": src.get("ThreeDSStatus") or (
                "Authenticated" if (avs_pass and delivered) else "Not Offered"),
            "transaction_date": cb["transaction_date"],
            "amount_authorized": cb.get("txn_original_amount") or cb["txn_amount"] or disputed_amount,
            # The sheet carries the settled figure and its SettlementDate. This
            # used to invent one — disputed * 0.85, a 15% haircut with no basis,
            # presented to the issuer in the representment packet as fact.
            "amount_settled": _safe_float(src.get("TransactionAmount")) or disputed_amount,
            "dispute_psp_ref": cb["dispute_ref"] or case_id,
            "payment_psp_ref": cb["payment_ref"],
            "dispute_creation_date": cb["dispute_date"],
            "order_id": order_id,
            "acquirer_ref": cb["arn"] or "N/A",
            "acquirer_code": src.get("AcquirerMID", ""),
            "acquirer_name": src.get("AcquirerName", ""),
            "auth_code": src.get("AuthorizationCode", ""),
            "cardholder_email": src.get("UserEmail", ""),
            "cardholder_phone": src.get("UserPhone", ""),
            "auto_defended": delivered and avs_pass,
            "liability_shift": (src["ThreeDSLiabilityShift"] == "Yes"
                                if src.get("ThreeDSLiabilityShift") else avs_pass),
            "issuer_comments": "",
            "dispute_stage": cb["stage"],
            "dispute_status": cb["status"],
            "due_date": cb["due_date"],
            "currency": cb["currency"],
            "refund_type": cb["refund_type"],
            "win_rate": cb["win_rate"],
            "reason_description": cb["reason_description"],
            # Full sheet row, kept intact so the evidence documents can read the
            # order, delivery, refund and account columns without the case dict
            # having to mirror all 89 of them.
            "source": src,
            "dispute_history": [
                {"event": "CaseCreated", "date": cb["dispute_date"]},
                {"event": "CSVUpload", "date": datetime.now().strftime("%b %d, %Y, %H:%M:%S")},
            ],
        }
        new_cases.append(new_case)

    # Win probability is the classifier's confidence, not a rescaled CSV column.
    #
    # It used to be `max(1, int(win_rate * 10000))`. WinRate is a fraction
    # (0.0003–0.0120 in the shipped sheet), so that multiplied a 0.03%–1.20%
    # portfolio rate by 10,000: a floor of 1 with no ceiling, which put 20 of
    # 100 cases above 100% and left the other 80 inflated by the same 100x
    # without it showing. The scorer already returns a clamped 0–100 built from
    # this case's own AVS, CVV, 3DS, amount and reason code, and it is the same
    # number the Auto-Represent / HITL / Refund routing is decided on — so a
    # case can no longer be routed for automatic defence while its own page
    # reports a poor chance of winning.
    for case in new_cases:
        case["win_probability"] = AIValidationEngine.score(case)

    return new_cases


def _auto_submit_filed_cases():
    """Make the Auto-Represent lane's promise true: file the representment.

    The routing copy ("the system builds the evidence packet and files the
    representment") described a submission that never happened — auto-routed
    cases sat at submission_status "Pending" forever while every other page
    counted them as filed. Once evidence collection has run, stamp each
    qualifying case Submitted with provenance and a timeline event; the
    caller persists so the filing date survives a restart.

    Deliberately NOT _record_agent_action: no agent acted, so agent_action
    stays unset and team metrics keep counting only human work. The
    agent_action gate below also protects an agent's explicit "Pending"
    revert (the one action that puts submission_status back) from being
    re-stamped on the next boot.

    Idempotent by the first gate: a restore that brings "Submitted" back
    makes this a no-op, so the stamped date is stable across restarts.
    Returns the number of cases newly stamped.
    """
    stamped = 0
    for case in CASES:
        if (case.get("submission_status") or "") != "Pending":
            continue
        # get-or-default, not equality: /add-case builds cases with no
        # case_status key at all, and every other reader treats that as
        # Decision Pending. A concession or ruling never re-files.
        if (case.get("case_status") or "Decision Pending") != "Decision Pending":
            continue
        if case.get("agent_action"):
            continue
        ev = EVIDENCE_RESULTS.get(case.get("case_id")) or {}
        # auto_representable already encodes the whole gate: override-aware
        # routing == auto_represent AND evidence completeness >= 85. Files
        # only when the packet is actually complete.
        if not ev.get("auto_representable"):
            continue

        at = datetime.now().strftime("%b %d, %Y, %H:%M:%S")
        case["submission_status"] = "Submitted"
        case["auto_submitted"] = {
            "at": at,
            "completeness": ev.get("overall_completeness_pct", 0),
            "confidence": ev.get("ml_confidence", 0),
        }
        history = case.setdefault("dispute_history", [])
        # Guarded append: restore replays the stored history wholesale, so a
        # replayed case already carries the event. "AutoDefenseSubmitted" is
        # already in CLIENT_EVENT_LABELS with no writer — this is the writer
        # it was waiting for.
        if not any((e.get("event") or "") == "AutoDefenseSubmitted"
                   for e in history):
            history.append({"event": "AutoDefenseSubmitted", "date": at})
        stamped += 1
    return stamped


def _assignment_pool(case, mapping):
    """The agents an auto-assignment may pick from for this case.

    The team of the lead this case's client book routes to, so the case lands
    where the lead who has to re-allocate it can see it -- TeamConsole.for_lead
    hides a case owned by an agent off the lead's roster. Falls back to the
    whole roster when the book routes nowhere: no channel, or a routing file
    that left the lead with no agents.
    """
    lead = CLIENT_ROUTING.get(ClientConsole.client_of(case, mapping), "")
    pool = [a for a in LEAD_AGENTS.get(lead, []) if a in AgentDesk.AGENTS]
    return pool or list(AgentDesk.AGENTS)


def _auto_assign_unowned_cases():
    """Give every case nobody owns to the least-loaded agent on its team.

    The gate is key *presence*, not truthiness: /admin/allocate writes
    assigned_agent="" for an explicit unassign, and StateStore stores and
    restores that "" (presence-and-difference), so a lead's return-to-pool
    survives a restart the way an agent's "Pending" revert survives
    _auto_submit_filed_cases. Idempotent for the same reason: a restore that
    brings the owner back makes this a no-op with the original stamp.

    Walked in deterministic_seed order rather than sheet order, so the same
    book always lands the same way after a reset and no agent ends up holding
    a single card network (AgentDesk explains the positional trap). Load is
    seeded from cases already owned, so a lead's allocations count. Decided
    cases are assigned too: agent history and productivity read them, and a
    won case on nobody's desk is a chart with a hole in it. This is a
    one-time stamp at ingest, never a re-balance.

    Returns Counter(agent -> newly assigned).
    """
    unowned = [c for c in CASES if "assigned_agent" not in c and c.get("case_id")]
    assigned = Counter()
    if not unowned:
        return assigned
    mapping = TeamConsole._bucket_map(CASES)
    load = Counter(c["assigned_agent"] for c in CASES if c.get("assigned_agent"))
    at = datetime.now().strftime("%b %d, %Y, %H:%M:%S")
    for case in sorted(unowned,
                       key=lambda c: (deterministic_seed(c["case_id"]), c["case_id"])):
        pool = _assignment_pool(case, mapping)
        agent = min(pool, key=lambda a: load[a])   # min is stable: ties go to roster order
        case["assigned_agent"] = agent
        case["auto_assigned"] = {"at": at}
        load[agent] += 1
        assigned[agent] += 1
    return assigned


def _apply_cases(new_cases, source="manual", merge=False):
    """Swap in — or merge in — a case set and recompute cached evidence.

    `source` records how a case arrived. It defaults to "manual" because every
    way in goes through a person: an upload at /ingest, or a case typed at
    /add-case. There is no automated feed. The default used to be "automated",
    which was the whole bug — _load_startup_cases calls this with no source, so
    an uploaded sheet was correctly tagged manual and then silently relabelled
    on the next restart.

    `merge=True` keeps the cases already loaded: a case id that is already known
    is updated in place and keeps its original source, anything new is appended.
    Without it an upload would silently discard the existing book.

    Agent decisions are re-applied before classification so the restored status
    feeds evidence and routing. They are keyed by case id, so both a merge and a
    replace keep the work an agent has already done.
    """
    global EVIDENCE_RESULTS, EVIDENCE_STATS

    if merge:
        existing = {c["case_id"]: c for c in CASES}
        for case in new_cases:
            known = existing.get(case["case_id"])
            if known is None:
                case["ingest_source"] = source
                CASES.append(case)
            else:
                # Keep how this case originally arrived, and keep the fields a
                # lead or agent has since set on it.
                # Only how this case arrived. Everything a lead or agent set on
                # it is re-applied from the state store below, which is a
                # superset of what this list used to name -- it never covered
                # outcome, case_status, submission_status or ml_override, so an
                # accepted case was silently un-accepted by a re-upload.
                keep = {k: known[k] for k in ("ingest_source",) if k in known}
                known.update(case)
                known.update(keep)
    else:
        for case in new_cases:
            case["ingest_source"] = source
        CASES.clear()
        CASES.extend(new_cases)

    # Manually entered cases first: they have no row in the sheet, so without
    # this they vanish on restart. Ahead of everything below because the
    # narrative restore and the state restore both key off the case list.
    known_ids = {c.get("case_id") for c in CASES}
    for stored in StateStore.added_cases():
        if stored.get("case_id") not in known_ids:
            # setdefault, not assignment: rows saved before /add-case started
            # tagging carry no source and would otherwise fall through to the
            # reader's fallback. A case typed by hand is as manual as it gets.
            stored.setdefault("ingest_source", "manual")
            CASES.append(stored)
            known_ids.add(stored["case_id"])

    _restore_routing()
    # Second, beside routing: both are client-keyed manager-owned state, and
    # neither depends on the case list. Everything below this line does.
    _restore_client_profiles()
    # Third, and also case-independent: templates are keyed by reason category
    # and document, never by case id, so a re-ingest cannot invalidate them.
    _restore_template_overrides()
    # Also case-independent: profiles are keyed by username, so re-ingesting the
    # book cannot touch them.
    _restore_user_profiles()
    # Keyed by client label, like the two above — a merchant's third-party
    # logins have nothing to do with which cases are loaded.
    _restore_credentials()
    # After the case list is rebuilt: prose for a case that no longer exists is
    # dropped rather than stranded, unlike the templates restored above.
    _restore_case_narrative()
    # Everything a user did to a case, in one restore. Must land before
    # classify_all below: ml_override feeds the routing override, so replaying
    # after classification would silently ignore every accepted case.
    #
    # Assignment, not merge — the stored dispute_history *is* the history, so
    # running this twice replaces rather than appends. That matters because
    # _apply_cases runs again on every sheet re-upload.
    _capture_baseline()
    StateStore.migrate_json(AGENT_ACTIONS_FILE, ALLOCATIONS_FILE, REWORK_FILE)
    StateStore.restore(CASES,
                       valid_actions=set(AGENT_ACTION_EFFECTS),
                       valid_agents=set(AgentDesk.AGENTS))
    # After restore, so a lead's allocation -- and an explicit unassign -- win
    # and seed the load; before classify_all, whose {**case} copies would
    # otherwise miss the owner in this load's derived lists.
    auto_assigned = _auto_assign_unowned_cases()
    if auto_assigned:
        print(f"Auto-assigned {sum(auto_assigned.values())} unowned case(s) "
              f"across {len(auto_assigned)} agent(s).", flush=True)
    _classified = AIValidationEngine.classify_all(CASES)
    EVIDENCE_RESULTS = EvidenceCollectionEngine.collect_all(_classified)
    EVIDENCE_STATS = EvidenceCollectionEngine.get_aggregate_stats(EVIDENCE_RESULTS)
    # After evidence, before the version bump: the stamp reads
    # EVIDENCE_RESULTS and writes CASES, and the save diffs against the
    # baseline captured above — so the filing survives a restart, and the
    # next boot's restore turns this into a no-op with the original date.
    auto_filed = _auto_submit_filed_cases()
    if auto_filed:
        # print, not app.logger.info: the dev server leaves the app logger at
        # WARNING, and this line sits beside the "Loaded N cases" print.
        # flush: stdout is block-buffered when the server runs behind a pipe,
        # and an unflushed line here looks like the stamp never ran.
        print(f"Auto-filed {auto_filed} auto-represent case(s).", flush=True)
    # One save covers both stamps: each diffs against the baseline captured
    # above, so the owner and the filing survive a restart together.
    if auto_filed or auto_assigned:
        _save_case_state()
    # An upload changes the book under everyone, so it counts as a change even
    # though nothing here went through one of the _save_* paths.
    _bump_state()
    return {"auto_filed": auto_filed, "auto_assigned": auto_assigned}


def _read_csv_rows(path):
    """Parse a CSV off disk, tolerating what Excel actually writes.

    Returns [] rather than raising for anything unreadable. This is called at
    import, so a bad sheet has to degrade into an empty book rather than take
    the app down -- and `UnicodeDecodeError` subclasses `ValueError`, not
    `OSError`, so it needs naming explicitly. `utf-8-sig` eats the BOM; cp1252
    is what Excel on Windows exports by default; latin-1 never fails and is
    therefore the last resort rather than the first choice.
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                return list(_csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except (OSError, _csv.Error):
            return []
    return []


def _load_startup_cases():
    """Reload the ingested sheet at boot, if there is one.

    The app deliberately starts with an EMPTY book. `CASES` is a module-level
    list that dies with the process, so the only thing that makes an ingest
    outlast a restart is the dataset pointer in the state store: the uploaded
    CSV stays on disk under data/ and is re-parsed here.

    With nothing ingested this clears `CASES` and returns 0. That is a normal
    state, not a failure -- seed.py's sample cases must not leak in as a
    fallback, or the app would look populated before anyone uploaded anything.
    """
    name = StateStore.active_dataset()
    rows = _read_csv_rows(os.path.join(UPLOAD_DIR, name)) if name else []

    if name and not rows:
        # The pointer names a sheet that is gone or unreadable. Drop it so the
        # app settles into its empty state instead of claiming a dataset it
        # cannot show.
        app.logger.warning("Active dataset %r could not be read; starting empty.", name)
        StateStore.clear_active_dataset()

    # Even with no sheet this goes through _apply_cases rather than clearing
    # CASES directly: manually added cases, client routing, user profiles and
    # stored credentials all restore in there, and none of them depend on a
    # dataset being present.
    # source is named rather than left to the default: the only way a sheet
    # reaches data/ and the dataset pointer is somebody uploading it at
    # /ingest, so a reloaded book is exactly as manual as it was when ingested.
    _apply_cases(_build_cases_from_rows(rows) if rows else [], source="manual")
    return len(CASES)


@app.route("/ingest/upload", methods=["POST"])
@role_required("admin", "manager")
def ingest_upload():
    chargebacks_file = request.files.get("chargebacks_csv")

    if not chargebacks_file:
        flash("Please upload a Chargebacks CSV file.", "error")
        return redirect(url_for("ingest"))

    try:
        blob = chargebacks_file.read()
        # Excel on Windows still exports cp1252 by default. Rejecting those
        # outright would be a worse answer than reading them: latin-1 never
        # fails, so it is the last resort rather than the first choice.
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = blob.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        chargebacks_text = io.StringIO(text)
        chargebacks = list(_csv.DictReader(chargebacks_text))
    except Exception as e:
        flash(f"Error reading CSV file: {e}", "error")
        return redirect(url_for("ingest"))

    if not chargebacks:
        flash("CSV file appears to be empty.", "error")
        return redirect(url_for("ingest"))

    # Keep the sheet, not just the rows it parsed into. CASES is a module-level
    # list that dies with the process, so without a copy on disk plus the
    # pointer below, this upload would last exactly until the next restart.
    stored_name = ""
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stored_name = f"{stamp}-{secure_filename(chargebacks_file.filename or 'upload.csv')}"
        with open(os.path.join(UPLOAD_DIR, stored_name), "wb") as f:
            f.write(blob)
        StateStore.set_active_dataset(stored_name)
    except OSError as exc:
        # The book still loads for this session; it just will not survive a
        # restart. Say so rather than implying the ingest failed outright.
        app.logger.warning("Could not store the uploaded sheet: %s", exc)
        flash("Loaded, but the file could not be saved — it will not survive a "
              "restart.", "error")
        stored_name = ""

    # Replace rather than merge. One sheet is the active dataset, so a second
    # upload switches books instead of topping up the first — which is what
    # makes the case count on every page match the file just uploaded.
    # Counted here as well as inside _build_cases_from_rows so the message can
    # say what the join actually did. Silent partial enrichment is the failure
    # worth surfacing: an unmatched row keeps the invented authentication
    # defaults and scores on them.
    _, enriched = _enriched_rows(chargebacks)
    summary = _apply_cases(_build_cases_from_rows(chargebacks), source="manual",
                           merge=False)
    if stored_name:
        if not StateStore.reference_dataset():
            detail = ("No backend reference sheet is configured, so these cases "
                      "carry only what the file itself holds.")
        elif enriched == len(chargebacks):
            detail = "All rows enriched from the backend reference sheet."
        else:
            detail = (f"{enriched} of {len(chargebacks)} row(s) matched the "
                      f"backend reference sheet; the rest carry only what the "
                      f"file itself holds.")
        # Say what the system did with the work, and where to undo it.
        auto = summary["auto_assigned"]
        if auto:
            detail += (f" Auto-assigned {sum(auto.values())} case(s) across "
                       f"{len(auto)} agent(s); re-allocate from Case Allocation.")
        flash(f"Ingested {len(CASES)} case(s) from {chargebacks_file.filename}. "
              f"This is now the active dataset. {detail}", "success")
    # Back to whichever console the uploader came from. This used to land on the
    # legacy /dashboard, which belongs to no role and has no way back.
    return redirect(_role_home_url())


@app.errorhandler(413)
def upload_too_large(_exc):
    """Say which limit was hit rather than showing Werkzeug's bare 413.

    Redirects to whichever page posted, so an evidence upload lands back on the
    case it came from and a case-list upload lands back on /ingest.
    """
    flash(f"That file is larger than the {MAX_UPLOAD_MB} MB limit. "
          f"Split the export and upload it in parts.", "error")
    return redirect(request.referrer or url_for("ingest"))


@app.route("/ingest/reset", methods=["POST"])
@role_required("admin", "manager")
def ingest_reset():
    """Put the app back to its empty state, ready for a fresh upload.

    Uploading already replaces the book, so this exists for the other half:
    everything worked in the app — agent actions, allocations, recorded issuer
    rulings, manually added cases — is keyed on DisputeId and survives an
    upload by design. Demoing to somebody new, that residue reappears on the
    new sheet and the book looks half-worked before anyone has touched it.

    StateStore.clear() has always done this; it just had nothing calling it.
    The uploaded CSVs stay on disk under data/ — this drops the pointer, not
    the files, so nothing a user gave us is destroyed.
    """
    cleared = StateStore.clear()
    StateStore.clear_active_dataset()
    # Settles CASES to empty through the normal path rather than by clearing
    # the list, so client routing and credentials restore exactly as at boot.
    _load_startup_cases()
    flash("Reset. Upload a CSV to load a case book." if cleared
          else "Could not clear stored case state.",
          "success" if cleared else "error")
    return redirect(url_for("ingest"))


@app.route("/ingest/reference", methods=["POST"])
@role_required("admin", "manager")
def ingest_reference():
    """Replace the backend sheet the case list is joined against.

    Deliberately does not touch CASES. This changes what the app knows about
    disputes, never which disputes exist -- so it takes effect on the next
    ingest or restart rather than silently re-deriving the book underfoot,
    which would rewrite every case's ML routing with no upload having happened.
    """
    ref_file = request.files.get("reference_csv")
    if not ref_file:
        flash("Please choose a reference CSV file.", "error")
        return redirect(url_for("ingest"))

    blob = ref_file.read()
    # Same encoding ladder as the case-list upload: Excel on Windows still
    # exports cp1252, and latin-1 never fails so it is the last resort.
    text = ""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = blob.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        rows = list(_csv.DictReader(io.StringIO(text)))
    except _csv.Error as exc:
        flash(f"Error reading reference CSV: {exc}", "error")
        return redirect(url_for("ingest"))

    if not rows:
        flash("Reference CSV appears to be empty.", "error")
        return redirect(url_for("ingest"))

    keyed = sum(1 for r in rows if (r.get("DisputeId") or "").strip())
    if not keyed:
        # Without DisputeId there is nothing to join on, so storing it would
        # leave a reference sheet configured that silently enriches nothing.
        flash("Reference CSV has no DisputeId column — nothing to join on. "
              "Not saved.", "error")
        return redirect(url_for("ingest"))

    try:
        os.makedirs(REFERENCE_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stored = f"{stamp}-{secure_filename(ref_file.filename or 'reference.csv')}"
        with open(os.path.join(REFERENCE_DIR, stored), "wb") as f:
            f.write(blob)
        StateStore.set_reference_dataset(stored)
    except OSError as exc:
        app.logger.warning("Could not store the reference sheet: %s", exc)
        flash(f"Could not save the reference sheet: {exc.strerror or exc}", "error")
        return redirect(url_for("ingest"))

    flash(f"Backend reference sheet replaced — {keyed} dispute(s) on file from "
          f"{ref_file.filename}. It applies to the next ingest.", "success")
    return redirect(url_for("ingest"))


@app.route("/executive")
def executive():
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    ex = ExecutiveAnalytics.compute(CASES, ml_stats, EVIDENCE_STATS)
    return render_template("executive.html", ex=ex, ml=ml_stats)


@app.route("/agent-desk")
@role_required("admin", "manager")
def agent_desk():
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    desk = AgentDesk.build_queue(CASES, ml_stats, EVIDENCE_RESULTS)
    active = request.args.get("agent") or (desk["agents"][0] if desk["agents"] else "")
    return render_template("agent_desk.html", d=desk, active_agent=active,
                           actions=AGENT_ACTIONS)


def _case_owner(case):
    """Which agent owns this case, or "" when nobody does.

    A case used to fall back to AGENTS[hash(case_id) % 3] when no lead had
    allocated it, so every case always had a worker and "unassigned" could not
    be expressed. An ingested book now arrives owned by
    _auto_assign_unowned_cases, and a lead re-allocates or returns a case to
    the pool -- an explicit "" that the store keeps, so "unassigned" is still
    a real state and the queue counts still mean something.
    """
    return case.get("assigned_agent") or ""


def _current_agent():
    """Which queue the signed-in user owns.

    A manager opening the agent pages is inspecting someone's workspace, so
    they get the default queue rather than nothing at all.
    """
    return AGENT_LOGIN_MAP.get(session.get("user", ""), DEFAULT_AGENT)


def _case_locked(case):
    """Is this case frozen pending a team lead's rework approval?

    Submitting is meant to be final: the packet has gone to the PSP, so a later
    "correction" by the agent who filed it is exactly what the approval step
    exists to catch. A lead's release lifts it until the case is resubmitted.
    """
    return ((case.get("submission_status") or "") == "Submitted"
            and not case.get("rework_released"))


def _case_write_block(case):
    """Why the signed-in user may not write to this case, or None if they may.

    One definition for every route that changes a case. This rule used to live
    inside agent_desk_action alone, which is how four other write routes —
    evidence upload, upload delete, the agent-desk attachment and the legacy
    accept — ended up accepting changes to a case the agent was locked out of.
    Hiding a control is not a rule; this is the rule.
    """
    role = session.get("role")
    # Reopening and correcting a case is precisely a lead's job, so they are
    # never blocked by the lock they administer.
    if role in ("admin", "manager"):
        return None
    if role != "agent":
        return "Only the assigned agent may change this case."
    if _case_owner(case) != _current_agent():
        return "That case belongs to another agent."
    if _case_locked(case):
        return "Submitted — rework needs team-lead approval."
    return None


def _current_client():
    """Which client book the signed-in user owns, or None.

    No default, unlike _current_agent: falling back to a brand would show one
    merchant another's disputes. The label is checked against the live roster
    rather than trusted, so a stale mapping resolves to nothing rather than to
    a book that no longer exists.
    """
    label = CLIENT_LOGIN_MAP.get(session.get("user", ""))
    return label if label in TeamConsole.BUCKET_LABELS else None


def _client_console():
    """Everything the signed-in client may see, or None if they own no book."""
    client = _current_client()
    if not client:
        return None
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    return ClientConsole.for_client(CASES, ml_stats, EVIDENCE_RESULTS, client,
                                    CLIENT_PROFILES.get(client, {}))


def _agent_console(year=None, month=None):
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    return AgentConsole.for_agent(CASES, ml_stats, EVIDENCE_RESULTS,
                                  _current_agent(), year=year, month=month)


@app.route("/agent/dashboard")
@role_required("agent", "manager")
def agent_dashboard():
    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)
    a = _agent_console(year=year, month=month)
    return render_template("agent_dashboard.html", a=a,
                           period=request.args.get("period", "daily"))


@app.route("/agent/chargebacks")
@role_required("agent", "manager")
def agent_chargebacks():
    return render_template("agent_chargebacks.html", a=_agent_console(),
                           agent_actions=AGENT_ACTIONS)


def _repository_library():
    """The template content the repository page lists, from its real sources.

    Both tiles the page keeps are backed by content that already ships: the
    reason-code cover letters and the generated evidence documents. Reading
    them here rather than hardcoding a tile means the page cannot drift from
    what a case would actually pull.

    Every card is shown with the edit a team lead has saved layered on top, so
    the page always reads as what a case would send right now, not as what the
    built-in text says.
    """
    letters = []
    for key, body in COVER_LETTER_BODIES.items():
        live = TemplateRepository.apply_letter(body, TEMPLATE_OVERRIDES, key)
        letters.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "subheading": body.get("subheading", ""),
            "intro": live.get("intro", ""),
            "primary_label": body.get("primary_defense_label", ""),
            "primary_text": live.get("primary_defense_text", ""),
            "secondary_label": body.get("secondary_defense_label", ""),
            "secondary_text": live.get("secondary_defense_text", ""),
            "points": live.get("defense_points", []),
            "conclusion": live.get("conclusion", ""),
            # What an editor prefills with. Cover letters have real source
            # text, so a lead edits from the built-in rather than a blank box.
            "builtin": {f: body.get(f, "") for f in TemplateRepository.LETTER_FIELDS},
        })

    documents = [{
        "key": key,
        "title": doc.get("title", ""),
        "icon": doc.get("icon", ""),
        "blurb": doc.get("blurb", ""),
        # Shown as a column list so a reader can see what the generated
        # document actually contains before pulling it into a packet.
        "columns": [c.strip() for c in (doc.get("columns") or "").split(",")
                    if c.strip()],
        "policy": bool(doc.get("policy")),
        # Policy text is generated per case, so there is no single source
        # string to prefill. An empty editor means "keep generating it".
        "body": (TEMPLATE_OVERRIDES.get(f"policy:{key}") or {}).get("body", ""),
    } for key, doc in DOCUMENTS.items()]

    return TemplateRepository.catalog(
        TEMPLATE_OVERRIDES, letters, documents,
        TemplateRepository.sop_list(TEMPLATE_OVERRIDES))


@app.route("/client/dashboard")
@role_required("client")
def client_dashboard():
    c = _client_console()
    if c is None:
        # A client login pointing at no book is a misconfiguration, not a
        # permission question. Drop the session rather than render an empty
        # portal that looks like the merchant has no disputes.
        session.clear()
        return redirect(url_for("portal"))
    # The merchant's own view of the connection state their credentials give
    # the platform — the same set-or-not reading the staff pages use, shown to
    # the person who can actually fix a gap.
    return render_template("client_dashboard.html", c=c, dbs=DATABASES,
                           connections=_client_connections(c["client"]))


@app.route("/client/chargebacks")
@role_required("client")
def client_chargebacks():
    c = _client_console()
    if c is None:
        session.clear()
        return redirect(url_for("portal"))
    return render_template("client_chargebacks.html", c=c)


def _client_case_or_404(case_id):
    """The signed-in merchant's own case, or 404.

    404 rather than 403: a client must not be able to learn which case ids exist
    in another brand's book by watching the status change. Every per-case client
    route goes through this one check so the four cannot drift apart.
    """
    client = _current_client()
    case = _find_case(case_id)
    if (not client or not case
            or ClientConsole.client_of(case, TeamConsole._bucket_map(CASES)) != client):
        abort(404)
    return case


def _case_is_filed(case):
    """Whether the packet actually went to the network.

    The one definition the client portal asks about, shared by the buttons on
    the case page and the routes behind them so a hand-typed URL cannot reach
    what the page will not offer.
    """
    return (case.get("submission_status") or "") == "Submitted"


@app.route("/client/case/<case_id>")
@role_required("client")
def client_case(case_id):
    case = _client_case_or_404(case_id)
    return render_template("client_case.html", c=_client_console(), case=case,
                           filed=_case_is_filed(case))


# The merchant-facing wording for a dispute event. `dispute_history` is our
# internal audit trail — it carries staff usernames, uploaded filenames and the
# note a lead wrote when reopening a case — so a client's timeline is built by
# translation and never by passing the raw event through. A real processor
# portal would not carry any of that either.
CLIENT_EVENT_LABELS = {
    "CaseCreated":              "Chargeback received",
    "NotificationOfChargeback": "Chargeback received",
    "OpenDispute":              "Chargeback received",
    "Chargeback":               "Chargeback received",
    "AgentAction: Contested":   "Defence submitted",
    "DefenseSubmitted":         "Defence submitted",
    "AutoDefenseSubmitted":     "Defence submitted",
    "AgentAction: Not Fought":  "Chargeback accepted",
    "DisputeWon":               "Dispute won",
    "DisputeLost":              "Dispute lost",
    "Refunded":                 "Refunded",
}

# Events whose tail is free text we must not repeat back — a staff username, an
# uploaded filename. Matched by prefix, and only the label survives.
CLIENT_EVENT_PREFIXES = (
    ("Submitted by ", "Defence submitted"),
    ("EvidenceUploaded: ", "Evidence attached"),
)


def _client_timeline(case):
    """`dispute_history` in network vocabulary, with everything internal gone.

    An unmapped event is dropped rather than passed through, so a label added to
    the audit trail later cannot reach a merchant's screen by default.
    """
    out = []
    for entry in case.get("dispute_history") or []:
        event = (entry.get("event") or "").strip()
        label = CLIENT_EVENT_LABELS.get(event)
        if not label:
            label = next((mapped for prefix, mapped in CLIENT_EVENT_PREFIXES
                          if event.startswith(prefix)), None)
        if not label:
            continue
        if out and out[-1]["event"] == label:
            # Five uploads are one "evidence attached" as far as the network
            # screen is concerned. Keep the latest date rather than the first.
            out[-1]["date"] = entry.get("date", "")
            continue
        out.append({"event": label, "date": entry.get("date", "")})
    return out


def _client_processor_view(case):
    """What a merchant may see of their own case on the processor's screen.

    Built here rather than handing the template the case dict: a case carries
    `assigned_agent`, `agent_action`, `win_probability`, `rework_released` (a
    lead's name and their private note about what the agent got wrong) and the
    whole sheet row. A template is not an access control.
    """
    timeline = _client_timeline(case)
    return {
        "case_id": case.get("case_id", ""),
        "processor": case.get("processor", ""),
        "outcome": case.get("outcome", ""),
        "scenario": case.get("scenario", ""),
        "reason_code": case.get("reason_code", ""),
        "currency": case.get("currency", "USD"),
        "amount": _safe_float(case.get("amount"), 0.0),
        "amount_authorized": _safe_float(case.get("amount_authorized"), 0.0),
        "amount_settled": _safe_float(case.get("amount_settled"), 0.0),
        "payment_method": case.get("payment_method", ""),
        "dispute_psp_ref": case.get("dispute_psp_ref", ""),
        "payment_psp_ref": case.get("payment_psp_ref", ""),
        "dispute_creation_date": case.get("dispute_creation_date", ""),
        "transaction_date": case.get("transaction_date", ""),
        "auto_defended": bool(case.get("auto_defended")),
        "acquirer_ref": case.get("acquirer_ref", ""),
        "acquirer_code": case.get("acquirer_code", ""),
        "cardholder": case.get("cardholder", ""),
        "card_last_four": case.get("card_last_four", ""),
        "card_expiry": case.get("card_expiry", ""),
        "issuer_country": case.get("issuer_country", ""),
        "issuer_name": case.get("issuer_name", ""),
        "cvv_response": case.get("cvv_response", ""),
        "avs_response": case.get("avs_response", ""),
        "threed_secure": case.get("threed_secure", ""),
        "liability_shift": bool(case.get("liability_shift")),
        "issuer_comments": case.get("issuer_comments", ""),
        "order_id": case.get("order_id", ""),
        "merchant": case.get("merchant", ""),
        "merchant_account": case.get("merchant_account", ""),
        "descriptor_name": case.get("descriptor_name", ""),
        "descriptor_url": case.get("descriptor_url", ""),
        "timeline": timeline,
        "last_event": timeline[-1]["event"] if timeline else "",
        "filed": _case_is_filed(case),
    }


@app.route("/client/case/<case_id>/processor")
@role_required("client")
def client_processor(case_id):
    """One of the merchant's own disputes, as their processor shows it."""
    case = _client_case_or_404(case_id)
    return render_template("client_processor.html", c=_client_console(),
                           p=_client_processor_view(case))


# The letter's nine sections as the counter evidence page words them — which is
# neither the document title nor the upload label. Each carries the mandate line
# and the attachment line that names it, so a packet built from fewer sections
# cannot go on claiming all nine.
PACKET_SECTIONS = [
    {"key": "transaction_copy", "title": "Transaction Copy",
     "block": "intro_transaction_copy",
     "mandate": "Transaction Copy with an AVS code of ({avs}), CVV captured as "
                "({cvv}) & Authorization code {auth}",
     "attachment": "Transaction Copy"},
    {"key": "order_information", "title": "Order Confirmation",
     "block": "intro_order_confirmation",
     "mandate": "Order Confirmation", "attachment": "Order Information"},
    {"key": "invoice_breakup", "title": "Invoice Breakup",
     "block": "intro_invoice_breakup",
     "mandate": "Invoice Breakup", "attachment": "Invoice Breakup"},
    {"key": "refund_information", "title": "Refund Information",
     "block": "intro_refund_information",
     "mandate": "Refund Information", "attachment": "Refund Information"},
    {"key": "account_history",
     "title": "{pm} Cardholder Registration and Order History",
     "block": "intro_account_history",
     "mandate": "{pm} Cardholder Registration and Order History",
     "attachment": "Account History ({pm} Cardholder Registration and Order History)"},
    {"key": "activity_log", "title": "{pm} Cardholder Activity Log",
     "block": "intro_activity_log",
     "mandate": "{pm} Cardholder Activity Log",
     "attachment": "{pm} Cardholder Activity Log"},
    {"key": "checkout_record", "title": "Checkout Page",
     "block": "intro_checkout_record",
     "mandate": "Attachment showing that the Cardholder is aware of Checkout "
                "Terms prior to purchase",
     "attachment": "Checkout Page"},
    {"key": "terms_conditions", "title": "Terms & Conditions",
     "block": "intro_terms_conditions",
     "mandate": "Attachment showing that the Cardholder is aware of Terms & "
                "Conditions prior to purchase",
     "attachment": "Terms and Conditions"},
    {"key": "refund_policy", "title": "Refund Policy",
     "block": "intro_refund_policy",
     "mandate": "Refund Policy in force at the time of purchase",
     "attachment": "Refund Policy"},
]


def _packet_attachment(case_id, upload):
    """One attached file, as the merchant's packet describes it.

    Neither staff URL survives — the delete route obviously, but the download
    route too, since it serves any file for any case id with no ownership check.
    Nor does the mtime: that records when we did the work, not when anything was
    filed, and can post-date the filing date the merchant was given.
    """
    return {
        "name": upload["filename"],
        "kind": ("image" if os.path.splitext(upload["filename"])[1].lower()
                 in INLINE_UPLOAD_EXT else "file"),
        "size_kb": upload["size_kb"],
        "url": url_for("client_packet_file", case_id=case_id,
                       filename=upload["stored"]),
        "path": os.path.join(_case_upload_dir(case_id) or "", upload["stored"]),
    }


def _client_packet(case):
    """The representment packet as the merchant may read it.

    A projection, not a filtered render. Everything staff-authored about *how*
    the packet was assembled is dropped here rather than left out of the
    template: who rewrote a block and whether it was written for this case or is
    the category boilerplate, which of our databases a document came from, our
    own odds of winning and the recommendation that goes with them, the service
    tier's wording, and the internal label we file this merchant's book under.
    """
    p = _packet_doc(case)
    documents, by_slug, blocks = p["documents"], p["by_slug"], p["blocks"]
    modes, labels = p["section_modes"], p["section_labels"]
    case_id = case["case_id"]
    pm = case.get("payment_method") or "Card"

    # One file belongs to the packet once. A letter section and an evidence rule
    # item can slugify to the same string — "Refund Information" and "Refund
    # information" do — and in a PDF that means embedding the same photo twice.
    seen = set()

    def _files(label):
        out = []
        for up in by_slug.get(_slug(label), []):
            if up["stored"] in seen:
                continue
            seen.add(up["stored"])
            out.append(_packet_attachment(case_id, up))
        return out

    tokens = {"pm": pm,
              "avs": (case.get("avs_response") or "N/A")[:3],
              "cvv": (case.get("cvv_response") or "N/A")[:3],
              "auth": case.get("auth_code") or "N/A"}

    sections, mandate, attachment_names = [], [], []
    for spec in PACKET_SECTIONS:
        key = spec["key"]
        doc = documents[key]
        built = modes[key] == "system" and doc["available"] and bool(doc["sections"])
        files = _files(labels[key])
        # Only what was attached: a section nobody filled is left out rather than
        # printed as a gap.
        if not built and not files:
            continue
        sections.append({
            "title": spec["title"].format(**tokens),
            "intro": blocks[spec["block"]]["text"],
            "document": {"title": doc["title"], "blurb": doc["blurb"],
                         "policy": doc["policy"], "sections": doc["sections"]}
            if built else None,
            "attachments": files,
        })
        mandate.append(spec["mandate"].format(**tokens))
        attachment_names.append(spec["attachment"].format(**tokens))

    amount = _safe_float(case.get("amount"), 0.0)
    return {
        "case_id": case_id,
        "document_title": f"Counter Evidence - {case_id}",
        "subtitle": " | ".join(x for x in [
            case.get("reason_description") or case.get("scenario"),
            f"{case.get('currency', 'USD')} {amount:,.2f}"] if x),
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        "header": [
            ("Merchant Number", case.get("acquirer_code")
             or case.get("merchant_account") or "N/A"),
            ("DBA Name", case.get("merchant") or "Merchant"),
            ("Order ID", case.get("order_id") or "N/A"),
            ("Case / ARN", case.get("acquirer_ref") or "N/A"),
            ("Transaction ID", case.get("payment_psp_ref")
             or case.get("dispute_psp_ref") or "N/A"),
            ("Reason Code", case.get("reason_code") or "N/A"),
            (f"{pm} Amount", f"{amount:,.2f} {case.get('currency', 'USD')}"),
            ("Response Date", case.get("dispute_creation_date") or "N/A"),
        ],
        "payment_method": pm,
        "letter_body": blocks["letter_body"]["text"],
        "mandate": mandate,
        "sections": sections,
        "attachment_names": attachment_names,
        # Name and rank only. The source database, the fetched-or-uploaded call
        # and the winning ratio built on them all stay ours.
        "evidence_primary": [i["name"] for i in p["scored"]
                             if i["critical"] and i["available"]],
        "evidence_secondary": [i["name"] for i in p["scored"]
                               if not i["critical"] and i["available"]],
        # Anything not claimed by a section above — files uploaded against an
        # evidence rule item, and any that were orphaned by a relabelling.
        "other_attachments": [_packet_attachment(case_id, u) for u in p["uploads"]
                              if u["stored"] not in seen],
        "conclusion": blocks["conclusion"]["text"],
    }


@app.route("/client/case/<case_id>/letter")
@role_required("client")
def client_letter(case_id):
    """The representment packet filed on this merchant's behalf.

    404 on a case we have not filed rather than showing a draft: the button for
    those is greyed out, and a page reached by typing the URL should not
    contradict what the page offers.
    """
    case = _client_case_or_404(case_id)
    if not _case_is_filed(case):
        abort(404)
    return render_template(
        "client_packet.html", packet=_client_packet(case),
        back_url=url_for("client_case", case_id=case_id),
        pdf_url=url_for("client_letter_pdf", case_id=case_id))


@app.route("/client/case/<case_id>/packet/<filename>")
@role_required("client")
def client_packet_file(case_id, filename):
    """One attachment from the merchant's own packet.

    Scoped before anything else. counter_upload_download would serve these too,
    but it takes any case id and does no ownership check at all — which is why
    it is not on the client allow-list and this exists beside it instead.
    """
    case = _client_case_or_404(case_id)
    if not _case_is_filed(case):
        abort(404)
    folder = _case_upload_dir(case_id)
    if not folder or not os.path.isdir(folder):
        abort(404)
    inline = os.path.splitext(filename)[1].lower() in INLINE_UPLOAD_EXT
    return send_from_directory(folder, filename, as_attachment=not inline)


@app.route("/client/case/<case_id>/letter.pdf")
@role_required("client")
def client_letter_pdf(case_id):
    """The same packet as a file, from the same projection the page renders."""
    case = _client_case_or_404(case_id)
    if not _case_is_filed(case):
        abort(404)
    pdf = render_packet_pdf(_client_packet(case), case)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", case_id)[:64]
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"{safe}-Evidence-Packet.pdf")


def _credential_scope():
    """(client label, their MID records) for the signed-in merchant, or None.

    Every credential route goes through this. A merchant addresses their own
    records by index into their own list, so there is no id another client could
    guess or type — the scoping is structural rather than a check that could be
    forgotten on one route.
    """
    client = _current_client()
    if not client:
        return None, None
    return client, _client_mids(client)


@app.route("/client/credentials")
@role_required("client")
def client_credentials():
    """The third-party logins a merchant keeps with us.

    Secrets are encrypted at rest and are never rendered — `_mid_for_display`
    replaces each with a set/not-set flag, so nothing on this page's source
    carries a password or an API key.
    """
    c = _client_console()
    client, mids = _credential_scope()
    if c is None or client is None:
        session.clear()
        return redirect(url_for("portal"))

    try:
        index = max(0, min(int(request.args.get("mid", 0)), len(mids) - 1))
    except (TypeError, ValueError):
        index = 0

    return render_template(
        "client_credentials.html", c=c,
        panels=CREDENTIAL_PANELS, secrets=sorted(CREDENTIAL_SECRETS),
        categories=CATEGORY_ORDER, providers=PROVIDERS, schemas=SCHEMAS,
        generic_schema=GENERIC_SCHEMA, pending_notes=PENDING_NOTES,
        mids=[{"index": i, "label": m.get("mid_no") or f"MID {i + 1}"}
              for i, m in enumerate(mids)],
        index=index, record=_mid_for_display(mids[index]),
        key_is_managed=_credential_key_is_managed(),
        max_mids=MAX_CREDENTIAL_MIDS)


@app.route("/client/credentials/save", methods=["POST"])
@role_required("client")
def client_credentials_save():
    """Write one MID record.

    A secret field submitted blank means "leave it alone", not "clear it" — the
    page never shows what is stored, so a blank box is the normal state of an
    already-set secret rather than an instruction to wipe it. Clearing is an
    explicit act, via the `clear` list.
    """
    client, mids = _credential_scope()
    if client is None:
        return jsonify({"ok": False, "error": "No client book."}), 403

    payload = request.get_json(silent=True) or {}
    try:
        index = int(payload.get("index", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad MID."}), 400
    if not 0 <= index < len(mids):
        return jsonify({"ok": False, "error": "Unknown MID."}), 404

    record = mids[index]
    record["mid_no"] = str(payload.get("mid_no", record.get("mid_no", "")))[:60].strip()

    clear = set(payload.get("clear") or [])
    submitted = payload.get("panels")
    if not isinstance(submitted, dict):
        return jsonify({"ok": False, "error": "Nothing to save."}), 400

    for panel, values in submitted.items():
        if panel not in CREDENTIAL_PANELS or not isinstance(values, dict):
            continue
        spec = CREDENTIAL_PANELS[panel]
        allowed = set(spec["fields"]) | panel_allowed_fields(panel)
        if spec["choose"]:
            allowed.add(spec["choose"][0])
        stored = record["panels"].setdefault(panel, {})
        # Which fields are secrets depends on the provider this panel is being
        # saved as — FedEx's apiKey is a plain client key, DHL's apiKey IS the
        # secret — so the submitted adapter's own schema decides, with the
        # legacy password/api_key names secret under every provider.
        adapter = str(values.get("adapter") or stored.get("adapter") or "").strip()
        secret_names = secret_fields_for(adapter) | CREDENTIAL_SECRETS
        for field, value in values.items():
            if field not in allowed or not isinstance(value, str):
                continue
            if field in secret_names:
                if f"{panel}.{field}" in clear:
                    stored.pop(field, None)
                elif value:
                    stored[field] = _encrypt_secret(value)
            else:
                stored[field] = value[:400].strip()

    record["updated_at"] = datetime.now().strftime("%b %d, %Y, %H:%M:%S")
    _save_credentials()
    return jsonify({"ok": True, "index": index,
                    "record": _mid_for_display(record)})


@app.route("/client/credentials/mid", methods=["POST"])
@role_required("client")
def client_credentials_mid():
    """Add or delete a MID record."""
    client, mids = _credential_scope()
    if client is None:
        return jsonify({"ok": False, "error": "No client book."}), 403

    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()

    if action == "add":
        if len(mids) >= MAX_CREDENTIAL_MIDS:
            return jsonify({"ok": False,
                            "error": f"That is the {MAX_CREDENTIAL_MIDS} MID limit."}), 400
        mids.append(_blank_mid(str(payload.get("mid_no", ""))[:60].strip()))
        _save_credentials()
        return jsonify({"ok": True, "index": len(mids) - 1})

    if action == "delete":
        try:
            index = int(payload.get("index", -1))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Bad MID."}), 400
        if not 0 <= index < len(mids):
            return jsonify({"ok": False, "error": "Unknown MID."}), 404
        mids.pop(index)
        # Never leave a merchant with no record at all — the page needs one to
        # render, and an empty one reads the same as a fresh account.
        if not mids:
            mids.append(_blank_mid())
        _save_credentials()
        return jsonify({"ok": True, "index": max(0, index - 1)})

    return jsonify({"ok": False, "error": f"Unknown action '{action}'."}), 400


@app.route("/client/credentials/reveal", methods=["POST"])
@role_required("client")
def client_credentials_reveal():
    """Hand one secret back to the merchant who stored it.

    The only path that decrypts. It is scoped to the caller's own records, one
    field per request, and is never used while rendering the page — so a stored
    secret leaves the server only when its owner asks for that exact field.
    """
    client, mids = _credential_scope()
    if client is None:
        return jsonify({"ok": False, "error": "No client book."}), 403

    payload = request.get_json(silent=True) or {}
    panel = (payload.get("panel") or "").strip()
    field = (payload.get("field") or "").strip()
    try:
        index = int(payload.get("index", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad MID."}), 400

    if not 0 <= index < len(mids):
        return jsonify({"ok": False, "error": "Unknown MID."}), 404
    if panel not in CREDENTIAL_PANELS:
        return jsonify({"ok": False, "error": "Unknown field."}), 404
    stored = mids[index]["panels"].get(panel, {})
    # A field is revealable only if it is a secret under this record's own
    # provider schema (or a legacy secret name) — asking for a plain field,
    # or for another provider's secret name, is refused rather than decrypted.
    adapter = str(stored.get("adapter") or "").strip()
    if field not in (CREDENTIAL_SECRETS | secret_fields_for(adapter)):
        return jsonify({"ok": False, "error": "Unknown field."}), 404

    token = stored.get(field, "")
    if not token:
        return jsonify({"ok": False, "error": "Nothing stored."}), 404

    value = _decrypt_secret(token)
    if not value:
        return jsonify({"ok": False,
                        "error": "Stored under a different key — re-enter it."}), 409
    return jsonify({"ok": True, "value": value})


@app.route("/client/settings")
@role_required("client")
def client_settings():
    """A merchant's own account preferences.

    Same store and same routes as the staff pages — the client logins are in
    STRAIVE_USERS, so they already carry USER_PROFILES records. The theme card
    is left off: the portal is merchant-facing branding rather than a staff
    preference, and offering a picker that changed nothing would be worse than
    not offering one.
    """
    c = _client_console()
    if c is None:
        session.clear()
        return redirect(url_for("portal"))
    return render_template("client_settings.html", c=c, **_settings_context())


@app.route("/client/repository")
@role_required("client")
def client_repository():
    """The templates behind a merchant's rebuttals, read-only.

    Deliberately not the staff repository page. That one carries the SOPs, which
    are procedure written for our own analysts, and stamps every edited template
    with the team lead who changed it — neither belongs in front of a customer.
    Only the cover letters and the evidence documents are passed through, with
    the edit provenance dropped.
    """
    c = _client_console()
    if c is None:
        session.clear()
        return redirect(url_for("portal"))
    lib = _repository_library()
    public = {
        "cover_letters": [{k: v for k, v in item.items()
                           if k not in ("edited", "edited_by", "edited_at", "builtin")}
                          for item in lib["cover_letters"]],
        "documents": [{k: v for k, v in item.items()
                       if k not in ("edited", "edited_by", "edited_at", "body")}
                      for item in lib["documents"]],
    }
    return render_template("client_repository.html", c=c, lib=public)


@app.route("/agent/repository")
@role_required("agent", "manager")
def agent_repository():
    # editable is never passed here. The shared partials default it to false,
    # so an agent's page renders no edit control and no save script at all.
    return render_template("agent_repository.html", a=_agent_console(),
                           lib=_repository_library())


@app.route("/agent/settings")
@role_required("agent", "manager")
def agent_settings():
    return render_template("agent_settings.html", a=_agent_console(),
                           **_settings_context())


# ─── Account settings, shared by all three staff consoles ─────────────────────
MIN_PASSWORD_LENGTH = 8


def _settings_context():
    """Profile, theme and password-age facts for whichever settings page renders."""
    user = session.get("user", "")
    rec = USER_PROFILES.get(user) or _seed_user_profile(user or "user")
    age = _password_age_days(user)
    return {
        "profile": rec,
        "themes": UI_THEMES,
        "pw_age": age,
        "pw_max_age": PASSWORD_MAX_AGE_DAYS,
        "pw_days_left": None if age is None else PASSWORD_MAX_AGE_DAYS - age,
        "pw_is_custom": bool(rec.get("pw_hash")),
        "min_password": MIN_PASSWORD_LENGTH,
    }


def _change_password(user, current, new, confirm):
    """Validate and apply a password change. Returns (ok, message, status)."""
    if not user or user not in STRAIVE_USERS:
        return False, "No signed-in user.", 403
    # _check_password rather than _authenticate, so the shared demo password
    # counts. Anyone who signed in through the dropdown holds nothing else, and
    # without this the forced-change wall would be unpassable for them — they
    # could not answer the question, and nothing but /logout opens while it is
    # up. It grants nothing: they already used this password to get in.
    if not _check_password(user, current or ""):
        return False, "That is not your current password.", 403
    if len(new or "") < MIN_PASSWORD_LENGTH:
        return False, f"Use at least {MIN_PASSWORD_LENGTH} characters.", 400
    if new != confirm:
        return False, "The two new passwords do not match.", 400
    # Same helper here, so the demo password cannot be chosen as a *new* one.
    # It is printed on the sign-in card; setting it would be choosing a password
    # that is already public.
    if _check_password(user, new):
        return False, "That is already your password.", 400

    salt = secrets.token_hex(16)
    USER_PROFILES[user]["pw_salt"] = salt
    USER_PROFILES[user]["pw_hash"] = _hash_password(new, salt)
    USER_PROFILES[user]["pw_changed_at"] = datetime.now().strftime("%Y-%m-%d")
    _save_user_profiles()
    return True, "Password changed.", 200


@app.route("/settings/password", methods=["POST"])
def settings_password():
    """Change the signed-in user's password.

    Exempt from the expiry gate so an expired user can actually use it — see
    PASSWORD_EXEMPT_ENDPOINTS. It still requires the current password, so the
    exemption grants nothing to someone who has not already signed in.
    """
    payload = request.get_json(silent=True) or request.form
    ok, message, status = _change_password(
        session.get("user", ""), payload.get("current"),
        payload.get("new"), payload.get("confirm"))
    return jsonify({"ok": ok, "error": None if ok else message,
                    "message": message}), status


@app.route("/settings/theme", methods=["POST"])
def settings_theme():
    """Set the signed-in user's colour theme."""
    user = session.get("user", "")
    if user not in USER_PROFILES:
        return jsonify({"ok": False, "error": "No signed-in user."}), 403
    payload = request.get_json(silent=True) or request.form
    theme = (payload.get("theme") or "").strip()
    if theme not in UI_THEMES:
        return jsonify({"ok": False, "error": f"Unknown theme '{theme}'"}), 400
    USER_PROFILES[user]["theme"] = theme
    _save_user_profiles()
    return jsonify({"ok": True, "theme": theme,
                    "label": UI_THEMES[theme]["label"]})


@app.route("/settings/profile", methods=["POST"])
def settings_profile():
    """Update the signed-in user's display name and email."""
    user = session.get("user", "")
    if user not in USER_PROFILES:
        return jsonify({"ok": False, "error": "No signed-in user."}), 403
    payload = request.get_json(silent=True) or request.form

    name = (payload.get("display_name") or "").strip()
    email = (payload.get("email") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "A display name is required."}), 400
    if len(name) > 60:
        return jsonify({"ok": False, "error": "Keep the display name under 60 characters."}), 400
    # Deliberately loose: this is a label on a demo profile, not a contact
    # channel, and rejecting a valid-but-unusual address would be worse than
    # accepting a malformed one. An empty value clears the field.
    if email and ("@" not in email or len(email) > 120):
        return jsonify({"ok": False, "error": "That does not look like an email address."}), 400

    USER_PROFILES[user]["display_name"] = name
    USER_PROFILES[user]["email"] = email
    _save_user_profiles()
    return jsonify({"ok": True, "display_name": name, "email": email})


@app.route("/settings/password/expired", methods=["GET", "POST"])
def password_expired():
    """The wall an expired password hits, and the form that clears it."""
    user = session.get("user", "")
    if not user:
        return redirect(url_for("portal"))
    # Reaching this page with a healthy password means the user typed the URL;
    # send them home rather than showing a warning that does not apply.
    if not _password_expired(user):
        return redirect(_role_home_url())

    error = ""
    if request.method == "POST":
        ok, message, _ = _change_password(
            user, request.form.get("current"), request.form.get("new"),
            request.form.get("confirm"))
        if ok:
            return redirect(_role_home_url())
        error = message
    return render_template("password_expired.html", error=error,
                           age=_password_age_days(user),
                           max_age=PASSWORD_MAX_AGE_DAYS,
                           min_password=MIN_PASSWORD_LENGTH), (400 if error else 200)


def _team_console():
    """Scoped to the signed-in lead's own agents and client books.

    A manager opening these pages is inspecting the whole operation, so they
    are not narrowed to one lead's roster.
    """
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    user = session.get("user", "")
    if session.get("role") == "manager":
        my_agents, my_clients = None, list(CLIENT_ROUTING)
    else:
        my_agents = LEAD_AGENTS.get(user, [])
        my_clients = [b for b, owner in CLIENT_ROUTING.items() if owner == user]
    return TeamConsole.for_lead(CASES, ml_stats, EVIDENCE_RESULTS,
                                my_agents=my_agents, my_clients=my_clients)


@app.route("/admin/dashboard")
@role_required("admin", "manager")
def admin_dashboard():
    # ml carries the auto / human-in-the-loop split the KPI row leads with.
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    t = _team_console()
    # Scoped the way TeamConsole scopes the rest of the page: an agent on this
    # lead's roster, or nobody yet -- allocating the unassigned is the lead's
    # job, so they have to be able to see them.
    roster = set(t["roster"])
    team = [c for c in ml_stats["classified_cases"]
            if not c.get("assigned_agent") or c["assigned_agent"] in roster]
    return render_template("admin_dashboard.html", t=t, ml=ml_stats,
                           rep=ManagerCharts.representment(team),
                           dataset=StateStore.active_dataset())


@app.route("/admin/allocation")
@role_required("admin", "manager")
def admin_allocation():
    return render_template("admin_allocation.html", t=_team_console(),
                           agents=AgentDesk.AGENTS)


@app.route("/admin/approvals")
@role_required("admin", "manager")
def admin_approvals():
    return render_template("admin_approvals.html", t=_team_console())


@app.route("/admin/settings")
@role_required("admin", "manager")
def admin_settings():
    return render_template("admin_settings.html", t=_team_console(),
                           **_settings_context())


@app.route("/admin/repository")
@role_required("admin", "manager")
def admin_repository():
    return render_template("admin_repository.html", t=_team_console(),
                           lib=_repository_library(), editable=True)


@app.route("/admin/allocate", methods=["POST"])
@role_required("admin", "manager")
def admin_allocate():
    """Re-assign one or more cases to an agent, or return them to the pool.

    An empty `agent` means unassign. That is a real destination now rather than
    a bad request: cases arrive unowned from an ingest, and a lead who has
    allocated one to the wrong person needs a way back.
    """
    payload = request.get_json(silent=True) or request.form
    agent = (payload.get("agent") or "").strip()
    ids = payload.get("case_ids") or []
    if isinstance(ids, str):
        ids = [ids]
    if agent and agent not in AgentDesk.AGENTS:
        return jsonify({"ok": False, "error": f"Unknown agent '{agent}'"}), 400

    moved = []
    for case_id in ids:
        case = _find_case((case_id or "").strip())
        if case is None:
            continue
        case["assigned_agent"] = agent
        # A person decided this now, whichever way it went -- the ingest stamp
        # would otherwise claim the system chose an owner it did not.
        case.pop("auto_assigned", None)
        moved.append(case["case_id"])
    if not moved:
        return jsonify({"ok": False, "error": "No matching cases."}), 404

    _save_allocations()
    return jsonify({"ok": True, "agent": agent, "moved": moved,
                    "count": len(moved)})


@app.route("/admin/rework", methods=["POST"])
@role_required("admin", "manager")
def admin_rework():
    """Release a submitted case for rework, or take the release back.

    Granting requires a note. The agent cannot see what the lead spotted, and
    "reopened" on its own tells them nothing — they would be back to guessing
    which of ten documents was the missing one. Revoking needs no note: taking
    access away mid-rework is usually a mistake being undone.
    """
    payload = request.get_json(silent=True) or request.form
    case_id = (payload.get("case_id") or "").strip()
    grant = str(payload.get("grant", "true")).lower() not in ("false", "0", "no")
    note = (payload.get("note") or "").strip()[:400]

    case = _find_case(case_id)
    if case is None:
        return jsonify({"ok": False, "error": f"Unknown case '{case_id}'"}), 404
    if grant and not note:
        return jsonify({"ok": False,
                        "error": "Say what needs reworking — the agent sees this."}), 400

    if grant:
        at = datetime.now().strftime("%b %d, %Y, %H:%M:%S")
        case["rework_released"] = {"released_by": session.get("user", ""),
                                   "at": at, "note": note}
        # In the history as well as on the release: the release is consumed when
        # the agent resubmits, and the reason should outlive it.
        case.setdefault("dispute_history", []).append(
            {"event": f"ReworkReleased by {session.get('user', '')}: {note}",
             "date": at})
    else:
        case.pop("rework_released", None)

    _save_rework_releases()
    return jsonify({"ok": True, "case_id": case_id, "released": grant,
                    "released_by": (case.get("rework_released") or {}).get("released_by", ""),
                    "note": (case.get("rework_released") or {}).get("note", ""),
                    "at": (case.get("rework_released") or {}).get("at", "")})


@app.route("/case/<case_id>/decision", methods=["POST"])
@role_required("admin", "manager")
def record_issuer_decision(case_id):
    """Record the ruling the card network sent back on a case.

    This is data entry of an external fact, not a decision the platform makes.
    Nothing here reads the confidence score: the moment the tool picks the
    outcome, the win rate stops measuring performance and starts measuring our
    own optimism. A lead reads the issuer's response and types what it says.

    Lead-or-manager only, matching /admin/rework — `admin` is the team lead
    role. Deliberately its own route rather than an AGENT_ACTION_EFFECTS key,
    because /agent-desk/action carries no role gate and would hand every agent
    the power to declare their own cases won.

    `clear` puts a case back to pending so a demo can be run twice.
    """
    payload = request.get_json(silent=True) or request.form
    decision = (payload.get("decision") or "").strip()
    ruling_date = (payload.get("ruling_date") or "").strip()
    reference = (payload.get("reference") or "").strip()[:120]

    case = _find_case(case_id)
    if case is None:
        return jsonify({"ok": False, "error": f"Unknown case '{case_id}'"}), 404

    at = datetime.now().strftime("%b %d, %Y, %H:%M:%S")

    if decision == "clear":
        case.pop("issuer_decision", None)
        case["case_status"] = "Decision Pending"
        case["outcome"] = "Pending"
        case["outcome_date"] = ""
        case.setdefault("dispute_history", []).append(
            {"event": f"DecisionCleared by {session.get('user', '')}", "date": at})
    elif decision in ISSUER_DECISIONS:
        # A ruling carries a date. Rejected rather than defaulted to today: the
        # date the issuer decided is not the date somebody got round to typing
        # it in, and the difference is what an SLA is measured against.
        try:
            datetime.strptime(ruling_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False,
                            "error": "Give the ruling date as YYYY-MM-DD."}), 400
        case["case_status"] = decision
        case["outcome"] = OUTCOME_BY_STATUS[decision]
        case["outcome_date"] = ruling_date
        case["issuer_decision"] = {"decision": decision, "ruling_date": ruling_date,
                                   "recorded_by": session.get("user", ""),
                                   "at": at, "reference": reference}
        # "DisputeWon"/"DisputeLost" are already in CLIENT_EVENT_LABELS and had
        # no writer until now, so the merchant's timeline picks this up as-is.
        case.setdefault("dispute_history", []).append(
            {"event": f"Dispute{decision}", "date": at})
    else:
        return jsonify({"ok": False,
                        "error": f"Unknown decision '{decision}'."}), 400

    _save_case_state()
    return jsonify({"ok": True, "case_id": case_id,
                    "case_status": case["case_status"],
                    "outcome": case["outcome"],
                    "outcome_date": case.get("outcome_date", ""),
                    "issuer_decision": case.get("issuer_decision") or {}})


@app.route("/admin/repository/template", methods=["POST"])
@role_required("admin", "manager")
def admin_repository_template():
    """Save a team lead's edit to a repository template, or revert it.

    Reverting is a delete, not a restore: the built-in text was never copied
    into the store, so removing the entry is exactly what puts it back. An edit
    that submits every field blank is treated as a revert for that reason.
    """
    payload = request.get_json(silent=True) or request.form
    kind = (payload.get("kind") or "").strip()
    key = (payload.get("key") or "").strip()

    if kind not in TemplateRepository.KINDS:
        return jsonify({"ok": False, "error": f"Unknown template kind '{kind}'"}), 400
    if not TemplateRepository.valid_key(kind, key):
        return jsonify({"ok": False, "error": f"Unknown template '{key}'"}), 404

    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return jsonify({"ok": False, "error": "No fields supplied."}), 400

    # Keep only what this kind actually renders, so a crafted payload cannot
    # park arbitrary keys in the store.
    allowed = (TemplateRepository.LETTER_FIELDS if kind == "cover_letter"
               else ("body",) if kind == "policy" else ("title", "body"))
    cleaned = {}
    for field, value in fields.items():
        if field not in allowed:
            continue
        if field == "defense_points":
            if isinstance(value, list):
                points = [str(p).strip() for p in value if str(p).strip()]
                if points:
                    cleaned[field] = points
        elif isinstance(value, str) and value.strip():
            cleaned[field] = value.strip()

    store_key = TemplateRepository.store_key(kind, key)
    if not cleaned:
        reverted = TEMPLATE_OVERRIDES.pop(store_key, None) is not None
        _save_template_overrides()
        return jsonify({"ok": True, "kind": kind, "key": key,
                        "edited": False, "reverted": reverted})

    cleaned["edited_by"] = session.get("user", "")
    cleaned["edited_at"] = datetime.now().strftime("%b %d, %Y, %H:%M:%S")
    TEMPLATE_OVERRIDES[store_key] = cleaned
    _save_template_overrides()
    return jsonify({"ok": True, "kind": kind, "key": key, "edited": True,
                    "edited_by": cleaned["edited_by"], "edited_at": cleaned["edited_at"]})


@app.route("/admin/repository/sop", methods=["POST"])
@role_required("admin", "manager")
def admin_repository_sop():
    """Create or delete a standard operating procedure.

    A seeded SOP cannot be removed from the code, so deleting one stores a
    tombstone instead. That keeps delete reversible and keeps the seeds where
    they belong — in the module, not copied into the store.
    """
    payload = request.get_json(silent=True) or request.form
    key = re.sub(r"[^a-z0-9-]", "", (payload.get("key") or "")
                 .strip().lower().replace(" ", "-"))[:64]
    if not key:
        return jsonify({"ok": False, "error": "A procedure needs a name."}), 400

    store_key = TemplateRepository.store_key("sop", key)
    if str(payload.get("delete", "")).lower() in ("true", "1", "yes"):
        if key in TemplateRepository.SEED_SOPS:
            TEMPLATE_OVERRIDES[store_key] = {"deleted": True,
                                             "edited_by": session.get("user", "")}
        else:
            TEMPLATE_OVERRIDES.pop(store_key, None)
        _save_template_overrides()
        return jsonify({"ok": True, "key": key, "deleted": True})

    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        return jsonify({"ok": False, "error": "A procedure needs a title and body."}), 400

    TEMPLATE_OVERRIDES[store_key] = {
        "title": title, "body": body,
        "edited_by": session.get("user", ""),
        "edited_at": datetime.now().strftime("%b %d, %Y, %H:%M:%S")}
    _save_template_overrides()
    return jsonify({"ok": True, "key": key, "deleted": False})


def _find_case(case_id):
    return next((c for c in CASES if c["case_id"] == case_id), None)


@app.route("/agent-desk/action", methods=["POST"])
def agent_desk_action():
    """Record an agent's decision on a case.

    The decision rewrites the case's reporting status, so Manager Hub and the
    dashboard reflect it immediately, and is written to disk so it survives a
    restart.
    """
    payload = request.get_json(silent=True) or request.form
    case_id = (payload.get("case_id") or "").strip()
    action = (payload.get("action") or "").strip()

    case = _find_case(case_id)
    if case is None:
        return jsonify({"ok": False, "error": f"Unknown case '{case_id}'"}), 404
    if action not in AGENT_ACTION_EFFECTS:
        return jsonify({"ok": False, "error": f"Unknown action '{action}'"}), 400

    blocked = _case_write_block(case)
    if blocked:
        return jsonify({"ok": False, "error": blocked}), 403

    at = _record_agent_action(case, action)
    return jsonify({"ok": True, "case_id": case_id, "action": action, "at": at,
                    "case_status": case["case_status"],
                    "outcome": case["outcome"],
                    "submission_status": case["submission_status"]})


@app.route("/agent-desk/evidence", methods=["POST"])
@role_required("agent", "admin", "manager")
def agent_desk_evidence():
    """Attach a manually uploaded evidence file to a case.

    Records the file's name, size and timestamp only — the bytes are not
    written to disk. This is a demo; persisting arbitrary uploads into the
    project folder would add risk without adding capability.
    """
    case_id = (request.form.get("case_id") or "").strip()
    upload = request.files.get("evidence_file")

    case = _find_case(case_id)
    if case is None:
        return jsonify({"ok": False, "error": f"Unknown case '{case_id}'"}), 404
    # This route carried no role, owner or lock check at all — the page it
    # serves is a lead's, but the route was open to anyone signed in.
    blocked = _case_write_block(case)
    if blocked:
        return jsonify({"ok": False, "error": blocked}), 403
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "No file supplied"}), 400

    size = len(upload.read())
    attachment = {
        "filename": upload.filename,
        "size_kb": round(size / 1024, 1),
        "uploaded_by": request.form.get("agent", "Agent"),
        "uploaded_at": datetime.now().strftime("%b %d, %Y, %H:%M:%S"),
    }
    case.setdefault("manual_evidence", []).append(attachment)
    case.setdefault("dispute_history", []).append(
        {"event": f"EvidenceUploaded: {upload.filename}", "date": attachment["uploaded_at"]})
    # This route keeps the metadata only — the bytes are read for their length
    # and dropped — so without this the attachment existed nowhere at all.
    _save_case_state()

    return jsonify({"ok": True, "attachment": attachment,
                    "total": len(case["manual_evidence"])})


@app.route("/qa-review")
@role_required("manager")
def qa_review():
    ml_stats = AIValidationEngine.get_pipeline_stats(CASES)
    qa = QAReviewEngine.compute(CASES, ml_stats, EVIDENCE_RESULTS, REASON_CODES)
    return render_template("qa_review.html", qa=qa)


def _order_view(case):
    """The order, delivery and customer view of a case.

    Joined from the dispute sheet first and the legacy orders file second,
    because the two files use incompatible order-id formats. Shared by every
    page that renders the DB-source cards — the case page and the review
    packet — so the two cannot drift into disagreeing about the same order.
    """
    # The dispute sheet first, the orders file only as a fallback.
    #
    # This used to read the orders file alone, joining on order_id — but the
    # dispute sheet writes ORD-202605-100003 and orders_1000.csv uses
    # TTS-ORD-20260601-1UF09, so the join matched 0 of 100 cases and every field
    # below fell through to its literal "N/A". Thirteen of them on every page,
    # across four sections, none of it actually missing: the whole sheet row is
    # already on the case as `source`.
    #
    # The orders lookup stays because the older chargebacks_12.csv shape does
    # join, and _rebuttal_doc reads the same file.
    orders = ChargebackCaseLoader.load_orders()
    orders_by_id = {o["order_id"]: o for o in orders}
    raw = orders_by_id.get(case.get("order_id", ""), {})
    src = case.get("source") or {}

    def _sheet(column):
        """A sheet cell, treating its own N/A placeholders as absent.

        Digital-goods rows write "N/A (Digital)" into the delivery columns.
        That is honest in the sheet but reads as broken on screen — the
        customer location rendered "N/A (Digital), N/A (Digital), ID".
        """
        value = (src.get(column) or "").strip()
        return "" if value.upper().startswith("N/A") else value

    def _field(column, legacy_key, default="—"):
        return _sheet(column) or raw.get(legacy_key) or default

    digital = "digital" in (src.get("DeliveryStatus", "") or "").lower()
    location = ", ".join(p for p in (_sheet("DeliveryCity"), _sheet("DeliveryState"),
                                     _sheet("DeliveryCountry")) if p)

    order = {
        "product_name": _field("ProductName", "product_name"),
        "product_id": _field("Sku", "product_id"),
        "product_category": _field("ProductCategory", "product_category"),
        "quantity": _field("Quantity", "quantity", "1"),
        "unit_price": _field("UnitPrice", "unit_price", ""),
        "return_policy_days": raw.get("return_policy_days", "30"),
        "customer_id": _field("UserId", "customer_id"),
        "customer_email": _field("UserEmail", "customer_email"),
        "customer_phone": _field("UserPhone", "customer_phone"),
        # One joined string: the template used to print "city, state" with no
        # regard for either being blank, which on a digital order produced
        # "N/A (Digital), N/A (Digital), ID".
        "customer_location": location or (raw.get("customer_city") or "—"),
        "customer_ip": _field("DeviceIp", "customer_ip"),
        "device_type": _field("DeviceType", "device_type"),
        "fulfillment_status": _field("DeliveryStatus", "fulfillment_status"),
        "shipping_carrier": (_field("ShippingCarrier", "shipping_carrier", "")
                             or ("Digital delivery" if digital else "—")),
        "tracking_number": (_field("TrackingNumber", "tracking_number", "")
                            or ("Not applicable" if digital else "—")),
        # Legitimately blank on the four cases still in transit — say so rather
        # than printing a dash that reads like missing data.
        "delivery_date": (src.get("ActualDeliveryDate") or "").strip()
                         or raw.get("delivery_date")
                         or (src.get("DeliveryStatus") or "").strip() or "—",
        "delivery_signed": _field("DeliverySignedBy", "delivery_signed"),
    }
    return order


@app.route("/case/<case_id>")
def case_detail(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    reason = _get_reason(case)
    ml = AIValidationEngine.classify_one(case)
    order = _order_view(case)
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    return render_template("case_detail.html", case=case, reason=reason, ml=ml, order=order,
                           fetched_at=fetched_at,
                           # The matrix row this dispute type dictates, and the
                           # credential state of the systems that would supply it.
                           checklist=_case_evidence_checklist(case, order),
                           connections=_case_connections(case), dbs=DATABASES,
                           history=CustomerHistory.for_case(case, CASES))


@app.route("/chargeback/<case_id>")
def chargeback_detail(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    ml = AIValidationEngine.classify_one(case)
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Why this user may not accept the case, or None. The Accept button reads it
    # so the refusal is visible before the confirm dialog rather than after it.
    # accept_case re-checks server-side — this only labels the control.
    return render_template("chargeback_detail.html", case=case, ml=ml,
                           fetched_at=fetched_at,
                           write_block=_case_write_block(case),
                           history=CustomerHistory.for_case(case, CASES))


# ─── Counter evidence ──────────────────────────────────────────────────────────
# Manual evidence is written to disk so it can be downloaded back. Everything
# below assumes the filename and case id are hostile input.
UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "static", "uploads")
ALLOWED_UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".eml", ".msg",
                      ".csv", ".txt", ".docx", ".xlsx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _slug(text, fallback="general"):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or fallback


# The letter's fixed sections name their own evidence requirement, so the
# template needs the same slug the upload route stores files under.
app.jinja_env.filters["slug"] = _slug


def _distinct_reason_codes(cases):
    """Sorted [{code, network, label}] over a case list.

    Filters and coverage chips used to build `set(c["reason_code"])`, which
    drops the network — and a code without its network cannot be named, because
    the same string can belong to two schemes.
    """
    seen = {}
    for case in cases or []:
        code = (case.get("reason_code") or "").strip()
        if not code or code in seen:
            continue
        network = case.get("payment_method", "")
        seen[code] = {"code": code, "network": network,
                      "label": _reason_label(code, network)}
    return [seen[k] for k in sorted(seen)]


def _reason_label(code, network=""):
    """A reason code with its published meaning: "4837 — No Cardholder Authorization".

    A bare code is meaningless to anyone who does not work chargebacks daily,
    and it was bare in twenty places. The network matters: codes are only
    unambiguous within their own scheme, and 4860 is Mastercard's credit-not-
    processed while Discover's is RN2.

    Falls back to the bare code — never a dangling em-dash — when the code is
    unknown, so a sheet carrying something the catalog has not got still renders
    cleanly.
    """
    code = (code or "").strip()
    if not code:
        return ""
    description = ReasonCodeInterpreter.describe(code, network)
    return "%s — %s" % (code, description) if description else code


# Registered as a global rather than returned from _inject_nav: it is a pure
# function of its arguments with no session dependence, so there is no reason to
# rebuild it on every render.
app.jinja_env.globals["reason_label"] = _reason_label
# The description on its own, for the few places that already print the code in
# its own column and only need the meaning beside it.
app.jinja_env.globals["reason_description"] = ReasonCodeInterpreter.describe


def _case_upload_dir(case_id, create=False):
    """Folder holding one case's manual uploads.

    The case id comes from the sheet and is used as a directory name, so it is
    reduced to word characters first — a crafted id must not be able to walk out
    of static/uploads.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", case_id or "")[:64]
    if not safe:
        return None
    path = os.path.join(UPLOAD_ROOT, safe)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _list_uploads(case_id):
    """Manual uploads on disk for a case, newest last.

    The requirement each file answers is stored as a filename prefix
    ('<slug>__<name>') — this app has no database, and the alternative is
    losing the association on restart.
    """
    folder = _case_upload_dir(case_id)
    if not folder or not os.path.isdir(folder):
        return []

    uploads = []
    for stored in sorted(os.listdir(folder)):
        full = os.path.join(folder, stored)
        if not os.path.isfile(full):
            continue
        slug, _, original = stored.partition("__")
        info = os.stat(full)
        uploads.append({
            "stored": stored,
            "slug": slug,
            "filename": original or stored,
            "size_kb": round(info.st_size / 1024, 1),
            "uploaded_at": datetime.fromtimestamp(info.st_mtime).strftime("%d %b %Y, %H:%M"),
            "url": url_for("counter_upload_download", case_id=case_id, filename=stored),
            "delete_url": url_for("counter_upload_delete", case_id=case_id, filename=stored),
        })
    return uploads


def _packet_doc(case):
    """The representment packet for one case, without any notion of who is asking.

    Everything the counter evidence page shows as a *document* — the prose, the
    nine sections, the assembled documents and the files attached to them. The
    role-dependent half (can_edit, the lock, the submit bar) stays in the route,
    because it reads the session and the merchant's copy of this packet must not
    be built against a merchant's session.
    """
    case_id = case["case_id"]
    from chargeback.engines.evidence_rules import get_evidence_for_case
    from chargeback.engines.cover_letter import letter_context
    from chargeback.engines.evidence_documents import build_documents

    ev_info = get_evidence_for_case(case)
    documents = build_documents(case, MERCHANT_CONFIG, TEMPLATE_OVERRIDES)

    uploads = _list_uploads(case_id)
    by_slug = defaultdict(list)
    for up in uploads:
        by_slug[up["slug"]].append(up)

    # The client's service tier decides how this packet is built, so it has to
    # be resolved before anything is called available.
    mapping = TeamConsole._bucket_map(CASES)
    client = ClientConsole.client_of(case, mapping)
    tier = ClientConsole.tier_of(case, CLIENT_PROFILES, mapping)
    section_modes, section_labels = ClientConsole.section_plan(tier, documents, case)

    # Split the reason code's rule set: items a generated document satisfies are
    # already in hand, the rest need an agent to upload something. An item counts
    # as available only when the document actually built or a file actually
    # landed — never just because the rule names it.
    #
    # The tier overrides the engine's own system/manual call. On a manual
    # account there are no API keys behind these documents, so an item a
    # document could satisfy still has to be uploaded like any other — claiming
    # it was fetched would be a lie told to the person assembling the packet.
    scored, claimed_slugs = [], set()
    for item in ev_info["evidence"]:
        doc_key = item.get("doc_key")
        if doc_key and section_modes.get(doc_key) == "system":
            source = "system"
            available = documents[doc_key]["available"]
        else:
            source = "manual"
            slug = _slug(item["name"])
            claimed_slugs.add(slug)
            available = bool(by_slug.get(slug))
        scored.append({**item, "source": source, "available": available})

    # The letter's nine sections own their slugs in every mode, not just the
    # modes that render an upload box. A file uploaded before the client moved
    # to a hands-off tier stays attached to its section instead of being
    # orphaned into "other attachments".
    claimed_slugs.update(_slug(label) for label in section_labels.values())
    other_uploads = [u for u in uploads if u["slug"] not in claimed_slugs]

    # Rebuttal prose: per-case text wins, then a template for this reason
    # category, then the default template, then the built-in string.
    blocks = NarrativeBlocks.resolve_all(
        letter_context(case), category=ev_info["rule_key"],
        case_texts=CASE_NARRATIVE.get(case_id), overrides=TEMPLATE_OVERRIDES)

    return {"ev": ev_info, "documents": documents, "blocks": blocks,
            "uploads": uploads, "by_slug": by_slug, "other_uploads": other_uploads,
            "scored": scored, "tier": tier, "client": client,
            "section_modes": section_modes, "section_labels": section_labels}


@app.route("/counter/<case_id>")
# Staff only, said out loud. This relied on counter_evidence being absent from
# CLIENT_ENDPOINTS, which is real but incidental — the page carries upload and
# delete controls and staff-authored prose, so the restriction should not depend
# on an omission somewhere else.
@role_required("agent", "admin", "manager")
def counter_evidence(case_id):
    case = _find_case(case_id)
    if not case:
        return "Case not found", 404
    from chargeback.engines.evidence_rules import calculate_winning_ratio

    packet = _packet_doc(case)
    ev_info, documents, blocks = packet["ev"], packet["documents"], packet["blocks"]
    by_slug, scored, tier = packet["by_slug"], packet["scored"], packet["tier"]

    # Computed here, never in the template: a role test in Jinja is a display
    # rule, and the write routes need the same answer anyway.
    #
    # Two levels, because they are two different powers. Writing the prose for
    # the case in front of you is the job; deciding what every case in the
    # category says is not.
    role = session.get("role")
    can_template = role in ("admin", "manager")
    can_edit = can_template or (
        role == "agent"
        and _case_owner(case) == _current_agent()
        # A submitted case is locked to its agent until a lead releases it —
        # the same rule agent_action enforces. Without this the prose would be
        # a way around the submission lock.
        and ((case.get("submission_status") or "") != "Submitted"
             or bool(case.get("rework_released"))))

    # What the Submit bar reports. Counted from the same `scored` list the
    # checklist renders, so the summary cannot claim readiness the sidebar
    # disagrees with.
    submitted = (case.get("submission_status") or "") == "Submitted"
    release = case.get("rework_released") or {}
    readiness = {
        "met": sum(1 for i in scored if i["available"]),
        "total": len(scored),
        "documents": sum(1 for d in documents.values() if d.get("available")),
        "uploads": sum(len(v) for v in by_slug.values()),
        "submitted": submitted,
        # A lead may submit on an agent's behalf; an agent gets the button only
        # on their own case, and only while it is theirs to change.
        "can_submit": can_edit and not (submitted and not release),
    }
    lock = {
        "locked": submitted and not release,
        "submitted": submitted,
        "released": bool(release),
        "released_by": release.get("released_by", ""),
        "released_at": release.get("at", ""),
        "note": release.get("note", ""),
        # Named so the lock banner can tell a lead who the case is locked *to*.
        # Staff-only: this whole page is, and the merchant's copy is built from
        # _client_packet, which never sees this dict.
        "owner": _case_owner(case),
        # Whether *this* lead can actually reopen it. A lead may write to any
        # case, but Rework Approvals lists only the agents reporting to them, so
        # naming that page to the wrong lead is a dead end — 13 of the 50 locked
        # cases for admin, 37 for admin2. The manager's console covers every team.
        "reopenable_here": (
            role == "manager"
            or (role == "admin"
                and _case_owner(case) in LEAD_AGENTS.get(session.get("user", ""), []))),
    }

    # The letter addresses documents one at a time, so hand the template the
    # slug -> uploads map as well; each manual section pulls just its own files.
    return render_template("counter_evidence.html", case=case, ev=ev_info,
                           blocks=blocks, can_edit=can_edit,
                           can_template=can_template,
                           readiness=readiness, lock=lock,
                           block_scope=ev_info["rule_key"],
                           block_placeholders=NarrativeBlocks.PLACEHOLDERS,
                           documents=documents, uploads_by_slug=by_slug,
                           other_uploads=packet["other_uploads"], evidence_items=scored,
                           ratio=calculate_winning_ratio(scored),
                           tier=tier, client=packet["client"],
                           tier_label=ClientConsole.TIERS[tier]["label"],
                           tier_blurb=ClientConsole.TIERS[tier]["blurb"],
                           section_modes=packet["section_modes"],
                           section_labels=packet["section_labels"],
                           upload_exts=sorted(ALLOWED_UPLOAD_EXT),
                           max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024))


@app.route("/counter/<case_id>/submit", methods=["POST"])
def counter_submit(case_id):
    """File the packet from the page the packet was assembled on.

    The Submit Evidence button used to open a success modal and change nothing —
    an agent could believe they had filed a case that was still sitting in their
    queue. It now records the same "Contested" decision the Agent Page dropdown
    records, through the same helper, so the two paths cannot disagree about
    what submitted means.

    Incomplete evidence warns rather than blocks: a thin packet filed before the
    deadline beats no packet, and the readiness figures are on the page in front
    of whoever presses it.
    """
    case = _find_case(case_id)
    if case is None:
        return jsonify({"ok": False, "error": f"Unknown case '{case_id}'"}), 404

    blocked = _case_write_block(case)
    if blocked:
        return jsonify({"ok": False, "error": blocked}), 403
    # An agent is already stopped by the guard above; this catches a lead
    # pressing Submit twice on a case that is filed and not released.
    if (case.get("submission_status") or "") == "Submitted" and not case.get("rework_released"):
        return jsonify({"ok": False, "error": "This case is already submitted."}), 409

    at = _record_agent_action(case, "Contested",
                              event=f"Submitted by {session.get('user', '')}")
    return jsonify({"ok": True, "case_id": case_id, "at": at,
                    "case_status": case["case_status"],
                    "submission_status": case["submission_status"]})


def _narrative_payload(case_id):
    """Shared validation for both narrative writes: (case, block, text, error)."""
    case = _find_case(case_id)
    if case is None:
        return None, None, None, (jsonify({"ok": False,
                                           "error": f"Unknown case '{case_id}'"}), 404)
    payload = request.get_json(silent=True) or request.form
    block = (payload.get("block") or "").strip()
    if not NarrativeBlocks.valid_block(block):
        return None, None, None, (jsonify({"ok": False,
                                           "error": f"Unknown block '{block}'"}), 400)
    text = payload.get("text")
    return case, block, (text if isinstance(text, str) else ""), None


@app.route("/counter/<case_id>/narrative", methods=["POST"])
@role_required("agent", "admin", "manager")
def counter_narrative(case_id):
    """Save rebuttal prose for this one case, or clear it.

    Open to the agent working the case: writing the rebuttal is the job. What
    an agent cannot do is write the template behind it — that is the route
    below, and it stays with team leads.

    Clearing is a delete, so the block falls back to whatever the cascade holds
    underneath — a category template if one exists, otherwise the built-in.
    """
    from chargeback.engines.evidence_rules import get_evidence_for_case
    from chargeback.engines.cover_letter import letter_context

    case, block, text, err = _narrative_payload(case_id)
    if err:
        return err

    # Prose on a submitted case would otherwise be a way straight through the
    # submission lock, so it goes through the same guard as every other write.
    blocked = _case_write_block(case)
    if blocked:
        return jsonify({"ok": False, "error": blocked}), 403

    blocks = CASE_NARRATIVE.setdefault(case_id, {})
    if text.strip():
        blocks[block] = text
    else:
        blocks.pop(block, None)
        if not blocks:
            CASE_NARRATIVE.pop(case_id, None)
    _save_case_narrative()

    ev_info = get_evidence_for_case(case)
    resolved = NarrativeBlocks.resolve(
        block, letter_context(case), ev_info["rule_key"],
        CASE_NARRATIVE.get(case_id, {}).get(block), TEMPLATE_OVERRIDES)
    return jsonify({"ok": True, "block": block, "scope": "case",
                    "level": resolved["level"], "text": resolved["text"],
                    "raw": resolved["raw"]})


@app.route("/counter/<case_id>/narrative/template", methods=["POST"])
@role_required("admin", "manager")
def counter_narrative_template(case_id):
    """Save this block as the template for every case in a reason category.

    Stored unrendered, placeholders intact, which is why the editor works on
    the raw text: capturing the rendered box would freeze this case's order id
    and amount into text meant for all of them.
    """
    from chargeback.engines.evidence_rules import get_evidence_for_case
    from chargeback.engines.cover_letter import letter_context

    case, block, text, err = _narrative_payload(case_id)
    if err:
        return err

    payload = request.get_json(silent=True) or request.form
    ev_info = get_evidence_for_case(case)
    scope = (payload.get("scope") or "category").strip()
    scope = "default" if scope == "default" else ev_info["rule_key"]

    store_key = NarrativeBlocks.store_key(block, scope)
    if not TemplateRepository.valid_key("narrative", f"{block}:{scope}"):
        return jsonify({"ok": False, "error": f"Unknown scope '{scope}'"}), 400

    if text.strip():
        TEMPLATE_OVERRIDES[store_key] = {
            "text": text,
            "edited_by": session.get("user", ""),
            "edited_at": datetime.now().strftime("%b %d, %Y, %H:%M:%S")}
        saved = True
    else:
        saved = TEMPLATE_OVERRIDES.pop(store_key, None) is not None
    _save_template_overrides()

    resolved = NarrativeBlocks.resolve(
        block, letter_context(case), ev_info["rule_key"],
        CASE_NARRATIVE.get(case_id, {}).get(block), TEMPLATE_OVERRIDES)
    return jsonify({"ok": True, "block": block, "scope": scope,
                    "saved": saved, "level": resolved["level"],
                    "text": resolved["text"], "raw": resolved["raw"]})


@app.route("/counter/<case_id>/upload", methods=["POST"])
@role_required("agent", "admin", "manager")
def counter_upload(case_id):
    """Store a manually supplied evidence file for a case."""
    case = _find_case(case_id)
    if not case:
        abort(404)

    # Attaching the missing document is the single most likely thing an agent
    # would try after submitting — which is exactly what the approval step is
    # for, so it is refused here and not merely hidden on the page.
    blocked = _case_write_block(case)
    if blocked:
        flash(blocked, "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    upload = request.files.get("evidence_file")
    if not upload or not upload.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    name = secure_filename(upload.filename)
    if not name:
        flash("That filename is not usable.", "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        flash(f"{ext or 'That file type'} is not accepted. Allowed: "
              f"{', '.join(sorted(ALLOWED_UPLOAD_EXT))}.", "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    # Size from the stream rather than reading it all in first.
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        flash(f"File is too large ({round(size / 1024 / 1024, 1)} MB). "
              f"Limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    folder = _case_upload_dir(case_id, create=True)
    if not folder:
        abort(404)

    stored = f"{_slug(request.form.get('requirement'))}__{name}"
    upload.save(os.path.join(folder, stored))

    case.setdefault("manual_evidence", []).append({
        "filename": name,
        "size_kb": round(size / 1024, 1),
        "uploaded_by": session.get("user", "Agent"),
        "uploaded_at": datetime.now().strftime("%b %d, %Y, %H:%M:%S"),
    })
    case.setdefault("dispute_history", []).append(
        {"event": f"EvidenceUploaded: {name}",
         "date": datetime.now().strftime("%b %d, %Y, %H:%M:%S")})
    # The bytes were already on disk; the record of them was not, so the Agent
    # Desk forgot every attachment on restart while the files stayed.
    _save_case_state()

    flash(f"Uploaded {name}.", "success")
    return redirect(url_for("counter_evidence", case_id=case_id))


INLINE_UPLOAD_EXT = {".png", ".jpg", ".jpeg"}


@app.route("/counter/<case_id>/upload/<filename>")
def counter_upload_download(case_id, filename):
    """Serve a manual upload back. send_from_directory rejects traversal.

    Images are served inline so the letter can show them as a thumbnail the way
    the page always has; every other type stays an attachment. Serving inline is
    only safe because the allowlist has no .html or .svg — those would run
    script on this origin.
    """
    folder = _case_upload_dir(case_id)
    if not folder or not os.path.isdir(folder):
        abort(404)
    inline = os.path.splitext(filename)[1].lower() in INLINE_UPLOAD_EXT
    return send_from_directory(folder, filename, as_attachment=not inline)


@app.route("/counter/<case_id>/upload/<filename>/delete", methods=["POST"])
def counter_upload_delete(case_id, filename):
    case = _find_case(case_id)
    if not case:
        abort(404)
    # Removing evidence from a filed packet is a bigger change than adding to
    # it, so it takes the same approval.
    blocked = _case_write_block(case)
    if blocked:
        flash(blocked, "error")
        return redirect(url_for("counter_evidence", case_id=case_id))

    folder = _case_upload_dir(case_id)
    if not folder:
        abort(404)

    # Resolve and confirm the target really sits inside this case's folder.
    target = os.path.realpath(os.path.join(folder, filename))
    if os.path.commonpath([target, os.path.realpath(folder)]) != os.path.realpath(folder):
        abort(404)
    if not os.path.isfile(target):
        abort(404)

    name = filename.partition("__")[2] or filename
    try:
        os.remove(target)
    except OSError as exc:
        # Windows refuses to unlink a file another process still holds open.
        # Report it rather than handing the agent a 500 page.
        flash(f"Could not remove {name}: {exc.strerror or exc}.", "error")
    else:
        flash(f"Removed {name}.", "success")
    return redirect(url_for("counter_evidence", case_id=case_id))


@app.route("/review/<case_id>")
def review_packet(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    reason = _get_reason(case)
    return render_template("review_packet.html", case=case, reason=reason,
                           order=_order_view(case),
                           # For the DB I-IV chips on the shared source cards.
                           dbs=DATABASES,
                           fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))


@app.route("/reason-codes")
def reason_codes():
    return render_template("reason_codes.html", codes=REASON_CODES)


@app.route("/reason-code/<code_id>")
def reason_code_detail(code_id):
    # The case pages link here with whatever code the case carries, so a
    # Mastercard 4837 or Discover UA02 used to dead-end on a 404 — which was
    # every non-Visa case. Resolve to the family and show that, keeping the
    # code the visitor asked for in the heading so the page answers the
    # question they actually asked.
    family, code = ReasonCodeInterpreter.resolve(code_id)
    if not code:
        return "Reason code not found", 404
    return render_template("reason_code_detail.html", code_id=code_id,
                           family_id=family, code=code)


@app.route("/processor/<case_id>")
def processor_view(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    return render_template("processor_view.html", case=case)


@app.route("/defend/<case_id>")
def defend_case(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    reason = _get_reason(case)
    return render_template("defend.html", case=case, reason=reason)


def _rebuttal_doc(case, reason):
    """Everything the representment letter says, assembled once.

    Lifted out of the route so the letter a merchant reads on screen and the PDF
    they download are two renderings of one document rather than two documents
    that can drift apart. Only the styling differs between them.
    """
    orders = ChargebackCaseLoader.load_orders()
    orders_by_id = {o["order_id"]: o for o in orders}

    def parse_date_only(value):
        dt = _parse_any_datetime(value)
        return dt.date() if dt else None

    def fmt_human_date(value, fallback=""):
        dt = _parse_any_datetime(value)
        if not dt:
            return fallback
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"

    def fmt_human_datetime(value, fallback=""):
        dt = _parse_any_datetime(value)
        if not dt:
            return fallback
        ampm = dt.strftime("%p")
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {dt.strftime('%I:%M')} {ampm}"

    def safe_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def resolve_order_row():
        order_id = case.get("order_id", "")
        direct = orders_by_id.get(order_id)
        if direct:
            return direct, "order_id_exact", 100

        target_last4 = str(case.get("card_last_four", "")).strip()
        target_method = str(case.get("payment_method", "")).strip().lower()
        target_amount = _safe_float(case.get("amount_authorized", case.get("amount", 0)))
        target_date = parse_date_only(case.get("transaction_date", ""))

        best_row = None
        best_score = -1
        for row in orders:
            score = 0
            if target_last4 and row.get("card_last_four") == target_last4:
                score += 35
            if target_method and row.get("payment_method", "").strip().lower() == target_method:
                score += 20
            row_amount = _safe_float(row.get("order_amount"))
            if abs(row_amount - target_amount) < 0.01:
                score += 25
            elif abs(row_amount - target_amount) <= 5:
                score += 10
            row_date = parse_date_only(row.get("order_date", ""))
            if target_date and row_date and row_date == target_date:
                score += 20
            if score > best_score:
                best_score = score
                best_row = row

        if best_score >= 45 and best_row:
            return best_row, "heuristic_match", best_score
        return {}, "no_match", 0

    raw, match_mode, match_score = resolve_order_row()
    customer_id = raw.get("customer_id", "")
    same_customer_orders = [o for o in orders if customer_id and o.get("customer_id") == customer_id]
    same_customer_orders.sort(key=lambda r: _parse_any_datetime(r.get("order_date", "")) or datetime.min)

    tx_dt = _parse_any_datetime(case.get("transaction_date", "")) or datetime.utcnow()
    tx_date = tx_dt.date()

    previous_order = None
    for row in same_customer_orders:
        row_dt = _parse_any_datetime(row.get("order_date", ""))
        if row_dt and row_dt.date() < tx_date:
            previous_order = row
    if previous_order is None and same_customer_orders:
        previous_order = same_customer_orders[0]

    customer_name = case.get("cardholder", "Not available in source record")
    customer_email = raw.get("customer_email", "Not available in source record")
    customer_phone = raw.get("customer_phone", "Not available in source record")
    customer_ip = raw.get("customer_ip", "Not available in source record")
    customer_city = raw.get("customer_city", "N/A")
    customer_state = raw.get("customer_state", "N/A")
    customer_country = case.get("issuer_country", "United States") or "United States"

    card_bin = raw.get("card_bin", case.get("card_bin", "Not available in source record"))
    auth_code = case.get("auth_code", "Not available in source record")
    device_id = raw.get("device_id", case.get("device_id", "Not available in source record"))

    first_order_dt = _parse_any_datetime(same_customer_orders[0].get("order_date", "")) if same_customer_orders else None
    account_created = first_order_dt or _parse_any_datetime(raw.get("order_date", ""))
    card_binding = _parse_any_datetime(raw.get("order_date", ""))

    prev_amount = _safe_float(previous_order.get("order_amount")) if previous_order else None
    prev_fallback_dt = "Not available in source record"
    prev_date_text = (
        fmt_human_datetime(previous_order.get("order_date", ""), fallback=prev_fallback_dt)
        if previous_order
        else prev_fallback_dt
    )
    prev_ip = previous_order.get("customer_ip", "Not available in source record") if previous_order else "Not available in source record"

    dispute_amount = _safe_float(case.get("amount", 0))
    refunded_amount = _safe_float(case.get("amount_settled", dispute_amount)) or dispute_amount
    reason_line = f"{case.get('reason_code', '')} - {reason.get('title', '')}".strip(" -")
    tx_ref = case.get("payment_psp_ref", "") or case.get("dispute_psp_ref", "")
    dispute_case_ref = case.get("dispute_psp_ref", case.get("case_id", ""))

    from chargeback.engines.cover_letter import build_cover_letter, build_evidence_list
    cover_letter = build_cover_letter(case, raw, TEMPLATE_OVERRIDES)
    dynamic_evidence = build_evidence_list(case, raw)

    doc = {
        "generated_at": datetime.now().strftime("%m/%d/%y, %I:%M %p").lstrip("0").replace(" 0", " "),
        "document_title": f"Rebuttal Document - {case.get('case_id', '')}",
        "heading": cover_letter["heading"],
        "subheading": cover_letter["subheading"],
        "cover_letter": cover_letter,
        "dynamic_evidence": dynamic_evidence,
        "summary": {
            "dispute_case_id": dispute_case_ref,
            "original_charge_date": fmt_human_datetime(case.get("transaction_date", ""), fallback=case.get("transaction_date", "")),
            "disputed_amount": dispute_amount,
            "reason_code_line": reason_line,
            "cardholder_name": customer_name,
            "card_brand_last4": f"{case.get('payment_method', 'Card')} ending in {case.get('card_last_four', '----')}",
            "merchant_identity": case.get("merchant", "Merchant"),
            "arn_number": case.get("acquirer_ref", "N/A"),
            "refund_processing_date": fmt_human_date(case.get("submission_date", ""), fallback=case.get("submission_date", case.get("dispute_creation_date", ""))),
            "refunded_amount": refunded_amount,
        },
        "statement": {
            "transaction_ref": tx_ref,
            "arn_number": case.get("acquirer_ref", "N/A"),
            "avs": case.get("avs_response", "N/A"),
            "cvv": case.get("cvv_response", "N/A"),
            "threed_secure": case.get("threed_secure", "N/A"),
        },
        "evidence": {
            "refund_rows": [
                {
                    "exhibit": "Exhibit A-1",
                    "type": "Gateway Refund Receipt Screenshot",
                    "purpose": (
                        f"Proves our merchant terminal successfully issued a formal reversal command for the amount of ${refunded_amount:.2f} "
                        f"on {fmt_human_date(case.get('submission_date', ''), fallback='recorded settlement date')}."
                    ),
                },
                {
                    "exhibit": "Exhibit A-2",
                    "type": "Settlement Log & ARN Metadata",
                    "purpose": (
                        f"Displays the raw transactional metadata confirming generation of "
                        f"ARN: {case.get('acquirer_ref', 'N/A')}. "
                        "This acts as federal/banking tracking confirmation that the credit has passed from our acquirer to the "
                        "customer's card network."
                    ),
                },
            ],
            "security_rows": [
                {
                    "exhibit": "Exhibit B",
                    "type": "AVS & CVV Authentication Log",
                    "details": (
                        f"AVS Response: {case.get('avs_response', 'N/A')}\n"
                        f"CVV Response: {case.get('cvv_response', 'N/A')}\n\n"
                        "Proves the user possessed the true billing credentials."
                    ),
                },
                {
                    "exhibit": "Exhibit C",
                    "type": "Digital Footprint / IP Address Data",
                    "details": (
                        f"IP Address recorded at checkout with geolocation "
                        f"data, aligning directly with the cardholder's known "
                        f"billing jurisdiction ({customer_country})."
                    ),
                },
                {
                    "exhibit": "Exhibit D",
                    "type": "Proof of Fulfillment / Delivery",
                    "details": (
                        "Carrier details, signed delivery confirmation, or "
                        "digital logs confirming that the order was actively "
                        "received or downloaded by the customer."
                    ),
                },
            ],
        },
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "phone": customer_phone,
            "city": customer_city,
            "state": customer_state,
            "country": customer_country,
            "ip_address": customer_ip,
            "ip_country": "US" if "united states" in customer_country.lower() else customer_country,
            "device_id": device_id,
            "account_created": account_created.strftime("%Y-%m-%dT%H:%M:%SZ") if account_created else "Not available in source record",
            "card_binding_time": card_binding.strftime("%Y-%m-%dT%H:%M:%SZ") if card_binding else "Not available in source record",
            "card_bin": card_bin,
            "card_last_four": case.get("card_last_four", "----"),
            "bin_country": "US" if "united states" in customer_country.lower() else customer_country,
        },
        "payment_history": {
            "txn1_date": prev_date_text,
            "txn1_amount": prev_amount,
            "txn1_email": previous_order.get("customer_email", customer_email) if previous_order else customer_email,
            "txn1_card_bin": card_bin,
            "txn1_last4": previous_order.get("card_last_four", case.get("card_last_four", "----")) if previous_order else case.get("card_last_four", "----"),
            "txn1_bin_country": "US" if "united states" in customer_country.lower() else customer_country,
            "txn1_ip_country": "US" if "united states" in customer_country.lower() else customer_country,
            "txn1_ip_address": prev_ip,
            "txn2_date": fmt_human_datetime(case.get("transaction_date", ""), fallback=case.get("transaction_date", "")),
            "txn2_amount": dispute_amount,
            "txn2_email": customer_email,
            "txn2_card_bin": card_bin,
            "txn2_last4": case.get("card_last_four", "----"),
            "txn2_bin_country": "US" if "united states" in customer_country.lower() else customer_country,
            "txn2_ip_country": "US" if "united states" in customer_country.lower() else customer_country,
            "txn2_ip_address": customer_ip,
            "device_id": device_id,
        },
        "order": {
            "match_mode": match_mode,
            "match_score": match_score,
            "order_id": case.get("order_id", ""),
            "product_name": raw.get("product_name", "Program / Service Access"),
            "product_id": raw.get("product_id", f"SVC-{case.get('case_id', '0000')}"),
            "quantity": safe_int(raw.get("quantity", 1), 1),
            "price": _safe_float(raw.get("unit_price", dispute_amount)),
            "purchase_amount": _safe_float(raw.get("order_amount", dispute_amount)),
            "order_date": fmt_human_datetime(case.get("transaction_date", ""), fallback=case.get("transaction_date", "")),
            "delivery_option": "STANDARD",
            "ship_from": raw.get("ship_from_warehouse", "FC-N/A"),
            "shop_name": case.get("descriptor_name", case.get("merchant", "N/A")),
            "delivery_status": "NORMAL" if str(raw.get("fulfillment_status", "")).lower() == "delivered" else raw.get("fulfillment_status", "Disputed Status"),
            "delivery_event": (
                "Package has been delivered!"
                if str(raw.get("fulfillment_status", "")).lower() == "delivered"
                else "Delivery status available in tracking record."
            ),
            "delivery_time": raw.get("delivery_date", case.get("submission_date", "N/A")),
            "delivery_title": raw.get("fulfillment_status", "Status Pending"),
            "shipment_provider": raw.get("shipping_carrier", "N/A"),
            "tracking_number": raw.get("tracking_number", "N/A"),
        },
        "payment": {
            "merchant_name": case.get("merchant", "N/A"),
            "merchant_id": case.get("merchant_account", "N/A"),
            "currency": "USD",
            "transaction_amount": refunded_amount,
            "transaction_date": fmt_human_datetime(case.get("transaction_date", ""), fallback=case.get("transaction_date", "")),
            "authorization_code": auth_code,
            "threed_secure": case.get("threed_secure", "N/A"),
            "order_id": case.get("order_id", "N/A"),
        },
        "support_email": f"support@{MERCHANT_CONFIG['descriptor_url'] or 'merchant.example.com'}",
        "page_total": 4,
    }

    return doc


@app.route("/rebuttal/<case_id>")
def rebuttal(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    reason = _get_reason(case)
    return render_template("rebuttal.html", case=case, reason=reason,
                           auto_print=request.args.get("print", "") == "1",
                           doc=_rebuttal_doc(case, reason))


@app.route("/add-case", methods=["GET", "POST"])
def add_case():
    if request.method == "GET":
        # The ten options used to be hardcoded in the template with their own
        # copies of the descriptions, already drifting from the knowledge base.
        return render_template(
            "add_case.html",
            reason_options=[{"code": rc, "label": _reason_label(rc, "Visa")}
                            for rc in REASON_CODES])

    form = request.form
    case_id = form.get("case_id", "NEW-001")
    amount = float(form.get("amount", 0))
    reason_code = form.get("reason_code", "13.1")
    h = int(hashlib.md5(case_id.encode()).hexdigest(), 16)

    category_map = {
        "Fraud": "Fraud - Card Not Present (CNP)",
        "Merchandise": "Merchandise - Item Not Received",
        "Processing": "Processing - Incorrect Amount",
        "Subscription": "Subscription - Cancelled Recurring",
        "Refund": "Refund - Credit Not Processed",
    }
    category = form.get("category", "Fraud")
    scenario = category_map.get(category, "Fraud - Card Not Present (CNP)")

    new_case = {
        "case_id": case_id,
        "scenario": scenario,
        "chargeback_category": category,
        "reason_code": reason_code,
        "processor": form.get("processor", "Adyen"),
        "amount": amount,
        # Set from the scorer below, once the AVS/CVV/3DS fields this form
        # collects are actually on the dict. A flat 50 ignored them entirely.
        "win_probability": 0,
        "submission_date": form.get("chargeback_date", ""),
        "submission_status": "Pending",
        "outcome": "Pending",
        "merchant": MERCHANT_CONFIG["company_name"],
        "merchant_account": form.get("merchant_id", MERCHANT_CONFIG["merchant_account_number"]),
        "descriptor_name": MERCHANT_CONFIG["dba_name"],
        "descriptor_url": MERCHANT_CONFIG["descriptor_url"],
        "payment_method": form.get("card_type", "Visa"),
        "card_last_four": form.get("card_last_four", f"{h % 10000:04d}"),
        "card_expiry": form.get("card_expiry", "12/2028"),
        "cardholder": form.get("customer_name", "***REDACTED***"),
        "issuer_country": form.get("country", "United States"),
        "issuer_name": form.get("state", ""),
        "avs_response": "Both postal code and address match (Y)" if form.get("avs_cvv") == "Pass" else "No match",
        "cvv_response": "Supplied, Matches (M)" if form.get("avs_cvv") == "Pass" else "Not provided",
        "threed_secure": "Authenticated" if form.get("avs_cvv") == "Pass" else "Not Offered",
        "transaction_date": form.get("transaction_date", ""),
        "amount_authorized": amount,
        "amount_settled": amount,
        "dispute_psp_ref": case_id,
        "payment_psp_ref": form.get("transaction_id", ""),
        "dispute_creation_date": form.get("chargeback_date", ""),
        "order_id": form.get("order_id", f"ORD-{case_id}"),
        "acquirer_ref": form.get("arn", f"{24793306171002500000000 + h % 999999}"),
        "acquirer_code": form.get("merchant_id", ""),
        "auto_defended": form.get("action", "") == "save_and_represent",
        "liability_shift": form.get("avs_cvv") == "Pass",
        "issuer_comments": form.get("notes", ""),
        "dispute_history": [
            {"event": "CaseCreated", "date": form.get("chargeback_date", "")},
            {"event": "ManualEntry", "date": "Now"},
        ],
    }
    new_case["win_probability"] = AIValidationEngine.score(new_case)
    # A second case under an existing id would shadow the first everywhere —
    # _find_case takes the first match — and persisting it would make that
    # permanent.
    if _find_case(case_id) is not None:
        flash(f"Case {case_id} already exists.", "error")
        return redirect(url_for("case_detail", case_id=case_id))
    # Set before the append so it persists in the stored blob below, rather
    # than relying on the reader to guess how this case arrived.
    new_case["ingest_source"] = "manual"
    CASES.append(new_case)
    # Owned before it is stored, so the owner rides in the whole-case blob and
    # the ingest stamp skips it on every later boot. Every other case already
    # carries the key, so only this one is touched.
    _auto_assign_unowned_cases()
    # This case has no row in the sheet, so unlike every other one it cannot be
    # rebuilt at boot. Stored whole rather than as a patch.
    StateStore.save_added_case(new_case)
    _save_case_state()
    return redirect(url_for("case_detail", case_id=case_id))


@app.route("/case/<case_id>/accept", methods=["POST"])
def accept_case(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return jsonify({"status": "error"}), 404
    # Legacy page, same rule: conceding a case already filed with the PSP is a
    # correction, and corrections go through a team lead.
    blocked = _case_write_block(case)
    if blocked:
        return jsonify({"status": "error", "error": blocked}), 403
    # Conceding here and conceding from the Agent Desk are the same act, so they
    # go through the same path — _apply_agent_action now sets the accept_refund
    # override for every "Not Fought", so this route no longer writes it itself.
    # This used to set outcome="Accepted" and never touch case_status, which
    # left the case reading "Accepted" in the outcome column while every manager
    # chart still counted it as Decision Pending — and gave that column a fifth
    # word for a state it already called Refunded.
    # _record_agent_action also writes the timeline entry and persists.
    _record_agent_action(case, "Not Fought")
    return jsonify({"status": "ok", "case_id": case_id})


@app.route("/gateway-receipt/<case_id>")
def gateway_receipt(case_id):
    case = next((c for c in CASES if c["case_id"] == case_id), None)
    if not case:
        return "Case not found", 404
    h = int(hashlib.md5(case_id.encode()).hexdigest(), 16)
    card_type = case.get("payment_method", "Visa")
    last4 = case.get("card_last_four", "0000")
    bin_map = {"Visa": "411111", "VISA": "411111", "Mastercard": "520000", "MASTERCARD": "520000",
               "Amex": "371449", "AMEX": "371449", "Discover": "601100", "DISCOVER": "601100",
               "Klarna": "540200", "KLARNA": "540200"}
    receipt = {
        "merchant_name": case.get("merchant") or MERCHANT_CONFIG["company_name"],
        "transaction_id": case.get("payment_psp_ref", "") or case.get("dispute_psp_ref", case_id),
        "transaction_date": case.get("transaction_date", "N/A"),
        "amount": case.get("amount_authorized", case.get("amount", 0)),
        "transaction_type": "Card Void" if case.get("refund_type") else "Sale",
        "entry_method": "Keyed",
        "cc_number": f"{bin_map.get(card_type, '400000')}******{last4}",
        "cc_expiration": case.get("card_expiry", "") or "XX/XX",
        "cc_type": card_type,
        "avs_status": case.get("avs_response", "N/A"),
        "cvv_status": case.get("cvv_response", "N/A"),
        "auth_code": f"{h % 999999:06d}",
        "processor": case.get("processor", "Unknown"),
        "currency": case.get("currency", "USD"),
    }
    return render_template("gateway_receipt.html", case=case, receipt=receipt)


# ─── API Routes ────────────────────────────────────────────────────────────────

@app.route("/api/cases")
def api_cases():
    scenario = request.args.get("scenario", "All")
    processor = request.args.get("processor", "All")
    outcome = request.args.get("outcome", "All")

    filtered = CASES
    if scenario != "All":
        filtered = [c for c in filtered if c["scenario"] == scenario]
    if processor != "All":
        filtered = [c for c in filtered if c["processor"] == processor]
    if outcome != "All":
        filtered = [c for c in filtered if c["outcome"] == outcome]

    return jsonify(filtered)



# Reload the ingested sheet at import time so every worker/reload sees the same
# book. With nothing ingested this leaves the app empty on purpose.
_STARTUP_LOADED = _load_startup_cases()

if __name__ == "__main__":
    if _STARTUP_LOADED:
        print(f"Loaded {_STARTUP_LOADED} cases from "
              f"{StateStore.active_dataset()}")
    else:
        print("No dataset ingested yet — starting empty. "
              "Upload a CSV at /ingest to begin.")
    app.run(debug=True, port=8000)
