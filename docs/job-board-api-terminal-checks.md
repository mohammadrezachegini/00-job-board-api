# Job Board API — Terminal Checks (Phases 1–6)

Every manual check run from the terminal so far, in the order we ran them. Each one is the **final, working** version: commands that had typos or bugs during the sessions are given here in their corrected form.

**How to use this file**
- Run everything from the repo root (`~/projects/00-job-board-api`) unless a step says otherwise.
- **Data-dependent IDs.** Many checks use IDs from this database: job 1 (Acme), job 3 (Initech), application 3 (sam → job 1), application 12 (riya → job 1). On a fresh database they'll differ. Look them up first (section 0.3).
- **⚠ marks commands that change data** (create users, jobs, applications, files). Running them twice usually fails with a uniqueness error, which is expected.
- Tokens last **15 minutes**. If you start seeing `401` with `Given token not valid`, run `login_all` again.
- Most checks will become pytest tests in Phase 5.
- **Behaviour changed after some checks were first run.** Checks are listed with the result they gave *at the time*. Running them today can give a different, correct answer:
  - Applying with JSON (no file) now returns `400 {"resume": ["No file was submitted."]}`: resumes are required since Phase 2, Step 3.
  - Posting a job now needs a **verified** company: only Acme is verified.
  - Responses no longer include `resume`; they include `has_resume` (Phase 2, Step 3, Part C).
  - **Since Phase 4, Step 3, every log line is JSON** (`{"level": ..., "logger": ..., "message": ...}`). Greps on message text (`grep "Emailed"`) still work; expectations of the old plain format (`2026-... INFO worker ...`, `Found credentials...`) no longer match. botocore's INFO lines are hidden (WARNING level).
  - **Since Phase 4, Step 4, Phase 1's host-side `uv run python manage.py ...` checks don't work as written:** `POSTGRES_HOST=db` is required and only resolves inside the Compose network, and `.env` isn't loaded on the host. Run them with `docker compose exec api python manage.py ...` instead.
  - **Since Phase 4, Step 4, unknown `Host` headers get `400`.** Other machines must use an address listed in `DJANGO_ALLOWED_HOSTS` (thor: `10.0.0.149`).
  - **The secret key was rotated in Phase 4, Step 4:** tokens issued before that get `401`. Run `login_all` again.
  - **`docker compose up -d` / `restart` return before the API listens.** Run `waitapi` before any check (Phase 4, Step 2).
  - **LocalStack now needs `.env.localstack`** (its auth token, Phase 4, Step 4). Without it, `docker compose up` refuses to start.

---

## 0. Setup used by most checks

### 0.1 Helper script: `scripts/dev-helper.sh`

```bash
API=http://localhost:8006/api
J='Content-Type: application/json'

token() {
  curl -s -X POST "$API/auth/token/" \
    -H "$J" \
    -d "{\"username\": \"$1\", \"password\": \"${2:-test-pass-123}\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])"
}

login_all() {
  ACME=$(token acme); GLOBEX=$(token globex); INITECH=$(token initech)
  DANA=$(token dana); SAM=$(token sam); RIYA=$(token riya)
  echo "Tokens loaded (valid 15 min)."
}

# Count + titles of a paginated job list (end of a pipe)
titles() { python3 -c "import sys, json; d = json.load(sys.stdin); print(d['count'], [j['title'] for j in d['results']])" 2>/dev/null || echo "not JSON: run the same curl with -i"; }

# Show only the X-Cache response header (Phase 3, Step 1)
xcache() { curl -s -o /dev/null -D - "$@" | grep -i '^x-cache' || echo "(no X-Cache header)"; }

# Status-code assertion: check "label" expected curl-args...
check() { local got; got=$(curl -s -o /dev/null -w "%{http_code}" "${@:3}"); printf "%-45s expected %s got %s %s\n" "$1" "$2" "$got" "$([ "$got" = "$2" ] && echo OK || echo FAIL)"; }

# SQS queue depth: messages waiting / in flight (Phase 3, Step 2). Usage: qdepth job-board-status
qdepth() { docker compose exec -T localstack sh -c "awslocal sqs get-queue-attributes --queue-url \"\$(awslocal sqs get-queue-url --queue-name $1 --query QueueUrl --output text)\" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes" 2>/dev/null | grep -v WARNING | tr -d '\n '; echo; }

# Readiness check: status, time, curl exit code, JSON (Phase 4, Step 1). Usage: r
# rm first, so a killed curl can never show the previous result; exit=124 means timeout killed it
r() { rm -f /tmp/ready.json; timeout 30 curl -s -o /tmp/ready.json -w "HTTP %{http_code} in %{time_total}s\n" http://localhost:8006/readyz; echo "curl exit=$?"; [ -s /tmp/ready.json ] && python3 -m json.tool /tmp/ready.json; }

# Wait until the API really answers (after up -d / restart / rebuild). Usage: waitapi
waitapi() { for i in $(seq 30); do curl -s -o /dev/null http://localhost:8006/healthz && { echo "api up after ${i}s"; return 0; }; sleep 1; done; echo "api NOT up after 30s: docker compose logs --tail=30 api"; return 1; }

# Grep the Prometheus metrics (Phase 4, Step 2). Usage: m 'view="job-list"'
m() { curl -s http://localhost:8006/metrics | grep "$1"; }

R=~/resume-test   # folder with the resume test files (section 2.3)
```

This is the **complete** helper file as it should be now. If `titles`, `xcache`, `check`, `qdepth`, `r`, `waitapi` or `m` gives `command not found`, they're missing from your copy.

Load it **with `source`**, so the variables and functions stay in your current shell:

```bash
source scripts/dev-helper.sh; login_all
```

### 0.2 Pipe helpers

All of them now live in `scripts/dev-helper.sh` (section 0.1), so every terminal gets them through `source`.

### 0.3 Test accounts and current data

| User | Role | Notes |
| --- | --- | --- |
| admin | superuser | role empty |
| acme | company | **verified**; owns jobs 1, 2 (closed), 4, 6 |
| globex | company | unverified |
| initech | company | unverified; owns job 3 |
| dana, sam, riya | candidate | |

All test passwords are `test-pass-123` (local throwaway accounts only).

```bash
# Users
docker compose exec api python manage.py shell -c "from jobs.models import User; print(list(User.objects.values_list('id', 'username', 'role')))"

# Companies and verification
docker compose exec api python manage.py shell -c "from jobs.models import Company; print(list(Company.objects.values_list('name', 'is_verified')))"

# Jobs
docker compose exec api python manage.py shell -c "from jobs.models import Job; [print(j.id, j.is_open, j.job_type, repr(j.location), j.company.name, j.required_skills, j.title, j.created_at) for j in Job.objects.select_related('company').order_by('id')]"

# Applications
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(list(Application.objects.values_list('id', 'job_id', 'candidate__user__username', 'status', 'resume')))"

# Candidate skills
docker compose exec api python manage.py shell -c "from jobs.models import CandidateProfile; print({c.user.username: c.skills for c in CandidateProfile.objects.select_related('user')})"
```

### 0.4 Debugging toolbox (used throughout)

```bash
# See the status code when output "looks wrong" (JSONDecodeError = not JSON = probably HTML 404/500)
curl -s -i <url> -H "Authorization: Bearer $DANA" | head -n 1

# Read the real error: last line of the traceback, last frame in /app/jobs/...
docker compose logs --tail=40 api

# Is a method really defined on the class? (catches get_permission vs get_permissions)
docker compose exec api python manage.py shell -c "from jobs.views import JobViewSet; print('get_permissions' in JobViewSet.__dict__)"

# Which URLs does the router actually generate? (catches url_path / @action name mistakes)
docker compose exec api python manage.py shell -c "from jobs.urls import router; print([str(u.pattern) for u in router.urls])"

# Look inside Redis (cache keys, TTLs)
docker compose exec redis redis-cli --scan --pattern 'jobboard:*'
docker compose exec redis redis-cli ttl <key>

# Queue depth (waiting / in flight)
qdepth job-board-status
qdepth job-board-status-dlq

# Only recent log lines; count matches
docker compose logs --since 10s worker
docker compose logs --since 15m worker | grep -c "Failed to handle message"
docker compose logs localstack | tail -n 40      # init-script errors

# Readiness of every dependency, with timings (Phase 4)
r
curl -s -i http://localhost:8006/healthz | head -n 1

# After ANY up -d / restart / rebuild: wait for the app, not the container (000 / exit 56 = not listening yet)
waitapi

# Metrics: a series, its before/after, or everything for one view
m 'django_http_responses_total_by_status_view_method_total{.*view="job-list"'
m 'view="application-set-status"'

# Freeze vs stop a dependency (pause = accepts connections, never answers; only timeouts help)
docker compose pause localstack;  r;  docker compose unpause localstack
docker compose stop redis;        r;  docker compose start redis

# Which restart policy does a container REALLY have? (set at creation; `restart` doesn't change it)
docker inspect -f '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}' $(docker compose ps -aq api worker)

# Is an env var set inside the container, without printing a secret?
docker compose exec api sh -c 'echo "key=$AWS_ACCESS_KEY_ID secret_len=${#AWS_SECRET_ACCESS_KEY}"'
```

**Reading error shapes:** `{"field": ["msg"]}` (a list) comes from a **serializer**; `{"field": "msg"}` (a string) was raised in a **view**; `{"detail": "msg"}` is a permission or auth error.

---

## 1. Phase 1 — Core App

### 1.1 Step 1: Django + DRF + PostgreSQL in Docker Compose

**Tool versions**
```bash
python3.12 --version          # the first check given: not installed on thor (that's why uv provides 3.12)
python3.14 --version          # system Python (not used by the project)
docker compose version
uv --version
uv python install 3.12
uv python list --only-installed
uv run python --version       # expect Python 3.12.x
```

**Packages installed in the project venv**
```bash
uv run python -c "import django, rest_framework, psycopg; print(django.get_version(), rest_framework.VERSION, psycopg.__version__)"
```

**Settings load from env vars (on thor, no Docker)**
```bash
set -a; source .env; set +a
uv run python manage.py check
# System check identified no issues (0 silenced).

uv run python manage.py shell -c "from django.conf import settings; print(settings.DEBUG, settings.ALLOWED_HOSTS, settings.DATABASES['default']['ENGINE'])"
# True ['localhost', '127.0.0.1'] django.db.backends.postgresql
```

**Required-variable guard (negative test)**
```bash
env -u DJANGO_SECRET_KEY uv run python manage.py check
# ...ImproperlyConfigured: Missing required environment variable: DJANGO_SECRET_KEY
```

**Stack up**
```bash
id -u                                    # expect 1000
docker compose up -d --build
docker compose ps                        # db (healthy), api Up   (+ localstack (healthy) since Phase 2, Step 3)
docker compose logs api
```

**Migrations applied to Postgres**
```bash
docker compose exec api python manage.py migrate
docker compose exec api python manage.py showmigrations auth          # all [X]
docker compose exec db psql -U jobboard -d jobboard -c '\dt'          # note: '\dt' with no trailing backslash
```

**App answers HTTP**
```bash
curl -I http://localhost:8006/admin/
# HTTP/1.1 302 Found, Location: /admin/login/?next=/admin/
```

**Which database is the API really connected to?** (used when `\dt` showed no tables)
```bash
docker compose exec api python manage.py shell -c "from django.db import connection as c; s = c.settings_dict; print(s['HOST'], s['NAME'], s['USER'])"
# db jobboard jobboard   (host "localhost" here = the Compose environment override isn't applied)
```

**What holds port 8000 on thor?** (why the app moved to 8006)
```bash
sudo ss -ltnp | grep ':8000'
```

**Unbuffered output in the image**
```bash
docker compose exec api env | grep PYTHONUNBUFFERED      # PYTHONUNBUFFERED=1
```

**Secrets stay out of git**
```bash
git status --short       # .env must never appear
```

### 1.2 Step 2: Models

**Part A — custom User**
```bash
docker compose exec api python manage.py startapp jobs        # ⚠ once only
ls -l jobs/ jobs/migrations/                                   # owned by reza (UID 1000)

docker compose exec api python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model())"
# <class 'jobs.models.User'>

docker compose exec db psql -U jobboard -d jobboard -c '\dt'
# jobs_user, jobs_user_groups, jobs_user_user_permissions, no auth_user

docker compose exec api python manage.py shell -c "from jobs.models import User; u = User(role=User.Role.CANDIDATE); print(u.is_candidate, u.is_company)"
# True False   (in memory only, nothing saved)
```

**Part B — Company and CandidateProfile** ⚠ creates acme and dana
```bash
docker compose exec -T api python manage.py shell <<'EOF'
from jobs.models import User, Company, CandidateProfile

acme = User.objects.create_user(username="acme", email="hr@acme.test", password="test-pass-123", role=User.Role.COMPANY)
Company.objects.create(user=acme, name="Acme")

dana = User.objects.create_user(username="dana", email="dana@example.test", password="test-pass-123", role=User.Role.CANDIDATE)
CandidateProfile.objects.create(user=dana, headline="Junior Python dev", skills=["python", "django", "docker"])

print(acme.company, acme.company.is_verified)
print(dana.candidate_profile.skills)
print(CandidateProfile.objects.filter(skills__contains=["django"]).count())
EOF
# Acme False / ['python', 'django', 'docker'] / 1
```

Array lookup on its own:
```bash
docker compose exec api python manage.py shell -c "from jobs.models import CandidateProfile; print(CandidateProfile.objects.filter(skills__contains=['django']).count())"
```

Verify a company (this is what the admin checkbox does):
```bash
docker compose exec api python manage.py shell -c "from jobs.models import Company; print(Company.objects.filter(name='Acme').update(is_verified=True))"
```

**Part C — Job and Application** ⚠ creates job 1 and application 1
```bash
docker compose exec -T api python manage.py shell <<'EOF'
from django.db import IntegrityError, transaction
from jobs.models import Application, CandidateProfile, Company, Job

acme = Company.objects.get(name="Acme")
dana = CandidateProfile.objects.get(user__username="dana")

job = Job.objects.create(
    company=acme,
    title="Junior DevOps Engineer",
    description="Run our Kubernetes platform.",
    location="Vancouver, BC",
    required_skills=["python", "docker", "kubernetes"],
)
app = Application.objects.create(job=job, candidate=dana, cover_letter="Hi!")
print(app, app.status)
print(acme.jobs.count(), job.applications.count(), dana.applications.count())

try:
    with transaction.atomic():
        Application.objects.create(job=job, candidate=dana)
except IntegrityError as e:
    print("Duplicate blocked:", type(e).__name__)

print(Job.objects.filter(required_skills__overlap=dana.skills).count())
EOF
# dana -> Junior DevOps Engineer (Acme) submitted / 1 1 1 / Duplicate blocked: IntegrityError / 1
```

**Browser checks in the admin** (not terminal, but part of this step): open `http://localhost:8006/admin/` and log in with the superuser.
- **Users** has a Role column and a Role filter.
- **Companies** shows each company with an editable "Is verified" checkbox (tick it and **Save**; Phase 1 planned this for Acme but it was never done).
- **Candidate profiles** lists the candidates.
- **Jobs** has the job type and open filters; **Applications** shows `dana -> Junior DevOps Engineer (Acme)` with its status.
- From another machine, thor's IP must be in `DJANGO_ALLOWED_HOSTS`, or you get a 400.

**Schema state**
```bash
docker compose exec api python manage.py showmigrations jobs
docker compose exec db psql -U jobboard -d jobboard -c '\dt jobs_*'
ls jobs/migrations/
```

### 1.3 Step 3: JWT auth

**Package in the container (not just on thor)**
```bash
docker compose exec api python -c "from importlib.metadata import version; print(version('djangorestframework-simplejwt'))"
```

**Token pair**
```bash
curl -s -X POST http://localhost:8006/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dana", "password": "test-pass-123"}'
# {"refresh":"eyJ...","access":"eyJ..."}
```

**Wrong password → 401**
```bash
curl -s -i -X POST http://localhost:8006/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dana", "password": "wrong"}'
# 401 {"detail":"No active account found with the given credentials"}
```

**Decode a JWT payload (no key needed: signed, not encrypted)**
```bash
ACCESS=$(curl -s -X POST http://localhost:8006/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dana", "password": "test-pass-123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])")

python3 -c "import sys, base64, json; p = sys.argv[1].split('.')[1]; print(json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))))" "$ACCESS"
# {'token_type': 'access', 'exp': ..., 'iat': ..., 'jti': '...', 'user_id': '3'}   exp - iat = 900
```

**Refresh**
```bash
REFRESH=$(curl -s -X POST http://localhost:8006/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "dana", "password": "test-pass-123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['refresh'])")

curl -s -X POST http://localhost:8006/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH\"}"
# {"access":"eyJ..."}
```

**Register** ⚠ creates globex and sam
```bash
# Company, with a sneaked is_verified (must be ignored)
curl -s -i -X POST http://localhost:8006/api/auth/register/company/ \
  -H "Content-Type: application/json" \
  -d '{"username": "globex", "email": "HR@Globex.test", "password": "test-pass-123", "company_name": "Globex", "website": "https://globex.test", "is_verified": true}'
# 201 {"id":4,"username":"globex","email":"hr@globex.test","role":"company"}

# Candidate
curl -s -i -X POST http://localhost:8006/api/auth/register/candidate/ \
  -H "Content-Type: application/json" \
  -d '{"username": "sam", "email": "sam@example.test", "password": "test-pass-123", "headline": "Junior SRE", "skills": ["python", "kubernetes"]}'
# 201 {"id":5,...,"role":"candidate"}

# New user can log in
curl -s -X POST http://localhost:8006/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "globex", "password": "test-pass-123"}'
```

**Both rows exist; mass assignment blocked**
```bash
docker compose exec api python manage.py shell -c "from jobs.models import User; g = User.objects.get(username='globex'); s = User.objects.get(username='sam'); print(g.role, g.company.name, g.company.website, g.company.is_verified); print(s.role, s.candidate_profile.headline, s.candidate_profile.skills)"
# company Globex https://globex.test False / candidate Junior SRE ['python', 'kubernetes']
```

**Validation errors → 400 keyed by field**
```bash
# Duplicate username, different case
curl -s -i -X POST http://localhost:8006/api/auth/register/candidate/ -H "Content-Type: application/json" \
  -d '{"username": "SAM", "email": "other@example.test", "password": "test-pass-123"}'
# {"username":["This username is already taken."]}

# Weak password
curl -s -X POST http://localhost:8006/api/auth/register/candidate/ -H "Content-Type: application/json" \
  -d '{"username": "weakling", "email": "weak@example.test", "password": "12345"}'; echo
# {"password":[...too short..., ...too common..., ...entirely numeric...]}

# Missing company_name
curl -s -X POST http://localhost:8006/api/auth/register/company/ -H "Content-Type: application/json" \
  -d '{"username": "noname", "email": "noname@example.test", "password": "test-pass-123"}'; echo
# {"company_name":["This field is required."]}
```

### 1.4 Step 4: CRUD endpoints

Setup: `source scripts/dev-helper.sh; login_all`

**Part A — jobs**
```bash
# No token → 401
curl -s -i $API/jobs/ | head -n 1

# List as a candidate (paginated)
curl -s $API/jobs/ -H "Authorization: Bearer $DANA" | python3 -m json.tool

# ⚠ Company posts a job, trying to post it for Globex (must be ignored)
JOB_ID=$(curl -s -X POST $API/jobs/ \
  -H "Authorization: Bearer $ACME" -H "$J" \
  -d '{"title": "Junior SRE", "description": "Keep our services up.", "location": "Remote, Canada", "job_type": "contract", "required_skills": ["python", "prometheus"], "company": "Globex"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "JOB_ID=$JOB_ID"
curl -s $API/jobs/$JOB_ID/ -H "Authorization: Bearer $ACME" | python3 -m json.tool      # "company": "Acme"

# Candidate posts → 403
curl -s -i -X POST $API/jobs/ -H "Authorization: Bearer $DANA" -H "$J" \
  -d '{"title": "x", "description": "x", "location": "x"}'

# ⚠ PUT (full) then PATCH (partial, closes the job)
curl -s -X PUT $API/jobs/$JOB_ID/ -H "Authorization: Bearer $ACME" -H "$J" \
  -d '{"title": "Junior SRE (Contract)", "description": "Keep our services up.", "location": "Remote, Canada", "job_type": "contract", "required_skills": ["python", "prometheus", "grafana"]}' | python3 -m json.tool
curl -s -X PATCH $API/jobs/$JOB_ID/ -H "Authorization: Bearer $ACME" -H "$J" -d '{"is_open": false}' | python3 -m json.tool

# Closed job: gone from the list, still reachable by ID
curl -s $API/jobs/ -H "Authorization: Bearer $DANA" | titles
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/$JOB_ID/ -H "Authorization: Bearer $DANA"     # 200

# No delete → 405
curl -s -i -X DELETE $API/jobs/$JOB_ID/ -H "Authorization: Bearer $ACME" | head -n 1
```

**Part B — applications** (the JSON-only versions from Phase 1; since Phase 2, Step 3, applying needs a resume file, see section 2.3)
```bash
# ⚠ sam applies and tries to set his own status (must stay "submitted") — Phase 1 JSON version
APP_ID=$(curl -s -X POST $API/applications/ \
  -H "Authorization: Bearer $SAM" -H "$J" \
  -d "{\"job\": 1, \"cover_letter\": \"I run Prometheus at home.\", \"status\": \"offered\"}" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d, file=sys.stderr); print(d['id'])")
echo "APP_ID=$APP_ID"

OPEN_JOB=$(docker compose exec -T api python manage.py shell -c "from jobs.models import Job; print(Job.objects.filter(title='Junior DevOps Engineer').first().id)" | tail -n 1)
CLOSED_JOB=$(docker compose exec -T api python manage.py shell -c "from jobs.models import Job; print(Job.objects.filter(is_open=False).first().id)" | tail -n 1)
echo "OPEN_JOB=$OPEN_JOB CLOSED_JOB=$CLOSED_JOB"

# Duplicate → 400 (list = serializer caught it)
curl -s -X POST $API/applications/ -H "Authorization: Bearer $SAM" -H "$J" -d "{\"job\": $OPEN_JOB}"; echo

# Closed job → 400
curl -s -X POST $API/applications/ -H "Authorization: Bearer $DANA" -H "$J" -d "{\"job\": $CLOSED_JOB}"; echo

# Unknown job → 400 (not 404: the body is bad, not the URL)
curl -s -X POST $API/applications/ -H "Authorization: Bearer $DANA" -H "$J" -d '{"job": 99999}'; echo

# Company applies → 403
curl -s -i -X POST $API/applications/ -H "Authorization: Bearer $ACME" -H "$J" -d "{\"job\": $OPEN_JOB}" | head -n 1

# Application detail
curl -s $API/applications/3/ -H "Authorization: Bearer $SAM" | python3 -m json.tool

# Applicants for job 1
curl -s $API/jobs/$OPEN_JOB/applications/ -H "Authorization: Bearer $ACME" | python3 -m json.tool

# No list / no delete on applications → 405, 405
curl -s -o /dev/null -w "%{http_code}\n" $API/applications/ -H "Authorization: Bearer $SAM"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE $API/applications/3/ -H "Authorization: Bearer $SAM"
```

### 1.5 Phase 1 Done-when: end-to-end with fresh users ⚠

Change the usernames if `initech` and `riya` already exist.

```bash
API=http://localhost:8006/api
J='Content-Type: application/json'

echo "== 1. Company registers =="
curl -s -X POST $API/auth/register/company/ -H "$J" \
  -d '{"username": "initech", "email": "jobs@initech.test", "password": "test-pass-123", "company_name": "Initech"}'; echo

echo "== 2. Company logs in =="
CO=$(curl -s -X POST $API/auth/token/ -H "$J" -d '{"username": "initech", "password": "test-pass-123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])")
echo "token: ${CO:0:20}..."

echo "== 3. Company posts a job =="
NEW_JOB=$(curl -s -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $CO" \
  -d '{"title": "Platform Engineer I", "description": "Terraform and EKS.", "location": "Vancouver, BC", "required_skills": ["terraform", "kubernetes"]}' \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d, file=sys.stderr); print(d['id'])")
echo "job id: $NEW_JOB"

echo "== 4. Candidate registers =="
curl -s -X POST $API/auth/register/candidate/ -H "$J" \
  -d '{"username": "riya", "email": "riya@example.test", "password": "test-pass-123", "skills": ["terraform", "aws"]}'; echo

echo "== 5. Candidate logs in =="
CA=$(curl -s -X POST $API/auth/token/ -H "$J" -d '{"username": "riya", "password": "test-pass-123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])")
echo "token: ${CA:0:20}..."

echo "== 6. Candidate sees the job =="
curl -s $API/jobs/ -H "Authorization: Bearer $CA" \
  | python3 -c "import sys, json; print([j['title'] for j in json.load(sys.stdin)['results']])"

echo "== 7. Candidate applies (resume required since Phase 2) =="
curl -s -X POST $API/applications/ -H "Authorization: Bearer $CA" \
  -F "job=$NEW_JOB" -F "cover_letter=I build EKS with Terraform." -F "resume=@$HOME/resume-test/good.pdf"; echo

echo "== 8. Company sees the applicant =="
curl -s $API/jobs/$NEW_JOB/applications/ -H "Authorization: Bearer $CO" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['count'], [a['candidate'] for a in d['results']])"
```

