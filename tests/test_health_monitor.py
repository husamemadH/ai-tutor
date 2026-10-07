import json
from contextlib import contextmanager
from pathlib import Path
from runpy import run_path

import pytest

monitor = run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_health.py"))


def test_alerts_after_three_failures_once_then_recovery():
    notifications = []
    state = {"failures": 0, "notified": False}
    for _ in range(5):
        state = monitor["update_state"](state, False, 3, notifications.append)
    assert notifications == [False]
    state = monitor["update_state"](state, True, 3, notifications.append)
    state = monitor["update_state"](state, True, 3, notifications.append)
    assert notifications == [False, True]
    assert state == {"failures": 0, "notified": False}


def test_intermittent_failure_does_not_send_email():
    notifications = []
    state = {"failures": 0, "notified": False}
    for healthy in [False, False, True, False, True]:
        state = monitor["update_state"](state, healthy, 3, notifications.append)
    assert notifications == []


@pytest.mark.parametrize("recovery", [False, True])
def test_failed_email_can_be_retried_without_changing_state(recovery):
    original = {"failures": 2, "notified": recovery}

    def broken_notify(recovered):
        raise OSError("private-smtp-password")

    with pytest.raises(OSError):
        monitor["update_state"](original, recovery, 3, broken_notify)
    assert original == {"failures": 2, "notified": recovery}
    notifications = []
    monitor["update_state"](original, recovery, 3, notifications.append)
    assert notifications == [recovery]


def test_monitor_state_is_private_and_replaced_atomically(tmp_path):
    path = tmp_path / "state.json"
    monitor["save_state"](path, {"failures": 1})
    monitor["save_state"](path, {"failures": 2})
    assert json.loads(path.read_text()) == {"failures": 2}
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/health",
        "https://key@example.test/health",
        "https://example.test/health?token=private",
    ],
)
def test_insecure_or_credential_containing_health_url_is_rejected(url):
    with pytest.raises(ValueError):
        monitor["check_health"](url)


@pytest.mark.parametrize(
    "status,body,healthy",
    [
        (200, {"status": "ok", "database": True}, True),
        (200, {"status": "degraded", "database": False}, False),
        (503, {"status": "ok", "database": True}, False),
        (200, "not a health object", False),
    ],
)
def test_health_probe_validates_status_and_database(monkeypatch, status, body, healthy):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            assert size == 4097
            return json.dumps(body).encode()

    class Opener:
        def open(self, request, timeout):
            assert timeout == 10
            response = Response()
            response.status = status
            return response

    monkeypatch.setattr(monitor["urllib"].request, "build_opener", lambda *args: Opener())
    assert monitor["check_health"]("https://example.test/health") is healthy


def test_email_uses_verified_tls_and_sends_expected_notification(monkeypatch):
    calls = []
    for key, value in {
        "MONITOR_EMAIL_FROM": "monitor@example.test",
        "MONITOR_EMAIL_TO": "owner@example.test",
        "MONITOR_SMTP_HOST": "smtp.example.test",
        "MONITOR_SMTP_USER": "user",
        "MONITOR_SMTP_PASSWORD": "private-password",
    }.items():
        monkeypatch.setenv(key, value)

    class SMTP:
        def login(self, username, password):
            calls.append("login")

        def send_message(self, message):
            calls.append(message)

    @contextmanager
    def connect(host, port, timeout, context):
        assert host == "smtp.example.test" and port == 465 and timeout == 10
        assert context.check_hostname
        yield SMTP()

    monkeypatch.setattr(monitor["smtplib"], "SMTP_SSL", connect)
    monitor["send_email"](False)
    assert calls[0] == "login"
    assert calls[1]["Subject"] == "AI Tutor unavailable"
    assert calls[1]["To"] == "owner@example.test"
