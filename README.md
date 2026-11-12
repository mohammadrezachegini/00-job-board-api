# Job Board API

A Django REST API where companies post jobs and candidates apply with a resume. It has:
- JWT auth with two user types, and role and ownership permissions;
- skill match scoring, and private resume storage;
- cached job search;
- a background worker that emails candidates when their application status changes.

It's built to be operated and maintained: health and readiness probes, Prometheus metrics, JSON logs, configuration from environment variables only, and a non-root production image. **It's cloud-portable:** one environment variable, `CLOUD_PROVIDER`, switches storage and the queue between **AWS** (S3, SQS) and **Azure** (Blob Storage, Service Bus), and the same image runs on either. A 228-test suite runs with one command, and the API is documented in OpenAPI with Swagger UI.

> **Status:** Phase 6 (Azure portability) complete. Runs locally against emulators for both clouds: LocalStack for AWS; Azurite and the Service Bus emulator for Azure. No real cloud resources yet; those are created with Terraform in Project 01.

## Architecture

```text
Client (curl / frontend / Swagger UI)            Kubernetes probes / Prometheus (later)
   │  JWT (Authorization: Bearer <token>)              │  /healthz  /readyz  /metrics
   ▼                                                   ▼
┌──────────────────────────────────── Docker Compose ─────────────────────────────────────┐
│                                                                                         │
│  api  (Django 5.2 + DRF, port 8006)          CLOUD_PROVIDER = aws | azure               │
│   │   image default: gunicorn (1 process × 4 threads, non-root)                         │
│   │   Compose dev override: runserver + bind mount                                      │
│   ├── /api/auth/...          register, JWT tokens                                       │
│   ├── /api/jobs/...          search + filters (Redis cache), post, update, applicants   │
│   ├── /api/applications/...  apply with resume, detail + match score,                   │
│   │                          status change, resume download link                        │
│   ├── /api/schema/           OpenAPI 3 schema; /api/schema/swagger-ui/ interactive docs │
│   ├── /healthz               liveness: process is up (checks nothing else)              │
│   ├── /readyz                readiness: Postgres (critical), Redis, queue (bounded)     │
│   └── /metrics               requests, latency, DB queries (Prometheus format)          │
│        │    │     │                                                                     │
│        │    │     ├──▶ redis       job-list cache (versioned keys, 60 s TTL)            │
│        │    │     │                                                                     │
│        │    │     │    storage (django-storages), chosen by CLOUD_PROVIDER:             │
│        │    │     ├──▶ aws:   localstack S3   resumes bucket (private, presigned URLs)  │
│        │    │     └──▶ azure: azurite Blob    resumes container (private, SAS URLs)     │
│        │    │                                                                           │
│        │    │          queue (cloud/queue.py Queue interface), chosen by CLOUD_PROVIDER:│
│        │    ├──▶ aws:   localstack SQS   job-board-status ──▶ job-board-status-dlq      │
│        │    └──▶ azure: servicebus       job-board-status ──▶ built-in dead-letter      │
│        │                (emulator + SQL Server, profile "azure"; duplicate detection)   │
│        ▼  hostname "db"                        │                                        │
│  db   (PostgreSQL 17)  ◀───────────────────────┤                                        │
│        ▲                                       ▼                                        │
│        ├────────────────────────────── worker  (same image, python -m worker.run_worker)│
│        │                                 ├── reads the queue its CLOUD_PROVIDER picks   │
│        │                                 ├── claims event_id (ProcessedEvent, unique)   │
│        │                                 ├── sends status email (console backend)       │
│        │                                 └── survives queue outages, restarts on crash  │
│        │                                                                                │
│        └──── test  (profile "test": pytest in a test image; own test_jobboard database; │
│                     Azurite for Blob; Redis, AWS and Service Bus faked in-process)      │
│                                                                                         │
│  All processes: JSON logs on stdout; config only from environment variables             │
└─────────────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ 5-minute download link: presigned URL (S3) or SAS URL (Blob), straight from storage
```