Note: since Phase 2, step 3 needs a **verified** company (Initech is unverified, so it gets 403), and step 7 needs a resume file. Verify the company first (section 1.2) when re-running this.

---

## 2. Phase 2 — Business Logic + Permissions

Setup: `source scripts/dev-helper.sh; login_all`

### 2.1 Step 1: Permission classes

**Methods are where you think they are**
```bash
docker compose exec api python manage.py shell -c "from jobs.views import JobViewSet, ApplicationViewSet; from jobs.permissions import IsJobOwner, IsApplicationOwner; print(all('get_permissions' in c.__dict__ for c in (JobViewSet, ApplicationViewSet)), all('has_object_permission' in c.__dict__ for c in (IsJobOwner, IsApplicationOwner)))"
# True True
```

**Part A — role permissions**
```bash
JOB='{"title": "Backend Developer", "description": "Django APIs.", "location": "Burnaby, BC"}'

curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $ACME" -d "$JOB"     # ⚠ 201 (verified)
curl -s -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $GLOBEX" -d "$JOB"; echo                                # 403 not verified
curl -s -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $DANA" -d "$JOB"; echo                                  # 403 company only
curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/jobs/ -H "$J" -d "$JOB"                                        # 401 no token

curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/applications/ -H "$J" -H "Authorization: Bearer $SAM" -d '{"job": 3}'   # ⚠ 201 (Phase 2 Step 1, before resumes were required)
curl -s -X POST $API/applications/ -H "$J" -H "Authorization: Bearer $SAM" -d '{"job": 3}'; echo                               # 400 already applied (list = serializer)
curl -s -X POST $API/applications/ -H "Authorization: Bearer $ACME" -F "job=3"; echo                                 # 403 candidate only
curl -s -i -X POST $API/applications/ -H "Authorization: Bearer $ACME" -F "job=99999" | head -n 1                    # 403 (permission runs before validation)
```

**Part B — ownership permissions**
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $ACME"    -d '{"title": "Junior DevOps Engineer"}'   # 200 owner
curl -s -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $GLOBEX" -d '{"title": "Hacked"}'; echo                                         # 403 not owner
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $DANA"    -d '{"title": "Hacked"}'                    # 403
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/3/ -H "$J" -H "Authorization: Bearer $INITECH" -d '{"title": "Platform Engineer I"}'      # 200 unverified owner

# Applicants of job 1: owner / other company / candidate
curl -s $API/jobs/1/applications/ -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print(json.load(sys.stdin)['count'])"
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/1/applications/ -H "Authorization: Bearer $INITECH"     # 403
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/1/applications/ -H "Authorization: Bearer $SAM"         # 403

# Application 3 (sam → job 1): who can read it
for who in SAM ACME DANA INITECH; do
  printf "%-8s " "$who"
  curl -s -o /dev/null -w "%{http_code}\n" $API/applications/3/ -H "Authorization: Bearer ${!who}"
done
# SAM 200, ACME 200, DANA 403, INITECH 403

curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/99999/ -H "$J" -H "Authorization: Bearer $GLOBEX" -d '{"title": "x"}'   # 404
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/1/ -H "Authorization: Bearer $DANA"                                             # 200 browsing open
```

**Part C — status endpoint**
```bash
# Is the action on the class, and what URL segment does it use? (found url_path="set-status")
docker compose exec api python manage.py shell -c "from jobs.views import ApplicationViewSet; print('set_status' in ApplicationViewSet.__dict__, getattr(ApplicationViewSet.set_status, 'url_path', None))"
# True status

docker compose exec api python manage.py shell -c "from jobs.urls import router; print([str(u.pattern) for u in router.urls if 'status' in str(u.pattern)])"

curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}' \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['id'], d['candidate'], d['status'])"          # ⚠ 3 sam reviewing
curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $SAM" -d '{"status": "offered"}'; echo                 # 403
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $INITECH" -d '{"status": "rejected"}'   # 403
curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "hired"}'; echo                  # 400 invalid choice
curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{}'; echo                                   # 400 required
curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"stauts": "rejected"}'; echo               # 400 required (misspelled key)
curl -s $API/applications/3/ -H "Authorization: Bearer $SAM" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])"   # reviewing
curl -s -o /dev/null -w "%{http_code}\n" $API/applications/3/status/ -H "Authorization: Bearer $ACME"                                  # 405 GET
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/99999/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}'   # 404
```

### 2.2 Step 2: Match score

**Unit check of the pure function (no DB, no HTTP)**
```bash
docker compose exec -T api python manage.py shell <<'EOF'
from jobs.matching import match_score

cases = [
    (["python", "docker", "kubernetes"], ["Python", "docker"], 67),
    (["python", "docker"], ["python", "docker", "aws"], 100),
    (["python"], [], 0),
    ([], ["python"], None),
    ([" Python "], ["python"], 100),
    (["python", "python", "docker"], ["python"], 50),
    (["python", "", "  "], ["python"], 100),
]
for required, candidate, expected in cases:
    got = match_score(required, candidate)
    print("OK  " if got == expected else "FAIL", required, candidate, "->", got, "expected", expected)
EOF
```

**Through the API**
```bash
curl -s $API/applications/3/ -H "Authorization: Bearer $SAM" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['candidate'], d['job_title'], d['match_score'])"
curl -s $API/jobs/1/applications/ -H "Authorization: Bearer $ACME" \
  | python3 -c "import sys, json; print([(a['candidate'], a['match_score']) for a in json.load(sys.stdin)['results']])"
curl -s $API/jobs/3/applications/ -H "Authorization: Bearer $INITECH" \
  | python3 -c "import sys, json; print([(a['candidate'], a['match_score']) for a in json.load(sys.stdin)['results']])"
curl -s -o /dev/null -w "%{http_code}\n" $API/applications/3/ -H "Authorization: Bearer $DANA"       # 403
```

### 2.3 Step 3: Resume upload to S3 (LocalStack)

**Part A — S3 wiring**
```bash
docker compose exec localstack awslocal s3 ls 2>/dev/null | grep -v WARNING          # the bucket

docker compose exec api python manage.py shell -c "from django.core.files.storage import storages; print(type(storages['default']).__name__)"
# S3Storage   (type(default_storage) shows the lazy wrapper DefaultStorage)

docker compose exec api python manage.py shell -c "from django.core.files.storage import default_storage as s; print(s.bucket_name, s.endpoint_url)"

# Round trip: save, exists, read, size, delete
docker compose exec api python manage.py shell -c "from django.core.files.base import ContentFile; from django.core.files.storage import default_storage as s; n = s.save('healthcheck/hello.txt', ContentFile(b'hello s3')); print(n, s.exists(n), s.open(n).read(), s.size(n)); s.delete(n); print(s.exists(n))"
# healthcheck/hello.txt True b'hello s3' 8 / False

# No overwrite: second save gets a suffix
docker compose exec api python manage.py shell -c "from django.core.files.base import ContentFile; from django.core.files.storage import default_storage as s; a = s.save('healthcheck/same.txt', ContentFile(b'a')); b = s.save('healthcheck/same.txt', ContentFile(b'b')); print(a, b, a != b); s.delete(a); s.delete(b)"

# LocalStack version and S3 status, asked from the api container (curl isn't in the LocalStack image)
docker compose exec api python -c "import json, urllib.request; d = json.load(urllib.request.urlopen('http://localstack:4566/_localstack/health')); print(d.get('version'), d['services'].get('s3'))"
# 2026.10.4 running
```

**Part B — test files** (outside the repo)
```bash
mkdir -p ~/resume-test && cd ~/resume-test
printf '%%PDF-1.4\nfake resume\n%%%%EOF\n' > good.pdf          # 27 B, PDF signature
printf 'PK\x03\x04fake docx' > good.docx                       # 13 B, ZIP signature
echo "just text" > renamed.pdf                                  # wrong content
echo "just text" > notes.txt                                    # wrong extension
{ printf '%%PDF-'; head -c 6000000 /dev/zero; } > big.pdf       # ~6 MB, valid signature
ls -l
cd ~/projects/00-job-board-api
R=~/resume-test
```

**Part B — upload checks** (multipart: `-F`, and **no** JSON content-type header)
```bash
# ⚠ Valid PDF → 201
curl -s -X POST $API/applications/ -H "Authorization: Bearer $RIYA" \
  -F "job=1" -F "cover_letter=Terraform and AWS." -F "resume=@$R/good.pdf" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('id'), d.get('candidate'), d.get('has_resume'))"

# Each bad file rejected for its own reason (all 400)
for f in renamed.pdf notes.txt big.pdf; do
  printf "%-12s " "$f"
  curl -s -X POST $API/applications/ -H "Authorization: Bearer $DANA" -F "job=3" -F "resume=@$R/$f"; echo
done
printf "%-12s " "(no file)"
curl -s -X POST $API/applications/ -H "Authorization: Bearer $DANA" -F "job=3"; echo

# ⚠ Valid DOCX → 201
curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/applications/ -H "Authorization: Bearer $DANA" -F "job=3" -F "resume=@$R/good.docx"

# Stored files are complete (sizes equal local files: the seek(0) rewind works)
docker compose exec -T api python manage.py shell <<'EOF'
from jobs.models import Application
for a in Application.objects.exclude(resume="").select_related("candidate__user"):
    with a.resume.open("rb") as f:
        head = f.read(5)
    print(a.candidate.user.username, a.resume.name, a.resume.size, head)
EOF
wc -c ~/resume-test/good.pdf ~/resume-test/good.docx

# Only valid files reached S3
docker compose exec localstack awslocal s3 ls s3://00-job-board-api/ --recursive 2>/dev/null | grep -v WARNING

# Applicants of job 1: match score still works, and who has a resume
# (Part B used bool(a['resume']); since Part C the field is write-only, so read has_resume)
curl -s $API/jobs/1/applications/ -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print([(a['candidate'], a['match_score'], a['has_resume']) for a in json.load(sys.stdin)['results']])"
# [('riya', 0, True), ('sam', 67, False), ('dana', 67, False)]
```

**After a LocalStack restart** (S3 is empty again; re-upload a file) ⚠
```bash
docker compose exec -T api python manage.py shell <<'EOF'
from django.core.files.base import ContentFile
from jobs.models import Application
a = Application.objects.get(id=12)
a.resume.save("good.pdf", ContentFile(b"%PDF-1.4\nfake resume\n%%EOF\n"))
print(a.resume.name, a.resume.size)
EOF
```

**Part C — downloads**
```bash
# No resume link in normal responses
curl -s $API/applications/12/ -H "Authorization: Bearer $RIYA" | python3 -c "import sys, json; d = json.load(sys.stdin); print('resume' in d, d['has_resume'])"   # False True
curl -s $API/applications/3/ -H "Authorization: Bearer $SAM" | python3 -c "import sys, json; print(json.load(sys.stdin)['has_resume'])"                       # False

# Presigned URL (5 minutes)
URL=$(curl -s $API/applications/12/resume/ -H "Authorization: Bearer $RIYA" | python3 -c "import sys, json; print(json.load(sys.stdin)['url'])"); echo "${URL:0:60}"

# Inspect its parts (no secret in it)
echo "$URL" | tr '&?' '\n\n'

# POSITIVE: real link downloads the exact file, no token needed
curl -s -D /tmp/resume-headers.txt -o /tmp/downloaded.pdf "$URL"; grep -i -E "^HTTP|content-disposition" /tmp/resume-headers.txt; cmp /tmp/downloaded.pdf $R/good.pdf && echo "identical"
# HTTP/1.1 200 OK / Content-Disposition: attachment; filename="resume-12.pdf" / identical

# NEGATIVE: tampered signature refused (only meaningful when the positive check gave 200)
BAD=$(echo "$URL" | sed -E 's/(X-Amz-Signature=.)/\1X/'); curl -s -o /dev/null -w "%{http_code}\n" "$BAD"     # 403

# If a presigned URL fails, read S3's error body
cat /tmp/downloaded.pdf; echo                  # after a failed download, this "PDF" is S3's XML error (e.g. SignatureDoesNotMatch)
curl -s "$URL" | head -c 400; echo             # or fetch the error directly (look at <Code> and <AWSAccessKeyId>)

# Who may get the link
for who in RIYA ACME DANA INITECH; do printf "%-8s " "$who"; curl -s -o /dev/null -w "%{http_code}\n" $API/applications/12/resume/ -H "Authorization: Bearer ${!who}"; done
# RIYA 200, ACME 200, DANA 403, INITECH 403

# Edge cases
curl -s $API/applications/3/resume/ -H "Authorization: Bearer $SAM"; echo                                   # 404 no resume
curl -s -o /dev/null -w "%{http_code}\n" $API/applications/99999/resume/ -H "Authorization: Bearer $SAM"     # 404
curl -s -o /dev/null -w "%{http_code}\n" $API/applications/12/resume/                                        # 401

# Credentials the API signs with (must be key=test secret_len=4)
docker compose exec api sh -c 'echo "key=$AWS_ACCESS_KEY_ID secret_len=${#AWS_SECRET_ACCESS_KEY}"'
# After changing .env: docker compose up -d --force-recreate api
```

### 2.4 Step 4: Search and filters

```bash
# Filters
echo "type:";      curl -s "$API/jobs/?job_type=contract" -H "Authorization: Bearer $DANA" | titles
echo "location:";  curl -s "$API/jobs/?location=VANCOUVER" -H "Authorization: Bearer $DANA" | titles
echo "skill 1:";   curl -s "$API/jobs/?skills=Terraform" -H "Authorization: Bearer $DANA" | titles
echo "skill any:"; curl -s "$API/jobs/?skills=terraform,python" -H "Authorization: Bearer $DANA" | titles
echo "combined:";  curl -s "$API/jobs/?location=vancouver&skills=python" -H "Authorization: Bearer $DANA" | titles
echo "docker:";    curl -s "$API/jobs/?skills=docker" -H "Authorization: Bearer $DANA" | titles
echo "blank:";     curl -s "$API/jobs/?skills=,," -H "Authorization: Bearer $DANA" | titles

# Search (title, description, company name)
echo "title:";   curl -s "$API/jobs/?search=platform" -H "Authorization: Bearer $DANA" | titles
echo "company:"; curl -s "$API/jobs/?search=initech" -H "Authorization: Bearer $DANA" | titles
echo "desc:";    curl -s "$API/jobs/?search=django" -H "Authorization: Bearer $DANA" | titles
echo "none:";    curl -s "$API/jobs/?search=cobol" -H "Authorization: Bearer $DANA" | titles

# Ordering (default newest first; invalid field silently ignored)
echo "default:"; curl -s "$API/jobs/" -H "Authorization: Bearer $DANA" | titles
echo "title:";   curl -s "$API/jobs/?ordering=title" -H "Authorization: Bearer $DANA" | titles
echo "invalid:"; curl -s "$API/jobs/?ordering=password" -H "Authorization: Bearer $DANA" | titles

# Invalid filter value → 400
curl -s -i "$API/jobs/?job_type=freelance" -H "Authorization: Bearer $DANA" | head -n 1
curl -s "$API/jobs/?job_type=freelance" -H "Authorization: Bearer $DANA"; echo

# ⚠ Skills normalised on save
JOB_ID=$(curl -s "$API/jobs/?search=django" -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print(json.load(sys.stdin)['results'][0]['id'])")
curl -s -X PATCH "$API/jobs/$JOB_ID/" -H "$J" -H "Authorization: Bearer $ACME" -d '{"required_skills": [" Python ", "DOCKER", "python"]}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['required_skills'])"            # ['python', 'docker']
curl -s -X PATCH "$API/jobs/$JOB_ID/" -H "$J" -H "Authorization: Bearer $ACME" -d '{"required_skills": ["python", ""]}'; echo   # 400 {"1": ["This field may not be blank."]}

# Unchanged: auth required, still paginated
curl -s -o /dev/null -w "%{http_code}\n" "$API/jobs/?location=vancouver"                     # 401
curl -s "$API/jobs/?location=vancouver" -H "Authorization: Bearer $DANA" | python3 -c "import sys, json; print(sorted(json.load(sys.stdin).keys()))"

# Where ordering is set (view's ordering overrides the model's Meta.ordering)
grep -n "ordering" jobs/views.py jobs/models.py
```

### 2.5 Phase 2 Done-when: 403s and match scores

**Status:** run on the laptop and reported as passing ("fine as expected"); the output wasn't recorded here.

```bash
echo "== Wrong user types get 403 =="
check "unverified company posts job"        403 -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $GLOBEX" -d '{"title":"x","description":"x","location":"x"}'
check "candidate posts job"                 403 -X POST $API/jobs/ -H "$J" -H "Authorization: Bearer $DANA"   -d '{"title":"x","description":"x","location":"x"}'
check "company applies"                     403 -X POST $API/applications/ -H "Authorization: Bearer $ACME" -F "job=3"
check "other company edits job 1"           403 -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $GLOBEX" -d '{"title":"x"}'
check "candidate lists job 1 applicants"    403 $API/jobs/1/applications/ -H "Authorization: Bearer $SAM"
check "other candidate reads app 3"         403 $API/applications/3/ -H "Authorization: Bearer $DANA"
check "applicant changes own status"        403 -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $SAM" -d '{"status":"offered"}'
check "other candidate gets resume link"    403 $API/applications/12/resume/ -H "Authorization: Bearer $DANA"
echo "== Right user types still allowed =="
check "verified company lists applicants"   200 $API/jobs/1/applications/ -H "Authorization: Bearer $ACME"
check "applicant reads own app"             200 $API/applications/3/ -H "Authorization: Bearer $SAM"
check "job owner gets resume link"          200 $API/applications/12/resume/ -H "Authorization: Bearer $ACME"

echo "== Match scores =="
curl -s $API/jobs/1/applications/ -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print('job 1:', [(a['candidate'], a['match_score']) for a in json.load(sys.stdin)['results']])"
curl -s $API/jobs/3/applications/ -H "Authorization: Bearer $INITECH" | python3 -c "import sys, json; print('job 3:', [(a['candidate'], a['match_score']) for a in json.load(sys.stdin)['results']])"
# job 1: [('riya', 0), ('sam', 67), ('dana', 67)]
# job 3: [('dana', 0), ('sam', 50), ('riya', 50)]
```

---

## 3. Phase 3 — Background Worker

### 3.1 Step 1: Redis cache for job search

**Part A — Redis and Django's cache**
```bash
# Redis answers (no published port: only containers can reach it)
docker compose exec redis redis-cli ping
# PONG

# Django's default cache is Redis, at the URL from REDIS_URL
docker compose exec api python manage.py shell -c "from django.core.cache import caches; c = caches['default']; print(type(c).__name__, c._servers)"
# RedisCache ['redis://redis:6379/0']      (the attribute is _servers, plural)

# Write, read, miss, default, atomic counter
docker compose exec api python manage.py shell -c "from django.core.cache import cache; cache.set('hello', 'world', 60); print(cache.get('hello'), cache.get('missing'), cache.get('missing', 'default')); cache.set('counter', 1); print(cache.incr('counter'), cache.incr('counter'))"
# world None default / 2 3

# What Django stored, seen from Redis (KEY_PREFIX:version:key)
docker compose exec redis redis-cli --scan --pattern 'jobboard:*'
docker compose exec redis redis-cli ttl jobboard:1:hello        # <= 60 (timeout passed)
docker compose exec redis redis-cli ttl jobboard:1:counter      # <= 300 (default TIMEOUT)
docker compose exec redis redis-cli get jobboard:1:hello        # pickled bytes: "\x80\x05...world..."

# Clean up the test keys (False = already expired)
docker compose exec api python manage.py shell -c "from django.core.cache import cache; print(cache.delete('hello'), cache.delete('counter'))"
```

Use `--scan`, never `KEYS *`, on a busy Redis: `KEYS` blocks the server while it reads every key.

**Part B — cached job list**

The helpers `titles`, `xcache` and `check` live at the bottom of `scripts/dev-helper.sh`:
```bash
titles() { python3 -c "import sys, json; d = json.load(sys.stdin); print(d['count'], [j['title'] for j in d['results']])" 2>/dev/null || echo "not JSON: run the same curl with -i"; }
xcache() { curl -s -o /dev/null -D - "$@" | grep -i '^x-cache' || echo "(no X-Cache header)"; }
check() { local got; got=$(curl -s -o /dev/null -w "%{http_code}" "${@:3}"); printf "%-45s expected %s got %s %s\n" "$1" "$2" "$got" "$([ "$got" = "$2" ] && echo OK || echo FAIL)"; }
```

```bash
docker compose restart api          # apps.py (signal registration) is read only at startup

# 1. Miss, then hit
xcache "$API/jobs/?location=vancouver" -H "Authorization: Bearer $DANA"        # X-Cache: MISS
xcache "$API/jobs/?location=vancouver" -H "Authorization: Bearer $DANA"        # X-Cache: HIT

# 2. A hit returns exactly what the database would
curl -s "$API/jobs/?search=django" -H "Authorization: Bearer $DANA" > /tmp/jobs-1.json
curl -s "$API/jobs/?search=django" -H "Authorization: Bearer $DANA" > /tmp/jobs-2.json
diff /tmp/jobs-1.json /tmp/jobs-2.json && echo "identical"

# 3. Parameter order shares a key; different values don't
xcache "$API/jobs/?location=vancouver&skills=python" -H "Authorization: Bearer $DANA"   # MISS
xcache "$API/jobs/?skills=python&location=vancouver" -H "Authorization: Bearer $DANA"   # HIT
xcache "$API/jobs/?skills=docker&location=vancouver" -H "Authorization: Bearer $DANA"   # MISS

# 4. ⚠ Saving a job invalidates (version +1, next list is a MISS with the new data)
docker compose exec api python manage.py shell -c "from django.core.cache import cache; print(cache.get('jobs:list:version'))"
xcache "$API/jobs/" -H "Authorization: Bearer $DANA"                                      # MISS
xcache "$API/jobs/" -H "Authorization: Bearer $DANA"                                      # HIT
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"title": "Junior DevOps Engineer (Cached?)"}'
docker compose exec api python manage.py shell -c "from django.core.cache import cache; print(cache.get('jobs:list:version'))"   # +1
curl -s -D /tmp/h.txt "$API/jobs/" -H "Authorization: Bearer $DANA" | titles; grep -i '^x-cache' /tmp/h.txt     # new title, MISS
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"title": "Junior DevOps Engineer"}'
curl -s -D /tmp/h.txt "$API/jobs/" -H "Authorization: Bearer $DANA" | titles; grep -i '^x-cache' /tmp/h.txt     # original title, MISS

# Invalidation called directly (creates the version key first, then expects N N+1)
docker compose exec api python manage.py shell -c "from django.core.cache import cache; from jobs.cache import invalidate_job_list, job_list_cache_key; from rest_framework.test import APIRequestFactory; from rest_framework.request import Request; job_list_cache_key(Request(APIRequestFactory().get('/api/jobs/'))); b = cache.get('jobs:list:version'); invalidate_job_list(); print(b, cache.get('jobs:list:version'))"

# 5. Auth and validation run before the cache; errors are never cached
xcache "$API/jobs/?location=vancouver"                                                    # (no X-Cache header)
curl -s -o /dev/null -w "%{http_code}\n" "$API/jobs/?location=vancouver"                  # 401
curl -s -o /dev/null -w "%{http_code}\n" "$API/jobs/?job_type=freelance" -H "Authorization: Bearer $DANA"   # 400
curl -s -o /dev/null -w "%{http_code}\n" "$API/jobs/?job_type=freelance" -H "Authorization: Bearer $DANA"   # 400

# 6. Keys and TTLs in Redis
docker compose exec redis redis-cli --scan --pattern 'jobboard:1:jobs:list:*'
docker compose exec redis redis-cli ttl "$(docker compose exec -T redis redis-cli --scan --pattern 'jobboard:1:jobs:list:v*' | head -n 1)"   # <= 60
docker compose exec redis redis-cli ttl jobboard:1:jobs:list:version                     # -1 (never expires)

# 7. Signals registered; rollback doesn't invalidate, commit does
docker compose exec -T api python manage.py shell <<'EOF'
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save
from jobs.models import Job

print("receivers:", post_save.has_listeners(Job))

before = cache.get("jobs:list:version")
try:
    with transaction.atomic():
        Job.objects.get(id=1).save()
        raise RuntimeError("force a rollback")
except RuntimeError:
    pass
after_rollback = cache.get("jobs:list:version")

Job.objects.get(id=1).save()
after_commit = cache.get("jobs:list:version")

print(before, after_rollback, after_commit, after_rollback == before, after_commit == before + 1)
EOF
# receivers: True / N N N+1 True True

