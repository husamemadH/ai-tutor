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

An external HTTPS monitor still needs its own host and SMTP configuration.
See [OBSERVABILITY.md](OBSERVABILITY.md) for the existing monitor. Point it at
the new origin when configured. Heroku logs are not a replacement for retained
backups or tested outage notifications.

Keep the Lightsail deployment available during verification. Removing its
instance or database is a separate destructive action; stopping an instance
does not end its monthly bundle charge.

References: [dyno sizes](https://devcenter.heroku.com/articles/dyno-sizes),
[Postgres plans](https://devcenter.heroku.com/articles/heroku-postgres-plans),
[student credit](https://www.heroku.com/github-students/),
[Python build behavior](https://devcenter.heroku.com/articles/python-behavior-in-heroku),
[request timeouts](https://devcenter.heroku.com/articles/request-timeout),
[database backups](https://devcenter.heroku.com/articles/heroku-postgres-backups).
