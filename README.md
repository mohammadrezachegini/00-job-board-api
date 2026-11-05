# Job Board API

A Django REST API where companies post jobs and candidates apply with a resume. JWT auth with two user types, role and ownership permissions, skill match scoring, resume storage in S3, cached job search, and a background worker that emails candidates when their application status changes. PostgreSQL, Redis, SQS and Docker Compose.

> **Status:** Phase 3 (background worker) complete. Runs locally, with S3 and SQS emulated by LocalStack. Operations endpoints, structured logs, tests and cloud deployment come in later phases.

## Architecture

```text
Client (curl / frontend)
   │  JWT (Authorization: Bearer <token>)
   ▼
┌──────────────────────────────────── Docker Compose ─────────────────────────────────────┐
│                                                                                         │
│  api  (Django 5.2 + DRF, port 8006)                                                     │
│   ├── /api/auth/...          register, JWT tokens                                       │
│   ├── /api/jobs/...          search + filters (cached in Redis), post, update, applicants│
│   └── /api/applications/...  apply with resume, detail + match score,                   │
│        │     │     │         status change, resume download link                        │
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
│                                          └── sends status email (console backend)       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ presigned URL (5 min): client downloads the resume straight from S3
```

## Features

- Two user types (company, candidate) on a custom Django user model; the role is set by the signup endpoint, never by the client
- JWT login: 15-minute access tokens, 1-day refresh tokens; every endpoint needs a token unless it opts out
- Four DRF permission classes: verified companies post jobs; candidates apply; only the job's company edits it, sees its applicants or changes a status; only the applicant and the job's company read an application or get its resume
- Skill match score (0–100), case-insensitive, `null` when a job requires no skills
- Resume upload: PDF or DOCX, 5 MB max, file content checked against its extension; private S3 bucket, random keys; 5-minute presigned download links
- Job search and filters: type, location, skills, free-text search, ordering; invalid filter values return 400
- **Cached job search:** results cached in Redis for 60 seconds; invalidated immediately when any job or company changes (from the API, admin or shell); `X-Cache: HIT/MISS` header; the API keeps working if Redis is down
- **Background worker:** a status change publishes an event to SQS after the database commit; a separate worker emails the candidate
- **Reliable processing:** at-least-once delivery with a 30-second visibility timeout, a dead-letter queue after 3 failures, graceful shutdown on `SIGTERM`, and **idempotent** handling so a redelivered message never sends a second email
- All configuration from environment variables

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
| Local AWS | LocalStack (S3, SQS) |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker, Docker Compose |

## Cloud Services

| Purpose | AWS | Azure |
| --- | --- | --- |
| Resume storage | S3 (LocalStack locally) | — (Azure phase) |
| Status-change queue | SQS + DLQ (LocalStack locally) | — (Azure phase: Service Bus) |
| Job search cache | ElastiCache target (Redis container locally) | — (Azure phase: Azure Cache for Redis) |

No AWS resources are provisioned yet; they're created with Terraform in Project 01.

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

"Any user" means any logged-in user. Wrong user types get `403`; missing or expired tokens get `401`.

## Setup