## Features

- Two user types (company, candidate) on a custom Django user model. The role is set by the signup endpoint, never by the client.
- JWT login: 15-minute access tokens, 1-day refresh tokens. Every endpoint needs a token unless it opts out.
- Four DRF permission classes:
  - verified companies post jobs, and candidates apply;
  - only the job's company edits it, sees its applicants or changes a status;
  - only the applicant and the job's company read an application or get its resume.
- Skill match score (0–100), case-insensitive, `null` when a job requires no skills.
- **Resume upload:** PDF or DOCX, 5 MB max, file content checked against its extension.
  - Private storage with random keys.
  - 5-minute, read-only download links: a presigned URL on S3, a SAS URL on Azure Blob.
- Job search and filters: type, location, skills, free-text search, ordering. Invalid filter values return 400.
- **Cached job search:**
  - results are cached in Redis for 60 seconds;
  - the cache is invalidated when a job or company change is committed;
  - responses carry an `X-Cache: HIT/MISS` header;
  - the API keeps working if Redis is down or frozen.
- **Background worker:** a status change publishes an event to the queue after the database commit, and a separate worker emails the candidate.
- **Reliable processing:**
  - at-least-once delivery, a dead-letter queue after 3 failures, graceful shutdown;
  - **idempotent** handling, so a redelivered message never sends a second email;
  - on Azure, the queue also drops resends of the same message (duplicate detection).
- **Cloud portability:**
  - `CLOUD_PROVIDER=aws|azure` picks storage and the queue; anything else stops startup;
  - each cloud needs **only its own** settings;
  - the same image runs on both (proven: one image ID, one differing env line).
- **Bounded waits on Azure:**
  - a status change waits at most **3 s** for the queue, even if the broker is frozen;
  - the readiness check waits at most **2 s**, and while a check is stuck, the next ones fail at once.
- **Operations:**
  - `/healthz` (liveness) and `/readyz` (readiness, a time budget per dependency);
  - Prometheus metrics;
  - JSON logs with correlation IDs;
  - configuration from environment variables only (missing or empty required values stop startup).
