import json
import os
import smtplib
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_health(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MONITOR_HEALTH_URL must be a plain HTTPS health endpoint")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            data = json.loads(response.read(4097))
            return (
                response.status == 200
                and data.get("status") == "ok"
                and data.get("database") is True
            )
    except (OSError, ValueError, AttributeError):
        return False


def send_email(recovered: bool) -> None:
    message = EmailMessage()
    message["From"] = os.environ["MONITOR_EMAIL_FROM"]
    message["To"] = os.environ["MONITOR_EMAIL_TO"]
    message["Subject"] = "AI Tutor recovered" if recovered else "AI Tutor unavailable"
    message.set_content(
        "The AI Tutor health endpoint is healthy again."
        if recovered
        else "The AI Tutor health endpoint failed repeated checks. Check the service and database logs."
    )
    host = os.environ["MONITOR_SMTP_HOST"]
    port = int(os.environ.get("MONITOR_SMTP_PORT", "465"))
    username = os.environ.get("MONITOR_SMTP_USER", "")
    password = os.environ.get("MONITOR_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise ValueError("SMTP username and password must be configured together")
    with smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context()) as smtp:
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def update_state(state: dict, healthy: bool, threshold: int, notify) -> dict:
    state = dict(state)
    state["failures"] = 0 if healthy else state.get("failures", 0) + 1
    if healthy and state.get("notified", False):
        notify(True)
        state["notified"] = False
    elif not healthy and state["failures"] >= threshold and not state.get("notified", False):
        notify(False)
        state["notified"] = True
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(state, file)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    try:
        for key in ("MONITOR_EMAIL_FROM", "MONITOR_EMAIL_TO", "MONITOR_SMTP_HOST"):
            if not os.environ.get(key):
                raise ValueError("Email monitor configuration is incomplete")
        url = os.environ["MONITOR_HEALTH_URL"]
        threshold = int(os.environ.get("MONITOR_FAILURE_THRESHOLD", "3"))
        if threshold < 1:
            raise ValueError("Failure threshold must be positive")
        path = Path(os.environ.get("MONITOR_STATE_FILE", "/var/lib/ai-tutor-monitor/state.json"))
        state = (
            json.loads(path.read_text()) if path.exists() else {"failures": 0, "notified": False}
        )
        healthy = check_health(url)
        updated = update_state(state, healthy, threshold, send_email)
        save_state(path, updated)
        print(
            json.dumps(
                {
                    "event": "health_checked",
                    "healthy": healthy,
                    "consecutive_failures": updated["failures"],
                    "outage_notified": updated.get("notified", False),
                }
            )
        )
        return 0 if healthy else 1
    except (OSError, ValueError, KeyError, smtplib.SMTPException) as exc:
        print(json.dumps({"event": "monitor_failed", "reason": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