# 8. Redis down: still 200, correct data, no X-Cache header, warning logged
docker compose stop redis
curl -s -D /tmp/h.txt -o /tmp/body.json -w "%{http_code}\n" "$API/jobs/?location=vancouver" -H "Authorization: Bearer $DANA"; grep -i '^x-cache' /tmp/h.txt || echo "(no X-Cache header)"; cat /tmp/body.json | titles
docker compose logs --tail=60 api | grep -i "cache unavailable"     # --tail must be long: the traceback follows the warning
docker compose start redis          # data survives stop/start (image volume /data); only a recreate empties it
```

Debugging invalidation:
```bash
sed -n '/def invalidate_job_list/,$p' jobs/cache.py                 # transaction.on_commit(bump) must be the last line, at function level
docker compose logs api | grep -i -A3 "could not invalidate" | tail -n 20
```

### 3.2 Step 2: Queue (SQS via LocalStack) + worker

**Part A — queues and `cloud/queue.py`**

⚠ Recreating LocalStack empties S3 (re-upload resumes afterwards, see the end of this block).

```bash
chmod +x localstack/init/ready.d/create-queues.sh
docker compose up -d --force-recreate localstack api
docker compose ps                                   # localstack (healthy) = bucket AND queue exist
docker compose logs localstack | tail -n 40         # if it stays "starting": init-script errors show here

# 1. Both queues exist; redrive policy points at the DLQ
docker compose exec localstack awslocal sqs list-queues 2>/dev/null | grep -v WARNING
docker compose exec localstack sh -c 'awslocal sqs get-queue-attributes --queue-url "$(awslocal sqs get-queue-url --queue-name $SQS_QUEUE_NAME --query QueueUrl --output text)" --attribute-names VisibilityTimeout RedrivePolicy' 2>/dev/null | grep -v WARNING
# "VisibilityTimeout": "30", RedrivePolicy with the -dlq ARN and "maxReceiveCount":"3"
```

```bash
# 2. Send, receive, delete through the Queue interface
docker compose exec -T api python manage.py shell <<'EOF'
from cloud.queue import get_queue, Queue

q = get_queue()
print(type(q).__name__, isinstance(q, Queue))
mid = q.send({"type": "test", "n": 1})
print("sent", mid)

msgs = q.receive(wait_seconds=5)
print("received", [(m.id == mid, m.body) for m in msgs])
for m in msgs:
    q.delete(m)

print("after delete", q.receive(wait_seconds=1))
EOF
# SQSQueue True / sent <uuid> / received [(True, {'type': 'test', 'n': 1})] / after delete []
```

```bash
# 3. Not deleted → hidden for 30 s → comes back (same id, new receipt handle)
docker compose exec -T api python manage.py shell <<'EOF'
import time
from cloud.queue import get_queue

q = get_queue()
q.send({"type": "test", "n": 2})

first = q.receive(wait_seconds=5)
print("1st receive:", [m.body for m in first])
print("right away:", [m.body for m in q.receive(wait_seconds=1)])

print("waiting 31 s for the visibility timeout...")
time.sleep(31)
again = q.receive(wait_seconds=5)
print("after timeout:", [m.body for m in again], "same id:", [m.id for m in again] == [m.id for m in first])
print("new receipt handle:", again[0].receipt_handle != first[0].receipt_handle)
for m in again:
    q.delete(m)
EOF
# 1st receive: [...] / right away: [] / after timeout: [...] same id: True / new receipt handle: True
```

```bash
# 4. ⚠ Re-upload riya's resume after a LocalStack recreate
docker compose exec -T api python manage.py shell <<'EOF'
from django.core.files.base import ContentFile
from jobs.models import Application
a = Application.objects.get(id=12)
a.resume.save("good.pdf", ContentFile(b"%PDF-1.4\nfake resume\n%%EOF\n"))
print(a.resume.name, a.resume.size)
EOF
```

**Part B — publish on status change + worker**

`qdepth` (add to `scripts/dev-helper.sh`): messages waiting / in flight on a queue.
```bash
qdepth() { docker compose exec -T localstack sh -c "awslocal sqs get-queue-attributes --queue-url \"\$(awslocal sqs get-queue-url --queue-name $1 --query QueueUrl --output text)\" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes" 2>/dev/null | grep -v WARNING | tr -d '\n '; echo; }
```

```bash
docker compose up -d --build worker
docker compose ps                         # worker Up
docker compose logs worker                # ... INFO worker Worker started
docker compose restart worker             # after ANY worker code change (no auto-reload)

# 1. ⚠ Status change is queued and processed (application 3 starts at "reviewing")
curl -s -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])"
sleep 3
docker compose logs --since 10s worker | grep "Application 3"     # Application 3: reviewing -> interview (event ...)
qdepth job-board-status                                           # 0 / 0
# Note: the API's "Queued ..." INFO line does NOT appear yet (no LOGGING config until Phase 4)
#   Fixed in Phase 4, Step 3: docker compose logs --no-log-prefix --since 30s api | grep '"jobs.events"' | python3 -m json.tool

# 2. Same status again → nothing queued (the worker count is the meaningful one)
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'
sleep 3; docker compose logs --since 8s worker | grep -c "Application 3"     # 0
```

```bash
# 3. Rolled-back change sends nothing
docker compose exec -T api python manage.py shell <<'EOF'
from django.db import transaction
from jobs.events import publish_status_changed
from jobs.models import Application

app = Application.objects.get(id=3)
print("status before:", app.status)
try:
    with transaction.atomic():
        app.status = "offered"
        app.save()
        publish_status_changed(app, "reviewing")
        raise RuntimeError("force a rollback")
except RuntimeError:
    pass
print("status in DB:", Application.objects.get(id=3).status)
EOF
sleep 3
docker compose logs --since 10s worker | grep -c "Application 3"     # 0
qdepth job-board-status                                             # 0 / 0
```

```bash
# 4. ⚠ Worker down: message waits; processed on start
docker compose stop worker
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}'
sleep 2; qdepth job-board-status                                    # "1" waiting
docker compose start worker
sleep 5; docker compose logs --since 10s worker; qdepth job-board-status    # processed; 0 / 0

# 5. Graceful shutdown (SIGTERM = signal 15; must finish inside stop_grace_period 30s)
time docker compose stop worker
docker compose logs --tail=3 worker       # Received signal 15, finishing current batch / Worker stopped
docker compose start worker

# 6. Poison message → 3 retries → DLQ (~2 minutes; Ctrl+C cancels only the sleep)
docker compose exec -T api python manage.py shell -c "from cloud.queue import get_queue; print(get_queue().send({'type': 'bogus'}))"
sleep 100
docker compose logs --since 15m worker | grep -c "Failed to handle message"            # 3
docker compose logs --since 15m worker | grep "Unknown message type" | head -n 3
qdepth job-board-status                    # 0 / 0
qdepth job-board-status-dlq                # "1" (wait 30 s more if still 0)
docker compose ps worker                   # still Up

# 7. Inspect, then purge, the DLQ
docker compose exec localstack sh -c 'awslocal sqs receive-message --queue-url "$(awslocal sqs get-queue-url --queue-name ${SQS_QUEUE_NAME}-dlq --query QueueUrl --output text)" --query "Messages[].Body"' 2>/dev/null | grep -v WARNING
docker compose exec localstack sh -c 'awslocal sqs purge-queue --queue-url "$(awslocal sqs get-queue-url --queue-name ${SQS_QUEUE_NAME}-dlq --query QueueUrl --output text)"' 2>/dev/null | grep -v WARNING
sleep 2; qdepth job-board-status-dlq       # 0 / 0
```

---

### 3.3 Step 3: Status emails (console backend)

```bash
docker compose restart worker             # worker code changed (no auto-reload)
docker compose logs --tail=3 worker       # Worker started

# 1. ⚠ Status change → full email in the worker log
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'
sleep 3
docker compose logs --since 10s worker                 # Subject / From / To / "Hi sam" / "New status: Interview"
qdepth job-board-status                                # 0 / 0
docker compose logs --since 30m worker | grep "Emailed user"     # Emailed user 5 about application 3 ... (user id, no email address)

# 2. ⚠ Plain text isn't HTML-escaped (& and <> stay as typed); title restored at the end
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"title": "Junior DevOps & SRE <Engineer>"}'
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}'
sleep 3
docker compose logs --since 10s worker | grep -E "Subject:|application for"
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/jobs/1/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"title": "Junior DevOps Engineer"}'
```

```bash
# 3. In-memory (locmem) backend + header-injection cleanup (no queue, no worker; nothing saved)
docker compose exec -T api python manage.py shell <<'EOF'
from django.core import mail
from django.test.utils import override_settings
from jobs.emails import send_status_changed_email
from jobs.models import Application

app = Application.objects.select_related("job__company", "candidate__user").get(id=3)
app.job.title = "Line one\nBcc: attacker@evil.test"

with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
    send_status_changed_email(app, "offered")

m = mail.outbox[-1]
print("subject:", repr(m.subject))
print("to:", m.to, "| from:", m.from_email, "| bcc:", m.bcc)
print("one line:", "\n" not in m.subject)
EOF
# subject: '... Line one Bcc: attacker@evil.test: Offered' / bcc: [] / one line: True
```

```bash
# 4. Missing application → warning, message deleted (not retried, not in DLQ)
docker compose exec -T api python manage.py shell -c "from cloud.queue import get_queue; print(get_queue().send({'type': 'application.status_changed', 'event_id': 'test-missing', 'application_id': 99999, 'old_status': 'submitted', 'new_status': 'reviewing'}))"
sleep 3
docker compose logs --since 10s worker | grep "no longer exists"
qdepth job-board-status                   # 0 / 0
qdepth job-board-status-dlq               # 0 / 0

# 5. Nothing else broke
docker compose ps worker                                                # Up
docker compose logs --since 2m worker | grep -c "Failed to handle message"    # 0
```

### 3.4 Step 4: Idempotent processing

```bash
docker compose restart worker
docker compose logs --tail=3 worker       # Worker stopped / Found credentials... / Worker started
#   since Phase 4, Step 3: JSON lines, and no "Found credentials" (botocore logs at WARNING only)

# 1. ⚠ Unique constraint in Postgres; one change → one email, one ProcessedEvent row
docker compose exec db psql -U jobboard -d jobboard -c '\d jobs_processedevent' | grep -E "event_id|unique|UNIQUE"
# "jobs_processedevent_event_id_key" UNIQUE CONSTRAINT, btree (event_id)   (+ a _like index Django adds on Postgres)
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'
sleep 3
docker compose logs --since 10s worker | grep -E "Subject:|Emailed user"
docker compose exec api python manage.py shell -c "from jobs.models import ProcessedEvent; e = ProcessedEvent.objects.latest('processed_at'); print(e.event_type, e.event_id, ProcessedEvent.objects.count())"
```

```bash
# 2. Same event_id sent twice (two messages) → one email, one "already processed"
docker compose exec -T api python manage.py shell <<'EOF'
import uuid
from cloud.queue import get_queue

body = {
    "type": "application.status_changed",
    "event_id": f"dup-test-{uuid.uuid4().hex[:8]}",
    "application_id": 3,
    "old_status": "interview",
    "new_status": "interview",
}
q = get_queue()
q.send(body)
q.send(body)
print("sent twice:", body["event_id"])
EOF
sleep 5
docker compose logs --since 10s worker | grep -E "Subject:|Emailed user|already processed"
qdepth job-board-status                   # 0 / 0
```

```bash
# 3. ⚠ Crash after sending, before deleting (~40 s): the redelivery is skipped
docker compose stop worker
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}'
sleep 2

docker compose exec -T api python manage.py shell <<'EOF' | grep -E "Subject:|crash"
from cloud.queue import get_queue
from worker.run_worker import handle

q = get_queue()
messages = q.receive(wait_seconds=5)
for m in messages:
    handle(m)
print("crash: handled", len(messages), "message(s) but did NOT delete")
EOF

docker compose start worker
echo "waiting 35 s for the visibility timeout..."
sleep 35
docker compose logs --since 40s worker | grep -E "Subject:|Emailed user|already processed"   # ONLY "already processed"
qdepth job-board-status                   # 0 / 0
```

```bash
# 4. Failed send → claim rolled back (mock.patch where the name is USED: worker.run_worker)
docker compose exec -T api python manage.py shell <<'EOF'
import uuid
from unittest import mock
from jobs.models import ProcessedEvent
from worker import run_worker

event_id = f"fail-test-{uuid.uuid4().hex[:8]}"
body = {"type": "application.status_changed", "event_id": event_id,
        "application_id": 3, "old_status": "reviewing", "new_status": "reviewing"}

with mock.patch.object(run_worker, "send_status_changed_email", side_effect=RuntimeError("mail server down")):
    try:
        run_worker.handle_status_changed(body)
    except RuntimeError as e:
        print("1st attempt failed:", e)
print("claimed after failure:", ProcessedEvent.objects.filter(event_id=event_id).exists())

run_worker.handle_status_changed(body)
print("claimed after retry:", ProcessedEvent.objects.filter(event_id=event_id).exists())
EOF
# 1st attempt failed: mail server down / claimed after failure: False / (email printed) / claimed after retry: True
# Tip: the printed email can push the first two lines off screen; drop the last 2 lines of the heredoc to see them alone.
```

```bash
# 5. Nothing else broke
docker compose ps worker                                                     # Up
docker compose logs --since 5m worker | grep -c "Failed to handle message"   # 0
qdepth job-board-status-dlq                                                  # 0 / 0

# Look at the dedup table
docker compose exec api python manage.py shell -c "from jobs.models import ProcessedEvent; [print(e.processed_at, e) for e in ProcessedEvent.objects.order_by('-processed_at')[:10]]"
```

---

## 4. Phase 4 — Operations-Ready

### 4.1 Step 1: `/healthz` and `/readyz`

No token needed: these are plain Django views outside `/api/`. Define `r` first (section 0.1), or `source scripts/dev-helper.sh` after adding it (section 7).

**How dependencies are broken:** `docker compose stop` = unreachable (refused, fast). `docker compose pause` = frozen (accepts connections, never answers): only timeouts help, and that is what exposed the hangs.

⚠ Stopping LocalStack empties S3: re-upload riya's resume at the end (check D).

```bash
# 0. Routes exist, without a trailing slash (a slash = 301 from APPEND_SLASH, which probes count as success)
grep -n "healthz\|readyz" config/urls.py
curl -s -i http://localhost:8006/healthz | grep -i "^HTTP\|^location"     # HTTP/1.1 200 OK, no Location line

# 1. Liveness: 200, JSON, never cached
curl -s -i http://localhost:8006/healthz | grep -iE "^HTTP|^content-type|^cache-control|^\{"
# HTTP/1.1 200 OK / Content-Type: application/json / Cache-Control: max-age=0, no-cache, no-store, must-revalidate, private / {"status": "ok"}

# 2. Readiness, all up: 200, "ready", database + cache + queue all "ok" with ms
r
# HTTP 200 in 0.0xs / curl exit=0 / "status": "ready" / database ~6-13 ms, cache ~2-4 ms, queue ~3-44 ms (first call slower)

# 3. Writes refused: 403 (CSRF middleware runs BEFORE @require_GET could answer 405)
curl -s -o /dev/null -w "POST healthz %{http_code}\n" -X POST http://localhost:8006/healthz     # 403
curl -s -o /dev/null -w "POST readyz  %{http_code}\n" -X POST http://localhost:8006/readyz      # 403

# 4. Redis STOPPED: non-critical, so still 200 "ready", cache reported as failed
docker compose stop redis
r                                  # HTTP 200 / "ready" / cache: "fail", "error": "ConnectionError", "critical": false
docker compose start redis
r                                  # all ok again

# 5. Postgres stopped: alive (don't restart) but not ready (no traffic)
docker compose stop db
curl -s -o /dev/null -w "healthz %{http_code}\n" http://localhost:8006/healthz     # healthz 200
r                                  # HTTP 503 / "not_ready" / database: "fail", "error": "OperationalError", "critical": true
docker compose start db
sleep 3; r                         # HTTP 200 / "ready"  (Django reconnects on the next request)

# 6. LocalStack PAUSED, fresh API process (empty lru_cache): each check bounded to ~1 s
docker compose restart api; sleep 5
docker compose pause localstack
r; r                               # HTTP 200 in ~1.0 s (twice) / queue: "fail", "error": "ReadTimeoutError", ms ~1000-1050
docker compose unpause localstack
# Before the fixes: curl exit=124 after 90 s (no timeouts); then ~2.3-3.0 s (max_attempts:1 = 1 retry). Now ~1.02-1.06 s.

# 6b. Prove the ping client makes exactly ONE attempt (manage.py shell loads settings; plain python -c does not)
docker compose exec api python manage.py shell -c "from cloud.queue import get_queue; print(get_queue()._ping_client.meta.config.retries)"
# {'mode': 'standard', 'total_max_attempts': 1}

# 7. Redis PAUSED: the timeouts protect the API too, not only the probe
docker compose pause redis
r                                                                                    # HTTP 200 in ~1.03 s / cache: "TimeoutError", ~1010 ms
curl -s -o /dev/null -w "jobs %{http_code} in %{time_total}s\n" $API/jobs/ -H "Authorization: Bearer $SAM"   # jobs 200 in ~1.03 s (falls back to Postgres)
docker compose unpause redis

# 8. All up again; long polling still works with the new main-client timeouts (read 30 s > 20 s poll)
r                                                                                    # 200, all ok
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'   # ⚠ 200
sleep 3; docker compose logs --since 30s worker | grep "Emailed"                     # Emailed user 5 ... reviewing -> interview
docker compose logs --since 10m worker | grep -ci "timeout"                          # 0

# 9. The failing check's traceback is in the API log (response shows only the exception class name)
docker compose logs --since 15m api | grep -c "Readiness check"                      # >= 1
```

**Worker resilience**

```bash
# Apply the restart policy: it is fixed when a container is CREATED. `docker compose restart` keeps the old one.
grep -n -B1 -A1 "restart:" docker-compose.yml      # restart: unless-stopped under api and worker
docker compose up -d                               # recreates api and worker (config changed)
docker compose ps -a api worker                    # both Up, "Created" just now
docker inspect -f '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}' $(docker compose ps -aq api worker)
# /00-job-board-api-api-1 restart=unless-stopped
# /00-job-board-api-worker-1 restart=unless-stopped

# B. Worker survives a queue outage (catches BotoCoreError/ClientError around receive, sleeps 5 s)
docker compose stop localstack
sleep 15
docker compose ps -a worker                                                     # still Up (before the fix: Exited (1))
docker compose logs --since 30s worker | grep -c "Could not receive messages"   # 2 or more
docker compose start localstack
sleep 20; docker compose ps -a worker                                           # still Up

# C. Worker STARTED during an outage: fails fast on queue.url, Docker restarts it until SQS is back
docker compose stop localstack
docker compose restart worker
sleep 10; docker compose ps -a worker                                           # Restarting (1) ... or Exited
docker compose logs --tail=40 worker                                            # traceback from queue.url at startup
docker compose start localstack
sleep 30; docker compose ps -a worker                                           # Up NN seconds
docker compose logs --since 1m worker | grep "Worker started"                   # Worker started, queue http://.../job-board-status
qdepth job-board-status                                                         # 0 / 0 (anything queued during the outage was processed)

# D. ⚠ Re-upload riya's resume (stopping LocalStack emptied S3), then everything is ok
docker compose exec -T api python manage.py shell <<'EOF'
from django.core.files.base import ContentFile
from jobs.models import Application
a = Application.objects.get(id=12)
a.resume.save("good.pdf", ContentFile(b"%PDF-1.4\nfake resume\n%%EOF\n"))
print(a.resume.name, a.resume.size)
EOF
# resume/job-1/<uuid>.pdf 27
r                                                                               # 200, all ok
```

### 4.2 Step 2: `/metrics` via django-prometheus

A labelled series doesn't exist until its first event: an empty `m` before traffic means "0 so far". Histogram buckets are cumulative (`le="0.025"` counts everything ≤ 25 ms).

```bash
# 0. Rebuild for the new dependency, then WAIT for the app (checks run too early get 000 / curl exit=56)
docker compose up -d --build
waitapi                                                                      # api up after Ns
docker compose exec api python manage.py makemigrations --check --dry-run    # No changes detected

# 1. Endpoint: 200, Prometheus text format, no token
curl -s -i http://localhost:8006/metrics | grep -i "^HTTP\|^content-type"
# HTTP/1.1 200 OK / Content-Type: text/plain; version=1.0.0; charset=utf-8
curl -s http://localhost:8006/metrics | grep -c "^django_"                   # 182 (a large number)

# 2. Request counter: before / 5 requests / after
source scripts/dev-helper.sh; login_all
m 'django_http_responses_total_by_status_view_method_total{.*view="job-list"'      # nothing yet after a restart (= 0)
for i in 1 2 3 4 5; do curl -s -o /dev/null $API/jobs/ -H "Authorization: Bearer $SAM"; done
m 'django_http_responses_total_by_status_view_method_total{.*view="job-list"'
# ...{method="GET",status="200",view="job-list"} 5.0   (+5 compared with before)

# 3. Errors labelled by status
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/99999/ -H "Authorization: Bearer $SAM"   # 404
m 'django_http_responses_total_by_status_view_method_total{.*status="404"'
# ...{method="GET",status="404",view="job-detail"} 1.0

# 4. Latency histogram (cumulative buckets)
m 'django_http_requests_latency_seconds_by_view_method_.*view="job-list"' | head -n 5
# le="0.01" 1.0 / le="0.025" 5.0 / ... (1 request <= 10 ms, all 5 <= 25 ms)

# 5. Database wrapper
m '^django_db_execute_total'            # django_db_execute_total{alias="default",vendor="postgresql"} 30.0
m '^django_db_errors_total'             # nothing = no DB errors since start

# 6. Nothing else broke. ⚠ PATCH a REAL change: check the current status first (same status = no event, no email)
r                                                                            # 200, ready
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.get(id=3).status)"
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'   # ⚠ 200 (use a status different from the one printed)
sleep 3; docker compose logs --since 30s worker | grep "Emailed"            # Emailed user 5 about application 3: reviewing -> interview

# 7. Every PATCH that reached Django is counted
m 'django_http_responses_total_by_status_view_method_total{.*method="PATCH"'
# ...{method="PATCH",status="200",view="application-set-status"} 2.0
```

**"No Emailed line" checklist** (used in this step; the cause was a no-op PATCH):
```bash
docker compose ps -a worker                                                  # Up?
docker compose logs --since 3m worker | tail -n 25                           # Worker started ... Emailed / traceback?
qdepth job-board-status                                                      # stuck message?
qdepth job-board-status-dlq
docker compose logs --since 3m api | grep -i -B2 -A8 "traceback\|could not\|error" | tail -n 30   # publish failed?
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.get(id=3).status)"
```

### 4.3 Step 3: Structured JSON logs

Order matters: `source` the helper file **before** `waitapi`, or nothing waits. Only lines that pass `json.loads` count as JSON. The console email backend's output is plain text by design (development only).

```bash
source scripts/dev-helper.sh
type waitapi m | grep "is a function" || echo "waitapi/m missing: add them (section 7, Phase 4 Step 2)"
waitapi
login_all

# 1. Every api log line is JSON (prints any line that isn't)
curl -s -o /dev/null $API/jobs/ -H "Authorization: Bearer $SAM"
docker compose logs --no-log-prefix --since 30s api | python3 -c "
import sys, json
ok, other = 0, []
for line in sys.stdin:
    if not line.strip(): continue
    try: json.loads(line); ok += 1
    except ValueError: other.append(line.rstrip())
print(ok, 'JSON lines,', len(other), 'other')
for l in other: print('OTHER:', l)"
# 7 JSON lines, 0 other

# 2. A request line: JSON, status_code kept, no "request" socket field
docker compose logs --no-log-prefix --since 30s api | grep '"django.server"' | tail -n 1 | python3 -m json.tool
# level, logger "django.server", message "\"GET /api/jobs/ HTTP/1.1\" 200 1170", server_time, status_code 200, timestamp

# 3. ⚠ A REAL status change (check the current status first), then both sides' structured lines
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.get(id=3).status)"
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'   # 200 (use a status different from the one printed)
sleep 3
docker compose logs --no-log-prefix --since 30s api | grep '"jobs.events"' | python3 -m json.tool
# "Queued application.status_changed for application 3 (message ...)", event, event_id, application_id 3, message_id
docker compose logs --no-log-prefix --since 30s worker | grep "Emailed" | python3 -m json.tool
# event, event_id (same as the API's), application_id 3, user_id 5, old_status, new_status

# 4. Correlation by FIELD: event_id from the API line → the matching worker line
EID=$(docker compose logs --no-log-prefix --since 30s api | grep '"jobs.events"' | tail -n 1 | python3 -c "import sys, json; print(json.load(sys.stdin)['event_id'])"); echo "event_id=$EID"
docker compose logs --no-log-prefix --since 30s worker | python3 -c "
import sys, json
for line in sys.stdin:
    try: r = json.loads(line)
    except ValueError: continue
    if r.get('event_id') == '$EID': print(r['logger'], r['level'], r['old_status'], '->', r['new_status'])"
