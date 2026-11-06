# Job Board API

A Django REST API where companies post jobs and candidates apply with a resume. It has:
- JWT auth with two user types, and role and ownership permissions;
- skill match scoring, and resume storage in S3;
- cached job search;
- a background worker that emails candidates when their application status changes.

It's built to be operated: health and readiness probes, Prometheus metrics, JSON logs, configuration from environment variables only, and a non-root production image. Stack: PostgreSQL, Redis, SQS, gunicorn and Docker.

> **Status:** Phase 4 (operations-ready) complete. Runs locally, with S3 and SQS emulated by LocalStack. Automated tests, the Azure path and cloud deployment come in later phases.

## Architecture

```text
Client (curl / frontend)                         Kubernetes probes / Prometheus (later)
   │  JWT (Authorization: Bearer <token>)              │  /healthz  /readyz  /metrics
   ▼                                                   ▼
┌──────────────────────────────────── Docker Compose ─────────────────────────────────────┐
│                                                                                         │
│  api  (Django 5.2 + DRF, port 8006)                                                     │
│   │   image default: gunicorn (1 process × 4 threads, non-root)                         │
│   │   Compose dev override: runserver + bind mount                                      │
│   ├── /api/auth/...          register, JWT tokens                                       │
│   ├── /api/jobs/...          search + filters (cached in Redis), post, update, applicants│
│   ├── /api/applications/...  apply with resume, detail + match score,                   │
│   │                          status change, resume download link                        │
│   ├── /healthz               liveness: process is up (checks nothing else)              │
│   ├── /readyz                readiness: Postgres (critical), Redis, SQS (~1 s each)     │
│   └── /metrics               requests, latency, DB queries (Prometheus format)          │
│        │     │     │                                                                    │
│        │     │     └──▶ redis      job-list cache (versioned keys, 60 s TTL)            │
│        │     └────────▶ localstack S3:  resumes bucket (private)                        │
│        │                           SQS:  job-board-status  ──▶  job-board-status-dlq    │
│        │                                   (status-change events)   (after 3 failures)  │
│        ▼  hostname "db"                        │                                        │
│  db   (PostgreSQL 17)  ◀───────────────────────┤                                        │
│        ▲                                       ▼ long poll                              │
│        └────────────────────────────── worker  (same image, python -m worker.run_worker)│
│                                          ├── claims event_id (ProcessedEvent, unique)   │
│                                          ├── sends status email (console backend)       │
│                                          └── survives queue outages, restarts on crash  │
│                                                                                         │
│  All processes: JSON logs on stdout; config only from environment variables             │
└─────────────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ presigned URL (5 min): client downloads the resume straight from S3
```

## Features

- Two user types (company, candidate) on a custom Django user model. The role is set by the signup endpoint, never by the client.
- JWT login: 15-minute access tokens, 1-day refresh tokens. Every endpoint needs a token unless it opts out.
- Four DRF permission classes:
  - verified companies post jobs, and candidates apply;
  - only the job's company edits it, sees its applicants or changes a status;
  - only the applicant and the job's company read an application or get its resume.
- Skill match score (0–100), case-insensitive, `null` when a job requires no skills.
- Resume upload: PDF or DOCX, 5 MB max, file content checked against its extension. Private S3 bucket, random keys, 5-minute presigned download links.
- Job search and filters: type, location, skills, free-text search, ordering. Invalid filter values return 400.
- **Cached job search:**
  - results are cached in Redis for 60 seconds;
  - the cache is invalidated immediately when any job or company changes (from the API, the admin or the shell);
  - responses carry an `X-Cache: HIT/MISS` header;
  - the API keeps working if Redis is down or frozen.
- **Background worker:** a status change publishes an event to SQS after the database commit, and a separate worker emails the candidate.
- **Reliable processing:**
  - at-least-once delivery with a 30-second visibility timeout;
  - a dead-letter queue after 3 failures;
  - graceful shutdown on `SIGTERM`;
  - **idempotent** handling, so a redelivered message never sends a second email.
- **Health and readiness probes:**
  - `/healthz` only says "the process is alive";
  - `/readyz` checks each dependency within about 1 second and returns `503` only if PostgreSQL is down. Redis and SQS failures are reported, but the API keeps serving.
