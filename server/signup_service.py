#!/usr/bin/env python3
"""DopeHub.net sign-up service (updates list, team applications, survey, visitor stats).

Standard library only (Python 3.10+). Listens on 127.0.0.1 behind Caddy.
Caddy forwards /api/* (public) and /admin/api/* (password protected; Caddy adds
the X-Admin-Secret header after basic auth). IP addresses are only used in memory
for rate limiting and daily unique-visitor counting and are never written to disk.

Public endpoints
  POST /api/subscribe    {email, who?, consent, website}  -> queues a confirmation email
  POST /api/confirm      {token}                           -> confirms the email address
  POST /api/unsubscribe  {token}  (or RFC 8058 one-click form post with ?t=token)
  POST /api/survey       {token, answers[], other?}
  POST /api/apply        {name, email, role, availability, link?, message, consent, website}
  POST /api/hit          {p, r?, s?, w?}                   -> cookie-free page view
  GET  /api/health

Admin endpoints (only via Caddy /admin/api/*)
  GET  /admin/api/summary
  GET  /admin/api/applications
  POST /admin/api/applications/<id>   {status}
  GET  /admin/api/export/subscribers.csv | applications.csv | survey.csv
  POST /admin/api/forget               {email}

CLI: python3 signup_service.py stats | export <table> | forget <email> | outbox | retry | send-test <email>
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from pathlib import Path

# ---------------------------------------------------------------- config
E = os.environ.get
DB_PATH = E("SIGNUP_DB", "/var/lib/dopehub-signup/signups.db")
HOST = E("SIGNUP_HOST", "127.0.0.1")
PORT = int(E("SIGNUP_PORT", "8081"))
PUBLIC_URL = E("PUBLIC_URL", "https://dopehub.net").rstrip("/")
ALLOWED_ORIGINS = {o.strip() for o in E(
    "SIGNUP_ORIGINS", "https://dopehub.net,https://www.dopehub.net,http://dopehub.net,http://132.226.212.103"
).split(",") if o.strip()}
ADMIN_SECRET = E("ADMIN_SECRET", "")
SMTP_HOST = E("SMTP_HOST", "")
SMTP_PORT = int(E("SMTP_PORT", "465"))
SMTP_USER = E("SMTP_USER", "")
SMTP_PASS = E("SMTP_PASS", "")
SMTP_SECURITY = E("SMTP_SECURITY", "ssl")  # ssl | starttls | none (none only for local testing)
# MAIL_TRANSPORT=relay sends through Oracle Email Delivery via the demo server's gateway
# (https://demo.dopehub.net/relay/email, which only accepts this server's IP and RELAY_TOKEN).
MAIL_TRANSPORT = E("MAIL_TRANSPORT", "smtp").strip().lower()  # smtp | relay
RELAY_URL = E("RELAY_URL", "")
RELAY_TOKEN = E("RELAY_TOKEN", "")
MAIL_FROM = E("MAIL_FROM", "no-reply@dopehub.net")
MAIL_FROM_NAME = E("MAIL_FROM_NAME", "DopeHub.net")
REPLY_TO = E("REPLY_TO", "contact@dopehub.net")
ALERT_TO = E("ALERT_TO", "contact@dopehub.net")
# Logo in the email header: embedded in the message (cid:) when sending over SMTP, so it shows
# even when the mail app blocks remote images; the relay can't attach files, so it gets a URL.
LOGO_FILE = E("LOGO_FILE", "/opt/dopehub-signup/logo-mark.png")
LOGO_URL = E("LOGO_URL", f"{PUBLIC_URL}/media/logo-mark.png")
LOGO_CID = "dopehub-logo@dopehub.net"
OLD_LOGO_SRC = f"{PUBLIC_URL}/logo.png"  # used by emails queued before 28 Sep 2026 (that URL isn't an image)
MAX_BODY = 8 * 1024
CONSENT_VERSION = "2026-10-separate-preferences"
MAIL_PREVIEW_DIR = E("MAIL_PREVIEW_DIR", "")
BETA_INVITE_ORIGIN = E("BETA_INVITE_ORIGIN", "").rstrip("/")

EMAIL_RE = re.compile(r"^[^\s@<>\"',;]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
URL_RE = re.compile(r"^https?://[^\s<>\"]+\.[^\s<>\"]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|headless|lighthouse|monitor|curl|wget|python", re.I)
WHO = {"", "patient", "carer", "professional", "curious"}
ROLES = {"developer": "Developer", "moderator": "Community moderator", "writer": "Writer or reviewer",
         "clinical": "Clinical reviewer", "creative": "Design, social or video", "legal": "Legal or compliance",
         "other": "Something else"}
AVAIL = {"1-3": "1 to 3 hours a week", "3-8": "3 to 8 hours a week", "8+": "More than 8 hours a week", "unsure": "Not sure yet"}
SURVEY = {"strains": "Understanding strains and products", "access": "Getting started with a prescription",
          "clinics": "Finding clinics and pharmacies", "reviews": "Real reviews and experiences",
          "community": "Talking to others like me", "research": "Research and news"}
STATUSES = {"new", "contacted", "interview", "accepted", "declined"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  who TEXT NOT NULL DEFAULT '',
  consent_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL COLLATE NOCASE,
  role TEXT NOT NULL,
  availability TEXT NOT NULL,
  link TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL,
  consent_version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS applications_email ON applications(email);
CREATE TABLE IF NOT EXISTS survey (
  id INTEGER PRIMARY KEY,
  subscriber_id INTEGER NOT NULL UNIQUE REFERENCES subscribers(id) ON DELETE CASCADE,
  answers TEXT NOT NULL DEFAULT '',
  other TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  to_addr TEXT NOT NULL,
  subject TEXT NOT NULL,
  text_body TEXT NOT NULL,
  html_body TEXT NOT NULL DEFAULT '',
  reply_to TEXT NOT NULL DEFAULT '',
  unsub_token TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_try REAL NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  sent_at TEXT
);
CREATE TABLE IF NOT EXISTS preference_requests (
  token TEXT PRIMARY KEY,
  subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
  newsletter INTEGER NOT NULL,
  beta INTEGER NOT NULL,
  expires_at REAL NOT NULL,
  consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS mail_campaigns (
  campaign_id TEXT NOT NULL,
  subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  PRIMARY KEY(campaign_id, subscriber_id, kind)
);
CREATE TABLE IF NOT EXISTS hits (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  path TEXT NOT NULL,
  referrer TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  device TEXT NOT NULL DEFAULT '',
  unique_visit INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS hits_day ON hits(day);
"""
MIGRATIONS = [
    # Existing subscribers consented to updates AND early-access messages.
    ("subscribers", "newsletter", "ALTER TABLE subscribers ADD COLUMN newsletter INTEGER NOT NULL DEFAULT 1"),
    ("subscribers", "beta", "ALTER TABLE subscribers ADD COLUMN beta INTEGER NOT NULL DEFAULT 1"),
    ("subscribers", "newsletter_token", "ALTER TABLE subscribers ADD COLUMN newsletter_token TEXT"),
    ("subscribers", "beta_token", "ALTER TABLE subscribers ADD COLUMN beta_token TEXT"),
    ("subscribers", "token", "ALTER TABLE subscribers ADD COLUMN token TEXT"),
    ("subscribers", "confirmed_at", "ALTER TABLE subscribers ADD COLUMN confirmed_at TEXT"),
    ("subscribers", "last_mail_at", "ALTER TABLE subscribers ADD COLUMN last_mail_at REAL NOT NULL DEFAULT 0"),
]