# worker INFO reviewing -> interview

# 5. A traceback is ONE event (exc_info field)
docker compose stop redis; r > /dev/null; docker compose start redis
docker compose logs --no-log-prefix --since 30s api | grep '"cloud.health"' | tail -n 1 | python3 -m json.tool
# "level": "WARNING", "message": "Readiness check cache failed", "exc_info": "Traceback ...\n...ConnectionError: Error -3 connecting to redis:6379. Temporary failure in name resolution."

# 6. The level comes from the environment
docker compose exec api python manage.py shell -c "import logging; print(logging.getLevelName(logging.getLogger().level))"                    # INFO
docker compose exec -e LOG_LEVEL=warning api python manage.py shell -c "import logging; print(logging.getLevelName(logging.getLogger().level))"   # WARNING

# 7. Worker uses the same config
grep -n "basicConfig" worker/run_worker.py || echo "basicConfig removed"
docker compose logs --no-log-prefix worker | grep "Worker started" | tail -n 1      # {"level": "INFO", "logger": "worker", ...}

# 8. Worker + api: count JSON vs other, then SHOW the other lines (expected: only the console email)
docker compose logs --no-log-prefix --since 30s worker api | python3 -c "
import sys, json
ok = bad = 0
for line in sys.stdin:
    if not line.strip(): continue
    try: json.loads(line); ok += 1
    except ValueError: bad += 1
print(ok, 'JSON,', bad, 'other')"
# 8 JSON, 14 other   (14 = one console email: headers + body)
docker compose logs --no-log-prefix --since 15m worker api | python3 -c "
import sys, json
for line in sys.stdin:
    if not line.strip(): continue
    try: json.loads(line)
    except ValueError: print('OTHER:', line.rstrip())" | head -n 40

