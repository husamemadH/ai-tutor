# Heroku deployment

Use one Basic web dyno and a separate Heroku Postgres Essential-0 database.
At the October 2026 list prices this is $7 + $5 = $12/month, covered by the
$13 monthly GitHub Student credit when no other Heroku charges consume it.
AI provider charges remain separate. Basic has 512 MB RAM and stays awake;
Essential-0 has 1 GB storage, 20 connections, and supports pgvector.

The API calls remote AI providers. It does not load AI models or all textbook
embeddings into the web dyno. Keep one worker and the existing four-generation
limit, and check memory under concurrent use before increasing capacity.
Ingestion and OCR run on the workstation, outside the web dyno.

## Active deployment — October 8, 2026

- App: `futurix-ai-tutor`, Heroku-24, US region, one Basic web dyno.
- API: https://futurix-ai-tutor-a23b549f1136.herokuapp.com
- Database: `postgresql-reticulated-51885`, Essential-0, PostgreSQL 17.10,
  pgvector 0.8.2. Restored 35 books and 5,836 chunks, covering grades 1–10;
  database size was approximately 47 MiB after import.
- The existing dev frontend at https://lms-frontend-dev-eight.vercel.app uses
  https://lms-backend-dev.vercel.app, whose tutor origin now points to Heroku.
  Futurix production deployments and repository `main` branches were unchanged.
- Hosting migration keeps Groq Whisper STT and Azure TTS. Testing or switching
  to Azure STT is separate work. The existing Azure trial expiry still applies;
  see [the resource migration plan](../FEATURE_IDEAS.md).
- Daily logical backups run at 02:00 UTC. Initial backup `b001` was downloaded
  and restored into an isolated local database; all 35 books, 5,836 chunks, and
  1,024-dimensional embeddings were verified. The temporary database was removed.
- Runtime memory logging is enabled. Four simultaneous real chat requests
  completed in 6.3–6.8 seconds, with persisted histories. The highest reported
  memory sample through those checks was about 74 MB of the 512 MB quota, with
  no swap, memory-limit errors, or router timeout errors. These are sampled
  measurements of a small test, not a maximum-capacity guarantee.
- All ten grade test accounts passed login and book filtering through the dev
  LMS. Chat, history, ownership checks, STT, and TTS passed through its proxy.
  The tutor suite passed 86 tests with the PostgreSQL tests enabled.

Private deployment state, configuration, backups, and verification reports are
on the operator workstation under
`~/.local/share/ai-tutor/deployments/heroku/`. Do not commit that directory.
The owner confirmed UptimeRobot activation on October 8 for the Heroku `/health`
URL and the confirmed email. Activation is recorded from that confirmation;
dashboard configuration and outage/recovery email delivery have not been
independently tested. The free plan checks every five minutes and sends
outage/recovery emails.
See [the monitoring guide](OBSERVABILITY.md). Lightsail was removed at the
owner's request after a final full database backup was saved locally.

## Build and configuration

Heroku's Python buildpack uses `.python-version`, `pyproject.toml`, and
`uv.lock`. The `Procfile` starts Uvicorn on Heroku's assigned port and runs
schema initialization plus the existing ownership migration during release.
The app accepts Heroku's PostgreSQL URL and selects its installed psycopg driver.

Create an app on the `heroku-24` stack in the `us` region, provision
`heroku-postgresql:essential-0` with PostgreSQL 17, and select a Basic web dyno.
Use the account that has the student credit. Before adding resources, check
existing app and add-on charges against the monthly allowance.

Set provider keys and tutor behavior through private Heroku config vars.
Preserve Heroku's managed `DATABASE_URL`; credentials can rotate. Set a private
`TUTOR_SERVICE_TOKEN`, `TUTOR_DIALECT=msa`, `TUTOR_MAX_CONCURRENT=4`, and the
current chat, embedding, STT, and TTS settings. Keep secrets out of Git and
terminal output. Provider changes are separate from this hosting migration.

Deploy the reviewed tutor commit, then restore only `books` and `chunks` from
the private `db-data` release into the empty database. Do not run OCR again or
copy local test conversations. PDFs are unnecessary for serving existing books.
Verify restored counts and grade coverage before connecting the LMS.

## Verification and operation

Verify HTTPS `/health`, rejection of unauthenticated requests, grade-scoped
books, session ownership, streamed replies, saved history, and voice endpoints.
Measure memory and latency with concurrent requests on the actual dyno.
Heroku's router requires an initial response within 30 seconds and subsequent
stream traffic within its idle timeout. Check both chat streaming and complete
STT/TTS responses through the hosted LMS proxy.

Connect the existing Futurix development backend to the new tutor origin and
verify the complete student flow there. Production LMS repositories and
projects remain separate deployment targets.

Enable daily logical backups with `heroku pg:backups:schedule DATABASE_URL
--at '02:00 UTC' --app APP`, capture an initial backup, and verify a restore into
an isolated local database. Use `heroku logs --tail --app APP` for the tutor's
structured request/provider events. Chat text stays in PostgreSQL; audio is
not stored. Heroku's temporary filesystem is unsuitable for persistent data.

The selected hosted uptime monitor runs externally and delivers email itself.
The existing Python monitor in [OBSERVABILITY.md](OBSERVABILITY.md) remains an
alternative requiring its own host and SMTP configuration. Heroku logs are not
a replacement for retained backups or tested outage notifications.

The previous Lightsail deployment was deleted on October 8, including its
static IP and SSH key pair. Its final full database backup is retained privately
at `~/.local/share/ai-tutor/deployments/lightsail-dev/final-database-backup.dump`.

References: [dyno sizes](https://devcenter.heroku.com/articles/dyno-sizes),
[Postgres plans](https://devcenter.heroku.com/articles/heroku-postgres-plans),
[student credit](https://www.heroku.com/github-students/),
[Python build behavior](https://devcenter.heroku.com/articles/python-behavior-in-heroku),
[request timeouts](https://devcenter.heroku.com/articles/request-timeout),
[database backups](https://devcenter.heroku.com/articles/heroku-postgres-backups).