_lock = threading.Lock()
_wake = threading.Event()     # wakes the mailer thread
_queued = threading.Event()   # set when an email was queued in a not-yet-committed transaction


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
        if _queued.is_set():
            _queued.clear()
            _wake.set()
    finally:
        conn.close()


def init_db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        for table, col, sql in MIGRATIONS:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(sql)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS subscribers_token ON subscribers(token)")
        for row in conn.execute("SELECT id FROM subscribers WHERE token IS NULL").fetchall():
            conn.execute("UPDATE subscribers SET token=? WHERE id=?", (secrets.token_urlsafe(24), row[0]))
        for column in ("newsletter_token", "beta_token"):
            for row in conn.execute(f"SELECT id FROM subscribers WHERE {column} IS NULL").fetchall():
                conn.execute(f"UPDATE subscribers SET {column}=? WHERE id=?", (secrets.token_urlsafe(24), row[0]))
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS subscribers_{column} ON subscribers({column})")
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(s, n):
    s = s if isinstance(s, str) else ""
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 32).strip()
    return s[:n]


def valid_email(e):
    return len(e) <= 254 and bool(EMAIL_RE.match(e))


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------- rate limiting (memory only)
class RateLimiter:
    def __init__(self, limit, window):
        self.limit, self.window, self.hits, self.lock = limit, window, {}, threading.Lock()

    def allow(self, key):
        t = time.monotonic()
        with self.lock:
            q = [x for x in self.hits.get(key, []) if t - x < self.window]
            ok = len(q) < self.limit
            if ok:
                q.append(t)
            self.hits[key] = q
            if len(self.hits) > 5000:
                for k in list(self.hits)[:2500]:
                    del self.hits[k]
            return ok


LIMITS = {
    "/api/subscribe": RateLimiter(6, 600), "/api/apply": RateLimiter(4, 3600),
    "/api/confirm": RateLimiter(20, 600), "/api/unsubscribe": RateLimiter(20, 600),
    "/api/survey": RateLimiter(10, 600), "/api/hit": RateLimiter(120, 600),
}
SURVEY_TOKENS = {}  # token -> (subscriber_id, expires)


# ---------------------------------------------------------------- unique visitors (memory only)
class Visitors:
    """Counts a visitor once per day using a hash of IP + user agent with a random salt
    that is regenerated every day and never stored (the approach Plausible uses)."""

    def __init__(self):
        self.day, self.salt, self.seen, self.lock = None, b"", set(), threading.Lock()

    def first_today(self, ip, ua):
        today = date.today().isoformat()
        with self.lock:
            if today != self.day:
                self.day, self.salt, self.seen = today, secrets.token_bytes(16), set()
            h = hashlib.sha256(self.salt + ip.encode() + b"|" + ua.encode()).digest()[:12]
            if h in self.seen:
                return False
            self.seen.add(h)
            return True


VISITORS = Visitors()


# ---------------------------------------------------------------- email
def email_shell(title, inner_html, unsub_url=None):
    foot = ""
    if unsub_url:
        foot = (f'<p style="margin:14px 0 0">Don\'t want these emails? '
                f'<a href="{esc(unsub_url)}" style="color:#5c7a5f">Unsubscribe</a>.</p>')
    return f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{esc(title)}</title></head>
