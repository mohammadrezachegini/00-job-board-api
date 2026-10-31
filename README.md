# Job Board API

A Django REST API where companies post jobs and candidates apply with a resume. JWT auth with two user types, role and ownership permissions, skill match scoring, resume storage in S3, and job search. PostgreSQL and Docker Compose.

> **Status:** Phase 2 (business logic and permissions) complete. Runs locally, with S3 emulated by LocalStack. Background worker, operations endpoints, tests and cloud deployment come in later phases.

## Architecture

```text
Client (curl / frontend)
   │  JWT (Authorization: Bearer <token>)
   ▼
┌──────────────────────────────── Docker Compose ────────────────────────────────┐
│                                                                                │
│  api  (Django 5.2 + DRF, port 8006)                                            │
│   ├── /api/auth/...           register company / candidate, JWT tokens         │
│   ├── /api/jobs/...           list + search + filters, post, update, applicants│
│   └── /api/applications/...   apply with resume, detail + match score,         │
│          │        │           status change, resume download link              │
│          │        │                                                            │
│          │        └──▶ localstack (S3, port 4566 on 127.0.0.1 only)            │
│          │               bucket: resumes, private                              │
│          ▼  hostname "db"                                                      │
│  db   (PostgreSQL 17, named volume pgdata, not exposed to host)                │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ presigned URL (5 min): client downloads the resume straight from S3
```

## Features

- Two user types (company, candidate) on a custom Django user model; the role is set by the signup endpoint, never by the client
- JWT login: 15-minute access tokens, 1-day refresh tokens; every endpoint needs a token unless it opts out
- Four DRF permission classes:
  - `IsVerifiedCompany`: only verified companies post jobs
  - `IsCandidate`: only candidates apply
  - `IsJobOwner`: only the posting company edits a job, sees its applicants, or changes an application's status
  - `IsApplicationOwner`: only the applicant and the job's company read an application or get its resume
- Skill match score (0–100): share of a job's required skills the candidate has; case-insensitive, `null` when a job requires none
- Resume upload: PDF or DOCX, 5 MB max, file content checked against its extension (magic bytes); stored under random keys in a private S3 bucket
- Resume download through a 5-minute presigned URL, only for allowed users; no file links in normal responses
- Job search and filters: type, location, skills (any match), free-text search across title, description and company name, ordering; invalid filter values return 400
- Candidates apply once per job, enforced by a serializer check and a PostgreSQL unique constraint
- Jobs are closed instead of deleted, keeping their history; list endpoints are paginated (20 per page)
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
| Local AWS | LocalStack (S3) |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker, Docker Compose |

## Cloud Services

| Purpose | AWS | Azure |
| --- | --- | --- |
| Resume storage | S3 (LocalStack locally) | — (Azure phase) |

Only what's built so far. RDS, SQS and the Azure equivalents arrive in later phases and in Project 01.

## API Endpoints

| Method | Path | Who | Description |
| --- | --- | --- | --- |
| POST | `/api/auth/register/company/` | public | Register a company account |
| POST | `/api/auth/register/candidate/` | public | Register a candidate account |
| POST | `/api/auth/token/` | public | Get an access and refresh token |
| POST | `/api/auth/token/refresh/` | public | Get a new access token |
| GET | `/api/jobs/` | any user | List open jobs. Query: `job_type`, `location`, `skills=a,b`, `search`, `ordering` (`created_at`, `title`), `page` |
| POST | `/api/jobs/` | verified company | Post a job |
| GET | `/api/jobs/{id}/` | any user | Job detail |
| PUT / PATCH | `/api/jobs/{id}/` | job owner | Update or close a job |
| GET | `/api/jobs/{id}/applications/` | job owner | Applicants, with match scores |
| POST | `/api/applications/` | candidate | Apply (multipart, with `resume` file) |
| GET | `/api/applications/{id}/` | applicant or job owner | Application detail + match score |
| PATCH | `/api/applications/{id}/status/` | job owner | Change status (`submitted`, `reviewing`, `interview`, `offered`, `rejected`) |
| GET | `/api/applications/{id}/resume/` | applicant or job owner | Presigned resume download URL (5 min) |

"Any user" means any logged-in user. Wrong user types get `403`; missing or expired tokens get `401`.

## Setup