**Prerequisites:** Docker with Compose, [uv](https://docs.astral.sh/uv/), and a free LocalStack account (for its auth token). The project's `bootstrap.yml` (Ansible toolchain) is planned and not built yet.

```bash
git clone https://github.com/mohammadrezachegini/00-job-board-api.git
cd 00-job-board-api

cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # paste into DJANGO_SECRET_KEY
# also set POSTGRES_PASSWORD and LOCALSTACK_AUTH_TOKEN in .env

docker compose up -d --build        # api, worker, db, redis, localstack (creates the bucket and queues)
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

- API: `http://localhost:8006/api/`; admin: `http://localhost:8006/admin/`.
- Companies must be verified (admin → Companies → "Is verified") before they can post jobs.
- Emails are printed to `docker compose logs worker` (console backend).
- The worker doesn't auto-reload: `docker compose restart worker` after code changes.
- LocalStack keeps no data when its container is recreated: re-upload resumes afterwards.
- Stop: `docker compose down` (keeps the database). Delete the database too: `docker compose down -v`.

## Environment Variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | yes | — | Signs sessions and JWTs |
| `DJANGO_DEBUG` | no | `False` | Debug mode (local only) |
| `DJANGO_ALLOWED_HOSTS` | no | `localhost,127.0.0.1` | Comma-separated hostnames |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | yes | — | Database (also used by the Postgres container) |
| `POSTGRES_HOST` / `POSTGRES_PORT` | no | `localhost` / `5432` | `db` inside Compose |
| `REDIS_URL` | yes | — | Cache, e.g. `redis://redis:6379/0` |
| `AWS_STORAGE_BUCKET_NAME` | yes | — | Resume bucket |
| `AWS_S3_REGION_NAME` | no | `us-east-1` | S3 region |
| `AWS_S3_ENDPOINT_URL` | no | real S3 | Internal S3 address (`http://localstack:4566` locally) |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | no | same as above | Address used in presigned URLs (`http://localhost:4566` locally) |
| `AWS_REGION` | no | `us-east-1` | Region for the SQS client |
| `AWS_SQS_ENDPOINT_URL` | no | real SQS | `http://localstack:4566` locally |
| `SQS_QUEUE_NAME` | yes | — | Status-change queue (`job-board-status`); its DLQ is `<name>-dlq` |
| `EMAIL_BACKEND` | no | console backend | Where emails go |
| `DEFAULT_FROM_EMAIL` | no | `Job Board <no-reply@jobboard.test>` | Sender address |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | local only | — | `test` / `test` for LocalStack. Not set on AWS (IAM role) |
| `LOCALSTACK_AUTH_TOKEN` | local only | — | LocalStack account token (secret) |

The app fails at startup with a clear message if a required variable is missing.

## Testing

Automated tests (pytest, 80%+ coverage) are planned for Phase 5. Phases 1–3 were verified with manual checks over HTTP, in the Django shell and against Redis and SQS; the full list is in `docs/` (terminal checks).

Phase 3 checks included:
- cache hits/misses, invalidation on save (and **not** on a rolled-back save), and serving uncached data with Redis stopped;
- messages waiting in SQS while the worker is down;
- a poison message reaching the DLQ after 3 tries;
- a simulated crash after sending an email but before deleting the message: the redelivered copy was skipped, with no second email;
- a simulated mail-server failure: the claim was rolled back, and the retry sent the email.

## Project Structure

```text
00-job-board-api/
├── config/
│   ├── settings.py          ← config from env vars; DRF, JWT, S3, Redis cache, SQS, email
│   └── urls.py
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
│   └── queue.py             ← Queue interface + SQS implementation
├── worker/
│   └── run_worker.py        ← long-polls SQS, idempotent handling, graceful shutdown
├── localstack/init/ready.d/
│   ├── create-bucket.sh
│   └── create-queues.sh     ← queue + DLQ with redrive policy
├── scripts/dev-helper.sh    ← local test helpers
├── docs/
├── Dockerfile
├── docker-compose.yml       ← api, worker, PostgreSQL, Redis, LocalStack
├── pyproject.toml / uv.lock / .python-version / .env.example
└── manage.py
```

`cloud/` is the spec's `platform/` package under a safe name: a top-level `platform` package would hide Python's built-in `platform` module.

## Design Decisions

- **Permissions as classes**, run before validation; 403 for non-owners.
- **Resumes in a private S3 bucket**, downloaded through short-lived presigned URLs.
- **Versioned cache keys:** one atomic `INCR` invalidates every cached search page; old keys expire on their own.
- **Side effects only after commit** (`transaction.on_commit`) for both cache invalidation and queue messages, so a rolled-back change never invalidates the cache or emails anyone.
- **SQS locally through LocalStack**, not a Redis list: the same code runs locally and on AWS, with real redelivery and a DLQ.
- **Messages carry IDs, not personal data:** the worker reads current data from the database.
- **Idempotency in the database:** a unique `event_id` claimed in the same transaction as the send. Duplicates are skipped, and failed sends release the claim.
- **A queue interface (`cloud/queue.py`)** so Azure Service Bus can replace SQS without touching the API or worker.
- **One image, two process types** (API and worker), with a 30-second stop grace period for graceful shutdown.

## What Broke and How I Fixed It

**Phase 1**
- **Validators that never ran** (indented inside `class Meta`); duplicates were still blocked by a PostgreSQL unique constraint. The clue was the error shape: a string from the view instead of a list from the serializer.
- **Silent typos:** `getattr(user, "candidateprofile", None)`, `@action` named `application`, `User.Role.Company`, `PYTHONBUFFERED`, and `create_at` (which became a rename migration).

**Phase 2**
- **A misspelled hook,** `get_permission`, let an unverified company post a job.
- **Every presigned URL failed** because the fake AWS keys were `change-me` instead of LocalStack's `test`; found from S3's XML error body.
- **A test that passed for the wrong reason:** a tampered link returned 403, but so did the valid one.
- `lookup_expr` vs `method` on a filter (500), the view's `ordering` missing its `-`, `url_path="set-status"` (404), and empty status bodies accepted with 200.

**Phase 3**
- **Cache invalidation did nothing.** The version-bump function was defined but never passed to `transaction.on_commit`, so it was never called and nothing errored. Users would have seen stale job lists for up to 60 seconds. It was found by checking the version number **before and after** a save, not just the final response.
- **The API logs nothing at INFO level yet** (no `LOGGING` config), so a check grepping for an INFO line could never succeed. That's planned for Phase 4.

## Measured Results

- Worker graceful shutdown: `time docker compose stop worker` → `real 0m11.947s` (finishing a 20-second long poll), inside the 30-second grace period.