# 9. Graceful shutdown timing in the JSON log (restart waits for the current 20 s long poll)
docker compose restart worker
docker compose logs --since 2m worker | grep -E "Received signal|Worker stopped|Worker started"
# Received signal 15 ... (+~19 s) Worker stopped ... Worker started
```

### 4.4 Step 4: All config from environment variables

Never `cat .env` (real secrets). Every check prints names, counts or lengths. `-e VAR=` on one `exec`/`run` breaks one setting without editing files.

**Part A — audit (read-only)**
```bash
cat config/settings.py
cat .env.example
cut -d= -f1 .env | grep -v "^#" | grep -v "^$" | sort                  # names only
grep -v "^#" .env.example | cut -d= -f1 | grep -v "^$" | sort
grep -n -A15 "^  api:\|^  worker:" docker-compose.yml | grep -n "env_file\|environment\|- [A-Z_]*=\|[A-Z_]*:" | head -n 40
grep -rn "os.environ\|os.getenv\|getenv(" --include=*.py . | grep -v "/.venv/"
grep -rnE "localhost|127\.0\.0\.1|:4566|:6379|:5432|amazonaws\.com|us-east-1" --include=*.py . | grep -v "/.venv/"
git ls-files | grep -i "env"          # only .env.example (and later .env.localstack.example)
cat .dockerignore                     # .env and .env.* listed
sed -n '/^  localstack:/,/^  [a-z]/p' docker-compose.yml
grep -n "SQS_QUEUE_NAME\|AWS_STORAGE_BUCKET_NAME\|\$" localstack/init/ready.d/*.sh
```

**Part B — Compose stack**
```bash
docker compose up -d --force-recreate            # env files are read at container creation
source scripts/dev-helper.sh; waitapi; login_all
type r waitapi m | grep -c "is a function"       # 3

# 1. Settings as the app sees them
docker compose exec api python manage.py shell -c "from django.conf import settings as s; print(s.DEBUG, s.ALLOWED_HOSTS, s.AWS_REGION, s.AWS_S3_REGION_NAME, s.DATABASES['default']['HOST'])"
# True ['localhost', '127.0.0.1', '0.0.0.0', '10.0.0.149'] us-east-1 us-east-1 db
grep -c "AWS_S3_REGION=\|POSTGRES_HOST=db" docker-compose.yml     # 0

# 2. Host header protection (positive twin first)
curl -s -o /dev/null -w "Host localhost    %{http_code}\n" http://localhost:8006/healthz                           # 200
curl -s -o /dev/null -w "Host evil.example %{http_code}\n" -H "Host: evil.example" http://localhost:8006/healthz  # 400
# From the MacBook:
#   curl -s -o /dev/null -w "%{http_code}\n" http://10.0.0.149:8006/healthz                               # 200
#   curl -s -o /dev/null -w "%{http_code}\n" -H "Host: evil.example" http://10.0.0.149:8006/healthz       # 400

# 3. Fail fast: empty counts as missing
docker compose exec -e DJANGO_SECRET_KEY= api python manage.py check 2>&1 | tail -n 1     # Missing required environment variable: DJANGO_SECRET_KEY
docker compose exec -e AWS_REGION= api python manage.py check 2>&1 | tail -n 1            # ... AWS_REGION

# 4. Booleans
for v in False false 0 no True yes 1; do printf "%-6s " "$v"; docker compose exec -e DJANGO_DEBUG=$v api python manage.py shell -c "from django.conf import settings; print(settings.DEBUG)" 2>/dev/null | tail -n 1; done
# False False False False True True True

# 5. Secret key (counts and length only)
grep -c "^DJANGO_SECRET_KEY=change-me$" .env                       # 0
grep -c "django-insecure-6nxn" .env                                # 0
grep -c '^DJANGO_SECRET_KEY=[A-Za-z0-9_-]\{60,\}$' .env           # 1 (after rotation with token_urlsafe)
grep -c "django-insecure" config/settings.py                       # 0
head -n 1 config/settings.py                                       # import os

# 6. Key rotation took effect (run BEFORE login_all after a recreate with a new key)
curl -s -o /dev/null -w "old token %{http_code}\n" $API/jobs/ -H "Authorization: Bearer $SAM"   # 401
login_all
curl -s -o /dev/null -w "new token %{http_code}\n" $API/jobs/ -H "Authorization: Bearer $SAM"   # 200

# 7. LocalStack token only in localstack
docker compose exec api    printenv LOCALSTACK_AUTH_TOKEN > /dev/null && echo "api: SET (bad)"    || echo "api: not set"
docker compose exec worker printenv LOCALSTACK_AUTH_TOKEN > /dev/null && echo "worker: SET (bad)" || echo "worker: not set"
docker compose exec localstack sh -c 'echo "localstack: ${LOCALSTACK_AUTH_TOKEN:+set}"'            # localstack: set
docker compose ps localstack                                                                        # (healthy)
grep -c "^LOCALSTACK_AUTH_TOKEN=" .env .env.localstack                                             # .env:0  .env.localstack:1
git check-ignore -q .env.localstack && echo ".env.localstack: ignored"
git check-ignore -q .env.localstack.example || echo ".env.localstack.example: trackable"

# 8. ⚠ Re-upload riya's resume (recreating LocalStack empties S3), then everything still works
docker compose exec -T api python manage.py shell <<'EOF'
from django.core.files.base import ContentFile
from jobs.models import Application
a = Application.objects.get(id=12)
a.resume.save("good.pdf", ContentFile(b"%PDF-1.4\nfake resume\n%%EOF\n"))
print(a.resume.name, a.resume.size)
EOF
URL=$(curl -s $API/applications/12/resume/ -H "Authorization: Bearer $RIYA" | python3 -c "import sys, json; print(json.load(sys.stdin)['url'])")
curl -s -o /dev/null -w "resume download %{http_code}\n" "$URL"                                   # 200
r | head -n 3                                                                                       # HTTP 200 / curl exit=0
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.get(id=3).status)"
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "interview"}'   # ⚠ 200 (a DIFFERENT status)
sleep 3; docker compose logs --no-log-prefix --since 30s worker | grep "Emailed" | python3 -m json.tool | grep -E "old_status|new_status"
```

**Part C — the image alone: no mount, env vars only**
```bash
docker compose build api worker                  # the bind mount hides a stale image: rebuild first
IMG=00-job-board-api-api
NET=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' $(docker compose ps -q api)); echo "network=$NET"   # 00-job-board-api_default

grep -c '="' .env                                                     # 0 (docker run --env-file keeps quotes)
docker run --rm $IMG grep -c "def env_list" config/settings.py        # 1 = the IMAGE has this step's code
docker run --rm $IMG grep -c "django-insecure" config/settings.py     # 0
docker run --rm $IMG sh -c 'ls -a /app | grep -i env'                 # .env.example only

docker run --rm $IMG python manage.py check 2>&1 | tail -n 1                                  # Missing ... DJANGO_SECRET_KEY
docker run --rm --env-file .env -e AWS_REGION= $IMG python manage.py check 2>&1 | tail -n 1   # Missing ... AWS_REGION

docker run -d --name jb-envonly --network $NET --env-file .env -p 127.0.0.1:8016:8006 $IMG
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8016/healthz && { echo "up after ${i}s"; break; }; sleep 1; done
docker inspect -f '{{len .Mounts}} mounts' jb-envonly                                          # 0 mounts
curl -s http://localhost:8016/readyz | python3 -m json.tool | grep -E '"status"'                # ready + 3 × ok
curl -s -o /dev/null -w "metrics %{http_code}\n" http://localhost:8016/metrics                  # 200
curl -s -o /dev/null -w "jobs %{http_code}\n" http://localhost:8016/api/jobs/ -H "Authorization: Bearer $SAM"   # 200
curl -s -o /dev/null -w "evil host %{http_code}\n" -H "Host: evil.example" http://localhost:8016/healthz        # 400
docker exec jb-envonly printenv LOCALSTACK_AUTH_TOKEN > /dev/null && echo "token: SET (bad)" || echo "token: not set"
docker logs jb-envonly 2>&1 | grep '^{' | tail -n 1                                             # JSON, no "request" field
docker logs jb-envonly | tail -n 30                                                             # only if it didn't come up
docker rm -f jb-envonly

docker compose up -d; waitapi                    # the stack on the rebuilt image
```

### 4.5 Step 5: Multi-stage Dockerfile, non-root user, gunicorn

The image's default command is gunicorn (production); Compose overrides `api` with `runserver` for development.

```bash
# 0. Keep the old image to compare sizes, then build
docker tag 00-job-board-api-api jobboard:before-step5
docker compose up -d --build
source scripts/dev-helper.sh; waitapi; login_all
docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -E "jobboard:before-step5|00-job-board-api-api:latest"
# 00-job-board-api-api:latest 343MB / jobboard:before-step5 394MB

IMG=00-job-board-api-api
NET=00-job-board-api_default

# 1. What's inside the runtime image
docker run --rm $IMG id                                                     # uid=1000(app) gid=1000(app) groups=1000(app)
docker run --rm $IMG sh -c 'command -v uv || echo "no uv"'                  # no uv
docker run --rm $IMG sh -c 'touch /app/x 2>&1 | tail -n 1'                  # touch: cannot touch '/app/x': Permission denied
docker run --rm $IMG gunicorn --version                                     # gunicorn (version 26.2.0)
docker run --rm $IMG sh -c 'ls -a /app | grep -i env'                       # .env.example

# 2. Done-when: production image, env vars only, DEBUG off
docker run -d --name jb-prod --network $NET --env-file .env -e DJANGO_DEBUG=False -p 127.0.0.1:8016:8006 $IMG
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8016/healthz && { echo "up after ${i}s"; break; }; sleep 1; done   # up after 2s
docker logs jb-prod 2>&1 | tail -n 30                                       # only if it didn't come up
docker inspect -f '{{len .Mounts}} mounts, user={{.Config.User}}' jb-prod  # 0 mounts, user=app
docker top jb-prod -o pid,user,args                                         # 2 × gunicorn (master + 1 worker); USER shows "reza" = host name for uid 1000
curl -s http://localhost:8016/healthz; echo                                 # {"status": "ok"}
curl -s http://localhost:8016/readyz | python3 -m json.tool | grep '"status"'   # ready + 3 × ok
curl -s -o /dev/null -w "metrics %{http_code}\n" http://localhost:8016/metrics  # 200
curl -s -o /dev/null -w "jobs %{http_code}\n" http://localhost:8016/api/jobs/ -H "Authorization: Bearer $SAM"   # 200
curl -s -o /dev/null -w "evil host %{http_code}, %{size_download} bytes\n" -H "Host: evil.example" http://localhost:8016/healthz   # 400, 143 bytes

# 3. One process = consistent counters
for i in $(seq 10); do curl -s -o /dev/null http://localhost:8016/api/jobs/ -H "Authorization: Bearer $SAM"; done
for s in 1 2; do curl -s http://localhost:8016/metrics | grep 'responses_total_by_status_view_method_total{method="GET",status="200",view="job-list"}'; done
# ... 11.0 / ... 11.0

# 4. Every log line is JSON, gunicorn's included
docker logs jb-prod 2>&1 | python3 -c "
import sys, json
ok, other = 0, []
for line in sys.stdin:
    if not line.strip(): continue
    try: json.loads(line); ok += 1
    except ValueError: other.append(line.rstrip())
print(ok, 'JSON,', len(other), 'other')
for l in other[:10]: print('OTHER:', l)"
# 24 JSON, 0 other
docker logs jb-prod 2>&1 | grep '"gunicorn' | head -n 3
# Starting gunicorn 26.2.0 / Listening at: http://0.0.0.0:8006 (1) / Using worker: gthread

# 5. Graceful stop (gunicorn is PID 1 and gets SIGTERM)
time docker stop jb-prod                                                    # real 0m0.502s
docker logs jb-prod 2>&1 | grep -i "term\|shutting\|exiting" | tail -n 3
# Handling signal: term / Worker exiting (pid: 7) / Shutting down: Master
docker rm jb-prod

# 6. Dev stack on the new image (runserver via command:)
docker compose ps api worker                                                # "python manage.py ru…" Up / worker Up
docker compose exec api id                                                  # uid=1000(app)
r | head -n 3                                                               # HTTP 200
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.get(id=3).status)"
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH $API/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d '{"status": "reviewing"}'   # ⚠ 200 (a DIFFERENT status)
sleep 3; docker compose logs --no-log-prefix --since 30s worker | grep "Emailed" | python3 -m json.tool | grep -E "old_status|new_status"
```

### 4.6 Phase 4 Done-when: the container runs with only env vars and exposes health and metrics

Evidence: section 4.5, check 2 (`jb-prod`: production image, gunicorn, `0 mounts`, `--env-file` only, `DEBUG=False` → healthz `ok`, readyz `ready`, metrics `200`). Also section 4.4, Part C (the same with the pre-gunicorn image).

## 5. Phase 5 — Tests + Docs

Tests run in the `test` container (runtime + dev dependencies) on the Compose network, with the code bind-mounted. pytest-django creates a separate `test_jobboard` database and drops it at the end; the dev database is never touched.

### 5.1 Step 1, Part A: test tooling (pytest, pytest-django, pytest-cov)

```bash
grep -n -A5 "dependency-groups" pyproject.toml           # dev = pytest, pytest-cov, pytest-django
docker compose config --quiet && echo "compose file OK"

# 1. The one command (Phase 5 Done-when)
docker compose build test
docker compose run --rm test
# 2 passed in 0.77s; coverage table; TOTAL 677 stmts, 284 miss, 58%
# (if Compose complains about the profile: docker compose --profile test run --rm test)

# 2. One test, verbose, no coverage
docker compose run --rm test pytest jobs/tests/test_smoke.py::test_healthz -v --no-cov   # PASSED

# 3. Dev data untouched; test database dropped
docker compose exec api python manage.py shell -c "from jobs.models import User; print(User.objects.count())"   # 7
docker compose exec db psql -U jobboard -lqt | cut -d'|' -f1 | grep -c test_                                    # 0

# 4. The production image has no test tools and is unchanged
docker compose build api worker
docker run --rm 00-job-board-api-api sh -c 'command -v pytest || echo "no pytest"'        # no pytest
docker image ls --format '{{.Repository}} {{.Size}}' | grep -E "^00-job-board-api-(api|test) "
# 00-job-board-api-api 343MB / 00-job-board-api-test 365MB

# 5. Dev stack still runs
docker compose up -d
source scripts/dev-helper.sh; waitapi
r | head -n 3                                            # HTTP 200

# 6. Test output ignored by git
git status --short | grep -E "coverage|pytest_cache|htmlcov" || echo "nothing from tests in git status"

# 7. Remove the startapp stub (jobs/tests/ is the real package)
cat jobs/tests.py
git rm jobs/tests.py
```

### 5.2 Step 1, Part B: models, match score, resume validator

New files: `jobs/tests/conftest.py` (factory fixtures), `test_matching.py`, `test_validators.py`, `test_models.py`.

```bash
sed -i 's/extentsion/extension/g' jobs/models.py && grep -c extentsion jobs/models.py     # 0 (typo fix)

# 1. The whole suite
docker compose run --rm test
# 38 passed in 2.68s; matching.py, models.py, validators.py, signals.py 100%; TOTAL 62%

# 2. Part B only, one line per test
docker compose run --rm test pytest -v --no-cov jobs/tests/test_matching.py jobs/tests/test_validators.py jobs/tests/test_models.py
# 36 passed (pytest-django runs database tests first, so files appear out of order)

# 3. Prove the tests can FAIL: break the code, run, restore
sed -i 's/    if not required:/    if required is None:/' jobs/matching.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_matching.py
# 2 failed, 10 passed: ZeroDivisionError in test_match_score_is_none_when_job_requires_no_skills
git checkout jobs/matching.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_matching.py     # 12 passed
git status --short jobs/matching.py                                            # (nothing) = restored
```

### 5.3 Step 1, Part C: permission tests

New: `jobs/tests/test_permissions.py` (unit tests of the 4 classes + who-can-do-what matrix). `conftest.py` gains two autouse fixtures: `local_cache` (LocMemCache per test, no Redis) and `fast_password_hashing` (MD5 in tests only).

```bash
# 1. The whole suite
docker compose run --rm test
# 80 passed; permissions.py 100%, storage.py 100%, views.py 84%; TOTAL 74%

# 2. Part C only
docker compose run --rm test pytest -v --no-cov jobs/tests/test_permissions.py      # 42 passed

# 3. No Redis needed
docker compose stop redis
docker compose run --rm test pytest -q --no-cov                                      # 80 passed
docker compose start redis

# 4. Prove the matrix can FAIL: drop IsJobOwner from both get_permissions, run, restore
sed -i 's/            return \[IsAuthenticated(), IsJobOwner()\]$/            return [IsAuthenticated()]/' jobs/views.py
grep -n "return \[IsAuthenticated()\]" jobs/views.py           # lines 66 and 125
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py
# 7 failed, 35 passed: every non-owner case of job update, applicants, status change got 200 (and changed data)
git checkout jobs/views.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py   # 42 passed
git status --short jobs/views.py                                                # (nothing) = restored

# 5. Slow suite: measure, then fix with a fast hasher in tests only
sed -i 's/    settings.PASSWORD_HASHERS = /    settings.UNUSED_HASHERS = /' jobs/tests/conftest.py    # fixture disabled
docker compose run --rm test pytest -q --no-cov --durations=3
# 80 passed in 27.13s; slowest = setup of permission-matrix tests, 0.62-0.63 s each
sed -i 's/    settings.UNUSED_HASHERS = /    settings.PASSWORD_HASHERS = /' jobs/tests/conftest.py    # fixture enabled
docker compose run --rm test pytest -q --no-cov --durations=3
# 80 passed in 0.92s
grep -n "PASSWORD_HASHERS" jobs/tests/conftest.py config/settings.py   # only conftest.py
```

### 5.4 Step 1, Part D: API endpoint tests

New: `test_api_auth.py` (registration, real JWT flow), `test_api_jobs.py` (validation, normalisation, filters, search, ordering, pagination), `test_api_applications.py` (validation before upload, response shape, status). `conftest.py` gains `api_as`; `make_job` takes `location` as a parameter.

```bash
sed -i 's/def validate_email(delf, value):/def validate_email(self, value):/' jobs/serializers.py   # typo fix
grep -n "def validate_email" jobs/serializers.py

# 1. The whole suite
docker compose run --rm test 2>&1 | tail -n 40
# 131 passed in 2.35s; serializers.py 99%, filters.py 92%, views.py 85%; TOTAL 78%

# 2. Part D only
docker compose run --rm test pytest -q --no-cov jobs/tests/test_api_auth.py jobs/tests/test_api_jobs.py jobs/tests/test_api_applications.py
# 51 passed in 0.86s

# 3. Mutation: drop .lower() in JobSerializer → ONLY the 2 normalisation tests may fail
sed -i 's/skill.strip().lower() for skill in value/skill.strip() for skill in value/' jobs/serializers.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_api_jobs.py 2>&1 | tail -n 4
# FAILED ...test_create_normalises_skills_and_takes_company_from_the_user / ...test_update_normalises_skills / 2 failed, 19 passed
git checkout jobs/serializers.py
sed -i 's/def validate_email(delf, value):/def validate_email(self, value):/' jobs/serializers.py    # re-apply if not committed yet
git diff --stat jobs/serializers.py                       # 1 insertion(+), 1 deletion(-)
```

First run: 14 setup **errors** `TypeError: ... got multiple values for keyword argument 'location'` — the `make_job` fixture hard-coded `location=` AND passed `**fields`. Fix: `location="Vancouver"` as a parameter with a default.

### 5.5 Step 1, Part E: S3 and SQS with moto

New: `aws` fixture in `conftest.py` (endpoints → None, storage rebuilt, cached clients cleared, `mock_aws()` with bucket + queue + DLQ like `create-queues.sh`), `test_aws_storage.py`, `test_aws_queue.py`.

```bash
# 0. New dev dependency → rebuild the test image
docker compose build test

# 1. The whole suite
docker compose run --rm test 2>&1 | tail -n 35
# 144 passed in 5.10s; queue.py, events.py, serializers.py, storage.py 100%; views.py 90%; TOTAL 82%

# 2. Part E only
docker compose run --rm test pytest -v --no-cov jobs/tests/test_aws_storage.py jobs/tests/test_aws_queue.py   # 13 passed

# 3. Prove it's moto, not LocalStack (⚠ stopping LocalStack empties the DEV bucket)
docker compose stop localstack
docker compose run --rm test pytest -q --no-cov jobs/tests/test_aws_storage.py jobs/tests/test_aws_queue.py   # 13 passed
docker compose start localstack

# 4. Mutation: publish immediately instead of on commit
sed -i 's/^    transaction.on_commit(send)$/    send()/' jobs/events.py
grep -n "^    send()$" jobs/events.py                     # 50:    send()
docker compose run --rm test pytest -q --no-cov jobs/tests/test_aws_queue.py 2>&1 | tail -n 5
# FAILED ...test_status_change_is_published_only_after_commit / ...test_rolled_back_change_publishes_nothing / 2 failed, 6 passed
git checkout jobs/events.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_aws_queue.py 2>&1 | tail -n 1     # 8 passed
git status --short jobs/events.py                    # (nothing) = restored
```

### 5.6 Step 1, Part F: worker, emails, cache, health

New: `test_emails.py`, `test_worker.py` (handle + idempotency + one-pass main loop with a fake queue), `test_cache.py`, `test_health.py`.

```bash
# Fix for teardown errors: patch the cache BACKEND, not the `cache` proxy
sed -i 's/^from django.core.cache import cache$/from django.core.cache import cache, caches/' jobs/tests/test_cache.py
sed -i 's/monkeypatch.setattr(cache, /monkeypatch.setattr(caches["default"], /' jobs/tests/test_cache.py
sed -i 's/^from django.core.cache import cache$/from django.core.cache import caches/' jobs/tests/test_health.py
sed -i 's/monkeypatch.setattr(cache, /monkeypatch.setattr(caches["default"], /' jobs/tests/test_health.py
grep -n "import cache\|monkeypatch.setattr(caches" jobs/tests/test_cache.py jobs/tests/test_health.py

# 1. The whole suite
docker compose run --rm test 2>&1 | tail -n 6
# 178 passed in 5.71s; TOTAL 99% (missing: settings.py 16, filters.py 17, views.py 77/126/130, run_worker.py 133)

# 2. Part F only
docker compose run --rm test pytest -q --no-cov jobs/tests/test_emails.py jobs/tests/test_worker.py jobs/tests/test_cache.py jobs/tests/test_health.py
# 34 passed

# 3. Mutation: Phase 3 cache bug reversed (bump immediately instead of on commit)
sed -i 's/^    transaction.on_commit(bump)$/    bump()/' jobs/cache.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_cache.py 2>&1 | tail -n 3
# FAILED jobs/tests/test_cache.py::test_new_job_invalidates_the_list_only_after_commit / 1 failed, 8 passed
git checkout jobs/cache.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_cache.py 2>&1 | tail -n 1     # 9 passed
git status --short jobs/cache.py
```

First run: `178 passed, 4 errors` — errors at **teardown**: `AttributeError: 'RedisCache' object has no attribute 'get'`. `django.core.cache.cache` is a proxy to whatever cache is configured *now*; by the time monkeypatch undid its patch, the settings fixture had switched `CACHES` back to Redis, so the undo hit a different object. Patching `caches["default"]` (the real backend) fixes it.

### 5.7 Step 1, Part G: the last lines, and the 80% gate

```bash
# Dead role checks removed from views.py (both perform_create); unused import removed
grep -n "PermissionDenied" jobs/views.py
sed -i 's/^from rest_framework.exceptions import PermissionDenied, ValidationError$/from rest_framework.exceptions import ValidationError/' jobs/views.py
grep -c "PermissionDenied" jobs/views.py           # 0

# pyproject.toml: gate + exclusion (these are FILE edits, not shell commands)
sed -i 's/^addopts = "--cov --cov-report=term-missing"$/addopts = "--cov --cov-report=term-missing --cov-fail-under=80"/' pyproject.toml
grep -q '^\[tool.coverage.report\]' pyproject.toml || cat >> pyproject.toml <<'EOF'

[tool.coverage.report]
exclude_also = ['if __name__ == .__main__.:']
EOF
sed -n '/^\[tool.pytest.ini_options\]/,$p' pyproject.toml
python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('toml OK')"

# New tests appended / created (see the step1g explanation file for the code)
mkdir -p config/tests && touch config/tests/__init__.py
grep -c "def test_" jobs/tests/test_api_jobs.py jobs/tests/test_permissions.py config/tests/test_settings.py
# test_api_jobs.py:11 / test_permissions.py:15 / test_settings.py:5

# 1. Full suite: green AND above the gate (exit code read from a file, not after a pipe)
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 4 /tmp/pytest.out
# exit code: 0 / TOTAL 670 0 100% / Required test coverage of 80% reached. Total coverage: 100.00% / 194 passed in 5.80s
grep -E "^(jobs|cloud|config|worker)/.* [0-9]+%" /tmp/pytest.out | grep -v " 100%" || echo "every file at 100%"

# 2. The gate can FAIL even when every test passes
docker compose run --rm test pytest jobs/tests/test_smoke.py > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 4 /tmp/pytest.out
# exit code: 1 / FAIL Required test coverage of 80% not reached. Total coverage: 58.66% / 2 passed

# 3. The deleted checks were unreachable: permission tests still pass
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py 2>&1 | tail -n 1     # 42 passed (45 with the OPTIONS cases)

# 4. Dev API still serves
source scripts/dev-helper.sh; waitapi; login_all
curl -s -o /dev/null -w "%{http_code}\n" $API/jobs/ -H "Authorization: Bearer $SAM"       # 200
```

### 5.8 Phase 5, Step 1 result

`docker compose run --rm test` → **194 passed in 5.80s**, **100%** coverage (670/670), gate at 80% → exit code 0. Explanation files: `job-board-api-phase5-step1a-…` to `…-step1g-…` (one per part).

### 5.9 Step 2, Part A: OpenAPI schema and Swagger UI

```bash
uv add "drf-spectacular>=0.30"
docker compose build api worker test               # runtime dependency → rebuild every image
docker compose up -d
source scripts/dev-helper.sh; waitapi

curl -s -i http://localhost:8006/api/schema/ | grep -i "^HTTP\|^content-type"     # 200 / application/vnd.oai.openapi
curl -s http://localhost:8006/api/schema/ | head -n 6                              # openapi: 3.0.3 / info: title: Job Board API ...
curl -s http://localhost:8006/api/schema/ | grep -E "^  /api/"                     # 11 paths
curl -s http://localhost:8006/api/schema/ | grep -A3 "securitySchemes"             # jwtAuth: http bearer
curl -s -o /dev/null -w "swagger-ui %{http_code}\n" http://localhost:8006/api/schema/swagger-ui/   # 200

docker compose exec api python manage.py spectacular --validate --file /tmp/schema.yml 2>&1 | grep -E "Warning|Error|warning|error" | sort | uniq
# 2 unique warnings: get_has_resume, get_match_score ("Defaulting to string"); Errors: 0

docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out    # 194 passed

# Operation table: what the schema SAYS each operation accepts/returns (finds silent errors)
docker compose exec api python manage.py spectacular --file /tmp/schema.yml > /dev/null 2>&1
docker compose exec -T api python - <<'EOF'
import yaml

schema = yaml.safe_load(open("/tmp/schema.yml"))

def name(s):
    return s.get("$ref", "").split("/")[-1] or s.get("type", "?")

for path, ops in schema["paths"].items():
    for method, op in ops.items():
        request = sorted({name(v["schema"]) for v in op.get("requestBody", {}).get("content", {}).values()})
        responses = {code: sorted({name(v["schema"]) for v in r.get("content", {}).values()}) or "-" for code, r in op["responses"].items()}
        print(f"{method.upper():6} {path:40} request={request or '-'} responses={responses}")
EOF
# Before Part B, 4 silently wrong: resume → Application; status → PatchedApplicationRequest;
#   jobs/{id}/applications → Job; register/* → ...Registration
```

Browser (MacBook): `http://10.0.0.149:8006/api/schema/swagger-ui/` → `POST /api/auth/token/` (Try it out) → copy `access` → **Authorize** → `GET /api/jobs/` → 200.

### 5.10 Step 2, Part B: schema matches the code

```bash
# 1. No warnings, valid (PIPESTATUS[0] = exit code of the first command in the pipe, not tail)
docker compose exec api python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yml 2>&1 | tail -n 3; echo "exit code: ${PIPESTATUS[0]}"
# Warnings: 0 ; exit code: 0

# 2. Operation table again (same script as 5.9)
# resume → ResumeLink + 404; status → PatchedApplicationStatusRequest; jobs/{id}/applications → PaginatedApplicationList; register/* → RegisteredUser

# 3. Full suite
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out
# exit code: 0 / TOTAL 687 0 100% / 203 passed in 6.15s

# 4. Real response unchanged
source scripts/dev-helper.sh; waitapi; login_all
curl -s $API/applications/12/resume/ -H "Authorization: Bearer $RIYA" | python3 -m json.tool | grep -E '"url"|"expires_in"'
# "url": "http://localhost:4566/00-job-board-api/resume/job-1/...pdf?...X-Amz-Expires=300...X-Amz-Signature=..." / "expires_in": 300
```

### 5.11 Step 3: README (checked like code)

```bash
# Copy the README to thor: run scp ON THE MACBOOK (where the download is), not on thor
#   scp ~/Downloads/README.md reza@10.0.0.149:~/projects/00-job-board-api/README.md

# 1. Every path the README names exists
for f in config/settings.py config/urls.py config/wsgi.py config/tests jobs/models.py jobs/serializers.py \
         jobs/views.py jobs/permissions.py jobs/matching.py jobs/filters.py jobs/validators.py jobs/storage.py \
         jobs/cache.py jobs/signals.py jobs/events.py jobs/emails.py jobs/templates/emails/status_changed.txt \
         jobs/apps.py jobs/migrations jobs/tests/conftest.py cloud/queue.py cloud/health.py worker/run_worker.py \
         localstack/init/ready.d/create-bucket.sh localstack/init/ready.d/create-queues.sh scripts/dev-helper.sh \
         docs Dockerfile gunicorn.conf.py docker-compose.yml .env.example .env.localstack.example \
         pyproject.toml uv.lock .python-version manage.py; do
  [ -e "$f" ] || echo "MISSING: $f"
done; echo "path check done"

# 2. Counts and commands quoted in the README
ls jobs/tests/test_*.py | wc -l                                                                           # 15
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out    # 0 / 203 passed / 100%
docker compose run --rm test pytest -q --no-cov jobs/tests/test_permissions.py 2>&1 | tail -n 1         # 45 passed
docker compose run --rm test pytest -k "cache" -q --no-cov 2>&1 | tail -n 1                            # 11 passed, 192 deselected
curl -s -o /dev/null -w "swagger-ui %{http_code}\n" http://localhost:8006/api/schema/swagger-ui/         # 200

# 3. The file itself
wc -l < README.md                                       # 365
grep -c '^```' README.md                                # 14 (even = fences balanced)
grep -c "Phase 5 (tests and docs) complete" README.md   # 1
grep -nE "LOCALSTACK_AUTH_TOKEN=[^ ]|SECRET_KEY=[A-Za-z0-9_-]{20,}" README.md || echo "no secrets"
git diff --stat README.md                               # 119 insertions(+), 93 deletions(-)
```

### 5.12 Phase 5 Done-when: one command runs the full test suite green and coverage is reported

```bash
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 4 /tmp/pytest.out
# exit code: 0 / TOTAL 687 0 100% / Required test coverage of 80% reached. Total coverage: 100.00% / 203 passed in 6.11s
```

**Reading coverage:** importing a module runs its top-level lines (imports, classes, fields, decorators), so they count as covered without any test. Judge each file by its `Missing` column (function bodies), not by TOTAL.

## 6. Phase 6 — Azure Portability

`CLOUD_PROVIDER` (aws | azure, default aws) picks the backend. The same image runs either way; `.env` holds both providers' settings and only `CLOUD_PROVIDER` changes. Both providers share the dev database in these checks.

### 6.1 Step 1: Storage switches between S3 and Azure Blob (Azurite)

```bash
# Pin Azurite like LocalStack
docker pull mcr.microsoft.com/azure-storage/azurite:latest
docker run --rm mcr.microsoft.com/azure-storage/azurite:latest azurite --version           # 3.37.0
sed -i 's|mcr.microsoft.com/azure-storage/azurite:.*|mcr.microsoft.com/azure-storage/azurite:3.37.0|' docker-compose.yml
docker compose config --quiet && echo "compose file OK"
docker compose config | grep "azure-storage/azurite"                                       # image: ...:3.37.0
docker compose config | grep -A16 "^  azurite:" | grep -E "published|host_ip|target"      # 127.0.0.1 / "10000" / 10000

# Dependency and code in place
grep -n "django-storages" pyproject.toml                    # "django-storages[azure,s3]>=1.14.6"
grep -c '^name = "azure-storage-blob"' uv.lock              # 1
grep -n "^from azure\|^def _azure_download_url\|^def resume_download_url" jobs/storage.py   # lines 7, 12, 44
grep -n "DEFAULT_STORAGE_BACKEND" config/settings.py        # 2 assignments + STORAGES
grep -c "^AZURE_\|^CLOUD_PROVIDER=" .env .env.example       # .env:6  .env.example:6
grep -c '="' .env                                           # 0

# 0. Rebuild and start (Azurite joins the stack)
docker compose build api worker test
docker compose up -d
source scripts/dev-helper.sh; waitapi; login_all
docker compose ps azurite                                   # Up, 127.0.0.1:10000->10000/tcp

# 1. AWS is the default; an unknown provider fails fast
docker compose exec api python manage.py shell -c "from django.conf import settings as s; print(s.CLOUD_PROVIDER, s.STORAGES['default'])"
# aws {'BACKEND': 'storages.backends.s3.S3Storage'}
docker run --rm --env-file .env -e CLOUD_PROVIDER=gcp 00-job-board-api-api python manage.py check 2>&1 | tail -n 1
# django.core.exceptions.ImproperlyConfigured: CLOUD_PROVIDER must be 'aws' or 'azure', not 'gcp'

# 2. The SAME image as an Azure API on port 8017 (one env var different)
docker run -d --name jb-azure --network 00-job-board-api_default --env-file .env -e CLOUD_PROVIDER=azure \
  -p 127.0.0.1:8017:8006 00-job-board-api-api
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8017/healthz && { echo "up after ${i}s"; break; }; sleep 1; done   # up after 2s
docker logs jb-azure 2>&1 | tail -n 20                      # only if it didn't come up
docker exec jb-azure python manage.py shell -c "from django.conf import settings as s; print(s.CLOUD_PROVIDER, s.STORAGES['default'])"
# azure {'BACKEND': 'storages.backends.azure_storage.AzureStorage'}

# 3. Create the container in Azurite (on real Azure: Terraform)
docker exec jb-azure python manage.py shell -c "from azure.storage.blob import BlobServiceClient; from django.conf import settings as s; c = BlobServiceClient.from_connection_string(s.AZURE_CONNECTION_STRING); c.create_container(s.AZURE_CONTAINER); print([x.name for x in c.list_containers()])"
# ['resumes']

# 4. ⚠ Save riya's resume through the Azure backend (application 12); list the blob
docker exec jb-azure python manage.py shell -c "from django.core.files.base import ContentFile; from jobs.models import Application; a = Application.objects.get(id=12); a.resume.save('good.pdf', ContentFile(b'%PDF-1.4\nfake resume\n%%EOF\n')); print(a.resume.name, a.resume.size, a.resume.storage.__class__.__name__)"
# resume/job-1/<32 hex>.pdf 27 AzureStorage
docker exec jb-azure python manage.py shell -c "from azure.storage.blob import BlobServiceClient; from django.conf import settings as s; c = BlobServiceClient.from_connection_string(s.AZURE_CONNECTION_STRING).get_container_client(s.AZURE_CONTAINER); print([(b.name, b.size) for b in c.list_blobs()])"

# 5. SAS link from the Azure API, downloaded on thor (delete old output files FIRST)
rm -f /tmp/h.txt /tmp/r.pdf
URL=$(curl -s http://localhost:8017/api/applications/12/resume/ -H "Authorization: Bearer $RIYA" | python3 -c "import sys, json; print(json.load(sys.stdin)['url'])"); echo "${URL:0:90}..."
curl -s -D /tmp/h.txt -o /tmp/r.pdf "$URL" -w "download %{http_code}\n"            # download 200
grep -i "^content-disposition" /tmp/h.txt                                         # content-disposition: attachment; filename="resume-12.pdf"
head -c 8 /tmp/r.pdf; echo                                                        # %PDF-1.4
curl -s -o /dev/null -w "tampered %{http_code}\n" "${URL%sig=*}sig=AAAA"          # tampered 403

# 6. Clean up; riya's resume back on S3 for the AWS dev stack (one-line form, no heredoc to close)
docker rm -f jb-azure
docker compose exec api python manage.py shell -c "from django.core.files.base import ContentFile; from jobs.models import Application; a = Application.objects.get(id=12); a.resume.save('good.pdf', ContentFile(b'%PDF-1.4\nfake resume\n%%EOF\n')); print(a.resume.name, a.resume.storage.__class__.__name__)"
# resume/job-1/<hex>.pdf S3Storage

# 7. Test suite: AWS path unchanged; Azure lines uncovered until Step 3
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out
# exit code: 0 / TOTAL 712 13 98% / 98.17% / 203 passed in 6.46s
grep -E "^(jobs|cloud|config|worker)/.* [0-9]+%" /tmp/pytest.out | grep -v " 100%"
# config/settings.py 87% 35, 60-76 / jobs/storage.py 83% 14, 45-55

# Look inside Azurite from the AWS dev API (no CLOUD_PROVIDER switch needed)
docker compose exec api python -c "from azure.storage.blob import BlobServiceClient; c = BlobServiceClient.from_connection_string('DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;'); print([x.name for x in c.list_containers()], [(b.name, b.size) for b in c.get_container_client('resumes').list_blobs()])"

# 6b. After adding "azure": {"level": "WARNING"} to LOGGING (rebuild first: jb-azure runs the IMAGE's code)
docker compose build api
docker run -d --name jb-azure --network 00-job-board-api_default --env-file .env -e CLOUD_PROVIDER=azure -p 127.0.0.1:8017:8006 00-job-board-api-api
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8017/healthz && { echo "up after ${i}s"; break; }; sleep 1; done
docker exec jb-azure python manage.py shell -c "from azure.storage.blob import BlobServiceClient; from django.conf import settings as s; c = BlobServiceClient.from_connection_string(s.AZURE_CONNECTION_STRING).get_container_client(s.AZURE_CONTAINER); print([(b.name, b.size) for b in c.list_blobs()])" 2>&1 | grep -c "http_logging_policy"
# 0 (was 2 per SDK call)
docker rm -f jb-azure
```

⚠ **Rerunning checks 3–7 after check 6 removed `jb-azure`** gives `No such container`, `JSONDecodeError`, `tampered 000` — and **stale** `/tmp/h.txt` / `/tmp/r.pdf` from the earlier run that look like fresh results. Start again from check 2, and `rm -f` the output files first.

### 6.2 Step 2, Part A: Service Bus emulator in Compose (profile "azure")

The emulator needs SQL Server; both run only with `--profile azure` (SQL Server alone uses ~0.7 GB). Queues come from `servicebus/Config.json` at startup. The connection string uses the emulator's fixed development key (`SAS_KEY_VALUE`, published by Microsoft, not a secret); the SQL password lives only in `.env.servicebus`.

```bash
# Pin both images: newest version tags, picked by number (NOT "latest", never a <placeholder>)
SB_TAG=$(curl -s https://mcr.microsoft.com/v2/azure-messaging/servicebus-emulator/tags/list | python3 -c "import sys, json, re; t = [x for x in json.load(sys.stdin)['tags'] if re.fullmatch(r'\d+\.\d+\.\d+', x)]; print(max(t, key=lambda v: tuple(map(int, v.split('.')))) if t else '')")
SQL_TAG=$(curl -s https://mcr.microsoft.com/v2/mssql/server/tags/list | python3 -c "import sys, json, re; t = [x for x in json.load(sys.stdin)['tags'] if re.fullmatch(r'2022-CU\d+-ubuntu-22\.04', x)]; print(max(t, key=lambda v: int(re.search(r'CU(\d+)', v).group(1))) if t else '')")
echo "SB_TAG=$SB_TAG  SQL_TAG=$SQL_TAG"                                       # SB_TAG=2.0.1  SQL_TAG=2022-CU27-ubuntu-22.04
docker compose --profile azure config | grep -E "servicebus-emulator:|mssql/server:"   # both pinned
grep -n '<[A-Z_]*_TAG>' docker-compose.yml || echo "no placeholders left"

# Files in place, secret file ignored
python3 -m json.tool servicebus/Config.json > /dev/null && echo "Config.json is valid JSON"
git check-ignore -q .env.servicebus && echo ".env.servicebus: ignored"
git check-ignore -q .env.servicebus.example || echo ".env.servicebus.example: trackable"
cut -d= -f1 .env.servicebus                                                   # ACCEPT_EULA / MSSQL_SA_PASSWORD (names only)

# 0. Rebuild (new SDK) and start the pair
docker compose build api worker test
docker compose --profile azure up -d
docker compose --profile azure ps servicebus servicebus-sql                   # both Up; ports with no host part = network only

# 1. Ready: Config.json applied and emulator up
docker compose logs servicebus 2>&1 | grep -ci "successfully up"              # 1
docker compose logs --tail=15 servicebus                                      # "User defined entities created" ... "Emulator Service is Successfully Up!"

# 2. Health (management port 5300) from inside the Compose network
docker compose exec api python -c "import urllib.request; r = urllib.request.urlopen('http://servicebus:5300/health', timeout=5); print(r.status, r.read()[:200])"
# 200 b'{"status":"healthy","message":"Service is healthy."}'

# 3. Send → receive → complete
docker compose exec -T api python - <<'EOF'
from azure.servicebus import ServiceBusClient, ServiceBusMessage

CS = "Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
with ServiceBusClient.from_connection_string(CS) as client:
    with client.get_queue_sender("job-board-status") as sender:
        sender.send_messages(ServiceBusMessage('{"hello": "service bus"}'))
    with client.get_queue_receiver("job-board-status", max_wait_time=5) as receiver:
        [message] = receiver.receive_messages(max_message_count=1, max_wait_time=5)
        print("received:", str(message), "delivery_count:", message.delivery_count)
        receiver.complete_message(message)
    with client.get_queue_receiver("job-board-status", max_wait_time=3) as receiver:
        print("left after complete:", len(receiver.receive_messages(max_wait_time=3)))
EOF
# received: {"hello": "service bus"} delivery_count: 0 / left after complete: 0

# 4. Abandon 3 times → dead-letter subqueue (proves LockDuration/MaxDeliveryCount from Config.json)
docker compose exec -T api python - <<'EOF'
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusSubQueue

CS = "Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
with ServiceBusClient.from_connection_string(CS) as client:
    with client.get_queue_sender("job-board-status") as sender:
        sender.send_messages(ServiceBusMessage('{"poison": true}'))
    with client.get_queue_receiver("job-board-status", max_wait_time=5) as receiver:
        for attempt in range(1, 4):
            [message] = receiver.receive_messages(max_message_count=1, max_wait_time=5)
            print("attempt", attempt, "delivery_count", message.delivery_count)
            receiver.abandon_message(message)
        print("left in main queue:", len(receiver.receive_messages(max_wait_time=3)))
    with client.get_queue_receiver("job-board-status", sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=5) as dlq:
        dead = dlq.receive_messages(max_message_count=1, max_wait_time=5)
        print("dead-lettered:", [str(m) for m in dead], [m.dead_letter_reason for m in dead])
        for m in dead:
            dlq.complete_message(m)
EOF
# attempt 1 delivery_count 0 / attempt 2 ... 1 / attempt 3 ... 2 / left in main queue: 0
# dead-lettered: ['{"poison": true}'] ['MaxDeliveryCountExceeded']

# 4b. Anything left in either queue? (peek = look without locking or removing)
docker compose exec -T api python - <<'EOF'
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue

CS = "Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
with ServiceBusClient.from_connection_string(CS) as client:
    for label, sub in (("main", None), ("dead-letter", ServiceBusSubQueue.DEAD_LETTER)):
        with client.get_queue_receiver("job-board-status", sub_queue=sub) as r:
            print(label, len(r.peek_messages(max_message_count=50)))
EOF
# main 0 / dead-letter 0

# 5. Memory, 6. running services
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" | grep -i servicebus   # emulator 130.8MiB, sql 734MiB
docker compose ps --format "{{.Service}}" | sort | tr '\n' ' '; echo            # api azurite db localstack redis servicebus servicebus-sql worker

# Stop the pair when not working on Azure (frees ~0.9 GB); data is not kept, Config.json recreates the queue
docker compose --profile azure stop servicebus servicebus-sql
```

⚠ **Copy only the commands.** Pasting a block's OUTPUT back into the shell gives `image:: command not found`, `no: command not found` and a syntax error on the prompt line. Harmless, nothing runs.

### 6.3 Step 2, Part B: `ServiceBusQueue` behind the `Queue` interface

One-off containers with the current code (bind mount, no rebuild) and only `CLOUD_PROVIDER` different. The emulator pair must be up (`docker compose --profile azure up -d`).

```bash
AZ="docker compose run --rm --no-deps -e CLOUD_PROVIDER=azure api python manage.py shell -c"

# 0. Code in place
docker compose run --rm --no-deps api python -c "import azure.servicebus as s; print(s.__version__)"   # 7.15.0
grep -n "BotoCoreError\|ClientError\|QUEUE_ERRORS" jobs/events.py worker/run_worker.py               # only QUEUE_ERRORS lines
python3 -m py_compile config/settings.py && echo "syntax OK"
grep -c '^if CLOUD_PROVIDER == "aws":' config/settings.py                                           # 1
grep -n "rest of your\|still SQS" config/settings.py || echo "no placeholders or old comments left"
grep -n "^AWS_\|^SQS_\|^AZURE_\|^SERVICE_BUS_" config/settings.py || echo "nothing outside the branches"
grep -c "^SERVICE_BUS_" .env .env.example                                                           # 2 / 2
grep -n '"azure"' config/settings.py                                                                # "azure": {"level": "WARNING"} in LOGGING

# 1. The switch; each cloud loads only its own settings
docker compose run --rm --no-deps api python manage.py shell -c "from django.conf import settings as s; from cloud.queue import get_queue; q = get_queue(); print(s.CLOUD_PROVIDER, type(q).__name__, q.url, hasattr(s, 'SERVICE_BUS_QUEUE_NAME'))"
# aws SQSQueue http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/job-board-status False
$AZ "from django.conf import settings as s; from cloud.queue import get_queue; q = get_queue(); print(s.CLOUD_PROVIDER, type(q).__name__, q.url, hasattr(s, 'SQS_QUEUE_NAME'), hasattr(s, 'AWS_REGION'), s.STORAGES['default']['BACKEND'])"
# azure ServiceBusQueue sb://servicebus/job-board-status False False storages.backends.azure_storage.AzureStorage

# 2. Round trip through our interface; peek proves the delete removed it
docker compose run --rm --no-deps -T -e CLOUD_PROVIDER=azure api python manage.py shell <<'EOF'
from azure.servicebus import ServiceBusClient
from django.conf import settings
from cloud.queue import get_queue

q = get_queue()
sent = q.send({"type": "test", "n": 1})
[m] = q.receive(max_messages=10, wait_seconds=5)
print("same id:", m.id == sent, "body:", m.body)
q.delete(m)
with ServiceBusClient.from_connection_string(settings.SERVICE_BUS_CONNECTION_STRING) as c, c.get_queue_receiver(settings.SERVICE_BUS_QUEUE_NAME) as r:
    print("left (peek):", len(r.peek_messages(max_message_count=10)))
EOF
# same id: True body: {'type': 'test', 'n': 1} / left (peek): 0

# 3. Not deleted → redelivered after the 30 s lock; old token rejected (~40 s)
docker compose run --rm --no-deps -T -e CLOUD_PROVIDER=azure api python manage.py shell 2>&1 <<'EOF' | grep -v '"logger": "azure'
import time
from cloud.queue import get_queue

q = get_queue()
sent = q.send({"type": "test", "n": 2})
[first] = q.receive(max_messages=10, wait_seconds=5)
print("got it, not deleting; waiting for the lock to expire...")
time.sleep(32)
[again] = q.receive(max_messages=10, wait_seconds=10)
print("redelivered:", again.id == sent, "new lock token:", again.receipt_handle != first.receipt_handle)
q.delete(again)
try:
    q.delete(first)
except Exception as exc:
    print("old lock rejected:", type(exc).__name__)
EOF
# redelivered: True new lock token: True / old lock rejected: ServiceBusError

# 4. ping() in every state (two pings per process)
PING='import time; from cloud.queue import get_queue; q = get_queue()
for i in range(2):
    t = time.monotonic()
    try:
        q.ping(); r = "ok"
    except Exception as exc:
        r = f"{type(exc).__name__}: {exc}"[:90]
    print("PING", i + 1, round((time.monotonic() - t) * 1000), "ms", r)'
$AZ "$PING" 2>&1 | grep "^PING"                                                     # ok ~1004 ms, ok ~1003 ms
$AZ "import time; from django.conf import settings as s; from cloud.queue import ServiceBusQueue; t = time.monotonic()
try:
    ServiceBusQueue(s.SERVICE_BUS_CONNECTION_STRING, 'no-such-queue').ping(); r = 'ok (WRONG)'
except Exception as exc:
    r = type(exc).__name__
print('PING missing-queue', round((time.monotonic() - t) * 1000), 'ms', r)" 2>&1 | grep "^PING"   # 2001 ms ServiceBusError (a timeout)
docker compose stop servicebus
$AZ "$PING" 2>&1 | grep "^PING"                                                     # 4 ms / 2 ms ServiceBusConnectionError [Errno -3] (DNS)
T=$(date -u +%Y-%m-%dT%H:%M:%SZ); docker compose start servicebus
for i in $(seq 60); do docker compose logs --since "$T" servicebus 2>&1 | grep -qi "successfully up" && { echo "ready after ~$((i*2))s"; break; }; sleep 2; done   # ~28s
$AZ "$PING" 2>&1 | grep "^PING"                                                     # ok, ok (really listening before the pause)
docker compose pause servicebus
timeout 30 $AZ "$PING" 2>&1 | grep "^PING"; echo "exit=${PIPESTATUS[0]}"
# PING 1 2001 ms ServiceBusError: Ping timed out after 2 s / PING 2 0 ms ... Previous ping still running / exit=0
docker compose unpause servicebus

# 5. AWS path unchanged
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out
# exit code: 0 / TOTAL 788 71 91% / 90.99% / 203 passed
```

Diagnostics used to design `ping()` (no code change needed to rerun them):

```bash
# A. Which time limit breaks a healthy ping (emulator UP); prints the error text, not just the class
docker compose run --rm --no-deps -T -e CLOUD_PROVIDER=azure api python manage.py shell 2>&1 <<'EOF' | grep "^TRY"
import time
from azure.servicebus import ServiceBusClient
from django.conf import settings

CS, Q = settings.SERVICE_BUS_CONNECTION_STRING, settings.SERVICE_BUS_QUEUE_NAME
for try_timeout, peek_timeout in ((1, 1), (None, 1), (1, 5), (None, 5), (3, 3)):
    kwargs = {"retry_total": 0}
    if try_timeout:
        kwargs["try_timeout"] = try_timeout
    t = time.monotonic()
    try:
        with ServiceBusClient.from_connection_string(CS, **kwargs) as c, c.get_queue_receiver(Q) as r:
            r.peek_messages(max_message_count=1, timeout=peek_timeout)
        res = "ok"
    except Exception as exc:
        res = f"{type(exc).__name__}: {str(exc)[:160]}"
    print("TRY", f"try_timeout={try_timeout}", f"peek_timeout={peek_timeout}", round((time.monotonic() - t) * 1000), "ms", res)
EOF
# every row ~1000 ms; any 1 s limit → "Message peek failed"; (None,5) and (3,3) → ok

# B. Where a call hangs: dump every thread's stack after 15 s, then exit
docker compose pause servicebus
timeout 40 docker compose run --rm --no-deps -T -e CLOUD_PROVIDER=azure api python manage.py shell 2>&1 <<'EOF' | grep -v '"logger": "azure' | tail -n 40
import faulthandler, sys
faulthandler.dump_traceback_later(15, exit=True, file=sys.stdout)
from cloud.queue import get_queue
get_queue().ping()
EOF
docker compose unpause servicebus
# (first ping version) stuck in _pyamqp/sasl.py _negotiate → _transport.py _read
```

### 6.4 Step 2, Part C: worker and API end to end on Service Bus

The real API (port 8017) and worker with `CLOUD_PROVIDER=azure`, next to the AWS stack. Same DB and `SECRET_KEY`, so tokens from `login_all` (8006) work on 8017.

```bash
# 0. Broker ready (GATE: stop if READY=no), then the Azure API + worker
docker compose --profile azure up -d --force-recreate servicebus
T=$(date -u +%Y-%m-%dT%H:%M:%SZ); READY=no
for i in $(seq 60); do docker compose logs --since "$T" servicebus 2>&1 | grep -qi "successfully up" && { READY=yes; echo "broker ready after ~$((i*2))s"; break; }; sleep 2; done
echo "READY=$READY"; docker inspect -f '{{.RestartCount}} restarts' 00-job-board-api-servicebus-1      # READY=yes, 0 restarts
docker rm -f jb-azure jb-azure-worker 2>/dev/null
docker compose run -d --name jb-azure-worker --no-deps -e CLOUD_PROVIDER=azure worker
docker compose run -d --name jb-azure --no-deps -e CLOUD_PROVIDER=azure -p 127.0.0.1:8017:8006 api
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8017/healthz && { echo "azure api up after ${i}s"; break; }; sleep 1; done
msgs() { docker logs "$1" 2>&1 | grep -o '"message": "[^"]*"' | grep -v "Connection state\|Session state\|Link state\|link .*state" | tail -n "${2:-10}"; }
flip() { OLD=$(curl -s http://localhost:8017/api/applications/3/ -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])"); NEW=$([ "$OLD" = "interview" ] && echo reviewing || echo interview); curl -s -o /dev/null -w "PATCH $1: $OLD -> $NEW %{http_code} in %{time_total}s\n" -X PATCH http://localhost:8017/api/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d "{\"status\": \"$NEW\"}"; }
waitsb() { local T=$1 i; for i in $(seq 60); do docker compose logs --since "$T" servicebus 2>&1 | grep -qi "successfully up" && { echo "broker ready after ~$((i*2))s"; return; }; sleep 2; done; echo "BROKER NOT READY"; }
source scripts/dev-helper.sh; waitapi; login_all
msgs jb-azure-worker 3                                    # Worker started, queue sb://servicebus/job-board-status
curl -s http://localhost:8017/readyz | python3 -m json.tool   # ready; queue ok ~1003 ms

# 1-4 (output also saved to a file)
{
echo "== 1. duplicate detection"
docker compose exec -T api python -c "
from azure.servicebus import ServiceBusClient, ServiceBusMessage
CS = 'Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;'
with ServiceBusClient.from_connection_string(CS) as c:
    with c.get_queue_sender('job-board-status') as s:
        for _ in range(2):
            s.send_messages(ServiceBusMessage('{\"type\": \"dup-test\"}', message_id='dup-test-2'))
    with c.get_queue_receiver('job-board-status') as r:
        print('DUP peek', len(r.peek_messages(max_message_count=10)))
" 2>&1 | grep "^DUP"                                                   # DUP peek 1  (use a NEW id each run: 5 min window)
echo "== 2. normal"
flip normal; sleep 5; msgs jb-azure-worker 4 | grep "Emailed\|Failed to handle"     # ~0.51 s; Emailed ...
echo "== 3. stopped"
docker compose stop servicebus 2>/dev/null
flip stopped                                                           # ~1.84 s (was 12.03 s before the fix)
echo "Could not queue lines: $(msgs jb-azure 20 | grep -c 'Could not queue')"
echo "== 4. frozen, fresh connection"
T=$(date -u +%Y-%m-%dT%H:%M:%SZ); docker compose start servicebus 2>/dev/null; waitsb "$T"
docker restart jb-azure >/dev/null; for i in $(seq 30); do curl -s -o /dev/null http://localhost:8017/healthz && break; sleep 1; done
docker compose pause servicebus 2>/dev/null
flip "frozen, new connection"                                          # ~3.02 s (could hang forever before)
docker compose unpause servicebus 2>/dev/null
echo "== 4b. after unpause: was it delivered?"
sleep 20; msgs jb-azure-worker 4 | grep "Emailed\|Failed to handle"     # yes: Emailed ...
} 2>&1 | tee /tmp/partc-1-4.txt

# 5. Frozen, OPEN connection: one email, no duplicates
flip "warm-up"; sleep 5; msgs jb-azure-worker 2 | grep "Emailed"
BEFORE=$(docker logs jb-azure-worker 2>&1 | grep -c "already processed")
docker compose pause servicebus
flip "frozen, open connection"                                         # ~3.02 s
msgs jb-azure 2 | grep "Could not queue"
docker compose unpause servicebus
sleep 60
msgs jb-azure-worker 6 | grep "Emailed"
echo "new duplicates: $(( $(docker logs jb-azure-worker 2>&1 | grep -c "already processed") - BEFORE ))"   # 0 (was 3 before the fix)
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" | grep -i servicebus   # 128MiB / 1003MiB

# Poison message → DLQ (~100 s), from the first run
docker compose run --rm --no-deps -T -e CLOUD_PROVIDER=azure api python manage.py shell 2>&1 <<'EOF' | grep "^SENT"
from cloud.queue import get_queue
print("SENT", get_queue().send({"type": "nope"}))
EOF
sleep 100
msgs jb-azure-worker 20 | grep -c "Failed to handle message"           # 3
docker compose exec -T api python -c "
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue
CS = 'Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;'
with ServiceBusClient.from_connection_string(CS) as c, c.get_queue_receiver('job-board-status', sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=5) as dlq:
    dead = dlq.receive_messages(max_message_count=10, max_wait_time=5)
    print('DLQ', [(str(m), m.dead_letter_reason, m.delivery_count) for m in dead])
    for m in dead:
        dlq.complete_message(m)
" 2>&1 | grep "^DLQ"                                                   # ('{"type": "nope"}', 'MaxDeliveryCountExceeded', 3)

# 6. Clean up
docker compose exec -T api python -c "
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue
CS = 'Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;'
with ServiceBusClient.from_connection_string(CS) as c:
    for label, sub in (('main', None), ('dead-letter', ServiceBusSubQueue.DEAD_LETTER)):
        with c.get_queue_receiver('job-board-status', sub_queue=sub, max_wait_time=3) as r:
            got = r.receive_messages(max_message_count=50, max_wait_time=3)
            for m in got: r.complete_message(m)
            print('CLEAN', label, len(got))
" 2>&1 | grep "^CLEAN"
docker rm -f jb-azure jb-azure-worker
docker compose --profile azure stop servicebus servicebus-sql       # frees ~1.1 GB
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out   # 0 / 89.64% / 203 passed

# Debugging a broker that doesn't come up
docker compose --profile azure ps -a servicebus servicebus-sql
docker inspect -f '{{.RestartCount}} restarts, status {{.State.Status}}, exit {{.State.ExitCode}}' 00-job-board-api-servicebus-1
docker compose logs --tail=40 servicebus                        # e.g. "Max Duplicate detection window supported 5m, but found 10m"
```

### 6.5 Step 3, Part A: Azure storage tests (Azurite) and per-cloud settings tests

```bash
# 0. The test service depends on azurite
docker compose --profile test config --format json | python3 -c "import sys, json; print('depends_on', sorted(json.load(sys.stdin)['services']['test']['depends_on']))"
# depends_on ['azurite', 'db']

# 1. The new tests, verbose (saved to a file)
{
docker compose run --rm test pytest -v --no-cov jobs/tests/test_azure_storage.py config/tests/test_settings.py 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed"
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out
} 2>&1 | tee /tmp/step3a.txt
# all PASSED / exit code: 0 / 90.14% / 211 passed
grep -E "^(jobs|config)/(storage|settings)\.py" /tmp/pytest.out      # storage.py 100%; settings.py 84% (57-76 run in a subprocess: not counted)

# Failure details, short (used to confirm the two test bugs)
docker compose run --rm test pytest -q --no-cov --tb=short jobs/tests/test_azure_storage.py 2>&1 | grep -E "^E |^jobs/tests.*Error|assert" | head -n 20

# 2. Azurite STOPPED → the storage tests must ERROR (not skip), in ~15 s each
docker compose stop azurite
time docker compose run --rm --no-deps test pytest -q --no-cov jobs/tests/test_azure_storage.py 2>&1 | tail -n 2
# 5 errors in 76.81s (was 428.77s before retry_total=0 / connection_timeout=2 in the fixture)
docker compose start azurite

# 3. The tests can fail: break the SAS permission, run, restore
sed -i 's/permission=BlobSasPermissions(read=True)/permission=BlobSasPermissions(read=False, write=True)/' jobs/storage.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_azure_storage.py -k sas 2>&1 | tail -n 3
# 1 failed, 1 passed
git checkout jobs/storage.py && git status --short jobs/storage.py                       # empty = restored

# 4. No test containers left in Azurite
docker compose exec api python -c "from azure.storage.blob import BlobServiceClient; c = BlobServiceClient.from_connection_string('DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;'); print([x.name for x in c.list_containers()])"
# ['resumes']

# 5. Probe: what does Azurite answer for an anonymous read of a private blob?
docker compose exec -T api python - <<'EOF'
import urllib.error, urllib.request
from azure.storage.blob import BlobServiceClient
CS = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;"
c = BlobServiceClient.from_connection_string(CS).get_container_client("resumes")
c.upload_blob("probe.txt", b"x", overwrite=True)
try:
    urllib.request.urlopen("http://azurite:10000/devstoreaccount1/resumes/probe.txt", timeout=5)
    print("ANON 200 (PUBLIC!)")
except urllib.error.HTTPError as e:
    print("ANON", e.code, e.headers.get("x-ms-error-code"))
c.delete_blob("probe.txt")
EOF
# ANON 403 AuthorizationFailure

# 6. The warnings: 4x django-storages DeprecationWarning (datetime.utcnow); filtered in pyproject.toml, then:
python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['tool']['pytest']['ini_options']['filterwarnings'])"
docker compose run --rm test pytest -q --no-cov -rw jobs/tests/test_azure_storage.py 2>&1 | tail -n 2     # 5 passed, no warnings
```

### 6.6 Step 3, Part B: `ServiceBusQueue` unit tests (fakes)

```bash
# 1. The new file
docker compose run --rm test pytest -v --no-cov jobs/tests/test_azure_queue.py 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed"   # 17 passed

# 2. Whole suite
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 3 /tmp/pytest.out
grep -E "^cloud/queue\.py" /tmp/pytest.out
# exit code: 0 / TOTAL 801 11 99% / 98.63% / 228 passed / cloud/queue.py 122 0 100%

# 3. Mutations (COMMIT cloud/queue.py first: git checkout discards uncommitted changes)
git status --short cloud/queue.py                                   # must be empty before starting
sed -i 's/retry_total=0, try_timeout=self.PING_SECONDS/retry_total=3, try_timeout=self.PING_SECONDS/' cloud/queue.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_azure_queue.py 2>&1 | grep -E "^FAILED|passed|failed"
git checkout cloud/queue.py
# FAILED ...test_ping_opens_a_receiver_on_its_own_client_with_no_retries / 1 failed, 16 passed
sed -i 's/self._pending = {str(m.lock_token): m for m in received}/self._pending.update({str(m.lock_token): m for m in received})/' cloud/queue.py
docker compose run --rm test pytest -q --no-cov jobs/tests/test_azure_queue.py 2>&1 | grep -E "^FAILED|passed|failed"
git checkout cloud/queue.py && git status --short cloud/queue.py
# FAILED ...test_a_new_receive_forgets_old_lock_tokens / 1 failed, 16 passed; then empty (restored)

# 4. Stability of the threaded tests
for i in 1 2 3; do docker compose run --rm test pytest -q --no-cov jobs/tests/test_azure_queue.py 2>&1 | tail -n 1; done   # 17 passed in ~1.8 s x3
```

### 6.7 Step 4: the same image on AWS and Azure (Phase 6 Done-when)

One image built from a commit, run with `docker run` (no bind mount, gunicorn), four containers that differ only in `CLOUD_PROVIDER`. Set `NET` and `IMG` in the SAME terminal as the commands.

```bash
# 0. Build from a committed state; tag with the commit hash
git status --short                                             # empty
docker compose build api
SHA=$(git rev-parse --short HEAD); IMG=jobboard:$SHA; NET=00-job-board-api_default
docker tag 00-job-board-api-api "$IMG"; echo "image: $IMG $(docker image inspect -f '{{.Id}}' "$IMG" | cut -c1-19)"   # jobboard:557de36 sha256:e2e3fcc124dc
docker image inspect -f '{{json .Config.Cmd}}' "$IMG"          # gunicorn ...
docker compose up -d
docker compose --profile azure up -d servicebus-sql servicebus
T=$(date -u +%Y-%m-%dT%H:%M:%SZ); for i in $(seq 60); do docker compose logs --since "$T" servicebus 2>&1 | grep -qi "successfully up" && { echo "broker ready"; break; }; sleep 2; done

# ⚠ BEFORE starting: no other Azure consumer may be running (names only, never env values)
for c in $(docker ps -q); do docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$c" | grep -qx 'CLOUD_PROVIDER=azure' && docker inspect -f 'azure container: {{.Name}} (up since {{.State.StartedAt}})' "$c"; done
# expected: nothing. Remove strays first (e.g. docker rm -f jb-azure jb-azure-worker)

# 1. Four containers, one image, one env difference
docker rm -f jb6-aws-api jb6-aws-worker jb6-az-api jb6-az-worker 2>/dev/null
docker run -d --name jb6-aws-api    --network $NET --env-file .env -e CLOUD_PROVIDER=aws   -p 127.0.0.1:8106:8006 "$IMG"
docker run -d --name jb6-aws-worker --network $NET --env-file .env -e CLOUD_PROVIDER=aws   "$IMG" python -m worker.run_worker
docker run -d --name jb6-az-api     --network $NET --env-file .env -e CLOUD_PROVIDER=azure -p 127.0.0.1:8117:8006 "$IMG"
docker run -d --name jb6-az-worker  --network $NET --env-file .env -e CLOUD_PROVIDER=azure "$IMG" python -m worker.run_worker
for p in 8106 8117; do for i in $(seq 30); do curl -s -o /dev/null http://localhost:$p/healthz && { echo ":$p up after ${i}s"; break; }; sleep 1; done; done
docker inspect -f '{{.Name}} image={{.Image}} mounts={{len .Mounts}}' jb6-aws-api jb6-aws-worker jb6-az-api jb6-az-worker | cut -c1-60   # mounts=0 x4
docker inspect -f '{{.Image}}' jb6-aws-api jb6-aws-worker jb6-az-api jb6-az-worker | sort -u | wc -l                                    # 1
diff <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' jb6-aws-api | sort) \
     <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' jb6-az-api | sort)
# 15c15 / < CLOUD_PROVIDER=aws / --- / > CLOUD_PROVIDER=azure   (only differing lines print: secrets are identical, never shown)
docker logs jb6-aws-worker 2>&1 | grep -o '"message": "Worker started[^"]*"'    # ...localstack.cloud:4566/000000000000/job-board-status
docker logs jb6-az-worker 2>&1 | grep -o '"message": "Worker started[^"]*"'     # sb://servicebus/job-board-status

# 2. The whole path per cloud
source scripts/dev-helper.sh; login_all
prove() {
  local cloud=$1 port=$2 base=http://localhost:$2/api u="p6-$1-$(date +%s)"
  echo "== $cloud on :$port"
  curl -s http://localhost:$port/readyz | python3 -c "import sys, json; d = json.load(sys.stdin); print('readyz', d['status'], {k: v['status'] for k, v in d['checks'].items()})"
  curl -s -o /dev/null -w "register %{http_code}\n" -X POST $base/auth/register/candidate/ -H "$J" -d "{\"username\": \"$u\", \"email\": \"$u@example.test\", \"password\": \"s3cure-pass-2026\", \"skills\": [\"aws\"]}"
  local tok=$(curl -s -X POST $base/auth/token/ -H "$J" -d "{\"username\": \"$u\", \"password\": \"s3cure-pass-2026\"}" | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])")
  local job=$(curl -s $base/jobs/ -H "Authorization: Bearer $tok" | python3 -c "import sys, json; print(json.load(sys.stdin)['results'][0]['id'])")
  printf '%%PDF-1.4\nphase6 %s\n%%%%EOF\n' "$cloud" > /tmp/p6-$cloud.pdf
  local app=$(curl -s -X POST $base/applications/ -H "Authorization: Bearer $tok" -F job=$job -F cover_letter=hi -F "resume=@/tmp/p6-$cloud.pdf;type=application/pdf" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
  echo "applied: application $app to job $job"
  local url=$(curl -s $base/applications/$app/resume/ -H "Authorization: Bearer $tok" | python3 -c "import sys, json; print(json.load(sys.stdin)['url'])")
  echo "link: $(echo "$url" | cut -d/ -f1-3)/..."
  rm -f /tmp/p6-$cloud-dl.pdf; curl -s -o /tmp/p6-$cloud-dl.pdf -w "download %{http_code}\n" "$url"
  cmp -s /tmp/p6-$cloud.pdf /tmp/p6-$cloud-dl.pdf && echo "same bytes: yes" || echo "same bytes: NO"
  local old=$(curl -s $base/applications/3/ -H "Authorization: Bearer $ACME" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  local new=$([ "$old" = "interview" ] && echo reviewing || echo interview)
  curl -s -o /dev/null -w "status $old -> $new: %{http_code} in %{time_total}s\n" -X PATCH $base/applications/3/status/ -H "$J" -H "Authorization: Bearer $ACME" -d "{\"status\": \"$new\"}"
}
{ prove aws 8106; prove azure 8117
  for w in jb6-aws-worker jb6-az-worker; do for i in $(seq 30); do docker logs $w 2>&1 | grep -q '"message": "Emailed' && { echo "$w emailed after ~$((i*2))s"; break; }; sleep 2; done; done
  docker logs jb6-aws-worker 2>&1 | grep -o '"message": "Emailed[^"]*"' | tail -n 1
  docker logs jb6-az-worker 2>&1 | grep -o '"message": "Emailed[^"]*"' | tail -n 1
} 2>&1 | tee /tmp/step4.txt
# per cloud: readyz ready (all ok) / register 201 / applied / link :4566 vs :10000 / download 200 / same bytes: yes / status 200 / Emailed

# 3. Clean up
docker rm -f jb6-aws-api jb6-aws-worker jb6-az-api jb6-az-worker
docker compose --profile azure stop servicebus servicebus-sql

# Diagnosing a SILENT consumer: (A) where did the message go? (B) what is the worker doing? (C) who else is listening?
docker compose exec -T api python -c "
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue
CS = 'Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;'
with ServiceBusClient.from_connection_string(CS) as c:
    for label, sub in (('main', None), ('dead-letter', ServiceBusSubQueue.DEAD_LETTER)):
        with c.get_queue_receiver('job-board-status', sub_queue=sub) as r:
            msgs = r.peek_messages(max_message_count=20)
            print('QUEUE', label, len(msgs), [(m.message_id, m.delivery_count) for m in msgs])
" 2>&1 | grep "^QUEUE"
docker run -d --name jb6-az-worker-dbg --network $NET --env-file .env -e CLOUD_PROVIDER=azure "$IMG" \
  python -c "import faulthandler, runpy, sys; faulthandler.dump_traceback_later(30, repeat=True, file=sys.stderr); runpy.run_module('worker.run_worker', run_name='__main__')"
sleep 45; docker logs jb6-az-worker-dbg 2>&1 | grep -A25 "^Thread .*most recent call first" | grep -E "Thread|File" | head -n 30
# (C) = the "azure container:" loop above

# gunicorn control socket (gunicorn 26): read the source, then verify it's disabled
docker run --rm --entrypoint sed 00-job-board-api-api -n '3229,3246p' /opt/venv/lib/python3.12/site-packages/gunicorn/config.py   # $XDG_RUNTIME_DIR or $HOME/.gunicorn/gunicorn.ctl
docker run --rm --entrypoint grep 00-job-board-api-api -n "control_socket_disable" gunicorn.conf.py                               # 40:control_socket_disable = True
docker run --rm --entrypoint gunicorn 00-job-board-api-api --config gunicorn.conf.py --print-config config.wsgi:application 2>/dev/null | grep -i "control_socket"
docker rm -f jb6-check 2>/dev/null
docker run -d --name jb6-check --network 00-job-board-api_default --env-file .env -p 127.0.0.1:8106:8006 00-job-board-api-api >/dev/null
for i in $(seq 30); do curl -s -o /dev/null http://localhost:8106/healthz && break; sleep 1; done
echo "control server errors: $(docker logs jb6-check 2>&1 | grep -c 'Control server')"            # 0
docker rm -f jb6-check
```

---

## 7. Setup, build and migration commands (in the order they were run)

Not checks, but the commands that changed the project. Re-running some of them on an existing project fails or destroys data (marked ⚠).

### Phase 1, Step 1 — project and stack
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # install uv (not the snap)
source ~/.bashrc
uv --version

mkdir 00-job-board-api && cd 00-job-board-api          # ⚠ once
git init
uv init --bare --name job-board-api --python 3.12
uv python pin 3.12
uv add "django>=5.2,<5.3" djangorestframework "psycopg[binary]"
uv run django-admin startproject config .
ls -a; cat .python-version; cat pyproject.toml

cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"   # paste into DJANGO_SECRET_KEY in .env

docker compose build
docker compose up -d
docker compose exec api python manage.py migrate

# Fix: PYTHONBUFFERED → PYTHONUNBUFFERED, then rebuild
sed -i 's/PYTHONBUFFERED=1/PYTHONUNBUFFERED=1/' Dockerfile
docker compose up -d --build

cat Dockerfile docker-compose.yml                       # inspect final files
```

### Phase 1, Step 2 — custom User needs a fresh DB
```bash
docker compose exec api python manage.py startapp jobs  # ⚠ once
docker compose down -v                                  # ⚠ DELETES the whole database volume
docker compose up -d
docker compose exec api python manage.py makemigrations jobs
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

After each model change in Parts B and C (and every later model change):
```bash
docker compose exec api python manage.py makemigrations jobs
docker compose exec api python manage.py migrate
```

### Phase 1, Step 3 — JWT
```bash
uv add djangorestframework-simplejwt
docker compose up -d --build                            # new dependency → rebuild
```

### Phase 2, Step 3 — S3 / LocalStack
```bash
uv add "django-storages[s3]"
mkdir -p localstack/init/ready.d
chmod +x localstack/init/ready.d/create-bucket.sh
docker compose up -d --build
docker compose ps
docker compose logs localstack                         # if LocalStack won't become healthy (token problems show here)

# Pin the image after reading the version, then:
docker compose up -d

# Resume field migration (0005)
docker compose exec api python manage.py makemigrations jobs
docker compose exec api python manage.py migrate

# After changing .env (env vars aren't reloaded by runserver; also clears the lru_cache'd S3 client)
docker compose up -d --force-recreate api
```

### Phase 2, Step 4 — filters
```bash
uv add django-filter
docker compose up -d --build
```

### Phase 3, Step 1 — Redis cache
```bash
uv add redis                    # redis-py, used by Django's built-in RedisCache
# add the redis service + depends_on in docker-compose.yml, REDIS_URL in .env, CACHES in settings
docker compose up -d --build
docker compose ps               # redis (healthy)

# Part B — after adding ready() to jobs/apps.py (read only at startup)
docker compose restart api
```

### Phase 3, Step 2 — SQS queues
```bash
mkdir -p cloud && touch cloud/__init__.py
chmod +x localstack/init/ready.d/create-queues.sh
# SERVICES=s3,sqs + SQS_QUEUE_NAME + extended healthcheck in docker-compose.yml; AWS_REGION, AWS_SQS_ENDPOINT_URL, SQS_QUEUE_NAME in .env
docker compose up -d --force-recreate localstack api

# Part B — worker
mkdir -p worker && touch worker/__init__.py
docker compose up -d --build worker
```

### Phase 3, Step 3 — emails
```bash
mkdir -p jobs/templates/emails            # status_changed.txt goes here
# EMAIL_BACKEND + DEFAULT_FROM_EMAIL in settings and .env.example
docker compose restart worker

# Add qdepth to the helper file permanently (quoted 'EOF' writes the text literally; >> appends)
grep -c "qdepth()" scripts/dev-helper.sh          # 0 = not there yet
grep -n "qdepth" scripts/dev-helper.sh            # if the count was 1: show the existing (maybe broken) line instead of appending
cat >> scripts/dev-helper.sh <<'EOF'

# SQS queue depth: messages waiting / in flight. Usage: qdepth job-board-status
qdepth() { docker compose exec -T localstack sh -c "awslocal sqs get-queue-attributes --queue-url \"\$(awslocal sqs get-queue-url --queue-name $1 --query QueueUrl --output text)\" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes" 2>/dev/null | grep -v WARNING | tr -d '\n '; echo; }
EOF
source scripts/dev-helper.sh
type qdepth | head -n 1                           # qdepth is a function
```

### Phase 3, Step 4 — idempotency
```bash
docker compose exec api python manage.py makemigrations jobs      # 0006_processedevent
docker compose exec api python manage.py migrate
docker compose restart worker
```

### Phase 4, Step 1 — health endpoints, timeouts, restart policy
```bash
# cloud/health.py + 2 routes in config/urls.py; Redis socket timeouts in settings; ping + 2 clients in cloud/queue.py
# runserver reloads the api on save; the worker does NOT reload:
docker compose restart worker
# restart: unless-stopped added to api and worker in docker-compose.yml. Only applied on (re)create:
docker compose up -d
docker inspect -f '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}' $(docker compose ps -aq api worker)

# Add r() to the helper file permanently (quoted 'EOF' writes the text literally)
grep -c "^r()" scripts/dev-helper.sh              # 0 = not there yet
cat >> scripts/dev-helper.sh <<'EOF'

# Readiness check: status, time, curl exit code, JSON. Usage: r
r() { rm -f /tmp/ready.json; timeout 30 curl -s -o /tmp/ready.json -w "HTTP %{http_code} in %{time_total}s\n" http://localhost:8006/readyz; echo "curl exit=$?"; [ -s /tmp/ready.json ] && python3 -m json.tool /tmp/ready.json; }
EOF
source scripts/dev-helper.sh
type r | head -n 1                                # r is a function
```

### Phase 4, Step 2 — django-prometheus
```bash
uv add "django-prometheus>=2.5"                   # 2.5.0 = first release supporting Django 5.2
# settings.py: "django_prometheus" at the end of INSTALLED_APPS;
#   PrometheusBeforeMiddleware FIRST and PrometheusAfterMiddleware LAST in MIDDLEWARE;
#   ENGINE = "django_prometheus.db.backends.postgresql"
# urls.py: path("", include("django_prometheus.urls"))   → /metrics
docker compose up -d --build                      # new dependency → rebuild (api and worker)
waitapi                                           # don't test before this prints "api up"
docker compose exec api python manage.py makemigrations --check --dry-run   # No changes detected

# Add waitapi() and m() to the helper file permanently
grep -c "^waitapi()\|^m()" scripts/dev-helper.sh  # 0 = not there yet
cat >> scripts/dev-helper.sh <<'EOF'

# Wait until the API really answers (after up -d / restart / rebuild). Usage: waitapi
waitapi() { for i in $(seq 30); do curl -s -o /dev/null http://localhost:8006/healthz && { echo "api up after ${i}s"; return 0; }; sleep 1; done; echo "api NOT up after 30s: docker compose logs --tail=30 api"; return 1; }

# Grep the Prometheus metrics. Usage: m 'view="job-list"'
m() { curl -s http://localhost:8006/metrics | grep "$1"; }
EOF
source scripts/dev-helper.sh
type waitapi m | grep "is a function"             # both listed
```

### Phase 4, Step 3 — JSON logs
```bash
uv add "python-json-logger>=3.1"                  # 3.1+ = pythonjsonlogger.json / pythonjsonlogger.core
# settings.py: LOG_LEVEL = env("LOG_LEVEL", "INFO").upper(); LOGGING dict (json formatter, stdout handler, root,
#   django / django.server / botocore / urllib3); from pythonjsonlogger.core import RESERVED_ATTRS (reserved_attrs + "request")
# .env.example: LOG_LEVEL=INFO
grep -n "basicConfig" worker/run_worker.py        # delete the whole logging.basicConfig(...) call
docker compose up -d --build                      # new dependency → rebuild
source scripts/dev-helper.sh; waitapi
# Part B: extra={...} on the log calls in jobs/events.py and worker/run_worker.py
docker compose exec worker python -c "import ast; ast.parse(open('worker/run_worker.py').read()); print('syntax ok')"
docker compose restart worker                     # the worker doesn't auto-reload (takes ~20 s: finishes the long poll)
```

### Phase 4, Step 4 — config from env, secrets isolated
```bash
# Backups (outside the repo)
cp config/settings.py /tmp/settings.py.bak
cp docker-compose.yml /tmp/docker-compose.yml.bak
cp .env /tmp/env.bak && chmod 600 /tmp/env.bak

# settings.py: drop the generated header + old commented SECRET_KEY (keep from the first "import os")
python3 - <<'EOF'
p = "config/settings.py"
s = open(p).read()
i = s.index("\nimport os\n") + 1
open(p, "w").write(s[i:])
EOF
# settings.py (by hand): env() with empty = missing, env_bool, env_list; DEBUG/ALLOWED_HOSTS via helpers;
#   AWS_REGION required and moved up; AWS_S3_REGION_NAME = AWS_REGION; "HOST": env("POSTGRES_HOST")

# .env edits without printing it
sed -i '/^AWS_S3_REGION=/d' .env
sed -i 's/^AWS_REGION=.*/AWS_REGION=us-east-1/' .env
sed -i 's/^POSTGRES_HOST=.*/POSTGRES_HOST=db/' .env
sed -i 's/^DJANGO_ALLOWED_HOSTS=.*/DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,10.0.0.149/' .env   # 10.0.0.149 = thor's LAN IP (MacBook)
hostname; hostname -I | tr ' ' '\n' | grep -v ":" | head -n 3     # find the name/IP other machines use

