# Job Board API

A Django REST API where companies post jobs and candidates apply with a resume. It has:
- JWT auth with two user types, and role and ownership permissions;
- skill match scoring, and resume storage in S3;
- cached job search;
- a background worker that emails candidates when their application status changes.

It's built to be operated and maintained: health and readiness probes, Prometheus metrics, JSON logs, configuration from environment variables only, and a non-root production image. A 203-test suite at 100% coverage runs with one command, and the API is documented in OpenAPI with Swagger UI.

> **Status:** Phase 5 (tests and docs) complete. Runs locally, with S3 and SQS emulated by LocalStack. The Azure path and cloud deployment come in later phases.

## Architecture

```text
Client (curl / frontend / Swagger UI)            Kubernetes probes / Prometheus (later)
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
│   ├── /api/schema/           OpenAPI 3 schema;  /api/schema/swagger-ui/  interactive docs│
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
│        ├────────────────────────────── worker  (same image, python -m worker.run_worker)│
│        │                                 ├── claims event_id (ProcessedEvent, unique)   │
│        │                                 ├── sends status email (console backend)       │
│        │                                 └── survives queue outages, restarts on crash  │
│        │                                                                                │
│        └──── test  (profile "test": pytest in a test image; own test_jobboard database; │
│                     Redis and AWS faked in-process: LocMemCache + moto)                 │
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
  - the cache is invalidated when a job or company change is committed;
  - responses carry an `X-Cache: HIT/MISS` header;
  - the API keeps working if Redis is down or frozen.
- **Background worker:** a status change publishes an event to SQS after the database commit, and a separate worker emails the candidate.
- **Reliable processing:**
  - at-least-once delivery, a dead-letter queue after 3 failures, graceful shutdown;
  - **idempotent** handling, so a redelivered message never sends a second email.
- **Operations:**
  - `/healthz` (liveness) and `/readyz` (readiness, ~1 s budget per dependency);
  - Prometheus metrics;
  - JSON logs with correlation IDs;
  - configuration from environment variables only (missing or empty required values stop startup).
- **Production image:** multi-stage build, non-root user, read-only code, gunicorn as PID 1 with a graceful stop.
- **Tests:**
  - 203 tests, one command, **100% line coverage**;
  - the run **fails below 80%**;
  - AWS faked with moto, and no Redis or LocalStack needed.
- **API docs:**
  - an OpenAPI 3 schema and Swagger UI, with the JWT **Authorize** flow;
  - tests fail on any schema warning, and check that key operations document the right shapes.

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
| API docs | drf-spectacular (OpenAPI 3, Swagger UI) |
| Testing | pytest, pytest-django, pytest-cov, moto |
| Local AWS | LocalStack (S3, SQS) |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker (multi-stage: builder / test / runtime, non-root), Docker Compose |

## Cloud Services

| Purpose | AWS | Azure |
| --- | --- | --- |
| Resume storage | S3 (LocalStack locally; moto in tests) | — (Azure phase: Blob Storage) |
| Status-change queue | SQS + DLQ (LocalStack locally; moto in tests) | — (Azure phase: Service Bus) |
| Job search cache | ElastiCache target (Redis container locally) | — (Azure phase: Azure Cache for Redis) |

No AWS resources are provisioned yet. They're created with Terraform in Project 01.

## API Endpoints

Full, interactive documentation: **`/api/schema/swagger-ui/`** (schema: `/api/schema/`).

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
| GET | `/api/jobs/{id}/applications/` | job owner | Applicants, with match scores (paginated) |
| POST | `/api/applications/` | candidate | Apply (multipart, with `resume` file) |
| GET | `/api/applications/{id}/` | applicant or job owner | Application detail + match score |
| PATCH | `/api/applications/{id}/status/` | job owner | Change status; queues an email to the candidate |
| GET | `/api/applications/{id}/resume/` | applicant or job owner | Presigned resume download URL (5 min); 404 if none |
| GET | `/api/schema/` · `/api/schema/swagger-ui/` | public | OpenAPI schema and interactive docs |
| GET | `/healthz` · `/readyz` · `/metrics` | no token | Liveness, readiness, Prometheus metrics |

"Any user" means any logged-in user. Wrong user types get `403`; missing or expired tokens get `401`.

The operations endpoints (`/healthz`, `/readyz`, `/metrics`) have no authentication, like most probe and scrape endpoints. They must not be exposed publicly: in Kubernetes, the Ingress will route only `/api/`.

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

- API: `http://localhost:8006/api/`. Docs: `http://localhost:8006/api/schema/swagger-ui/`. Admin: `http://localhost:8006/admin/`.
- Wait for `curl -s http://localhost:8006/healthz` to answer before testing. `docker compose up -d` returns before the server is listening.
- To reach the API from another machine, add the address that machine uses (e.g. the host's LAN IP) to `DJANGO_ALLOWED_HOSTS`.
- Companies must be verified (admin → Companies → "Is verified") before they can post jobs.
- Emails are printed to `docker compose logs worker` (console backend).
- The worker doesn't auto-reload: run `docker compose restart worker` after code changes.
- LocalStack keeps no data when its container is recreated: re-upload resumes afterwards.
- Stop: `docker compose down` (keeps the database). Delete the database too: `docker compose down -v`.

**Run the tests:**

```bash
docker compose run --rm test
```

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

```bash
docker compose run --rm test
```

- **One command:** pytest in a `test` image (runtime + dev dependencies), on the Compose network, with the code bind-mounted. Only PostgreSQL has to be running.
- **Result:** **203 tests**, about 6 seconds, **100% line coverage**. `--cov-fail-under=80` makes the run **fail below 80%**, even if every test passes.
- **Isolation:**
  - pytest-django creates a separate `test_jobboard` database, and each test runs in a transaction that's rolled back;
  - Redis is replaced by an in-memory cache per test;
  - S3 and SQS by **moto** (in-process fakes; the tests pass with LocalStack stopped).

| Area | What the tests prove |
| --- | --- |
| Models, match score, resume validator | Constraints enforced by PostgreSQL, rounding, file signatures, the 5 MB boundary, random S3 keys |
| Permissions | Each class on its own, plus a who-can-do-what matrix over every protected endpoint. Denied writes change nothing |
| API | Registration (atomic, role can't be chosen), the real JWT flow, validation, filters, ordering, pagination |
| S3 / SQS (moto) | Upload, privacy, presigned links; a status change is published **only after commit**, and never on rollback |
| Worker | One email per event, duplicates skipped, a failed send releases the claim, the loop survives queue errors |
| Cache | HIT/MISS, invalidation only after commit, fallback when Redis fails |
| Readiness | 503 only when PostgreSQL is down; error class names only, never messages; liveness ignores dependencies |
| Config | Required/empty variables fail; typed `env_bool` / `env_list` |
| API docs | A valid schema with zero warnings; key operations document the right request and response shapes |

**The tests can fail when the code is wrong.** Key areas were checked by breaking the code on purpose (removing an owner check, sending an event before commit, invalidating the cache too early, dropping skill normalisation). In each case, exactly the expected tests failed.

```bash
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py   # one file, no coverage
docker compose run --rm test pytest -k "cache" -v --no-cov                       # by name
```

## Project Structure

```text
00-job-board-api/
├── config/
│   ├── settings.py          ← config from env vars (required/optional, typed); DRF, JWT, S3, Redis, SQS, email, JSON logging, OpenAPI
│   ├── urls.py              ← /api/, /api/schema/, /healthz, /readyz, /metrics
│   ├── wsgi.py              ← gunicorn entry point
│   └── tests/               ← settings helper tests
├── jobs/
│   ├── models.py            ← User, Company, CandidateProfile, Job, Application, ProcessedEvent
│   ├── serializers.py       ← incl. RegisteredUserSerializer, ResumeLinkSerializer (responses + docs)
│   ├── views.py             ← JobViewSet (cached list), ApplicationViewSet (status → event); @extend_schema
│   ├── permissions.py       ← IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicantOwner
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
│   ├── migrations/
│   └── tests/               ← conftest.py (fixtures, moto) + 15 test modules
├── cloud/
│   ├── queue.py             ← Queue interface + SQS implementation (timeouts, fast ping client)
│   └── health.py            ← /healthz and /readyz
├── worker/
│   └── run_worker.py        ← long-polls SQS, idempotent handling, survives outages, graceful shutdown
├── localstack/init/ready.d/
│   ├── create-bucket.sh
│   └── create-queues.sh     ← queue + DLQ with redrive policy
├── scripts/dev-helper.sh    ← local test helpers
├── docs/                    ← terminal checks (manual verification commands)
├── Dockerfile               ← builder → builder-test → base → test → runtime (default)
├── gunicorn.conf.py         ← process model, timeouts, JSON logs
├── docker-compose.yml       ← api (runserver for dev), worker, test (profile), PostgreSQL, Redis, LocalStack
├── .env.example / .env.localstack.example
├── pyproject.toml / uv.lock / .python-version    ← dependencies, pytest + coverage config (80% gate)
└── manage.py
```

`cloud/` is the spec's `platform/` package under a safe name: a top-level `platform` package would hide Python's built-in `platform` module.

## Design Decisions

- **Permissions as classes,** run before validation; 403 for non-owners.
- **Resumes in a private S3 bucket,** downloaded through short-lived presigned URLs.
- **Versioned cache keys:** one atomic `INCR` invalidates every cached search page; old keys expire on their own.
- **Side effects only after commit** (`transaction.on_commit`), for both cache invalidation and queue messages. A rolled-back change never invalidates the cache or emails anyone.
- **SQS locally through LocalStack,** not a Redis list: the same code runs locally and on AWS, with real redelivery and a DLQ.
- **Messages and logs carry IDs, not personal data.** The worker reads current data from the database.
- **Idempotency in the database:** a unique `event_id` is claimed in the same transaction as the send. Duplicates are skipped, and failed sends release the claim.
- **A queue interface (`cloud/queue.py`),** so Azure Service Bus can replace SQS without touching the API or the worker.
- **Liveness checks nothing; readiness fails only on PostgreSQL.** A database outage takes instances out of traffic instead of restarting them in a loop.
- **Every dependency call has a time budget:** Redis socket timeouts, a separate 1-second SQS client for health checks, and a long-poll client for the worker.
- **One gunicorn process with threads per container;** scale with more containers. In-process Prometheus counters stay correct without multiprocess mode.
- **12-factor configuration:** what varies between deployments comes from the environment; tuning values that are the same everywhere stay in code.
- **Least privilege:** a non-root user, code owned by root, and secrets only in the container that needs them.
- **One image for development and production:** gunicorn by default, `runserver` through a Compose override.
- **Tests in a container,** with a dedicated `test` image stage. The production image ships no test tools; tests need PostgreSQL only.
- **Fakes at the edges:** moto for AWS and an in-memory cache for Redis. Each test gets fresh, isolated state, and the suite runs without the network.
- **Coverage as a gate,** not a number someone reads: 80% enforced, 100% reached. One narrow exclusion (`if __name__ == "__main__":`).
- **API docs generated from the code,** with the response serializers reused in the docs, so the two can't drift. Schema tests check content, not just validity.

## What Broke and How I Fixed It

**Phase 1**
- **Validators that never ran** (indented inside `class Meta`); duplicates were still blocked by a PostgreSQL unique constraint. The clue was the error shape: a string from the view instead of a list from the serializer.
- **Silent typos:** `getattr(user, "candidateprofile", None)`, an `@action` named `application`, `User.Role.Company`, `PYTHONBUFFERED`, and `create_at` (which became a rename migration).

**Phase 2**
- **A misspelled hook,** `get_permission`, let an unverified company post a job.
- **Every presigned URL failed,** because the fake AWS keys were `change-me` instead of LocalStack's `test`. Found from S3's XML error body.
- **A test that passed for the wrong reason:** a tampered link returned 403, but so did the valid one.

**Phase 3**
- **Cache invalidation did nothing.** The version-bump function was defined but never passed to `transaction.on_commit`. It was found by checking the version number before and after a save.

**Phase 4**
- **The readiness check hung for more than 90 seconds when LocalStack was frozen.** No call had a timeout. Fixed with Redis socket timeouts, a fast separate SQS client, and no network call in the queue's constructor.
- **`max_attempts: 1` meant two attempts.** In botocore's retry config, `max_attempts` counts *retries*. Switching to `total_max_attempts` brought the probe to about 1 second.
- **Health endpoints answered 301** (a trailing slash + `APPEND_SLASH`), which Kubernetes counts as success.
- **The worker crashed on any queue error.** Fixed with error handling plus a restart policy, which only applied after `docker compose up -d`.
- **The configuration audit found:**
  - a region variable the code never read;
  - `ALLOWED_HOSTS = *`;
  - the original secret key still in a comment;
  - the LocalStack token inside the API containers.
- **A test of the image ran stale code,** hidden by the bind mount.

**Phase 5**
- **The suite got 10× slower** after the permission tests (27.13 s). `--durations` pointed at fixture setup: PBKDF2 password hashing for about 160 test users. A fast hasher in tests only brought it to 0.92 s.
- **Tests passed but errored at teardown.** They patched Django's `cache` *proxy*, and by the time the patch was undone, the proxy pointed at a different cache. Patching the real backend (`caches["default"]`) fixed it.
- **Coverage revealed two checks that could never run** (role checks already guaranteed by the permission classes). They were deleted; the permission matrix still passes.
- **The generated API schema was valid, warning-free, and wrong in 4 places.** drf-spectacular silently fell back to the view's serializer for custom actions. Found by printing what the schema says per operation; fixed with `@extend_schema`, and locked in by schema tests.

## Known Limitations

- **A duplicate application in a race leaves an orphaned resume in S3.** The file is uploaded before the database rejects the duplicate (pinned by a test).
- **If SQS is down when a status changes, the email event is lost** (logged, not retried). A transactional outbox would fix it.
- **The status-change `PATCH` shows `status` as optional in the docs.** drf-spectacular treats every `PATCH` as partial. The API does require it (400 without it, tested).

## Measured Results

All numbers are from single runs on the local machine (thor).

- **Test suite:** 203 tests in **6.15 s**, **100%** line coverage (687 statements).
- **Fast password hashing in tests:** 80 tests went from 27.13 s to **0.92 s**.
- **Readiness check with a frozen dependency:** more than 90 s (curl killed at 90 s) → **1.02–1.06 s** with time limits and no retry.
- **Production image:** 394 MB → **343 MB** after the multi-stage build. The test image is 365 MB and is never deployed.
- **Graceful stop of the production container:** `time docker stop` → **0.50 s**.
- **Error page with `DEBUG=False`:** 143 bytes, compared with a 68 KB debug page when `DEBUG=True`.