- **Production image:** multi-stage build, non-root user, read-only code, gunicorn as PID 1 with a graceful stop.
- **Tests:**
  - 228 tests, one command, **98.63%** line coverage;
  - the run **fails below 80%**;
  - the Azure storage path tested against **real Azurite** (signed download links included);
  - AWS faked with moto, and Service Bus with fake SDK objects.
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
| File storage | django-storages (S3 and Azure backends), boto3, azure-storage-blob |
| Database | PostgreSQL 17 (psycopg 3) |
| Cache | Redis 7.4 (Django's built-in `RedisCache`, redis-py) |
| Queue | Amazon SQS + DLQ (boto3), or Azure Service Bus (azure-servicebus 7.15), behind one interface |
| Email | Django email framework (console backend locally) |
| Web server | gunicorn 26 (`gthread`) in the image; Django `runserver` for local development |
| Metrics | django-prometheus (prometheus_client) |
| Logging | python-json-logger |
| API docs | drf-spectacular (OpenAPI 3, Swagger UI) |
| Testing | pytest, pytest-django, pytest-cov, moto, Azurite |
| Local AWS | LocalStack (S3, SQS) |
| Local Azure | Azurite 3.37 (Blob), Azure Service Bus emulator 2.0.1 + SQL Server 2022 |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker (multi-stage: builder / test / runtime, non-root), Docker Compose (profiles `test`, `azure`) |

## Cloud Services

| Purpose | AWS | Azure |
| --- | --- | --- |
| Resume storage | S3, presigned URLs (LocalStack locally; moto in tests) | Blob Storage, SAS URLs (Azurite locally and in tests) |
| Status-change queue | SQS + DLQ (LocalStack locally; moto in tests) | Service Bus queue + built-in dead-letter, duplicate detection (emulator locally; fakes in tests) |
| Job search cache | ElastiCache target (Redis container locally) | Azure Cache for Redis target (Redis container locally) |

Only `CLOUD_PROVIDER` changes between the two columns. No cloud resources are provisioned yet: they're created with Terraform in Project 01, including a Service Bus namespace and queue for the Azure phase.

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
| GET | `/api/applications/{id}/resume/` | applicant or job owner | Resume download link, 5 min: presigned (S3) or SAS (Blob); 404 if none |
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

docker compose up -d --build        # api (runserver), worker, db, redis, localstack (bucket + queues), azurite
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

**Run the Azure path locally** (Azurite for Blob, the Service Bus emulator for the queue):

```bash
cp .env.servicebus.example .env.servicebus && chmod 600 .env.servicebus
# In .env.servicebus: set a strong MSSQL_SA_PASSWORD, and ACCEPT_EULA=Y only if you accept the
# Service Bus emulator and SQL Server Developer licenses (development and test use only).
docker compose --profile azure up -d servicebus-sql servicebus     # ~28 s until "Emulator Service is Successfully Up"
docker compose logs servicebus 2>&1 | grep -ci "successfully up"   # 1 or more

# Create the Blob container once (Azurite's well-known dev account, from .env)
docker compose exec api python -c "from azure.storage.blob import BlobServiceClient; import os; e = os.environ; BlobServiceClient.from_connection_string(f'DefaultEndpointsProtocol=http;AccountName={e[\"AZURE_ACCOUNT_NAME\"]};AccountKey={e[\"AZURE_ACCOUNT_KEY\"]};BlobEndpoint={e[\"AZURE_BLOB_ENDPOINT\"]};').create_container(e['AZURE_CONTAINER'])"

# Same image, Azure backend: only CLOUD_PROVIDER changes
docker compose build api
docker run -d --name jobboard-azure --network 00-job-board-api_default \
  --env-file .env -e CLOUD_PROVIDER=azure -p 127.0.0.1:8017:8006 00-job-board-api-api
docker run -d --name jobboard-azure-worker --network 00-job-board-api_default \
  --env-file .env -e CLOUD_PROVIDER=azure 00-job-board-api-api python -m worker.run_worker
curl -s http://localhost:8017/readyz
docker rm -f jobboard-azure jobboard-azure-worker
docker compose --profile azure stop servicebus servicebus-sql      # frees ~1.1 GB
```

- **Only one Azure worker at a time:** every worker on the queue competes for messages, so a leftover one takes events meant for another.
- **The emulator rebuilds its queue on every restart,** so queued messages are lost when it restarts. Real Service Bus keeps them.

**Run the production image** (gunicorn, no source mount, env vars only):

```bash
docker compose build api
docker run -d --name jobboard-prod --network 00-job-board-api_default \
  --env-file .env -e DJANGO_DEBUG=False -p 127.0.0.1:8016:8006 00-job-board-api-api
curl -s http://localhost:8016/readyz
docker stop jobboard-prod && docker rm jobboard-prod
```

## Environment Variables

A variable with no default is **required**. If it's missing **or empty**, the app stops at startup with `Missing required environment variable: <NAME>`. Cloud-specific variables are required **only** for the cloud that `CLOUD_PROVIDER` selects.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CLOUD_PROVIDER` | no | `aws` | `aws` or `azure`: picks storage and the queue. Anything else stops startup |
| `DJANGO_SECRET_KEY` | yes | — | Signs sessions and JWTs |
| `DJANGO_DEBUG` | no | `False` | Debug mode (local only). `1/true/yes/on` = on; anything else = off |
| `DJANGO_ALLOWED_HOSTS` | no | `localhost,127.0.0.1` | Comma-separated host names clients use |
| `LOG_LEVEL` | no | `INFO` | Log level for Django, the app and gunicorn |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | yes | — | Database (also used by the Postgres container) |
| `POSTGRES_HOST` | yes | — | `db` inside Compose |
| `POSTGRES_PORT` | no | `5432` | |
| `REDIS_URL` | yes | — | Cache, e.g. `redis://redis:6379/0` |
| `EMAIL_BACKEND` | no | console backend | Where emails go |
| `DEFAULT_FROM_EMAIL` | no | `Job Board <no-reply@jobboard.test>` | Sender address |
| **AWS** (`CLOUD_PROVIDER=aws`) | | | |
| `AWS_REGION` | yes | — | Region for S3 and SQS |
| `AWS_STORAGE_BUCKET_NAME` | yes | — | Resume bucket |
| `AWS_S3_ENDPOINT_URL` | no | real S3 | Internal S3 address (`http://localstack:4566` locally) |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | no | same as above | Address used in presigned URLs (`http://localhost:4566` locally) |
| `AWS_SQS_ENDPOINT_URL` | no | real SQS | `http://localstack:4566` locally |
| `SQS_QUEUE_NAME` | yes | — | Status-change queue (`job-board-status`); its DLQ is `<name>-dlq` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | local only | — | `test` / `test` for LocalStack. Not set on AWS (IAM role) |
| **Azure** (`CLOUD_PROVIDER=azure`) | | | |
| `AZURE_ACCOUNT_NAME` / `AZURE_ACCOUNT_KEY` | yes | — | Storage account. Locally, Azurite's published dev account; on Azure, the key comes from a secret store |
| `AZURE_CONTAINER` | yes | — | Resume container (`resumes`) |
| `AZURE_BLOB_ENDPOINT` | no | `https://<account>.blob.core.windows.net` | Internal Blob address (`http://azurite:10000/devstoreaccount1` locally) |
| `AZURE_PUBLIC_BLOB_ENDPOINT` | no | same as above | Address used in SAS URLs (`http://localhost:10000/devstoreaccount1` locally) |
| `SERVICE_BUS_CONNECTION_STRING` | yes | — | Locally, the emulator's fixed dev key; on Azure, from Key Vault (later Workload Identity) |
| `SERVICE_BUS_QUEUE_NAME` | yes | — | Status-change queue (`job-board-status`) |
| **Server and local-only** | | | |
| `PORT` | no | `8006` | gunicorn listen port (production image) |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | no | `1` / `4` | gunicorn processes and threads. Keep workers at 1: metrics are per process |
| `GUNICORN_TIMEOUT` | no | `30` | Seconds before a stuck worker is replaced |
| `LOCALSTACK_AUTH_TOKEN` | local only | — | In **`.env.localstack`**, read only by the LocalStack container (secret) |
| `ACCEPT_EULA` / `MSSQL_SA_PASSWORD` | local only | — | In **`.env.servicebus`**, read only by the emulator and SQL Server containers (secret) |

`.env`, `.env.localstack` and `.env.servicebus` are ignored by git and kept out of the image. Write values without quotes: `docker run --env-file` keeps quotes literally.

## Testing

```bash
docker compose run --rm test
```

- **One command:** pytest in a `test` image (runtime + dev dependencies), on the Compose network, with the code bind-mounted. PostgreSQL and Azurite have to be running; Compose starts both.
- **Result:** **228 tests**, about 10 seconds, **98.63% line coverage**. `--cov-fail-under=80` makes the run **fail below 80%**, even if every test passes.
  - The uncovered lines are the Azure settings branch, which **is** tested, in a child process that coverage doesn't measure.
- **Isolation:**
  - pytest-django creates a separate `test_jobboard` database, and each test runs in a transaction that's rolled back;
  - Redis is replaced by an in-memory cache per test;
  - S3 and SQS by **moto** (in-process fakes; the tests pass with LocalStack stopped);
  - Blob tests use **Azurite** with a new container per test, deleted afterwards. They **fail, not skip,** if Azurite is down;
  - Service Bus by **fake SDK objects** that can fail or freeze on cue.

| Area | What the tests prove |
| --- | --- |
| Models, match score, resume validator | Constraints enforced by PostgreSQL, rounding, file signatures, the 5 MB boundary, random storage keys |
| Permissions | Each class on its own, plus a who-can-do-what matrix over every protected endpoint. Denied writes change nothing |
| API | Registration (atomic, role can't be chosen), the real JWT flow, validation, filters, ordering, pagination |
| S3 / SQS (moto) | Upload, privacy, presigned links; a status change is published **only after commit**, and never on rollback |
| Blob (Azurite) | Upload through the API, a rejected upload stores nothing, anonymous reads get `403`, the SAS link downloads the file with the right name, a tampered link gets `403` |
| Service Bus (fakes) | One reused sender and receiver, recovery after errors, settle on the same receiver, old lock tokens rejected, the 3 s send limit, the 2 s ping limit, one stuck check at a time |
| Settings | Azure starts with no AWS variable and vice versa; a missing Azure variable stops startup, naming it |
| Worker | One email per event, duplicates skipped, a failed send releases the claim, the loop survives queue errors |
| Cache | HIT/MISS, invalidation only after commit, fallback when Redis fails |
| Readiness | 503 only when PostgreSQL is down; error class names only, never messages; liveness ignores dependencies |
| API docs | A valid schema with zero warnings; key operations document the right request and response shapes |

**The tests can fail when the code is wrong.** Key areas were checked by breaking the code on purpose. In each case, exactly the expected tests failed:
- removing an owner check;
- sending an event before commit;
- invalidating the cache too early;
- dropping skill normalisation;
- giving the SAS link write permission instead of read;
- letting the Service Bus ping retry;
- keeping old lock tokens around.

The real broker behaviour was verified by hand against the Service Bus emulator, including: locks and redelivery, dead-lettering after 3 deliveries, duplicate detection, and stopped and frozen brokers. The commands are in `docs/`.

```bash
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py   # one file, no coverage
docker compose run --rm test pytest -k "cache" -v --no-cov                       # by name
```

## Project Structure

```text
00-job-board-api/
├── config/
│   ├── settings.py          ← config from env vars; CLOUD_PROVIDER picks the AWS or Azure branch (storage + queue settings)
│   ├── urls.py              ← /api/, /api/schema/, /healthz, /readyz, /metrics
│   ├── wsgi.py              ← gunicorn entry point
│   └── tests/               ← settings helper tests + per-cloud startup tests (subprocess)
├── jobs/
│   ├── models.py            ← User, Company, CandidateProfile, Job, Application, ProcessedEvent
│   ├── serializers.py       ← incl. RegisteredUserSerializer, ResumeLinkSerializer (responses + docs)
│   ├── views.py             ← JobViewSet (cached list), ApplicationViewSet (status → event); @extend_schema
│   ├── permissions.py       ← IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicantOwner
│   ├── matching.py          ← skill match score
│   ├── filters.py           ← JobFilter
│   ├── validators.py        ← resume checks
│   ├── storage.py           ← download links: presigned (S3) or SAS (Blob), by CLOUD_PROVIDER
│   ├── cache.py             ← job-list cache keys and versioned invalidation
│   ├── signals.py           ← invalidate the cache when jobs or companies change
│   ├── events.py            ← publish status-change events on commit (catches QUEUE_ERRORS)
│   ├── emails.py            ← status-change email
│   ├── templates/emails/status_changed.txt
│   ├── apps.py              ← registers signals
│   ├── migrations/
│   └── tests/               ← conftest.py (fixtures: moto, Azurite) + 17 test modules
├── cloud/
│   ├── queue.py             ← Queue interface; SQSQueue and ServiceBusQueue; get_queue() by CLOUD_PROVIDER
│   └── health.py            ← /healthz and /readyz
├── worker/
│   └── run_worker.py        ← long-polls the queue, idempotent handling, survives outages, graceful shutdown
├── localstack/init/ready.d/
│   ├── create-bucket.sh
│   └── create-queues.sh     ← queue + DLQ with redrive policy
├── servicebus/Config.json   ← emulator namespace + queue (30 s lock, 3 deliveries, duplicate detection)
├── scripts/dev-helper.sh    ← local test helpers
├── docs/                    ← terminal checks (manual verification commands)
├── Dockerfile               ← builder → builder-test → base → test → runtime (default)
├── gunicorn.conf.py         ← process model, timeouts, JSON logs, control socket off
├── docker-compose.yml       ← api, worker, test (profile), PostgreSQL, Redis, LocalStack, Azurite,
│                              Service Bus emulator + SQL Server (profile "azure")
├── .env.example / .env.localstack.example / .env.servicebus.example
├── pyproject.toml / uv.lock / .python-version    ← dependencies, pytest + coverage config (80% gate)
└── manage.py
```

`cloud/` is the spec's `platform/` package under a safe name: a top-level `platform` package would hide Python's built-in `platform` module.

## Design Decisions

- **Permissions as classes,** run before validation; 403 for non-owners.
- **Resumes in private storage,** downloaded through short-lived, read-only links (presigned on S3, SAS on Blob).
- **Versioned cache keys:** one atomic `INCR` invalidates every cached search page; old keys expire on their own.
- **Side effects only after commit** (`transaction.on_commit`), for both cache invalidation and queue messages. A rolled-back change never invalidates the cache or emails anyone.
- **Real emulators locally:** LocalStack for SQS/S3, Azurite for Blob, and Microsoft's Service Bus emulator, not a Redis list. The same code runs locally and in the cloud, with real redelivery and dead-lettering.
- **Messages and logs carry IDs, not personal data.** The worker reads current data from the database.
- **Idempotency in the database:** a unique `event_id` is claimed in the same transaction as the send. Duplicates are skipped, and failed sends release the claim.
- **One `Queue` interface, two implementations:** the API, the worker and `/readyz` never name a cloud. `get_queue()` is the only place that decides, and callers catch one tuple, `QUEUE_ERRORS`.
- **Each cloud loads only its own settings,** so an Azure deployment needs no AWS variables (tested).
- **Liveness checks nothing; readiness fails only on PostgreSQL.** A database outage takes instances out of traffic instead of restarting them in a loop.
- **Every dependency call has a time budget.** Where an SDK can't bound a step (Service Bus's AMQP login hangs on a frozen broker), the call runs in a thread with a deadline, and only one stuck call is allowed at a time.
- **Publishing inside a request uses a small budget:** 2 attempts × 2 s, and a 3 s hard limit. A broker outage costs the user seconds, not minutes; the worker's receiver keeps a bigger budget.
- **Duplicate detection plus idempotency:** the message ID is fixed before any retry, so the broker drops resends, and the worker still skips anything that gets through.
- **One gunicorn process with threads per container;** scale with more containers. In-process Prometheus counters stay correct without multiprocess mode.
- **12-factor configuration:** what varies between deployments comes from the environment; tuning values that are the same everywhere stay in code.
- **Least privilege:**
  - a non-root user, and code owned by root;
  - secrets only in the container that needs them (LocalStack token, SQL Server password);
  - unused server features off (gunicorn's control socket).
- **One image for development and production:** gunicorn by default, `runserver` through a Compose override.
- **Heavy dependencies behind Compose profiles:** the Service Bus emulator and SQL Server (~1.1 GB) start only with `--profile azure`.
- **Tests in a container,** with a dedicated `test` image stage. The production image ships no test tools.
- **Fakes at the edges, real emulators where signatures matter:** moto for AWS, fakes for Service Bus, and Azurite for Blob, because SAS signatures need a real server to check them.
- **Coverage as a gate,** not a number someone reads: 80% enforced. One narrow exclusion (`if __name__ == "__main__":`).
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

**Phase 6**
- **A healthy Service Bus readiness check failed after exactly 1 s.** The check had a 1 s budget, and opening a connection to the emulator takes about 1 s. A table of timeout combinations showed it; the budget became 2 s.
- **A frozen broker hung the readiness check forever.** A `faulthandler` stack dump showed the hang in the SDK's AMQP login (SASL), which no SDK timeout covers. Fixed with a thread and a deadline, plus "one stuck check at a time".
- **A queue outage made a status change wait 12.03 s,** because the publish runs inside the request with the SDK's 3 retries. A small send budget and a 3 s hard limit brought it to **1.84 s**.
- **A frozen broker turned one message into four,** and the API logged "Could not queue" for a message that was delivered. Fixed with duplicate detection on the queue (one fixed message ID per message) and an honest error text ("may still be delivered"). Result: **0** duplicates (was 3).
- **The emulator crash-looped (14 restarts)** after the config change: its maximum duplicate-detection window is 5 minutes, not 10. Found with `docker inspect … RestartCount` and its last log lines.
- **The Azure settings still required AWS variables:** a replacement block was pasted next to the old one, so both ran. A test that starts Django without AWS variables now guards it.
- **With Azurite down, 5 tests took 7 min 8 s to fail.** The SDK's default retries ran inside one call; turning them off in the test fixture made it 77 s.
- **The Azure worker in the final proof never saw its messages:** a forgotten worker from an earlier test was competing on the same queue. Found by peeking the queue (empty), dumping the worker's stack (idle), then listing every Azure container.
- **gunicorn 26 logged `Permission denied: '/home/app'`:** its new control socket defaults to `$HOME`, and the app user has none. Read in gunicorn's source; turned off (`control_socket_disable = True`).

## Known Limitations

- **A duplicate application in a race leaves an orphaned resume in storage.** The file is uploaded before the database rejects the duplicate (pinned by a test).
- **If the queue is down when a status changes, the email event is lost** (logged, not retried), on both clouds. A transactional outbox would fix it.
- **On Azure, "Could not queue" can be logged for an event that is delivered later:** the send timed out on our side, but the broker had it. Duplicate detection and idempotency keep that safe.
- **The Service Bus worker's receive has no thread deadline:** on a frozen broker it waits until the broker answers. It isn't on a user's path, and it recovered by itself in testing.
- **Every Azure worker on one queue name competes for messages.** Real environments need one queue per environment (Terraform, Project 01).
- **The Service Bus emulator** loses queued messages when it restarts, caps duplicate detection at 5 minutes, and takes about 28 s to start. Real Service Bus doesn't have these limits.
- **The Azurite `resumes` container is created by a manual command** (see Setup). LocalStack's bucket has an init script; Azurite has no init hook.
- **The status-change `PATCH` shows `status` as optional in the docs.** drf-spectacular treats every `PATCH` as partial. The API does require it (400 without it, tested).

## Measured Results

All numbers are from single runs on the local machine (thor).

- **Test suite:** 228 tests in **9.94 s**, **98.63%** line coverage (801 statements).
- **Fast password hashing in tests:** 80 tests went from 27.13 s to **0.92 s**.
- **Readiness check with a frozen dependency:**
  - Redis/SQS: more than 90 s (curl killed at 90 s) → **1.02–1.06 s** with time limits and no retry;
  - Service Bus: hung (killed at 30 s) → **2.0 s**, then **0 ms** for each later check while frozen.
- **Status change during a Service Bus outage:**
  - broker stopped: **12.03 s → 1.84 s**;
  - broker frozen: **3.02 s** (bounded).
- **Duplicate messages from a frozen broker:** **3 → 0** after duplicate detection.
- **Readiness queue check:** SQS (LocalStack) **49.1 ms**; Service Bus (emulator) **~1.0 s**.
- **Azure tests with Azurite down:** **428.77 s → 76.81 s** to fail.
- **Service Bus emulator + SQL Server:** about **28 s** to start; **128 MiB + 1003 MiB** of memory after use.
- **Production image:** 394 MB → **343 MB** after the multi-stage build. The test image is 365 MB and is never deployed.
- **Graceful stop of the production container:** `time docker stop` → **0.50 s**.
- **Error page with `DEBUG=False`:** 143 bytes, compared with a 68 KB debug page when `DEBUG=True`.