- **Prometheus metrics** at `/metrics`: requests by view, method and status; latency histograms; database queries and errors.
- **Structured JSON logs** on stdout, from Django, the worker and gunicorn:
  - a traceback is one `exc_info` field;
  - the same `event_id` links the API's "queued" line to the worker's "emailed" line.
- **Configuration from environment variables only:**
  - a required variable that is missing **or empty** stops startup with a clear message;
  - safe defaults (`DEBUG` off, local hosts only);
  - the LocalStack token is visible only to the LocalStack container.
- **Production image:** multi-stage build, non-root user, read-only code, gunicorn as PID 1 with a graceful stop.
- **Resilience:**
  - every Redis and SQS call has a time limit;
  - the worker keeps running through queue outages;
  - API and worker restart automatically if they crash.

## Tech Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.12 |
| Framework | Django 5.2 LTS, Django REST Framework |
| Auth | djangorestframework-simplejwt |
| Filtering | django-filter, DRF SearchFilter / OrderingFilter |
| File storage | django-storages (S3 backend), boto3 |
| Database | PostgreSQL 17 (psycopg 3) |
| Cache | Redis 7.4 (Django's built-in `RedisCache`, redis-py) |
| Queue | Amazon SQS + dead-letter queue (boto3) |
| Email | Django email framework (console backend locally) |
| Web server | gunicorn 26 (`gthread`) in the image; Django `runserver` for local development |
| Metrics | django-prometheus (prometheus_client) |
| Logging | python-json-logger |
| Local AWS | LocalStack (S3, SQS) |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker (multi-stage, non-root), Docker Compose |

## Cloud Services

| Purpose | AWS | Azure |
| --- | --- | --- |
| Resume storage | S3 (LocalStack locally) | — (Azure phase: Blob Storage) |
| Status-change queue | SQS + DLQ (LocalStack locally) | — (Azure phase: Service Bus) |
| Job search cache | ElastiCache target (Redis container locally) | — (Azure phase: Azure Cache for Redis) |

No AWS resources are provisioned yet. They're created with Terraform in Project 01.

## API Endpoints

| Method | Path | Who | Description |
| --- | --- | --- | --- |
| POST | `/api/auth/register/company/` | public | Register a company account |
| POST | `/api/auth/register/candidate/` | public | Register a candidate account |
| POST | `/api/auth/token/` | public | Get an access and refresh token |
| POST | `/api/auth/token/refresh/` | public | Get a new access token |
| GET | `/api/jobs/` | any user | List open jobs (cached). Query: `job_type`, `location`, `skills=a,b`, `search`, `ordering`, `page` |
| POST | `/api/jobs/` | verified company | Post a job |
| GET | `/api/jobs/{id}/` | any user | Job detail |
| PUT / PATCH | `/api/jobs/{id}/` | job owner | Update or close a job |
| GET | `/api/jobs/{id}/applications/` | job owner | Applicants, with match scores |
| POST | `/api/applications/` | candidate | Apply (multipart, with `resume` file) |
| GET | `/api/applications/{id}/` | applicant or job owner | Application detail + match score |
| PATCH | `/api/applications/{id}/status/` | job owner | Change status; queues an email to the candidate |
| GET | `/api/applications/{id}/resume/` | applicant or job owner | Presigned resume download URL (5 min) |
| GET | `/healthz` | no token | Liveness: `200 {"status": "ok"}` |
| GET | `/readyz` | no token | Readiness: `200` or `503`, with per-dependency status and timing |
| GET | `/metrics` | no token | Prometheus metrics |

"Any user" means any logged-in user. Wrong user types get `403`; missing or expired tokens get `401`.

The three operations endpoints have no authentication, like most probe and scrape endpoints. They must not be exposed publicly: in Kubernetes, the Ingress will route only `/api/`.

## Setup

**Prerequisites:** Docker with Compose, [uv](https://docs.astral.sh/uv/), and a free LocalStack account (for its auth token). The project's `bootstrap.yml` (Ansible toolchain) is planned and not built yet.

```bash
git clone https://github.com/mohammadrezachegini/00-job-board-api.git
cd 00-job-board-api

cp .env.example .env
cp .env.localstack.example .env.localstack            # put your LocalStack auth token here
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # paste into DJANGO_SECRET_KEY in .env
chmod 600 .env .env.localstack

docker compose up -d --build        # api (runserver), worker, db, redis, localstack (creates the bucket and queues)
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

- API: `http://localhost:8006/api/`; admin: `http://localhost:8006/admin/`; probes: `/healthz`, `/readyz`; metrics: `/metrics`.
- Wait for `curl -s http://localhost:8006/healthz` to answer before testing. `docker compose up -d` returns before the server is listening.
- To reach the API from another machine, add the address that machine uses (e.g. the host's LAN IP) to `DJANGO_ALLOWED_HOSTS`.
- Companies must be verified (admin → Companies → "Is verified") before they can post jobs.
- Emails are printed to `docker compose logs worker` (console backend).
- The worker doesn't auto-reload: run `docker compose restart worker` after code changes.
- LocalStack keeps no data when its container is recreated: re-upload resumes afterwards.
- Stop: `docker compose down` (keeps the database). Delete the database too: `docker compose down -v`.

**Run the production image** (gunicorn, no source mount, env vars only):

```bash
docker compose build api
docker run -d --name jobboard-prod --network 00-job-board-api_default \
  --env-file .env -e DJANGO_DEBUG=False -p 127.0.0.1:8016:8006 00-job-board-api-api
curl -s http://localhost:8016/readyz
docker stop jobboard-prod && docker rm jobboard-prod
```

## Environment Variables

A variable with no default is **required**. If it's missing **or empty**, the app stops at startup with `Missing required environment variable: <NAME>`.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | yes | — | Signs sessions and JWTs |
| `DJANGO_DEBUG` | no | `False` | Debug mode (local only). `1/true/yes/on` = on; anything else = off |
| `DJANGO_ALLOWED_HOSTS` | no | `localhost,127.0.0.1` | Comma-separated host names clients use |
| `LOG_LEVEL` | no | `INFO` | Log level for Django, the app and gunicorn |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | yes | — | Database (also used by the Postgres container) |
| `POSTGRES_HOST` | yes | — | `db` inside Compose |
| `POSTGRES_PORT` | no | `5432` | |
| `REDIS_URL` | yes | — | Cache, e.g. `redis://redis:6379/0` |
| `AWS_REGION` | yes | — | Region for S3 and SQS |
| `AWS_STORAGE_BUCKET_NAME` | yes | — | Resume bucket |
| `AWS_S3_ENDPOINT_URL` | no | real S3 | Internal S3 address (`http://localstack:4566` locally) |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | no | same as above | Address used in presigned URLs (`http://localhost:4566` locally) |
| `AWS_SQS_ENDPOINT_URL` | no | real SQS | `http://localstack:4566` locally |
| `SQS_QUEUE_NAME` | yes | — | Status-change queue (`job-board-status`); its DLQ is `<name>-dlq` |
| `EMAIL_BACKEND` | no | console backend | Where emails go |
| `DEFAULT_FROM_EMAIL` | no | `Job Board <no-reply@jobboard.test>` | Sender address |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | local only | — | `test` / `test` for LocalStack. Not set on AWS (IAM role) |
| `PORT` | no | `8006` | gunicorn listen port (production image) |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | no | `1` / `4` | gunicorn processes and threads. Keep workers at 1: metrics are per process |
| `GUNICORN_TIMEOUT` | no | `30` | Seconds before a stuck worker is replaced |
| `LOCALSTACK_AUTH_TOKEN` | local only | — | In **`.env.localstack`**, read only by the LocalStack container (secret) |

`.env` and `.env.localstack` are ignored by git and kept out of the image. Write values without quotes: `docker run --env-file` keeps quotes literally.

## Testing

Automated tests (pytest, 80%+ coverage) are planned for Phase 5. Phases 1–4 were verified with manual checks over HTTP, in the Django shell, against Redis and SQS, and against the built image. The full list is in `docs/` (terminal checks).

Phase 4 checks included:
- **Readiness:**
  - PostgreSQL stopped → `/healthz` 200, `/readyz` 503;
  - Redis or SQS stopped or **frozen** (`docker compose pause`) → `/readyz` still 200 within about 1 second, with the failing dependency named.
- **The worker:** it kept running while SQS was down, and a worker started during an outage recovered on its own once SQS came back.
- **Metrics:** counters checked before and after a known number of requests.
- **Logs:** every line parsed as JSON, and one `event_id` traced from the API log to the worker log.
- **Configuration:**
  - missing and empty required variables stop startup;
  - an unknown `Host` header gets 400;
  - the image refuses to start with no environment at all.
- **The production image, with no source mount and env vars only:**
  - runs as a non-root user and can't write to its own code;
  - serves health, readiness, metrics and the API;
  - stops cleanly on `SIGTERM`.

## Project Structure

```text
00-job-board-api/
├── config/
│   ├── settings.py          ← config from env vars (required/optional, typed); DRF, JWT, S3, Redis, SQS, email, JSON logging
│   ├── urls.py              ← /api/, /healthz, /readyz, /metrics
│   └── wsgi.py              ← gunicorn entry point
├── jobs/
│   ├── models.py            ← User, Company, CandidateProfile, Job, Application, ProcessedEvent
│   ├── serializers.py
│   ├── views.py             ← JobViewSet (cached list), ApplicationViewSet (status → event)
│   ├── permissions.py       ← IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicationOwner
│   ├── matching.py          ← skill match score
│   ├── filters.py           ← JobFilter
│   ├── validators.py        ← resume checks
│   ├── storage.py           ← presigned download URLs
│   ├── cache.py             ← job-list cache keys and versioned invalidation
│   ├── signals.py           ← invalidate the cache when jobs or companies change
│   ├── events.py            ← publish status-change events on commit
│   ├── emails.py            ← status-change email
│   ├── templates/emails/status_changed.txt
│   ├── apps.py              ← registers signals
│   └── migrations/
├── cloud/
│   ├── queue.py             ← Queue interface + SQS implementation (timeouts, fast ping client)
│   └── health.py            ← /healthz and /readyz
├── worker/
│   └── run_worker.py        ← long-polls SQS, idempotent handling, survives outages, graceful shutdown
├── localstack/init/ready.d/
│   ├── create-bucket.sh
│   └── create-queues.sh     ← queue + DLQ with redrive policy
├── scripts/dev-helper.sh    ← local test helpers
├── docs/
├── Dockerfile               ← multi-stage (uv builder → slim runtime), non-root, gunicorn
├── gunicorn.conf.py         ← process model, timeouts, JSON logs
├── docker-compose.yml       ← api (runserver for dev), worker, PostgreSQL, Redis, LocalStack
├── .env.example / .env.localstack.example
├── pyproject.toml / uv.lock / .python-version
└── manage.py
```

`cloud/` is the spec's `platform/` package under a safe name: a top-level `platform` package would hide Python's built-in `platform` module.

## Design Decisions

- **Permissions as classes,** run before validation; 403 for non-owners.
- **Resumes in a private S3 bucket,** downloaded through short-lived presigned URLs.
- **Versioned cache keys:** one atomic `INCR` invalidates every cached search page; old keys expire on their own.
- **Side effects only after commit** (`transaction.on_commit`), for both cache invalidation and queue messages. A rolled-back change never invalidates the cache or emails anyone.
- **SQS locally through LocalStack,** not a Redis list: the same code runs locally and on AWS, with real redelivery and a DLQ.
- **Messages carry IDs, not personal data:** the worker reads current data from the database. Logs carry IDs too, never email addresses.
- **Idempotency in the database:** a unique `event_id` is claimed in the same transaction as the send. Duplicates are skipped, and failed sends release the claim.
- **A queue interface (`cloud/queue.py`),** so Azure Service Bus can replace SQS without touching the API or the worker.
- **Liveness checks nothing; readiness fails only on PostgreSQL.** A database outage takes instances out of traffic instead of restarting them in a loop. Redis and SQS problems are reported, because the API can work around them.
- **Every dependency call has a time budget:**
  - Redis socket timeouts;
  - a separate SQS client for health checks (1 s, one attempt, no retry);
  - a long-poll client with a 30 s read timeout.
- **One gunicorn process with threads per container;** scale with more containers. In-process Prometheus counters stay correct without multiprocess mode.
- **12-factor configuration:** what varies between deployments comes from the environment; tuning values that are the same everywhere stay in code.
- **Least privilege:** a non-root user, code owned by root, and secrets only in the container that needs them.
- **One image for development and production:** gunicorn by default, `runserver` through a Compose override.

## What Broke and How I Fixed It

**Phase 1**
- **Validators that never ran** (indented inside `class Meta`); duplicates were still blocked by a PostgreSQL unique constraint. The clue was the error shape: a string from the view instead of a list from the serializer.
- **Silent typos:** `getattr(user, "candidateprofile", None)`, an `@action` named `application`, `User.Role.Company`, `PYTHONBUFFERED`, and `create_at` (which became a rename migration).

**Phase 2**
- **A misspelled hook,** `get_permission`, let an unverified company post a job.
- **Every presigned URL failed,** because the fake AWS keys were `change-me` instead of LocalStack's `test`. Found from S3's XML error body.
- **A test that passed for the wrong reason:** a tampered link returned 403, but so did the valid one.
- Also:
  - `lookup_expr` vs `method` on a filter (500);
  - the view's `ordering` missing its `-`;
  - `url_path="set-status"` (404);
  - empty status bodies accepted with 200.

**Phase 3**
- **Cache invalidation did nothing.** The version-bump function was defined but never passed to `transaction.on_commit`, so it was never called and nothing errored. Users would have seen stale job lists for up to 60 seconds. It was found by checking the version number **before and after** a save, not just the final response.
- **The API logged nothing at INFO level** (no `LOGGING` config), so a check grepping for an INFO line could never succeed. Fixed in Phase 4 with JSON logging.

**Phase 4**
- **The readiness check hung for more than 90 seconds when LocalStack was frozen.** No call had a timeout. The fix was:
  - Redis socket timeouts;
  - a fast, separate SQS client for the probe;
  - no network call in the queue's constructor.
- **`max_attempts: 1` meant two attempts.** In botocore's retry config, `max_attempts` counts *retries*, so the "one-try" probe took 2.3–3.0 s. Switching to `total_max_attempts` brought it to about 1 second.
- **Health endpoints answered 301 instead of running.** A trailing slash in the URL patterns let `APPEND_SLASH` redirect every probe, and Kubernetes counts redirects as success.
- **A `return` indented inside the loop** made `/readyz` check only the database. Found because freezing Redis and SQS changed nothing.
- **The worker crashed on any queue error.** Fixed with error handling around receive and delete, plus a restart policy. The policy only applied after `docker compose up -d`, because `restart` reuses the old container.
- **The configuration audit found:**
  - a region variable the code never read (`AWS_S3_REGION` vs `AWS_S3_REGION_NAME`);
  - `ALLOWED_HOSTS = *`;
  - the original secret key still in a comment;
  - the LocalStack token inside the API and worker containers.
- **A test of the image ran stale code.** The bind mount had hidden that the image wasn't rebuilt. Testing the image with no mount caught it.

## Measured Results

All numbers are from single runs on the local machine (thor).

- **Readiness check with a frozen dependency:** more than 90 s (curl killed at 90 s) → **1.02–1.06 s** with time limits and no retry. With Redis frozen: `/readyz` 1.03 s, and the job list still served (200) in 1.03 s.
- **Production image:** 394 MB → **343 MB** after the multi-stage build.
- **Graceful stop of the production container:** `time docker stop` → **0.50 s** (gunicorn handles `SIGTERM` as PID 1).
- **Worker graceful shutdown:** about 12–19 s. It finishes the current 20-second long poll, inside the 30-second grace period (`11.9 s` in Phase 3; `18.8 s` from the Phase 4 logs).
- **Error page with `DEBUG=False`:** 143 bytes, compared with a 68 KB debug page when `DEBUG=True`.