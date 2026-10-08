# Operating the tutor

The API writes one JSON event when a request finishes, and one per provider
attempt. Events share a generated `request_id`, also returned as `X-Request-ID`.
They include the route template, status, outcome, duration, and safe failure
category. Chat requests also include time to first answer text. Logging wraps
the full streaming response without buffering its content.

`outcome` distinguishes completed replies, failed replies, cancelled work,
requests rejected by validation/authentication, and a busy service. A streamed
reply can have HTTP status 200 and outcome `failed`. `response_complete` records
whether the response body finished sending; a committed reply may complete even
if its final event cannot reach a disconnected client.

Provider events identify OpenRouter chat/embeddings, Groq STT, and Azure TTS, with
model/voice, status, outcome, duration, and the same request ID. Retries and TTS
chunks produce separate events. OpenRouter usage fields are recorded when
supplied: token counts and reported `cost`. Missing usage stays absent; it does
not imply zero cost. Incomplete provider calls may still incur charges. Billing
dashboards remain the source for reconciling provider spend.

These events exclude keys, headers, query strings, raw paths, student/school IDs,
session IDs, prompts, retrieved textbook passages, replies, SSML, recordings, and
exception messages. They are operational evidence, not an assessment of answer
correctness. They currently cover the tutor process, not the LMS proxy.

## Retained logs on the tutor host

The checked-in systemd unit is a deployment template, not a local installation.
It runs one API worker on loopback, disables Uvicorn's ordinary access log,
restarts failures, and writes to a dedicated `ai-tutor` journal namespace.
The namespace is capped at 100 MB and seven days. It uses systemd 246 or later.

Prepare `/opt/ai-tutor` with its `.venv`, database, books, and migrations. Create
the service user and keep configuration in a root-owned, mode-600 environment
file. The environment file must contain the actual database/provider settings
and shared LMS service token; `.env.example` is only a template.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin ai-tutor
sudo install -d -m 700 /etc/ai-tutor
sudo install -m 600 /path/to/private-tutor.env /etc/ai-tutor/tutor.env
sudo install -m 644 deploy/ai-tutor.service /etc/systemd/system/ai-tutor.service
sudo install -m 644 deploy/journald@ai-tutor.conf /etc/systemd/journald@ai-tutor.conf
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald@ai-tutor.service
sudo systemctl enable --now ai-tutor.service
```

The service user needs read/execute access to the checkout and virtualenv.
The unit uses a read-only filesystem; application data lives in PostgreSQL.
Provision HTTPS through the host's reverse proxy before connecting the LMS.
These templates do not provision that proxy, the database, or backups.

View the last hour or follow new events:

```bash
sudo journalctl --namespace=ai-tutor -u ai-tutor --since '1 hour ago' -o cat
sudo journalctl --namespace=ai-tutor -u ai-tutor -f -o cat
```

Filter structured events if `jq` is available:

```bash
sudo journalctl --namespace=ai-tutor -u ai-tutor --since '1 hour ago' -o cat |
  jq -R 'fromjson? | select(.outcome == "failed")'
```

The normal journal also contains process start/stop records. Logs here are local
to this server; the independent monitor below reports outages when the server
cannot be reached.

## External health check with email alerts

### Hosted monitor for Heroku

The selected option is UptimeRobot's free hosted HTTPS monitor for:

`https://futurix-ai-tutor-eu-4841b97391f8.herokuapp.com/health`

On October 8, 2026, the owner confirmed activation and receipt of both outage
and recovery emails during a controlled Heroku maintenance test. The public
health URL returned HTTP 503 during the outage, then HTTP 200 with `status: ok`
and `database: true` after restoration. An independent watchdog limited the
test outage to seven minutes; the service was restored after about two minutes.
Email delivery is verified by the owner's confirmation, without dashboard access.
This test used the original US deployment. After migration to Europe later that
day, the owner confirmed changing the existing monitor to the URL above while
keeping email alerts enabled. The European endpoint passed its health check;
no second deliberate outage was performed after the URL change.
For future setup, opening the email link alone does not
create the monitor: the owner must also click **Activate** on the confirmation
page. Submission HTTP 200 alone does not prove activation.

The free plan checks every five minutes. A confirmed unreachable endpoint or
unhealthy HTTP status triggers an outage email; recovery triggers another.
The tutor returns HTTP 503 when its database health check fails, so this covers
both service and database availability. This monitor does not call paid AI
providers, inspect student conversations, or detect wrong answers. Provider
failures remain visible in the tutor logs.

UptimeRobot runs the checks and handles email delivery. No monitor process has
been installed on Heroku. After activation, verify the dashboard has the correct
URL, expected healthy status, and enabled email contact. Repeat the delivery test
after changing the monitored URL or notification contact.

Reference: [UptimeRobot setup and activation](https://uptimerobot.com/quick-monitor-setup/),
[free-plan monitoring interval](https://help.uptimerobot.com/en/articles/11360876-what-is-a-monitoring-interval-in-uptimerobot).

### Existing Python monitor alternative

Install the monitor on a separate, continuously running machine. Running it on
the tutor host would miss a whole-server outage. `scripts/check_health.py` uses
only Python's standard library and performs one bounded HTTPS request per run.
It follows no redirects and requires HTTP 200 with `status: ok` and
`database: true`. It does not call paid AI providers.

The timer checks approximately once per minute. Three consecutive failures
send one outage email. Further failures do not repeat it. The next healthy
check sends one recovery email. State survives restarts, and a failed email is
retried on subsequent checks. A delivery failure logs `monitor_failed` on the
monitor machine; email cannot notify about failure of its own delivery channel.

The monitor needs the public tutor HTTPS URL, a recipient address, and an SMTP
relay supporting implicit TLS (usually port 465), with sender and credentials.
No emails are sent until it is configured and run.

On the monitor host, copy `deploy/monitor.env.example` to a private file, fill
its settings, then install:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin ai-tutor-monitor
sudo install -d -m 755 /opt/ai-tutor-monitor
sudo install -d -m 700 /etc/ai-tutor-monitor
sudo install -m 644 scripts/check_health.py /opt/ai-tutor-monitor/check_health.py
sudo install -m 600 /path/to/private-monitor.env /etc/ai-tutor-monitor/monitor.env
sudo install -m 644 deploy/ai-tutor-monitor.service deploy/ai-tutor-monitor.timer /etc/systemd/system/
sudo install -m 644 deploy/journald@ai-tutor.conf /etc/systemd/journald@ai-tutor.conf
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald@ai-tutor.service
sudo systemctl enable --now ai-tutor-monitor.timer
```

Before relying on notifications, run a controlled outage and recovery on a test
endpoint and confirm both emails arrive. Then verify the timer and inspect logs:

```bash
sudo systemctl list-timers ai-tutor-monitor.timer
sudo journalctl --namespace=ai-tutor -u ai-tutor-monitor -o cat
```

The health endpoint checks service/database availability; an Azure, Groq, or
OpenRouter outage appears in provider/request logs and is not detected by this
uptime monitor. CPU/burst-capacity alarms can be added through Lightsail's
existing instance metrics once the host exists. App error-rate alerts and a
dashboard are separate later additions if usage calls for them.

References: [Starlette middleware](https://starlette.dev/middleware/),
[systemd journal configuration](https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html),
[systemd execution configuration](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