**Prerequisites:** Docker with Compose, [uv](https://docs.astral.sh/uv/) (installs Python 3.12 itself), and a free LocalStack account for its auth token. The project's `bootstrap.yml` (Ansible toolchain) is planned and not built yet.

```bash
git clone https://github.com/mohammadrezachegini/00-job-board-api.git
cd 00-job-board-api

cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # paste into DJANGO_SECRET_KEY
# also set POSTGRES_PASSWORD and LOCALSTACK_AUTH_TOKEN in .env

docker compose up -d --build        # api, db, localstack (creates the S3 bucket on start)
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

- API: `http://localhost:8006/api/`; admin: `http://localhost:8006/admin/`.
- Companies must be verified (admin → Companies → "Is verified") before they can post jobs.
- LocalStack keeps no data between restarts: re-upload resumes after recreating it.
- Stop: `docker compose down` (keeps the database). Delete the database too: `docker compose down -v`.

## Environment Variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | yes | — | Signs sessions and JWTs |
| `DJANGO_DEBUG` | no | `False` | Debug mode (local only) |
| `DJANGO_ALLOWED_HOSTS` | no | `localhost,127.0.0.1` | Comma-separated hostnames |
| `POSTGRES_DB` | yes | — | Database name (also used by the Postgres container) |
| `POSTGRES_USER` | yes | — | Database user |
| `POSTGRES_PASSWORD` | yes | — | Database password |
| `POSTGRES_HOST` | no | `localhost` | Set to `db` inside Compose |
| `POSTGRES_PORT` | no | `5432` | Database port |
| `AWS_STORAGE_BUCKET_NAME` | yes | — | Resume bucket |
| `AWS_S3_REGION_NAME` | no | `us-east-1` | S3 region |
| `AWS_S3_ENDPOINT_URL` | no | real S3 | Internal S3 address (`http://localstack:4566` locally) |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | no | same as above | Address used in presigned URLs (`http://localhost:4566` locally) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | local only | — | `test` / `test` for LocalStack. Not set on AWS (IAM role) |
| `LOCALSTACK_AUTH_TOKEN` | local only | — | LocalStack account token (secret) |

The app fails at startup with a clear message if a required variable is missing.

## Testing

Automated tests (pytest, 80%+ coverage) are planned for Phase 5. Phases 1 and 2 were verified with manual checks over HTTP and in the Django shell: status codes for every user type, upload validation, presigned-URL download plus a tampered-signature check, and filter results. The full list is in `docs/` (terminal checks for Phases 1 and 2).

Phase 2 "Done when" (wrong user types get 403, match scores return correctly): every wrong-user request returned 403, the allowed users still got 200, and the scores matched hand-calculated values (e.g. 2 of 3 required skills → 67).

## Project Structure

```text
00-job-board-api/
├── config/
│   ├── settings.py          ← config from env vars; DRF, JWT, S3 storage settings
│   └── urls.py
├── jobs/
│   ├── models.py            ← User (role), Company, CandidateProfile, Job, Application (+ resume)
│   ├── serializers.py       ← registration, job, application, status serializers
│   ├── views.py             ← register views, JobViewSet, ApplicationViewSet
│   ├── permissions.py       ← IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicationOwner
│   ├── matching.py          ← skill match score (pure function)
│   ├── filters.py           ← JobFilter (type, location, skills)
│   ├── validators.py        ← resume type, size and signature checks
│   ├── storage.py           ← presigned download URLs
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
├── localstack/init/ready.d/
│   └── create-bucket.sh     ← creates the S3 bucket when LocalStack starts
├── scripts/
│   └── dev-helper.sh        ← local test helpers (tokens for test accounts)
├── docs/
├── Dockerfile               ← dev image: Python 3.12, uv, non-root user
├── docker-compose.yml       ← api + PostgreSQL 17 + LocalStack
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
└── manage.py
```

## Design Decisions

- **Permissions as classes, not `if` checks in views.** They're reusable and run before validation, so a wrong user type gets 403 even with a bad request body.
- **403 (not 404) for non-owners.** IDs aren't secret here, and it matches the phase goal. For private data, filtering the queryset (404) would hide existence.
- **The job's company can read an application, but only the job's company can change its status.** The candidate can read but not change it.
- **Match score computed on read.** No migration, always current; the trade-off is no sorting by score in SQL.
- **Resumes go to object storage, never the container disk.** Pods are replaceable and run as several replicas.
- **Random UUID keys, private bucket, 5-minute presigned links returned as JSON.** No personal data in keys, no long-lived links in responses, and the JWT is never forwarded to S3.
- **One settings file for LocalStack and AWS.** Endpoints come from env vars, and credentials come from boto3's credential chain (an IAM role on AWS), never from code.
- **Skills stored lowercase.** Postgres array lookups are case-sensitive.
- **Model validators for files.** The same rule applies in the admin and the API.

## What Broke and How I Fixed It

**Phase 1**
- **Validators that never ran.** Two serializer methods were indented inside `class Meta`, so a candidate could apply to a closed job. Duplicates were still blocked, by the PostgreSQL unique constraint alone. The clue was the error **shape**: a plain string (from the view) instead of a list (from the serializer).
- **A silent typo.** `getattr(user, "candidateprofile", None)` always returned `None` and switched the duplicate check off.
- **500 instead of 403.** Python's `PermissionError` was used instead of DRF's `PermissionDenied`.
- **404 on a route.** An `@action` method was named `application`; the method name is the URL.
- **Wrong enum member** (`User.Role.Company`) and a **silent env var typo** (`PYTHONBUFFERED`).
- **A typo that became a migration.** `create_at` was renamed to `created_at` with a `RenameField` migration.

**Phase 2**
- **A misspelled hook.** `get_permission` (no `s`) was never called by DRF, so an unverified company could post a job. Found by checking `'get_permissions' in JobViewSet.__dict__`.
- **Every presigned URL failed with `SignatureDoesNotMatch`.** The fake AWS keys were `change-me` instead of LocalStack's `test`. S3's own XML error body showed the access key. It only surfaced because LocalStack's signature validation was switched on.
- **A test that passed for the wrong reason.** A tampered download link returned 403, but so did the valid one. A "must fail" check needs a "must succeed" check on the same input.
- **Wrong setting name** (`AWS_S3_PRESIGNED_URL_EXPIRATION`) caused a 500 only when the line ran, not at startup.
- **`lookup_expr` vs `method`** on a django-filter field caused a 500 on every skills search.
- **Oldest jobs first.** The view's `ordering = ["created_at"]` (missing `-`) overrode the model's correct default.
- **`url_path="set-status"`** made the spec's `/status/` route return 404.
- **Blank or misspelled status bodies returned 200.** Model defaults make serializer fields optional; fixed with `extra_kwargs`.