# .env backup inside the repo (ignored by git via .env.*). ⚠ Holds secrets: delete it when done (section 9)
cp .env .env.bak

# docker-compose.yml (by hand): delete "environment: - POSTGRES_HOST=db" from api and worker

# Rotate the secret key safely (URL-safe characters only: no & or $ for sed/Compose to misread)
NEW=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$NEW|" .env; unset NEW
grep -c '^DJANGO_SECRET_KEY=[A-Za-z0-9_-]\{60,\}$' .env          # 1
# ⚠ Don't use get_random_secret_key() with sed: it can contain & and $.

# LocalStack token → its own file, only for the localstack service
[ -f .env.localstack ] || grep "^LOCALSTACK_AUTH_TOKEN=" .env > .env.localstack
sed -i '/^LOCALSTACK_AUTH_TOKEN=/d' .env
chmod 600 .env .env.localstack
python3 - <<'EOF'
p = "docker-compose.yml"
lines = open(p).read().split("\n")
out, in_ls = [], False
for line in lines:
    if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
        in_ls = line.strip() == "localstack:"
    if in_ls and "LOCALSTACK_AUTH_TOKEN=" in line:
        continue
    if in_ls and line == "    environment:":
        out.append("    env_file: .env.localstack")
    out.append(line)
open(p, "w").write("\n".join(out))
EOF
sed -i 's|AWS_STORAGE_BUCKET_NAME=${AWS_STORAGE_BUCKET_NAME}$|AWS_STORAGE_BUCKET_NAME=${AWS_STORAGE_BUCKET_NAME:?set AWS_STORAGE_BUCKET_NAME in .env}|' docker-compose.yml
docker compose config --quiet && echo "compose file OK"