<body style="margin:0;padding:0;background:#eef2ea;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#10231a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2ea;padding:28px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden">
<tr><td style="background:#1D2629;padding:20px 28px">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="vertical-align:middle;padding:0 10px 0 0"><img src="cid:{LOGO_CID}" width="40" height="40" alt="DopeHub" style="display:block;border:0;width:40px;height:40px"></td>
<td style="vertical-align:middle;font-family:Manrope,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:23px;line-height:1;font-weight:800;letter-spacing:-1px;color:#EDEFEA;white-space:nowrap">Dope<span style="color:#8CCB3F">Hub</span><span style="color:#8CCB3F;font-size:16px;letter-spacing:-0.5px">.net</span></td>
</tr></table>
</td></tr>
<tr><td style="padding:30px 28px 10px;font-size:16px;line-height:1.6">{inner_html}</td></tr>
<tr><td style="padding:18px 28px 26px;font-size:12px;line-height:1.6;color:#6b7f6e;border-top:1px solid #e5ebe1">
<p style="margin:0">DopeHub.net shares information and real experiences only. We don't sell, supply or advertise cannabis or any medicine, and nothing we send is medical advice.</p>{foot}
</td></tr></table></td></tr></table></body></html>"""


def btn(url, label):
    return (f'<p style="margin:26px 0"><a href="{esc(url)}" style="display:inline-block;background:#8bd14b;color:#06120b;'
            f'text-decoration:none;font-weight:800;padding:14px 26px;border-radius:999px">{esc(label)}</a></p>')


def queue(conn, kind, to, subject, text, html="", reply_to="", unsub_token=""):
    conn.execute(
        "INSERT INTO outbox(kind,to_addr,subject,text_body,html_body,reply_to,unsub_token,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (kind, to, subject, text, html, reply_to, unsub_token, now()))
    _queued.set()


def queue_confirm(conn, email, token, newsletter=True, beta=True, cancel_token=None):
    confirm = f"{PUBLIC_URL}/?confirm={token}"
    unsub = f"{PUBLIC_URL}/?unsubscribe={cancel_token or token}"
    choices = []
    if newsletter:
        choices.append("Occasional newsletters and launch news")
    if beta:
        choices.append("A beta invitation when access is ready (waiting list only)")
    text = ("Please confirm your DopeHub email preferences:\n\n" + "\n".join(choices)
            + f"\n\nConfirm your preferences: {confirm}\n\n"
            "This confirms your email preferences; it is not a beta access link. "
            "A beta invitation is sent separately when access is ready. "
            "If you didn't request this, ignore it; your current preferences won't change.\n\n"
            f"Cancel this signup: {unsub}\nQuestions: {REPLY_TO}")
    inner = ('<h1 style="font-size:26px">A little room to grow.</h1><p>Please confirm your email preferences:</p><ul>'
             + ''.join(f"<li>{esc(x)}</li>" for x in choices) + '</ul>' + btn(confirm, "Confirm my preferences")
             + '<p>This is email confirmation, not beta access. Your invitation comes separately when access is ready.</p>'
             + "<p>Didn't request this? Ignore the email. Your current preferences won't change.</p>")
    queue(conn, "confirm", email, "Confirm your DopeHub email preferences", text,
          email_shell("Confirm your preferences", inner, unsub), REPLY_TO)


def queue_acknowledgement(conn, application):
    text = (f"Hi {application['name']},\n\nThanks for offering to help shape DopeHub. "
            f"We've received your volunteer application for {ROLES[application['role']]}. "
            f"A member of the team will reply by email.\n\nQuestions or changes? Write to {REPLY_TO}. "
            "Applying does not subscribe you to our newsletter.")
    inner = (f"<h1 style='font-size:26px'>Thanks for putting down roots.</h1><p>Hi {esc(application['name'])},</p>"
             f"<p>We've received your volunteer application for <b>{esc(ROLES[application['role']])}</b>. "
             "A member of the team will reply by email.</p>"
             f"<p>Questions or changes? Reply to this email to reach {esc(REPLY_TO)}.</p>"
             "<p>Applying does not subscribe you to our newsletter.</p>")
    queue(conn, "application_ack", application['email'], "We've received your DopeHub application", text,
          email_shell("Application received", inner), REPLY_TO)


def valid_invitation(url):
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return bool(BETA_INVITE_ORIGIN and origin == BETA_INVITE_ORIGIN and parsed.scheme == 'https'
                and not parsed.username and not parsed.password and not any(c in url for c in '\r\n'))


def queue_invitation(conn, email, access_url, campaign_id):
    if not valid_invitation(access_url):
        raise ValueError("Set BETA_INVITE_ORIGIN to the approved HTTPS access origin and supply a real invitation URL.")
    row = conn.execute("SELECT * FROM subscribers WHERE email=? AND confirmed_at IS NOT NULL AND beta=1", (email,)).fetchone()
    if not row:
        raise ValueError("A confirmed beta request is required.")
    if not conn.execute("INSERT OR IGNORE INTO mail_campaigns VALUES (?,?,?)", (campaign_id,row['id'],'beta_invite')).rowcount:
        return False
    cancel = f"{PUBLIC_URL}/?unsubscribe={row['beta_token']}"
    text = f"Your DopeHub beta invitation is ready.\n\nOpen your invitation: {access_url}\n\nExplore the platform and share your feedback. This invitation does not subscribe you to newsletters.\n\nCancel beta messages: {cancel}\nReply to {REPLY_TO} for help."
    inner = ('<h1 style="font-size:26px">There’s a place for you.</h1><p>Your DopeHub beta invitation is ready.</p>'
             + btn(access_url, 'Open my beta invitation')
             + '<p>Explore the platform and tell us what works and what could be better.</p>'
             + f'<p><a href="{esc(cancel)}">Cancel beta messages</a>. Your newsletter preference is separate.</p>')
    queue(conn,'beta_invite',email,'Your DopeHub beta invitation',text,email_shell('Beta invitation',inner),REPLY_TO)
    return True


def queue_newsletter(conn, campaign_id, subject, body, kind='newsletter'):
    if kind not in ('newsletter','launch') or not subject.strip() or not body.strip():
        raise ValueError('A newsletter or launch update needs a subject and body.')
    count = 0
    for row in conn.execute("SELECT * FROM subscribers WHERE confirmed_at IS NOT NULL AND newsletter=1").fetchall():
        if not conn.execute("INSERT OR IGNORE INTO mail_campaigns VALUES (?,?,?)", (campaign_id,row['id'],kind)).rowcount:
            continue
        unsub = f"{PUBLIC_URL}/?unsubscribe={row['newsletter_token']}"
        text = f"{body}\n\nUnsubscribe from newsletters: {unsub}\nYour beta request is separate.\nContact: {REPLY_TO}"
        inner = f'<h1 style="font-size:26px">{esc(subject)}</h1>' + ''.join(f'<p>{esc(x)}</p>' for x in body.split('\n\n'))
        queue(conn,kind,row['email'],subject,text,email_shell(subject,inner,unsub),REPLY_TO,row['newsletter_token'])
        count += 1
    return count


def delivery_allowed(row):
    if row['kind'] not in ('newsletter','launch','beta_invite'):
        return True
    preference = 'beta' if row['kind'] == 'beta_invite' else 'newsletter'
    with db() as conn:
        return bool(conn.execute(f"SELECT 1 FROM subscribers WHERE email=? AND confirmed_at IS NOT NULL AND {preference}=1", (row['to_addr'],)).fetchone())


def sender_name(row):
    return 'DopeHub Newsletter' if row['kind'] in ('newsletter','launch') else 'DopeHub'


def queue_alert(conn, a):
    role, avail = ROLES.get(a["role"], a["role"]), AVAIL.get(a["availability"], a["availability"])
    text = (f"New team application\n\nName: {a['name']}\nEmail: {a['email']}\nRole: {role}\nTime: {avail}\n"
            f"Link: {a['link'] or '-'}\n\n{a['message']}\n\nReply to the applicant using the email address above from contact@dopehub.net.\n"
            f"All applications: {PUBLIC_URL}/admin/\n")
    rows = "".join(f'<tr><td style="padding:4px 12px 4px 0;color:#6b7f6e">{k}</td><td style="padding:4px 0"><b>{esc(v)}</b></td></tr>'
                   for k, v in [("Name", a["name"]), ("Email", a["email"]), ("Role", role), ("Time", avail), ("Link", a["link"] or "-")])
    inner = ('<h1 style="margin:0 0 14px;font-size:22px">New team application</h1>'
             f'<table role="presentation" style="font-size:15px">{rows}</table>'
             f'<div style="margin:18px 0;padding:16px;background:#f4f7f1;border-radius:12px;white-space:pre-wrap">{esc(a["message"])}</div>'
             '<p style="margin:0">Reply to the applicant using the email address above from contact@dopehub.net.</p>' + btn(f"{PUBLIC_URL}/admin/", "Open the dashboard"))
    queue(conn, "alert", ALERT_TO, f"New application: {role}, {a['name']}", text,
          email_shell("New team application", inner), REPLY_TO)


def smtp_ready():
    """True when outgoing email is configured (kept under this name: the dashboard reads smtp_configured)."""
    if MAIL_TRANSPORT == "preview":
        return bool(MAIL_PREVIEW_DIR)
    if MAIL_TRANSPORT == "relay":
        return RELAY_URL.startswith("https://") and len(RELAY_TOKEN) >= 32
    return bool(SMTP_HOST) and (not SMTP_USER or bool(SMTP_PASS))


def html_for_url(html):
    return html.replace(f"cid:{LOGO_CID}", LOGO_URL).replace(OLD_LOGO_SRC, LOGO_URL)


def relay_mail(row):
    payload = {
        "from": MAIL_FROM, "fromName": sender_name(row), "to": row["to_addr"], "subject": row["subject"],
        "text": row["text_body"], "html": html_for_url(row["html_body"] or ""), "replyTo": REPLY_TO,
    }
    if row["unsub_token"]:
        payload["listUnsubscribe"] = f"<{PUBLIC_URL}/api/unsubscribe?t={row['unsub_token']}>"
    headers = {"content-type": "application/json", "authorization": f"Bearer {RELAY_TOKEN}",
               "user-agent": "dopehub-signup"}
    if "id" in row.keys():  # outbox rows (sqlite3.Row); the send-test dict has no id
        headers["idempotency-key"] = f"landing-outbox-{row['id']}-{row['created_at']}"
    req = urllib.request.Request(RELAY_URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            result = json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"relay HTTP {e.code}: {e.read(300).decode(errors='replace')}") from None
    if result.get("status") not in ("sent", "duplicate", "suppressed"):
        raise RuntimeError(f"relay: unexpected reply {result}")


def send_mail(row):
    if not delivery_allowed(row):
        return
    if MAIL_TRANSPORT == 'preview':
        folder = Path(MAIL_PREVIEW_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{row['id'] if 'id' in row.keys() else 'test'}-{row['kind']}"
        (folder / (name + '.html')).write_text(html_for_url(row['html_body']), encoding='utf-8')
        (folder / (name + '.json')).write_text(json.dumps({'from': MAIL_FROM, 'fromName': sender_name(row),
            'to': row['to_addr'], 'replyTo': REPLY_TO, 'subject': row['subject'], 'text': row['text_body']}, indent=2), encoding='utf-8')
        return
    if MAIL_TRANSPORT == "relay":
        return relay_mail(row)
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name(row), MAIL_FROM))
    msg["To"] = row["to_addr"]
    msg["Subject"] = row["subject"]
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=MAIL_FROM.split("@")[-1])
    msg["Reply-To"] = REPLY_TO
    if row["unsub_token"]:
        msg["List-Unsubscribe"] = f"<{PUBLIC_URL}/api/unsubscribe?t={row['unsub_token']}>, <mailto:{REPLY_TO}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(row["text_body"])
    if row["html_body"]:
        html = row["html_body"].replace(OLD_LOGO_SRC, f"cid:{LOGO_CID}")
        logo = None
        if f"cid:{LOGO_CID}" in html:
            try:
                with open(LOGO_FILE, "rb") as f:
                    logo = f.read()
            except OSError:
                html = html_for_url(html)  # no local copy: fall back to the hosted image
        msg.add_alternative(html, subtype="html")
        if logo:
            msg.get_payload()[1].add_related(logo, "image", "png", cid=f"<{LOGO_CID}>",
                                             filename="dopehub-logo.png", disposition="inline")
    ctx = ssl.create_default_context()
    if SMTP_SECURITY == "ssl":
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=ctx)
    else:
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        if SMTP_SECURITY == "starttls":
            s.starttls(context=ctx)
    try:
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except Exception:
            pass


def mailer():
    while True:
        _wake.wait(20)
        _wake.clear()
        if not smtp_ready():
            continue
        try:
            with db() as conn:
                rows = conn.execute("SELECT * FROM outbox WHERE sent_at IS NULL AND attempts < 8 AND next_try <= ? "
                                    "ORDER BY id LIMIT 20", (time.time(),)).fetchall()
            for row in rows:
                try:
                    send_mail(row)
                    with db() as conn:
                        conn.execute("UPDATE outbox SET sent_at=?, last_error='' WHERE id=?", (now(), row["id"]))
                except Exception as e:  # retry with backoff: 1, 2, 4 ... minutes
                    wait = 60 * (2 ** row["attempts"])
                    with db() as conn:
                        conn.execute("UPDATE outbox SET attempts=attempts+1, next_try=?, last_error=? WHERE id=?",
                                     (time.time() + wait, str(e)[:300], row["id"]))
                    sys.stderr.write(f"mail {row['id']} failed: {e}\n")
                time.sleep(1)
        except Exception as e:
            sys.stderr.write(f"mailer error: {e}\n")


# ---------------------------------------------------------------- admin queries
def summary():
    with db() as conn:
        q = lambda sql, *a: conn.execute(sql, a).fetchall()
        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        since = (date.today() - timedelta(days=59)).isoformat()
        since30 = (date.today() - timedelta(days=29)).isoformat()
        subs_day = {r[0]: r[1] for r in q("SELECT substr(created_at,1,10) d, COUNT(*) FROM subscribers WHERE d >= ? GROUP BY d", since)}
        apps_day = {r[0]: r[1] for r in q("SELECT substr(created_at,1,10) d, COUNT(*) FROM applications WHERE d >= ? GROUP BY d", since)}
        hits_day = {r[0]: (r[1], r[2]) for r in q("SELECT day, COUNT(*), SUM(unique_visit) FROM hits WHERE day >= ? GROUP BY day", since)}
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(59, -1, -1)]
        visitors30 = one("SELECT COALESCE(SUM(unique_visit),0) FROM hits WHERE day >= ?", since30)
        subs30 = one("SELECT COUNT(*) FROM subscribers WHERE substr(created_at,1,10) >= ?", since30)
        survey_counts = {k: 0 for k in SURVEY}
        others = []
        for r in q("SELECT answers, other FROM survey"):
            for a in filter(None, r[0].split(",")):
                if a in survey_counts:
                    survey_counts[a] += 1
            if r[1]:
                others.append(r[1])
        return {
            "smtp_configured": smtp_ready(),
            "subscribers": {
                "total": one("SELECT COUNT(*) FROM subscribers"),
                "confirmed": one("SELECT COUNT(*) FROM subscribers WHERE confirmed_at IS NOT NULL"),
                "who": {r[0] or "not given": r[1] for r in q("SELECT who, COUNT(*) FROM subscribers GROUP BY who")},
            },
            "survey": {"responses": one("SELECT COUNT(*) FROM survey"),
                       "counts": [{"key": k, "label": SURVEY[k], "n": n} for k, n in survey_counts.items()],
                       "other": others[-30:][::-1]},
            "applications": {
                "total": one("SELECT COUNT(*) FROM applications"),
                "new": one("SELECT COUNT(*) FROM applications WHERE status='new'"),
                "roles": [{"key": r[0], "label": ROLES.get(r[0], r[0]), "n": r[1]}
                          for r in q("SELECT role, COUNT(*) FROM applications GROUP BY role ORDER BY 2 DESC")],
            },
            "visits": {
                "visitors30": visitors30, "pageviews30": one("SELECT COUNT(*) FROM hits WHERE day >= ?", since30),
                "conversion30": round(100 * subs30 / visitors30, 1) if visitors30 else None,
                "referrers": [{"k": r[0], "n": r[1]} for r in q(
                    "SELECT CASE WHEN source != '' THEN source WHEN referrer != '' THEN referrer ELSE 'Direct' END k, "
                    "SUM(unique_visit) n FROM hits WHERE day >= ? GROUP BY k ORDER BY n DESC LIMIT 8", since30)],
                "devices": [{"k": r[0] or "unknown", "n": r[1]} for r in q(
                    "SELECT device, SUM(unique_visit) FROM hits WHERE day >= ? GROUP BY device ORDER BY 2 DESC", since30)],
            },
            "daily": [{"d": d, "subs": subs_day.get(d, 0), "apps": apps_day.get(d, 0),
                       "views": hits_day.get(d, (0, 0))[0], "visitors": hits_day.get(d, (0, 0))[1] or 0} for d in days],
            "outbox": {"queued": one("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL AND attempts < 8"),
                       "failed": one("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL AND attempts >= 8"),
                       "last_error": (conn.execute("SELECT last_error FROM outbox WHERE last_error != '' AND sent_at IS NULL "
                                                   "ORDER BY id DESC LIMIT 1").fetchone() or [""])[0]},
        }


def export_csv(table):
    cols = {"subscribers": "id, email, who, newsletter, beta, CASE WHEN confirmed_at IS NULL THEN 'no' ELSE 'yes' END AS confirmed, confirmed_at, consent_version, created_at",
            "applications": "id, created_at, status, name, email, role, availability, link, message, consent_version",
            "survey": "survey.id, subscribers.email, survey.answers, survey.other, survey.created_at"}[table]
    frm = "survey JOIN subscribers ON subscribers.id = survey.subscriber_id" if table == "survey" else table
    out = io.StringIO()
    w = csv.writer(out)
    with db() as conn:
        cur = conn.execute(f"SELECT {cols} FROM {frm} ORDER BY 1")
        w.writerow([c[0] for c in cur.description])
        for row in cur:
            w.writerow(["'" + v if isinstance(v, str) and v and v[0] in "=+-@\t\r" else v for v in row])
    return out.getvalue()


def forget(email):
    e = email.strip().lower()
    with _lock, db() as conn:
        a = conn.execute("DELETE FROM subscribers WHERE email = ?", (e,)).rowcount
        b = conn.execute("DELETE FROM applications WHERE email = ?", (e,)).rowcount
        c = conn.execute("DELETE FROM outbox WHERE to_addr = ? OR reply_to = ?", (e, e)).rowcount
    return a, b, c


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "dopehub-signup"
    sys_version = ""

    def log_message(self, fmt, *args):  # no IPs, no query strings (tokens)
        sys.stderr.write("%s %s %s\n" % (self.command, urlsplit(self.path).path, args[1] if len(args) > 1 else ""))

    def client_ip(self):
        xff = self.headers.get("X-Forwarded-For", "")
        return (xff.split(",")[0].strip() if xff else "") or self.client_address[0]

    def reply(self, code, obj=None, ctype="application/json; charset=utf-8", body=None, extra=None):
        if body is None:
            body = json.dumps(obj if obj is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def is_admin(self):
        s = self.headers.get("X-Admin-Secret", "")
        return bool(ADMIN_SECRET) and hmac.compare_digest(s, ADMIN_SECRET)

    def read_body(self, allow_form=False):
        ctype = self.headers.get("Content-Type") or ""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length < 0 or length > MAX_BODY:
            raise ValueError("size")
        raw = self.rfile.read(length) if length else b""
        if "application/json" in ctype:
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("json")
            return data
        if allow_form:
            return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
        raise ValueError("ctype")

    # ---------- GET
    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/api/health":
            return self.reply(200, {"ok": True})
        if u.path.startswith("/admin/api/"):
            if not self.is_admin():
                return self.reply(403, {"error": "Forbidden."})
            if u.path == "/admin/api/summary":
                return self.reply(200, summary())
            if u.path == "/admin/api/applications":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute(
                        "SELECT id, name, email, role, availability, link, message, status, created_at FROM applications ORDER BY id DESC")]
                for r in rows:
                    r["role_label"], r["availability_label"] = ROLES.get(r["role"], r["role"]), AVAIL.get(r["availability"], r["availability"])
                return self.reply(200, {"applications": rows, "statuses": ["new", "contacted", "interview", "accepted", "declined"]})
            m = re.fullmatch(r"/admin/api/export/(subscribers|applications|survey)\.csv", u.path)
            if m:
                body = ("﻿" + export_csv(m.group(1))).encode("utf-8")
                return self.reply(200, ctype="text/csv; charset=utf-8", body=body, extra={
                    "Content-Disposition": f'attachment; filename="dopehub-{m.group(1)}-{date.today().isoformat()}.csv"'})
        self.reply(404, {"error": "Not found."})

    do_HEAD = do_GET

    # ---------- POST
    def do_POST(self):
        u = urlsplit(self.path)
        path = u.path
        if path.startswith("/admin/api/"):
            return self.admin_post(path)
        if path not in LIMITS:
            return self.reply(404, {"error": "Not found."})
        origin = self.headers.get("Origin")
        one_click = path == "/api/unsubscribe" and "t" in parse_qs(u.query)
        if origin and origin not in ALLOWED_ORIGINS and not one_click:
            return self.reply(403, {"error": "Forbidden."})
        if not LIMITS[path].allow(self.client_ip()):
            return self.reply(429, {"error": "Too many attempts. Please try again later."})
        try:
            data = self.read_body(allow_form=one_click)
        except (ValueError, UnicodeDecodeError) as e:
            return self.reply(413 if str(e) == "size" else 415 if str(e) == "ctype" else 400, {"error": "Invalid request."})
        try:
            if path == "/api/hit":
                return self.hit(data)
            if path == "/api/confirm":
                return self.confirm(data)
            if path == "/api/unsubscribe":
                return self.unsubscribe(parse_qs(u.query).get("t", [""])[0] if one_click else data.get("token"))
            if path == "/api/survey":
                return self.survey(data)
            if clean(data.get("website"), 200):  # honeypot
                return self.reply(200, {"ok": True})
            if data.get("consent") is not True:
                return self.reply(400, {"error": "Please confirm you're 18 or over and agree to the privacy notice."})
            if path == "/api/subscribe":
                return self.subscribe(data)
            return self.apply(data)
        except sqlite3.Error as e:
            sys.stderr.write("db error: %s\n" % e)
            return self.reply(500, {"error": "Something went wrong on our side. Please try again."})

    def subscribe(self, data):
        email = clean(data.get("email"), 254).lower()
        if not valid_email(email):
            return self.reply(400, {"error": "Please enter a valid email address."})
        # Old cached pages retain their original combined-consent contract.
        legacy = 'newsletter' not in data and 'beta' not in data
        newsletter, beta = (True, True) if legacy else (data.get('newsletter'), data.get('beta'))
        if type(newsletter) is not bool or type(beta) is not bool or not (newsletter or beta):
            return self.reply(400, {"error": "Choose the newsletter, a beta invitation, or both."})
        with _lock, db() as conn:
            row = conn.execute("SELECT * FROM subscribers WHERE email=?", (email,)).fetchone()
            if row is None:
                token = secrets.token_urlsafe(24)
                conn.execute("INSERT INTO subscribers(email,who,consent_version,created_at,token,newsletter,beta,newsletter_token,beta_token) VALUES (?,?,?,?,?,0,0,?,?)",
                    (email, clean(data.get('who'),20) if clean(data.get('who'),20) in WHO else '', CONSENT_VERSION,now(),token,secrets.token_urlsafe(24),secrets.token_urlsafe(24)))
                row = conn.execute("SELECT * FROM subscribers WHERE email=?", (email,)).fetchone()
            same = row['confirmed_at'] and row['newsletter'] == newsletter and row['beta'] == beta
            if not same and time.time() - row['last_mail_at'] > 900:
                request_token = secrets.token_urlsafe(24)
                conn.execute("DELETE FROM preference_requests WHERE subscriber_id=?", (row['id'],))
                conn.execute("DELETE FROM outbox WHERE to_addr=? AND kind='confirm' AND sent_at IS NULL", (email,))
                conn.execute("INSERT INTO preference_requests(token,subscriber_id,newsletter,beta,expires_at) VALUES (?,?,?,?,?)",
                             (request_token,row['id'],newsletter,beta,time.time()+7*86400))
                conn.execute("UPDATE subscribers SET last_mail_at=? WHERE id=?", (time.time(),row['id']))
                queue_confirm(conn,email,request_token,newsletter,beta,row['token'])
            sid = row['id']
        st = secrets.token_urlsafe(18)
        SURVEY_TOKENS[st] = (sid, time.time()+3600)
        for key in [k for k,v in list(SURVEY_TOKENS.items()) if v[1] < time.time()]:
            SURVEY_TOKENS.pop(key,None)
        return self.reply(200, {"ok": True, "survey": st})

    def confirm(self, data):
        token = clean(data.get('token'),64)
        if not TOKEN_RE.match(token):
            return self.reply(400, {"error": "This link isn't valid."})
        with _lock, db() as conn:
            request = conn.execute("SELECT * FROM preference_requests WHERE token=?", (token,)).fetchone()
            if request:
                if request['consumed_at']:
                    return self.reply(200, {"ok": True})
                if request['expires_at'] < time.time():
                    return self.reply(400, {"error": "This confirmation expired. Please sign up again for a fresh link."})
                conn.execute("UPDATE subscribers SET newsletter=?,beta=?,confirmed_at=COALESCE(confirmed_at,?),consent_version=? WHERE id=?",
                             (request['newsletter'],request['beta'],now(),CONSENT_VERSION,request['subscriber_id']))
                conn.execute("UPDATE preference_requests SET consumed_at=? WHERE token=?", (now(),token))
                return self.reply(200, {"ok": True})
            # Existing confirmation links keep working without changing their original tokens.
            row = conn.execute("SELECT * FROM subscribers WHERE token=?", (token,)).fetchone()
            if row and row['consent_version'] != CONSENT_VERSION:
                conn.execute("UPDATE subscribers SET confirmed_at=COALESCE(confirmed_at,?) WHERE id=?", (now(),row['id']))
                return self.reply(200, {"ok": True})
        return self.reply(404, {"error": "This link is no longer active. Please request a new confirmation."})

    def unsubscribe(self, token):
        token = clean(token,64)
        if not TOKEN_RE.match(token):
            return self.reply(400, {"error": "This link isn't valid."})
        message = 'These email preferences have been removed.'
        with _lock, db() as conn:
            row = conn.execute("SELECT * FROM subscribers WHERE token=? OR newsletter_token=? OR beta_token=?", (token,token,token)).fetchone()
            if row:
                conn.execute("DELETE FROM preference_requests WHERE subscriber_id=?", (row['id'],))
                if token == row['token']:
                    conn.execute("DELETE FROM subscribers WHERE id=?", (row['id'],))
                    conn.execute("DELETE FROM outbox WHERE to_addr=? AND sent_at IS NULL", (row['email'],))
                    message = 'Your combined signup and pending messages have been removed.'
                else:
                    newsletter = token == row['newsletter_token']
                    column = 'newsletter' if newsletter else 'beta'
                    conn.execute(f"UPDATE subscribers SET {column}=0 WHERE id=?", (row['id'],))
                    kinds = ('newsletter','launch','confirm') if newsletter else ('beta_invite','confirm')
                    conn.execute("DELETE FROM outbox WHERE to_addr=? AND sent_at IS NULL AND kind IN (" + ','.join('?' for _ in kinds) + ')', (row['email'],*kinds))
                    message = 'Newsletter emails stopped. Your beta preference is unchanged.' if newsletter else 'Beta messages stopped. Your newsletter preference is unchanged.'
                    remaining = conn.execute("SELECT newsletter,beta FROM subscribers WHERE id=?", (row['id'],)).fetchone()
                    if not remaining['newsletter'] and not remaining['beta']:
                        conn.execute("DELETE FROM subscribers WHERE id=?", (row['id'],))
                        conn.execute("DELETE FROM outbox WHERE to_addr=? AND kind IN ('confirm','newsletter','launch','beta_invite')", (row['email'],))

        return self.reply(200, {"ok": True, "message": message})

    def survey(self, data):
        st = clean(data.get("token"), 64)
        entry = SURVEY_TOKENS.pop(st, None)
        if not entry or entry[1] < time.time():
            return self.reply(400, {"error": "This survey has expired. Thanks anyway!"})
        answers = data.get("answers") if isinstance(data.get("answers"), list) else []
        answers = sorted({a for a in answers if isinstance(a, str) and a in SURVEY})
        other = clean(data.get("other"), 200)
        if not answers and not other:
            SURVEY_TOKENS[st] = entry
            return self.reply(400, {"error": "Pick at least one option."})
        with _lock, db() as conn:
            conn.execute("INSERT INTO survey(subscriber_id, answers, other, created_at) VALUES (?,?,?,?) "
                         "ON CONFLICT(subscriber_id) DO UPDATE SET answers=excluded.answers, other=excluded.other",
                         (entry[0], ",".join(answers), other, now()))
        return self.reply(200, {"ok": True})

    def apply(self, data):
        a = {"name": clean(data.get("name"), 100), "email": clean(data.get("email"), 254).lower(),
             "role": clean(data.get("role"), 20), "availability": clean(data.get("availability"), 10),
             "link": clean(data.get("link"), 300), "message": clean(data.get("message"), 1500)}
        if not a["name"]:
            return self.reply(400, {"error": "Please tell us your name."})
        if not valid_email(a["email"]):
            return self.reply(400, {"error": "Please enter a valid email address."})
        if a["role"] not in ROLES:
            return self.reply(400, {"error": "Please choose a role."})
        if a["availability"] not in AVAIL:
            return self.reply(400, {"error": "Please choose how much time you could give."})
        if a["link"] and not URL_RE.match(a["link"]):
            return self.reply(400, {"error": "Links should start with https://"})
        if len(a["message"]) < 20:
            return self.reply(400, {"error": "Please tell us a little more about you."})
        with _lock, db() as conn:
            day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat()
            if conn.execute("SELECT COUNT(*) FROM applications WHERE email=? AND created_at > ?", (a["email"], day_ago)).fetchone()[0] >= 3:
                return self.reply(429, {"error": "We've already got your application. We'll be in touch."})
            conn.execute("INSERT INTO applications(name, email, role, availability, link, message, consent_version, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?)", (a["name"], a["email"], a["role"], a["availability"], a["link"],
                                                     a["message"], CONSENT_VERSION, now()))
            queue_alert(conn, a)
            queue_acknowledgement(conn, a)
        return self.reply(200, {"ok": True})

    def hit(self, data):
        ua = self.headers.get("User-Agent", "")
        if not ua or BOT_RE.search(ua):
            return self.reply(204, body=b"")
        path = clean(data.get("p"), 120) or "/"
        path = path if path.startswith("/") else "/"
        ref = re.sub(r"^www\.", "", clean(data.get("r"), 120).lower())
        if not re.fullmatch(r"[a-z0-9.-]{0,120}", ref) or ref.endswith("dopehub.net"):
            ref = ""
        src = re.sub(r"[^a-z0-9._-]", "", clean(data.get("s"), 40).lower())
        try:
            w = int(data.get("w") or 0)
        except (TypeError, ValueError):
            w = 0
        device = "" if not w else "mobile" if w < 640 else "tablet" if w < 1024 else "desktop"
        uniq = 1 if VISITORS.first_today(self.client_ip(), ua) else 0
        with _lock, db() as conn:
            conn.execute("INSERT INTO hits(day, path, referrer, source, device, unique_visit) VALUES (?,?,?,?,?,?)",
                         (date.today().isoformat(), path, ref, src, device, uniq))
        return self.reply(204, body=b"")

    def admin_post(self, path):
        if not self.is_admin():
            return self.reply(403, {"error": "Forbidden."})
        try:
            data = self.read_body()
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"error": "Invalid request."})
        m = re.fullmatch(r"/admin/api/applications/(\d+)", path)
        if m:
            status = clean(data.get("status"), 20)
            if status not in STATUSES:
                return self.reply(400, {"error": "Unknown status."})
            with _lock, db() as conn:
                n = conn.execute("UPDATE applications SET status=? WHERE id=?", (status, int(m.group(1)))).rowcount
            return self.reply(200 if n else 404, {"ok": bool(n)})
        if path == "/admin/api/forget":
            e = clean(data.get("email"), 254)
            if not valid_email(e.lower()):
                return self.reply(400, {"error": "Enter a valid email address."})
            a, b, c = forget(e)
            return self.reply(200, {"ok": True, "subscribers": a, "applications": b})
        return self.reply(404, {"error": "Not found."})


# ---------------------------------------------------------------- CLI
def cli(args):
    init_db()
    cmd = args[0]
    if cmd == "export" and len(args) == 2 and args[1] in ("subscribers", "applications", "survey"):
        sys.stdout.write(export_csv(args[1]))
    elif cmd == "stats":
        s = summary()
        print(f"Subscribers: {s['subscribers']['total']} ({s['subscribers']['confirmed']} confirmed)")
        for k, v in s["subscribers"]["who"].items():
            print(f"  {k}: {v}")
        print(f"Applications: {s['applications']['total']} ({s['applications']['new']} new)")
        for r in s["applications"]["roles"]:
            print(f"  {r['label']}: {r['n']}")
        print(f"Visitors (30 days): {s['visits']['visitors30']}, page views: {s['visits']['pageviews30']}")
        print(f"Emails queued: {s['outbox']['queued']}, failed: {s['outbox']['failed']}, "
              f"email configured ({MAIL_TRANSPORT}): {s['smtp_configured']}")
    elif cmd == "forget" and len(args) == 2:
        a, b, c = forget(args[1])
        print(f"Deleted {a} subscriber and {b} application record(s), {c} queued email(s)")
    elif cmd == "outbox":
        with db() as conn:
            for r in conn.execute("SELECT id, kind, to_addr, attempts, sent_at, last_error FROM outbox ORDER BY id DESC LIMIT 20"):
                print(dict(r))
    elif cmd == "retry":
        with db() as conn:
            n = conn.execute("UPDATE outbox SET attempts=0, next_try=0 WHERE sent_at IS NULL").rowcount
        print(f"{n} email(s) will be retried by the running service within a minute")
    elif cmd == "send-test" and len(args) == 2:
        if not smtp_ready():
            sys.exit("Email is not configured (see /etc/dopehub-signup/env)")
        send_mail({"kind": "test", "to_addr": args[1], "subject": "DopeHub test email", "reply_to": REPLY_TO, "unsub_token": "",
                   "text_body": "If you can read this, DopeHub email sending works.",
                   "html_body": email_shell("Test", "<p>If you can read this, DopeHub email sending works.</p>")})
        print("sent")
    else:
        print(__doc__)
        sys.exit(2)


def main():
    if len(sys.argv) > 1:
        return cli(sys.argv[1:])
    init_db()
    threading.Thread(target=mailer, daemon=True).start()
    _wake.set()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    sys.stderr.write(f"dopehub-signup listening on {HOST}:{PORT}, email via {MAIL_TRANSPORT} {'on' if smtp_ready() else 'off (emails queued)'}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
