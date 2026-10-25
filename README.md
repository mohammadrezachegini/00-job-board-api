# Job Board API

A Django REST API where companies post jobs and candidates apply. JWT auth with two user types, PostgreSQL, Docker Compose.

> **Status:** Phase 1 (core app) complete. Runs locally. Permissions, matching, resume uploads, background worker and cloud deployment come in later phases.

## Architecture

```text
Client (curl / frontend)
   │  HTTPS + JWT (Authorization: Bearer <token>)
   ▼
┌──────────────────────────── Docker Compose ────────────────────────────┐
│                                                                        │
│  api  (Django 5.2 + DRF, port 8006)                                    │
│   ├── /api/auth/...        register company / candidate, JWT tokens    │
│   ├── /api/jobs/...        list, detail, post, update, applicants      │
│   └── /api/applications/   apply, detail                               │
│          │                                                             │
│          ▼  hostname "db"                                              │
│  db   (PostgreSQL 17, named volume pgdata, not exposed to host)        │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## Features

- Two user types (company, candidate) on a custom Django user model with a `role` field
- Signup endpoints that create the user and its profile in one database transaction
- JWT login with short-lived access tokens (15 min) and refresh tokens (1 day)
- Every endpoint requires a token unless it explicitly opts out (secure by default)
- Companies post and update jobs; jobs are closed instead of deleted, keeping their history
- Candidates apply once per job, enforced by both a serializer check and a PostgreSQL unique constraint
- Companies list the applicants for a job
- Paginated list endpoints (20 per page)
- All configuration from environment variables

## Tech Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.12 |
| Framework | Django 5.2 LTS, Django REST Framework |
| Auth | djangorestframework-simplejwt |
| Database | PostgreSQL 17 (psycopg 3) |
| Dependencies | uv (`pyproject.toml` + `uv.lock`) |
| Containers | Docker, Docker Compose |

## Cloud Services

None yet. Phase 1 runs locally only. AWS (S3, SQS, RDS) and Azure (Blob Storage, Service Bus, Azure Database for PostgreSQL) arrive in later phases and in Project 01.

## API Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/auth/register/company/` | public | Register a company account |
| POST | `/api/auth/register/candidate/` | public | Register a candidate account |
| POST | `/api/auth/token/` | public | Get an access and refresh token |
| POST | `/api/auth/token/refresh/` | public | Get a new access token |
| GET | `/api/jobs/` | token | List open jobs (paginated) |
| POST | `/api/jobs/` | company | Post a job |
| GET | `/api/jobs/{id}/` | token | Job detail |
| PUT / PATCH | `/api/jobs/{id}/` | token | Update a job |
| GET | `/api/jobs/{id}/applications/` | token | Applicants for a job |
| POST | `/api/applications/` | candidate | Apply to a job |
| GET | `/api/applications/{id}/` | token | Application detail |

Owner-only rules and verified-company checks are planned for Phase 2.

## Setup

**Prerequisites:** Docker with Compose, and [uv](https://docs.astral.sh/uv/) (installs Python 3.12 itself).

```bash
git clone https://github.com/mohammadrezachegini/job-board-api.git
cd job-board-api

cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # paste into DJANGO_SECRET_KEY
# also set a real POSTGRES_PASSWORD in .env

docker compose up -d --build
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

The API runs at `http://localhost:8006/api/` and the admin at `http://localhost:8006/admin/`.

To stop the stack: `docker compose down`, which keeps the data. To also delete the database: `docker compose down -v`.

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

The app fails at startup with a clear message if a required variable is missing.

## Testing

Automated tests (pytest, 80%+ coverage) are planned for Phase 5. Phase 1 was verified with an end-to-end smoke test over HTTP:

```bash
API=http://localhost:8006/api
J='Content-Type: application/json'

curl -s -X POST $API/auth/register/company/ -H "$J" \
  -d '{"username":"initech","email":"jobs@initech.test","password":"test-pass-123","company_name":"Initech"}'
CO=$(curl -s -X POST $API/auth/token/ -H "$J" -d '{"username":"initech","password":"test-pass-123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")
curl -s -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $CO" \
  -d '{"title":"Platform Engineer I","description":"Terraform and EKS.","location":"Vancouver, BC"}'
# ...register a candidate, log in, POST /api/applications/, then GET /api/jobs/{id}/applications/ as the company
```

Result: the company posted a job, the candidate applied, and the company's applicant list returned `1 ['riya']`.

## Project Structure

```text
job-board-api/
├── config/
│   ├── settings.py        ← all config from env vars; DRF + JWT settings
│   └── urls.py            ← mounts the admin and /api/
├── jobs/
│   ├── models.py          ← User (role), Company, CandidateProfile, Job, Application
│   ├── serializers.py     ← registration, job and application serializers
│   ├── views.py           ← register views, JobViewSet, ApplicationViewSet
│   ├── urls.py            ← auth paths + router
│   ├── admin.py
│   └── migrations/
├── Dockerfile             ← dev image: Python 3.12, uv, non-root user
├── docker-compose.yml     ← api + PostgreSQL 17
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
└── manage.py
```

## Design Decisions

- **Custom user model from the start**, with `role`. Changing Django's user model later means rewriting foreign keys.
- **The role comes from the endpoint, not the request body.** A client can't choose to be a company.
- **`company` and `candidate` are set from the token**, never from input, which blocks mass assignment.
- **Database constraint plus serializer check** for "one application per job". The check gives a clear error; the constraint handles race conditions.
- **PostgreSQL from day one**, not SQLite, so behaviour matches production (RDS).
- **uv with a lockfile**, for the same dependency versions locally and in Docker.
- **JWT**: stateless auth that works across many API replicas on Kubernetes.

## What Broke and How I Fixed It

- **Validators that never ran.** Two serializer methods were indented inside `class Meta`, so DRF never called them, and a candidate could apply to a closed job. Duplicate applications were still blocked, by the PostgreSQL unique constraint alone. The clue was the error **shape**: a plain string (raised in the view) instead of a list (raised in the serializer).
- **A typo that failed silently.** `getattr(user, "candidateprofile", None)` instead of `"candidate_profile"` always returned `None`, which turned the duplicate check off without any error.
- **500 instead of 403.** `PermissionError` (Python's built-in) was used instead of DRF's `PermissionDenied`.
- **404 on the applicants route.** The `@action` method was named `application`; the method name is the URL segment.
- **Wrong enum member.** `User.Role.Company` instead of `User.Role.COMPANY` raised a 500 on company signup.
- **Silent env var typo.** `PYTHONBUFFERED` instead of `PYTHONUNBUFFERED` in the Dockerfile. Python ignores unknown names, so there was no error, just buffered logs.