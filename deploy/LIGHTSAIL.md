# Lightsail development deployment

As of October 8, 2026, the dev LMS uses the [Heroku deployment](HEROKU.md).
The old Lightsail instance, static IP, and deployment SSH key pair were removed
at the owner's request. A final full database backup is retained privately at
`~/.local/share/ai-tutor/deployments/lightsail-dev/final-database-backup.dump`.
The instructions below are an archive of that deployment.

Run the tutor and PostgreSQL on one Ubuntu 24.04 instance. The 2 GB Linux/IPv4
bundle is `small_3_0`, currently $12/month, billed by the hour. The development
instance is in `us-east-1`, near the Vercel development backend in `iad1`.
An attached static IP is included; an unattached static IP can incur charges.

The LMS integration lives on `ai-integration` in the existing frontend and
backend repositories. Deploy only `lms-frontend-dev` and `lms-backend-dev`,
under Hobby scope `husamemad60-9280`. These projects use manual CLI deployment.
Their stable development URLs are:

- https://lms-frontend-dev-eight.vercel.app
- https://lms-backend-dev.vercel.app

The Khawarzmi production projects and LMS `main` branches are separate targets.
Do not use their project IDs or environment configuration for this deployment.

## Tutor host

1. Give the instance a static IP. Expose TCP 80/443; restrict SSH to the operator.
   Keep PostgreSQL on `127.0.0.1:5434` and the API on `127.0.0.1:8092`.
2. Install Docker with Compose v2, Python 3.12, uv, Nginx, and Certbot.
3. Put the tutor checkout in `/opt/ai-tutor`. Install locked dependencies with
   `uv sync --locked --no-dev --python /usr/bin/python3`.
4. Create a separate random database password and tutor service token. Store
   provider settings and `DATABASE_URL` in `/etc/ai-tutor/tutor.env`, and
   `POSTGRES_PASSWORD` in `/etc/ai-tutor/compose.env`. Both files are root-owned,
   mode 600. Do not reuse the LMS production token or copy its student database.
5. Start `docker compose --env-file /etc/ai-tutor/compose.env up -d`. The database
   has `restart: unless-stopped` and a persistent Docker volume.
6. Load tutor settings into the operator shell, run `.venv/bin/ai-tutor init-db`,
   restore the private `db-data` release's books/chunks with `psql`, and run
   `.venv/bin/python scripts/migrate_lms.py`. Download the release on the trusted
   workstation and transfer it over SSH; GitHub credentials are unnecessary on
   the host. Restore books and chunks only, excluding existing chat histories.
7. Install the service user, systemd service, and journal configuration described
   in [OBSERVABILITY.md](OBSERVABILITY.md). The service uses one worker and limits
   simultaneous chat/voice generations to four.
8. Replace `tutor.example.com` in [nginx.conf.example](nginx.conf.example) with
   the tutor hostname, install it in Nginx, validate with `nginx -t`, and obtain
   a publicly trusted TLS certificate with Certbot. Chat requires buffering off
   and a timeout longer than the tutor's generation deadline. Confirm renewal
   is scheduled. Development can use a temporary IP-derived DNS hostname;
   choose an owned domain before relying on it for production.
9. Verify public `/health` returns `{"status":"ok","database":true}`. Reject
   unauthenticated `/api/books`; keep secrets and trusted identity headers on
   the backend. Inspect request/provider JSON events in the dedicated journal.

## Development LMS configuration

On `lms-backend-dev`, set `TUTOR_SERVICE_URL` to the tutor HTTPS origin and
`TUTOR_SERVICE_TOKEN` to its separate dev token. Keep the existing dev MongoDB
and JWT settings. `TUTOR_REQUEST_TIMEOUT_MS=150000`; the frontend origin must
be allowed by CORS.

On `lms-frontend-dev`, set
`REACT_APP_API_URL=https://lms-backend-dev.vercel.app/api`. Provider and tutor
credentials must not appear in any frontend variable or bundle.

Verify the linked project name and Hobby scope before running a CLI deployment.
In these two dev projects, `vercel --prod` updates the stable **dev project** URL;
it does not refer to the separate Khawarzmi production projects.

Test student login, grade-scoped books, sessions, streamed replies, history,
voice input/output, and rejected unauthenticated/spoofed requests. Local tests
are not a substitute for checking the hosted proxy path. Compare production
deployment IDs and remote LMS `main` commits before and after deployment.

Email monitoring still needs a separate monitor host and private SMTP settings.
This deployment does not automatically activate email alerts or backups.
Before production, configure backups and test restoration, verify representative
textbook answers, measure concurrent workload, and use a permanent hostname.

## Updates and teardown

Keep source/configuration changes in Git; secrets, SSH keys, and instance state
stay in private local storage. For tutor updates, transfer a new source archive,
sync locked dependencies, apply required migrations, and restart `ai-tutor`.
Do not overwrite the private environment files or database volume.

A stopped instance still incurs its bundle charge. To end the test and its
hosting charges, first preserve anything needed, then explicitly delete the dev
instance and release its static IP. Deletion is destructive; obtain the owner's
instruction before removing data. Also remove unused dev SSH key resources.

References: [Lightsail billing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html),
[static IPs](https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-static-ip-addresses-in-amazon-lightsail.html),
[Vercel Git configuration](https://vercel.com/docs/project-configuration/git-configuration).