# Templates
sed -i '/^# LocalStack (still here/d; /^LOCALSTACK_AUTH_TOKEN=/d' .env.example
printf 'LOCALSTACK_AUTH_TOKEN=change-me\n' > .env.localstack.example
grep -q '^!.env.localstack.example' .gitignore || echo '!.env.localstack.example' >> .gitignore

# r() permanently in the helper file (guarded: no duplicate)
grep -q "^r()" scripts/dev-helper.sh || cat >> scripts/dev-helper.sh <<'EOF'

# Readiness check: status, time, curl exit code, JSON. Usage: r
r() { rm -f /tmp/ready.json; timeout 30 curl -s -o /tmp/ready.json -w "HTTP %{http_code} in %{time_total}s\n" http://localhost:8006/readyz; echo "curl exit=$?"; [ -s /tmp/ready.json ] && python3 -m json.tool /tmp/ready.json; }
EOF

docker compose up -d --force-recreate            # applies .env, .env.localstack and compose changes (empties S3)
docker compose build api worker                  # the image must contain the code too (Part C)
docker compose up -d
```

### Phase 4, Step 5 — production image
```bash
uv add gunicorn                                   # locked 26.2.0
# new: gunicorn.conf.py (bind, gthread, 1 worker × 4 threads, timeouts, JSON logconfig_dict)
# Dockerfile: replaced with builder + runtime stages, USER app, exec-form CMD gunicorn
# docker-compose.yml, api service: command: ["python", "manage.py", "runserver", "0.0.0.0:8006"]
docker tag 00-job-board-api-api jobboard:before-step5    # keep the old image for the size comparison
docker compose up -d --build
source scripts/dev-helper.sh; waitapi
docker image rm jobboard:before-step5            # once the size is recorded (optional)
```

### Phase 5, Step 1, Part A — test tooling
```bash
uv add --dev pytest pytest-django pytest-cov      # locked: pytest 9.2.0, pytest-django 4.14.0, pytest-cov 7.1.0
# pyproject.toml: [tool.pytest.ini_options] (DJANGO_SETTINGS_MODULE, python_files, addopts --cov --cov-report=term-missing)
#                 [tool.coverage.run] (source = jobs, cloud, worker, config; omit migrations, tests, asgi, wsgi)
# Dockerfile: builder → builder-test (+dev) → base → test → runtime (runtime last = default target)
# docker-compose.yml: api and worker build target runtime; new "test" service (profile test, env_file .env, bind mount, depends on db)
# jobs/tests/__init__.py (empty) + jobs/tests/test_smoke.py
for p in .coverage htmlcov/ .pytest_cache/; do grep -qxF "$p" .gitignore || echo "$p" >> .gitignore; done
docker compose build test
docker compose run --rm test
```

### Phase 5, Step 1, Part B — unit tests
```bash
sed -i 's/extentsion/extension/g' jobs/models.py
# new: jobs/tests/conftest.py, test_matching.py, test_validators.py, test_models.py
docker compose run --rm test                      # no rebuild needed: the code is bind-mounted
```

### Phase 5, Step 1, Part C — permission tests
```bash
# new: jobs/tests/test_permissions.py; conftest.py: autouse local_cache + fast_password_hashing
docker compose run --rm test
```

### Phase 5, Step 1, Part D — API tests
```bash
sed -i 's/def validate_email(delf, value):/def validate_email(self, value):/' jobs/serializers.py
# new: test_api_auth.py, test_api_jobs.py, test_api_applications.py; conftest.py: api_as fixture, make_job(location=...)
docker compose run --rm test
```

### Phase 5, Step 1, Part E — moto
```bash
uv add --dev "moto[s3,sqs]"
# conftest.py: aws fixture; new: test_aws_storage.py, test_aws_queue.py
docker compose build test                         # new dependency → rebuild the test image
docker compose run --rm test
```

### Phase 5, Step 1, Part F — worker, emails, cache, health
```bash
# new: test_emails.py, test_worker.py, test_cache.py, test_health.py (patch caches["default"], not the cache proxy)
docker compose run --rm test
```

### Phase 5, Step 1, Part G — coverage gate
```bash
# views.py: delete the two raise PermissionDenied blocks + the import; pyproject.toml: --cov-fail-under=80 + [tool.coverage.report] exclude_also
# new: config/tests/__init__.py, config/tests/test_settings.py; appended tests in test_api_jobs.py and test_permissions.py
docker compose run --rm test > /tmp/pytest.out 2>&1; echo "exit code: $?"; tail -n 4 /tmp/pytest.out
```

### Phase 5, Step 2 — drf-spectacular
```bash
uv add "drf-spectacular>=0.30"
# settings.py: "drf_spectacular" in INSTALLED_APPS; REST_FRAMEWORK DEFAULT_SCHEMA_CLASS; SPECTACULAR_SETTINGS
# urls.py: api/schema/ and api/schema/swagger-ui/ (before api/)
docker compose build api worker test
docker compose up -d
# Part B: serializers.py (RegisteredUserSerializer, ResumeLinkSerializer, type hints); views.py (@extend_schema x5); jobs/tests/test_schema.py
```

### Phase 6, Step 1 — Azure Blob storage
```bash
uv add "django-storages[azure,s3]"               # BOTH extras: [azure] alone could drop s3 (boto3)
# docker-compose.yml: azurite service (azurite-blob, --blobHost 0.0.0.0, --skipApiVersionCheck, 127.0.0.1:10000), pinned 3.37.0
# settings.py: CLOUD_PROVIDER (validated); S3 settings in "if aws", AZURE_* in "else"; STORAGES default = DEFAULT_STORAGE_BACKEND
# jobs/storage.py: resume_download_url → _s3_download_url / _azure_download_url (SAS)
cat >> .env.example <<'EOF'

# Cloud provider: aws (default) or azure
CLOUD_PROVIDER=aws

# Azure Storage (used when CLOUD_PROVIDER=azure). Azurite's well-known development account,
# published by Microsoft, not a secret. On real Azure: your account, key from a secret store, no endpoint URLs.
AZURE_ACCOUNT_NAME=devstoreaccount1
AZURE_ACCOUNT_KEY=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==
AZURE_CONTAINER=resumes
AZURE_BLOB_ENDPOINT=http://azurite:10000/devstoreaccount1
AZURE_PUBLIC_BLOB_ENDPOINT=http://localhost:10000/devstoreaccount1
EOF
grep -q "^CLOUD_PROVIDER=" .env || sed -n '/^# Cloud provider/,$p' .env.example >> .env
docker compose build api worker test
docker compose up -d
```

### Phase 6, Step 2, Part A — Service Bus emulator
```bash
uv add "azure-servicebus>=7.12"
mkdir -p servicebus                                   # servicebus/Config.json: namespace sbemulatorns, queue job-board-status (LockDuration PT30S, MaxDeliveryCount 3)
# ⚠ ACCEPT_EULA=Y = you accept the Service Bus emulator and SQL Server Developer licenses (dev/test only)
printf 'ACCEPT_EULA=Y\nMSSQL_SA_PASSWORD=%s\n' "Sb1-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > .env.servicebus
chmod 600 .env.servicebus
printf 'ACCEPT_EULA=N\nMSSQL_SA_PASSWORD=change-me-Str0ng\n' > .env.servicebus.example
grep -q '^!.env.servicebus.example' .gitignore || echo '!.env.servicebus.example' >> .gitignore
# docker-compose.yml: servicebus-sql (mssql/server, MSSQL_MEMORY_LIMIT_MB 2048) + servicebus (emulator, SQL_SERVER, Config.json :ro,
#   restart unless-stopped), both profiles: ["azure"], env_file .env.servicebus, no ports
sed -i "s|servicebus-emulator:<SB_TAG>|servicebus-emulator:$SB_TAG|; s|mssql/server:<SQL_TAG>|mssql/server:$SQL_TAG|" docker-compose.yml   # after the tag lookup in 6.2
docker compose build api worker test
docker compose --profile azure up -d
```

### Phase 6, Step 2, Part B — `ServiceBusQueue`
```bash
uv add "azure-servicebus>=7.15"
# cloud/queue.py: replaced with cat > cloud/queue.py <<'EOF' ... (QUEUE_ERRORS, ServiceBusQueue, get_queue by CLOUD_PROVIDER)
# then ping() replaced by a Python script (thread + 2 s deadline + single-flight lock; open receiver, no peek)
# config/settings.py: AWS_REGION / AWS_SQS_ENDPOINT_URL / SQS_QUEUE_NAME into the aws branch; SERVICE_BUS_* into the azure branch
#   ⚠ fixed by replacing lines 39-92 with one complete block (script with asserts; backup in /tmp/settings.py.bak)
# config/settings.py LOGGING: "azure": {"level": "WARNING"} next to "botocore"
cat >> .env.example <<'EOF'

# Azure Service Bus (used when CLOUD_PROVIDER=azure). The emulator's fixed development key,
# published by Microsoft, not a secret. On real Azure: the connection string comes from Key Vault
# (later replaced by Workload Identity), never from this file.
SERVICE_BUS_CONNECTION_STRING=Endpoint=sb://servicebus;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;
SERVICE_BUS_QUEUE_NAME=job-board-status
EOF
grep -q "^SERVICE_BUS_CONNECTION_STRING=" .env || sed -n '/^# Azure Service Bus/,$p' .env.example >> .env
sed -i 's/^from botocore.exceptions import BotoCoreError, ClientError\(.*\)$/from cloud.queue import QUEUE_ERRORS\1/' jobs/events.py worker/run_worker.py
sed -i 's/except (BotoCoreError, ClientError):/except QUEUE_ERRORS:/' jobs/events.py worker/run_worker.py
docker compose build api worker test
docker compose up -d
docker compose --profile azure up -d servicebus servicebus-sql
```

### Phase 6, Step 2, Part C — bounded publish, duplicate detection
```bash
# servicebus/Config.json: RequiresDuplicateDetection true, DuplicateDetectionHistoryTimeWindow PT5M (emulator max; PT10M crash-loops)
python3 - <<'PY'
import json
p = "servicebus/Config.json"
cfg = json.load(open(p))
props = cfg["UserConfig"]["Namespaces"][0]["Queues"][0]["Properties"]
props["RequiresDuplicateDetection"] = True
props["DuplicateDetectionHistoryTimeWindow"] = "PT5M"
json.dump(cfg, open(p, "w"), indent=2)
open(p, "a").write("\n")
PY
# cloud/queue.py (script with asserts, backup /tmp/queue.py.bak): _send_client (retry_total=1, try_timeout=2);
#   send() = acquire(timeout=1) + daemon thread + join(SEND_SECONDS=3); "may still be delivered"
docker compose --profile azure up -d --force-recreate servicebus     # the emulator reads Config.json only at startup
```

### Phase 6, Step 3, Part A — Azurite storage tests
```bash
# docker-compose.yml: test service depends_on azurite (condition: service_started)
# jobs/tests/conftest.py: azure_blob fixture appended (fresh container per test; settings switched; retry_total=0, connection_timeout=2)
# jobs/tests/test_azure_storage.py: new (5 tests)
# config/tests/test_settings.py: 3 subprocess tests appended (each cloud without the other's variables; missing Azure variable fails)
# fixes applied by script with asserts: .__class__ instead of type(); response.headers instead of dict(); exact 403 + AuthorizationFailure
# pyproject.toml [tool.pytest.ini_options]: filterwarnings = ["ignore:datetime.datetime.utcnow:DeprecationWarning:storages.backends.azure_storage"]
docker compose run --rm test
```

### Phase 6, Step 3, Part B — Service Bus unit tests
```bash
# jobs/tests/test_azure_queue.py: new (17 tests; fake ServiceBusClient patched into cloud.queue)
docker compose run --rm test
```

### Phase 6, Step 4 — same-image proof, gunicorn control socket
```bash
docker rm -f jb-azure jb-azure-worker jb6-az-worker-dbg            # ⚠ stray Azure consumers from Part C (competing consumers)
cat >> gunicorn.conf.py <<'EOF'

# gunicorn 26+ opens a control socket (for the gunicornc tool) in a default folder under $HOME.
# Our "app" user has no home folder, and the process is managed by Docker/Kubernetes signals,
# not gunicornc, so the socket is turned off.
control_socket_disable = True
EOF
docker compose build api
```

---

## 8. Code inspection commands (used while debugging)

```bash
# Phase 1, Step 4
cat jobs/views.py
sed -n '/class ApplicationSerializer/,$p' jobs/serializers.py
grep -n "candidateprofile\|candidate_profile\|This is job" jobs/serializers.py

# Phase 2, Step 1
sed -n '/class JobViewSet/,/class ApplicationViewSet/p' jobs/views.py
sed -n '/def set_status/,/return Response/p' jobs/views.py

# Phase 2, Step 3
cat jobs/validators.py
grep -n -A4 "def resume_upload_path" jobs/models.py
grep -n "resume" jobs/models.py jobs/serializers.py
ls jobs/migrations/
wc -l jobs/storage.py
grep -n "def resume\|\"resume\"\|resume_download_url\|PUBLIC_ENDPOINT\|RESUME_URL" jobs/views.py config/settings.py
grep -n "settings\." jobs/storage.py

# Phase 2, Step 4
sed -n '/skills = /p; /def filter_skills/,/overlap/p' jobs/filters.py
grep -n "ordering" jobs/views.py jobs/models.py
grep -n "ordering = " jobs/views.py

# Phase 3, Step 1
sed -n '/def invalidate_job_list/,$p' jobs/cache.py      # found the missing transaction.on_commit(bump)
docker compose logs api | grep -i -A3 "could not invalidate" | tail -n 20
docker compose exec api python manage.py shell -c "from django.db.models.signals import post_save; from jobs.models import Job; print(post_save.has_listeners(Job))"

# Phase 4, Step 1
grep -n "healthz\|readyz" config/urls.py                               # found the trailing slash (301s)
curl -s -i http://localhost:8006/healthz | grep -i "^location"         # Location: /healthz/ = APPEND_SLASH redirect
cat cloud/health.py                                                    # found the return inside the for loop
grep -n "def ping" cloud/queue.py
sed -n '/class SQSQueue/,/def send/p' cloud/queue.py                   # clients, timeouts, lazy url
sed -n '/^def main/,/Worker stopped/p' worker/run_worker.py            # receive/delete error handling
grep -n -B1 -A1 "restart:" docker-compose.yml
docker compose ps -a worker                                            # Exited (1) = crashed
docker compose logs --tail=40 worker                                   # EndpointConnectionError traceback
docker compose logs --since 15m api | grep -c "Readiness check"
docker compose exec api python manage.py shell -c "from cloud.queue import get_queue; print(get_queue()._ping_client.meta.config.retries)"

# Phase 4, Step 2
docker compose ps -a api                         # "Up Less than a second" = checks ran too early
docker compose logs --tail=30 api                # "Starting development server" + NO request lines = requests never arrived
grep -n "django_prometheus" config/settings.py config/urls.py
curl -s http://localhost:8006/metrics | grep job-list | head     # exact metric names this version prints

# Phase 4, Step 3
type waitapi m                                                  # "not found" = not in the helper file
grep -n "logger\.\(info\|warning\|error\|exception\)" jobs/*.py cloud/*.py worker/run_worker.py   # every log call
sed -n '20,40p' jobs/events.py                                   # publish log calls
sed -n '80,115p' worker/run_worker.py                            # handle_status_changed log calls
sed -n '/for message in messages/,/redelivered/p' worker/run_worker.py
docker compose logs --since 15m worker | head -n 20             # what the non-JSON lines are

# Phase 4, Step 4
grep -n "ALLOWED_HOSTS" .env config/settings.py docker-compose.yml     # where a value really comes from (hosts aren't secret)
grep -c "^LOCALSTACK_AUTH_TOKEN=" .env                                 # 1 = token still in the shared file
ls -l .env.localstack .env.localstack.example 2>&1
grep -n "env_file\|LOCALSTACK_AUTH_TOKEN" docker-compose.yml
grep -n "django-insecure\|^\"\"\"\|^import os" config/settings.py
docker run --rm 00-job-board-api-api grep -c "def env_list" config/settings.py   # does the IMAGE have the new code?

# Phase 4, Step 5
docker top jb-prod -o pid,user,args                     # process tree; USER = host's name for the uid
docker inspect -f '{{len .Mounts}} mounts, user={{.Config.User}}' jb-prod
docker run --rm 00-job-board-api-api id                 # the uid INSIDE the container

# Phase 5, Step 1
grep -c extentsion jobs/models.py                       # 0 after the typo fix
```

---

## 9. One-off fixes and data cleanup ⚠

```bash
# Phase 1, Step 4 — typos fixed with sed
sed -i 's/"candidateprofile"/"candidate_profile"/; s/This is job is/This job is/' jobs/serializers.py

# Phase 1, Step 4 — delete the application bug 1 let through (only if its job is closed)
docker compose exec api python manage.py shell -c "from jobs.models import Application; print(Application.objects.filter(id=5, job__is_open=False).delete())"

# Phase 2, Step 1 — delete Globex's job created while get_permission was misspelled
docker compose exec api python manage.py shell -c "from jobs.models import Job; print(Job.objects.filter(id=5, company__name='Globex').delete())"

# Phase 2, Step 1 — verify Acme (it never had been)
docker compose exec api python manage.py shell -c "from jobs.models import Company; print(Company.objects.filter(name='Acme').update(is_verified=True))"

# Phase 2, Step 3 — wrong setting name in storage.py
sed -i 's/settings.AWS_S3_PRESIGNED_URL_EXPIRATION/settings.RESUME_URL_EXPIRE_SECONDS/' jobs/storage.py

# Phase 2, Step 4 — default ordering missing its minus sign
sed -i 's/    ordering = \["created_at"\]/    ordering = ["-created_at"]/' jobs/views.py
```

```bash
# Phase 4, Step 4 — remove backups that contain the OLD secret key and the LocalStack token
rm -f .env.bak /tmp/env.bak
ls -a | grep -i "\.env"            # .env  .env.example  .env.localstack  .env.localstack.example
# The other Step 4 backups hold no secrets; remove them once the step works:
rm -f /tmp/settings.py.bak /tmp/docker-compose.yml.bak
```

Each delete has an extra filter (`job__is_open=False`, `company__name='Globex'`) so it can only remove the row it's meant to.

---

## 10. Git checks used between steps

```bash
git status --short          # .env never listed; migrations ARE listed and committed
git status --short | grep -E "\.env($|\.localstack$|\.servicebus$|\.bak$)" && echo "STOP: secret file staged" || echo "no secret files staged"   # since Phase 4, Step 4
git add .
git commit -m "..."
git push
git pull                    # before starting work: docs/ is edited on GitHub too
```

End of a phase:
```bash
# Phase 1
git add README.md
git commit -m "Add Phase 1 README"
git tag phase1

# Phase 2 (copy the commands file into the repo first, the README points to docs/)
cp ~/Downloads/job-board-api-terminal-checks.md docs/      # adjust the path to where you saved it
git add README.md docs/
git commit -m "Update README for Phase 2"
git tag phase2
git push --tags             # tags aren't pushed by a plain git push

# Phase 3
cp ~/Downloads/job-board-api-terminal-checks.md docs/      # refresh the commands file in the repo
git add README.md docs/
git commit -m "Update README for Phase 3"
git tag phase3
git push && git push --tags

# Phase 4
cp ~/Downloads/job-board-api-terminal-checks.md docs/      # refresh the commands file in the repo
cp ~/Downloads/README.md .                                   # Phase 4 README
git status --short | grep -E "\.env($|\.localstack$|\.servicebus$|\.bak$)" && echo "STOP: secret file staged" || echo "no secret files staged"
git add README.md docs/
git commit -m "Update README for Phase 4"
git tag phase4
git push && git push --tags

# Phase 5 (files are downloaded on the MacBook: copy them to thor FROM THE MACBOOK)
#   scp ~/Downloads/job-board-api-terminal-checks.md reza@10.0.0.149:~/projects/00-job-board-api/docs/
#   scp ~/Downloads/README.md reza@10.0.0.149:~/projects/00-job-board-api/README.md
git tag -l 'phase*'                                  # phase1 ... phase4 should already exist
git status --short                                   # only README.md / docs/ expected now
git status --short | grep -E "\.env($|\.localstack$|\.servicebus$|\.bak$)" && echo "STOP: secret file staged" || echo "no secret files staged"
git add README.md docs/
git commit -m "Update README and terminal checks for Phase 5"
git tag phase5
git push && git push --tags
git tag -l 'phase*'                                  # phase1 ... phase5
git log --oneline -1 phase5                          # the commit the tag points at

# Phase 6 (copy README + terminal checks from the MacBook FIRST, run ON THE MACBOOK)
#   scp ~/Downloads/job-board-api-terminal-checks.md reza@10.0.0.149:~/projects/00-job-board-api/docs/
#   scp ~/Downloads/README.md reza@10.0.0.149:~/projects/00-job-board-api/README.md
git status --short                                   # only README.md / docs/ expected now
git status --short | grep -E "\.env($|\.localstack$|\.servicebus$|\.bak$)" && echo "STOP: secret file staged" || echo "no secret files staged"
git add README.md docs/
git commit -m "Update README and terminal checks for Phase 6"
git tag phase6
git push && git push --tags
git tag -l 'phase*'                                  # phase1 ... phase6
```

Commit messages used, step by step:
```bash
# Phase 1
git commit -m "Scaffold Django project with uv (Python 3.12, Django 5.2, DRF, psycopg)"
git commit -m "Read Django settings from env vars; switch DB to PostgreSQL; add DRF"
git commit -m "Add dev Dockerfile and Compose stack (PostgreSQL 17, port 8006)"
git commit -m "Add custom User model with company/candidate roles; reset DB"
git commit -m "Add Company and CandidateProfile models with admin"
git commit -m "Add Job and Application models with unique-application constraint"
git commit -m "Add JWT auth (SimpleJWT): token and refresh endpoints, IsAuthenticated by default"
git commit -m "Add company and candidate registration endpoints (atomic user + profile create)"
git commit -m "Add job endpoints: list open, detail, create (company only), update; pagination"
git commit -m "Add application endpoints: apply, detail, job applicants; fix validator scope and typos"

# Phase 2
git commit -m "Add IsVerifiedCompany and IsCandidate permissions; replace inline role checks"
git commit -m "Add IsJobOwner and IsApplicationOwner object permissions; add dev helper script"
git commit -m "Add status endpoint (job owner only); IsJobOwner handles applications; require status field"
git commit -m "Add skill match score (matching.py) to application responses"
git commit -m "Add LocalStack S3 and django-storages; resumes storage backend"
git commit -m "Add resume upload with type, signature and 5 MB checks, stored in S3"
git commit -m "Add presigned resume downloads; hide resume links from responses; validate S3 signatures locally"
git commit -m "Add job search, filters (type, location, skills) and ordering; normalise job skills on save"

# Phase 3
git commit -m "Cache job list in Redis with versioned keys, signal invalidation on commit, graceful fallback"
git commit -m "Add SQS queue + DLQ in LocalStack and cloud.queue interface"
git commit -m "Publish status changes to SQS on commit; add worker service with graceful shutdown and DLQ"
git commit -m "Worker sends status-change emails (console backend); skip deleted applications"
git commit -m "Idempotent worker: claim event_id in ProcessedEvent within the send transaction"

# Phase 4
git commit -m "Add /healthz and /readyz with bounded dependency checks; resilient worker; restart policy"
git commit -m "Add /metrics via django-prometheus (request, latency and DB metrics)"
git commit -m "Structured JSON logs to stdout (python-json-logger), LOG_LEVEL from env, event_id/application_id fields"
git commit -m "All config from env: required/empty fail fast, typed helpers, safe defaults, one AWS_REGION; LocalStack token isolated"
git commit -m "Multi-stage Dockerfile, non-root user, gunicorn (gthread, JSON logs); Compose keeps runserver for dev"

# Phase 5
git commit -m "Add pytest, pytest-django, pytest-cov; test image stage and compose test service; smoke tests"
git commit -m "Unit tests: match score, resume validator, models; factory fixtures"
git commit -m "Permission tests: 4 classes + who-can-do-what matrix; per-test LocMem cache; fast hasher in tests"
git commit -m "API tests: registration, JWT flow, job validation/filters/ordering/pagination, application validation and status"
git commit -m "S3 and SQS tests with moto: upload, privacy, presigned URL, publish on commit only, queue round trip"
git commit -m "Worker, email, cache and readiness tests; one-pass worker loop with a fake queue"
git commit -m "Coverage gate at 80% (100% reached); remove unreachable role checks; settings, OPTIONS and empty-filter tests"
git commit -m "Add OpenAPI schema and Swagger UI (drf-spectacular)"
git commit -m "Make the OpenAPI schema match the code: extend_schema on 4 operations, typed method fields, schema tests"
git commit -m "Update README for Phase 5"

# Phase 6
git commit -m "Storage switches between S3 and Azure Blob by CLOUD_PROVIDER; Azurite in Compose; SAS download links"
git commit -m "Add Service Bus emulator + SQL Server in Compose (profile azure); queue mirrors SQS lock and redrive settings"
git commit -m "Queue switches between SQS and Service Bus by CLOUD_PROVIDER; QUEUE_ERRORS; per-cloud settings; bounded Service Bus ping"
git commit -m "Bound Service Bus publish (send client, 3 s deadline); duplicate detection on the queue (PT5M)"
git commit -m "Azure storage tests against Azurite (upload, privacy, SAS download, tampered link); per-cloud settings tests"
git commit -m "ServiceBusQueue unit tests with fake SDK objects: send/receive/delete, deadlines, single-flight, get_queue"
git commit -m "Disable gunicorn's control socket (no home dir for the app user; process managed by signals)"
```

---

## 11. Shell lessons from running these

- **`source` vs `bash`:** `source file` keeps functions and variables in your shell; `bash file` runs in a child shell and loses them.
- **Quote URLs with `&`**, or bash runs the command in the background.
- **`VAR=value cmd` on one line** sets `VAR` only for `cmd`. Use `;` between commands when pasting one-liners.
- **`curl -s` hides errors.** Add `-i` for the status line, or `-o /dev/null -w "%{http_code}"` for the code only.
- **`JSONDecodeError: Expecting value`** means the body wasn't JSON: usually an HTML 404 or 500 page, or empty output.
- **`2>/dev/null`** hides stderr (e.g. the `awslocal` deprecation banner).
- **`${!who}`** is indirect expansion: the value of the variable whose name is in `who`.
- **`${#VAR}`** is the length of a variable, useful to check a secret is set without printing it.
- **`printf '%%'`** prints a single `%`.
- **A negative test needs its positive twin** on the same input: a 403 means nothing if everything returns 403. Likewise, a log grep returning `0` means nothing if that logger can't print (the API's INFO lines in Phase 3).
- **Ctrl+C during `sleep`** cancels only the sleep; the next commands in the pasted block still run, earlier than planned.
- **`docker compose logs --since 10s`** shows only recent lines; **`grep -c`** counts matches instead of printing them.
- **`--tail=N` must be long enough:** a warning logged with a traceback is followed by many lines, so `--tail=5` can cut it off.
- **`sh -c '...'` inside `docker compose exec`** runs the whole command in the container, so `$VAR` is the container's variable. In a double-quoted string on thor, escape `\$(...)` to run it in the container too.
- **`time <command>`** measures how long a command takes (`real` = wall-clock time).
- **Heredocs:** `<<'EOF'` (quoted) passes text unchanged; `<<EOF` (unquoted) expands `$variables` inside it.
- **`timeout N cmd`** kills `cmd` after N seconds; exit code **124** means it was killed. `$?` is the exit code of the last command.
- **Delete an output file before writing it** in a check. A killed command writes nothing, and the old file looks like a fresh result.
- **`curl -w "%{time_total}"`** prints the full request time: the quickest way to measure a timeout.
- **`docker compose pause` vs `stop`:** paused = frozen (connections hang); stopped = refused (fails fast). Test both.
- **Plain `python -c` inside the api container can't import Django code that reads settings** (`ImproperlyConfigured`). Use `python manage.py shell -c "..."`.
- **`docker compose up -d` returns when the container STARTS, not when the app listens.** Wait on a real endpoint (`waitapi`). `curl` `000` with **exit 56** = the port accepted and then dropped the connection (nothing listening inside yet); exit 7 = connection refused.
- **No request lines in `runserver`'s log = the request never reached Django.** Check that before debugging the code.
- **Know the starting state before testing a change.** A PATCH to the status it already has is a no-op: `200`, but no event and no email.
- **`head -n N` on headers can cut off the one you want.** `grep -i "^content-type"` instead.
- **Order inside a pasted block matters:** a helper used before the `source` line that defines it fails with `command not found`, and the rest of the block still runs.
- **A function typed into the shell disappears with the terminal.** Only what's in `scripts/dev-helper.sh` survives; check with `type name`.
- **"Looks like JSON" isn't a check: parse it.** `python3 -m json.tool` for one line; a small `json.loads` loop for many, printing the lines that fail.
- **`docker compose logs --no-log-prefix`** drops the `api-1  |` prefix, so each line can be parsed as-is.
- **`docker compose exec -e VAR=value`** sets an env var for that one command only: the quickest way to prove a setting really comes from the environment.
- **Never `cat .env`.** Check secrets by name (`cut -d= -f1`), count (`grep -c`) or length (`awk ... length`), never by value.
- **`sed` replacement text treats `&` as "the whole match"**, and Compose interpolates `$` in env files. Generate secrets from a safe alphabet (`secrets.token_urlsafe`).
- **`docker run --env-file` keeps quotes; Compose strips them.** Write `.env` values unquoted.
- **A bind mount hides the image.** Test the real image with `docker run` and no mount; prove its contents with `docker run --rm IMAGE grep ...`.
- **`git check-ignore -q file`** exits 0 if the file is ignored: the quick proof for secret files.
- **`docker compose config --quiet`** validates the compose file (and its `${VAR:?}` checks) without starting anything.
- **`docker compose run --rm SERVICE [cmd]`** starts a one-off container for a service (with its dependencies) and removes it afterwards: the right shape for a test run.
- **Break the code on purpose, run the tests, `git checkout FILE`:** the quickest proof that a test can fail. `git status --short FILE` empty = restored.
- **A `>` prompt means bash is waiting for the rest of a command** (usually an unclosed heredoc or quote). Type the closing `EOF` alone and press Enter, or Ctrl+C and paste again. The one-line `-c "..."` form avoids heredocs entirely.
- **Placeholders like `<version-from-above>` are for you to replace,** not to paste. `docker compose config | grep image:` shows what Compose will really use.
- **`docker compose config` sorts keys alphabetically** — use a wide enough `grep -A` to see `image:` after `command:`.
- **`${VAR%pattern}`** removes the shortest match of `pattern` from the END of `$VAR` (`${URL%sig=*}` cuts off the signature).
- **`scp` runs on the machine that HAS the file.** `scp ~/Downloads/x host:path` on thor looks in thor's Downloads.
- **`${PIPESTATUS[0]}`** is the exit code of the FIRST command in the last pipe (bash), e.g. `cmd | tail; echo ${PIPESTATUS[0]}`.
- **A valid, warning-free generated schema can still be wrong.** Print what it says per operation and compare with the code.
- **`$?` after `cmd | tail` is tail's exit code (always 0).** Redirect to a file first: `cmd > /tmp/out 2>&1; echo $?; tail /tmp/out`.
- **A line of TOML/YAML/Python pasted into bash** gives `command not found`. File content goes into the file (editor, `sed`, or a `cat >> file <<'EOF'` heredoc).
- **`python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`** validates a TOML file after editing it with `sed`.
- **A passing test can still ERROR at teardown.** pytest counts it as passed AND errored, so `N passed, M errors` can overlap.
- **Stop the real dependency and re-run the tests** to prove they use the fake (moto) and not the network.
- **`2>&1 | tail -n N`** keeps only the end of a long run (summary + coverage table), including lines written to stderr.
- **`pytest --durations=N`** lists the N slowest test phases (setup / call / teardown). A slow `setup` points at fixtures.
- **Coverage counts lines that ran, including imports.** A high total with zero real tests is possible; read the `Missing` column.
- **`docker top` shows the HOST's name for a uid.** Use `docker run --rm IMAGE id` (or `docker exec ... id`) to see the user inside the container.
- **`time docker stop NAME`** is a quick signal-handling test: ~10 s means the process ignored `SIGTERM` and got `SIGKILL`.
- **`docker tag IMAGE name:tag`** keeps an old image around under a new name, for before/after comparisons.
- **`ALLOWED_HOSTS` needs the address clients type**, not the bind address `0.0.0.0`.
- **`docker compose restart` doesn't apply compose-file changes** like `restart:`; `docker compose up -d` recreates changed containers.
- **`docker: invalid reference format`** = the image name has characters Docker can't accept, usually an unreplaced `<placeholder>`.
- **Pick the newest version tag by number, not by text:** `max(tags, key=lambda v: tuple(map(int, v.split('.'))))`, so `1.10.0` beats `1.9.0`.
- **Services with `profiles:` start only with `--profile NAME`.** `docker compose up -d` alone leaves them off, but naming them (`logs servicebus`) still works.
- **Pasting command OUTPUT into the shell** runs each line as a command: `command not found` for every line. Harmless, but copy only the commands.
- **A `ports` entry with no host part** in `docker compose ps` (`5672/tcp`, not `127.0.0.1:5672->5672/tcp`) = reachable on the Compose network only.
- **A block meant to REPLACE code, pasted next to it, leaves both running.** Python runs both `if` blocks top to bottom; the later one wins silently. Count the block's first line with `grep -c` after editing.
- **`awk '{...; print}'` rebuilds a line from its fields and loses the indentation.** To see lines with numbers and whitespace intact: `sed -n 'A,Bp' FILE | cat -n` or `grep -n "" FILE | sed -n 'A,Bp'`.
- **Edit a file by script with `assert`s on the boundary lines** (and a backup first): if the file isn't what you saw, nothing changes.
- **`docker compose run --rm --no-deps -e VAR=value SERVICE cmd`** runs the CURRENT code (bind mount) with one env var changed, without touching the running service.
- **`faulthandler.dump_traceback_later(N, exit=True, file=sys.stdout)`** prints every thread's stack after N seconds: the quickest way to see WHERE a process hangs.
- **Measure before tuning a timeout.** Try a few limit combinations and print the time AND the error text, not just the exception class.
- **A test of a frozen service needs the service READY first.** Wait for its "ready" log line `--since` the restart, and prove it answers once, before `docker compose pause`.
- **`[Errno -3]` = "temporary failure in name resolution":** a stopped Compose container's name stops resolving in DNS.
- **`2>&1 | grep "^MARK"`:** print your result lines with a fixed prefix, then grep them out of noisy output.
- **`docker compose run -d --name X --no-deps -e VAR=v SERVICE`** starts a second copy of a service (its image, env_file, mounts, command) with one setting changed. Add `-p 127.0.0.1:HOST:CONTAINER` to publish a port (`run` doesn't by default).
- **`{ ...commands... } 2>&1 | tee FILE`** shows the output AND saves it, so a long run can't scroll away.
- **`docker inspect -f '{{.RestartCount}}'`:** a number above 0 on a service with `restart: unless-stopped` = it keeps crashing. Read its last log lines.
- **Every request taking the SAME time** (1.63 s each) is a clue: it's failing the same way every time, not working.
- **Count log lines before and after a test** (`BEFORE=$(... | grep -c ...)`): old lines from earlier runs otherwise look like new results.
- **A test ID that a system remembers** (duplicate detection, idempotency keys) must be NEW on each run, or the first send is already a "duplicate".
- **A heredoc inside a heredoc must use a different end word** (`<<'OUTER'` around `<<'PY'`), or the inner `PY` line ends the outer one.
- **`type(obj)` vs `obj.__class__`:** on a Django `LazyObject` (like `default_storage`), `__class__` reports the wrapped object's class, `type()` reports the wrapper.
- **`dict(response.headers)` makes header names case-sensitive.** Keep the `HTTPMessage` (`response.headers["content-type"]` works for any case).
- **An SDK's default retries can outlast your own deadline:** set `retry_total=0` (and a short `connection_timeout`) on clients used inside your own wait loop.
- **`pytest -rw`** prints the warnings summary; **`--tb=short` + `grep "^E "`** shows only the assertion lines of failures.
- **Code run in a subprocess isn't counted by coverage** (unless coverage's subprocess support is set up). The test can pass while the report still says "missing".
- **`filterwarnings = ["ignore:MESSAGE:CATEGORY:MODULE"]`** in pytest config hides one known library warning without hiding warnings from your own code.
- **`git checkout FILE` throws away uncommitted changes in FILE.** Before a mutation check, `git status --short FILE` must be empty (commit first).
- **Run threaded/timing tests several times** (`for i in 1 2 3; do ...; done`): a flaky test passes once and fails later.
- **Shell variables live only in the terminal that set them.** `docker run "$IMG"` with `IMG` unset → `'docker run' requires at least 1 argument`. Set variables at the top of every block you might paste elsewhere.
- **`docker run IMAGE cmd args`** replaces the image's CMD; **`--entrypoint prog`** replaces the program itself (`--entrypoint grep IMAGE -n x file`).
- **`git rev-parse --short HEAD`** = the short commit hash: tag images with it (`jobboard:557de36`).
- **`diff <(cmd1) <(cmd2)`** compares two commands' outputs; with identical secrets on both sides, only the real difference prints.
- **Competing consumers:** a silent worker on a queue may be healthy and LOSING the race to another consumer. Peek the queue, dump the worker's stack, then list who else is listening.
- **`faulthandler.dump_traceback_later(N, repeat=True)`** keeps the process running and dumps stacks every N s; `runpy.run_module('pkg.mod', run_name='__main__')` runs a module like `python -m`.
- **`gunicorn --print-config`** shows every effective setting after the config file is read.
- **Read the installed library's source** (`docker run --rm --entrypoint sed IMAGE -n 'A,Bp' /path/to/lib.py`) to learn what a new feature does before changing settings.
