# Technical Notes — 00-job-board-api

Deep-dive explanations of the code and the engineering decisions in this
project, kept in enough detail to be turned into LinkedIn articles later.
One entry per piece of work, newest last.

---

## Entry 1 — 2026-10-13 — A changelog that writes itself (GitHub Actions)

### The problem

A changelog is only useful if it is always current, and it only stays
current if nobody has to remember to update it. So the changelog has to be
a *by-product of pushing code*, not an extra task.

### The code — `.github/workflows/changelog.yml`

A GitHub Actions workflow is a YAML file in `.github/workflows/`. GitHub
runs it on a fresh cloud VM (a "runner") whenever its trigger event fires.

- **Trigger** — `on: push: branches: [master, main]` runs the workflow on
  every push to the default branch.
- **Permissions** — `permissions: contents: write` scopes the automatic
  `GITHUB_TOKEN` so the job is allowed to commit back to the repo. Without
  it the token is read-only and the final push fails. Least privilege: the
  token gets exactly one permission, nothing else.
- **Concurrency guard** — `concurrency: group: changelog` means two pushes
  in quick succession cannot run the job at the same time and race each
  other while committing.
- **Loop prevention** — the job's `if:` condition skips the run when the
  actor is `github-actions[bot]` or the commit message contains
  `[skip changelog]`. This is the critical line: the workflow ends by
  *pushing a commit*, and a push is its own trigger — without the guard it
  would trigger itself forever.
- **Checkout** — `actions/checkout@v4` with `fetch-depth: 0`. The default
  checkout is shallow (just the latest commit); `0` fetches the *full*
  history, because the changelog is built from the whole history.
- **Generation** — one shell pipeline: `git log --date=short
  --pretty=format:'- %ad — %s (%h)' --no-merges` walks every commit and
  formats each as a line with its date (`%ad`), subject line (`%s`), and
  short hash (`%h`). `--no-merges` keeps merge commits out so each line is
  one real change. Output is redirected into `docs/changelog.md` with a
  fixed header.
- **Commit back** — `git diff --quiet` checks whether the regenerated file
  actually changed; if not, the job exits cleanly (no empty commits). If
  it changed, the job configures the bot identity, commits with the
  message `docs: update changelog [skip changelog]`, and pushes.

### What actually happened (measured)

- Owner pushed the workflow at 20:04:30 PDT; the bot's changelog commit
  landed at 20:04:45 PDT — ~15 seconds end to end.
- The next doc push triggered it again: bot commit ~8 seconds later.
- Verified: no loop, no duplicate runs, changelog lists all commits.

### Platform lesson — app permissions vs. Actions permissions

The Muse GitHub App could read the repo and push normal files, but
GitHub returned `403 Resource not accessible by integration` for every
attempt to create a file under `.github/workflows/`. Workflow files are
special: creating or modifying them requires a dedicated "Workflows"
permission, separate from ordinary contents access, because a workflow
can run arbitrary code in CI. The workaround used here: the repo owner
adds the workflow file once, by hand; from then on the workflow runs
under the repo's own `GITHUB_TOKEN`, so the automation never depends on
the app's permissions again.

### Article angles

- "Automate the boring parts: a changelog that writes itself on every push"
- "The `if:` line that stops a GitHub Actions workflow from looping forever"
- "Why GitHub guards `.github/workflows/` harder than the rest of your repo"
- "Least-privilege CI: giving a workflow exactly one permission"

---

## Entry 2 — 2026-10-13 — Where the scaffold honestly stands

Article value here is the *before* picture — what `django-admin
startproject` gives you, and what has to change before it is a real API.

- **Tooling** — the project is managed with `uv`: `pyproject.toml` declares
  Django `>=5.2,<5.3`, Django REST Framework, and `psycopg[binary]`
  (the modern PostgreSQL driver), and `uv.lock` pins the exact resolved
  versions so every machine builds the same environment. `.python-version`
  pins Python 3.12. The `.venv/` is disposable — uv recreates it from the
  lockfile, which is why `.gitignore` excludes it.
- **`.gitignore` as a security boundary** — `.env` files are excluded from
  day one (real secrets never enter git), while `!.env.example` keeps a
  template committable. `db.sqlite3`, coverage output, and editor folders
  are local artifacts, also excluded.
- **Stock settings (the problem to fix next)** — the generated
  `config/settings.py` (Django 5.2.18) still has a hardcoded
  `SECRET_KEY` (with Django's own `django-insecure-` prefix warning),
  `DEBUG = True`, empty `ALLOWED_HOSTS`, SQLite as the database, and
  DRF is installed as a dependency but **not** yet registered in
  `INSTALLED_APPS`. `config/urls.py` routes only `/admin/`.
- **Next step (Night 3 of the plan)** — rewrite settings to read *every*
  value from environment variables (12-factor config), register DRF,
  point Django at PostgreSQL running in Docker Compose via psycopg, and
  get the first migration to run — without the secret key ever touching
  the repo.

### Article angles

- "What `startproject` really gives you — and the 5 things to fix before line 1 of business logic"
- "12-factor config in Django: settings from env vars, or it isn't production-shaped"
- "Lockfiles and disposable virtualenvs: reproducible Python with uv"

---

## Entry 3 — 2026-10-13 — Settings from env vars, PostgreSQL, DRF (commit `75eb0d1`)

This is the Night 3 change that turns the stock scaffold into an
environment-driven app — the "config" part of the 12-factor methodology:
*store config in the environment*, so the same code runs on a laptop, in
Docker, and on AWS/Azure with only the environment changing.

### The `env()` helper — fail fast, no new dependency

```python
def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value
```

- Uses only the standard library (`os.environ`) — no `django-environ`
  dependency needed for reading a handful of variables.
- The key design decision is what happens when a **required** variable is
  missing: instead of falling back to a silent default, it raises Django's
  `ImproperlyConfigured` with the variable's name, and the app refuses to
  start. A deploy that crashes loudly at boot with "Missing required
  environment variable: DJANGO_SECRET_KEY" is vastly better than one that
  starts with a wrong/default secret and fails mysteriously later — or
  worse, runs insecurely. Fail fast, fail at startup, fail with the name
  of the thing that is missing.

### Secrets and booleans

- `SECRET_KEY = env("DJANGO_SECRET_KEY")` — required, no fallback. The
  hardcoded `django-insecure-...` key from the generated scaffold is gone
  as a live value, so the repo no longer contains a usable secret.
- `DEBUG = env("DJANGO_DEBUG", "False").lower() in ("1", "true", "yes")` —
  environment variables are **always strings**, and in Python any non-empty
  string is truthy, so `bool("False")` is `True` — the classic bug that
  leaves DEBUG on in production. Parsing the string against an explicit
  allow-list of true-values avoids it, and the default is `"False"`:
  debug is off unless someone deliberately turns it on.
- `ALLOWED_HOSTS` is parsed from one comma-separated string
  (`"a, b ,c"` → `["a", "b", "c"]`): `split(",")`, `strip()` each entry,
  drop empties. One env var, any number of hosts.

### Database — SQLite out, PostgreSQL in

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}
```

- Changing `ENGINE` is the whole switch at the Django layer; the actual
  driver underneath is psycopg 3, already pinned in `pyproject.toml`.
  Name, user, and password are required env vars (the app will not boot
  without a database identity); host and port get local-development
  defaults because they are topology, not secrets.
- SQLite was fine for a scaffold, but it is a single file with one writer
  at a time — it cannot be the database for an API that will run in
  containers and Kubernetes. PostgreSQL is also what the later projects
  deploy against (RDS / Azure Database), so local now matches production.
- `.env.example` documents every required variable with placeholder
  values and is safe to commit; the real `.env` stays gitignored. The
  example file *is* the setup documentation for the config contract.

### DRF registered

- `"rest_framework"` added to `INSTALLED_APPS` — that single line is what
  activates Django REST Framework (it was already a declared dependency;
  until it is in `INSTALLED_APPS` Django does not load it).

### Honest gaps — what this commit does not do yet

- **No `docker-compose.yml` yet** — settings now expect a PostgreSQL
  server at `POSTGRES_HOST:POSTGRES_PORT`, but nothing in the repo starts
  one. Compose + the first successful `migrate` against Postgres is the
  remaining half of Night 3.
- **The old insecure key still sits in a commented-out block** at the top
  of `settings.py`. It is dead code, but secret scanners (Gitleaks, which
  arrives in Project 01) flag strings, not comments — deleting the whole
  commented scaffold block is a worthwhile cleanup.
- **The default `ALLOWED_HOSTS` includes `*`** (accept any Host header).
  Fine on a laptop; it should come out of the defaults before any real
  deployment, since the env var is the right place for it.

### Article angles

- "Fail fast: why your Django app should refuse to start when a secret is missing"
- "`bool('False')` is `True` — parsing booleans from env vars without shooting yourself"
- "12-factor config in practice: one `env()` helper, zero new dependencies"
- "The day SQLite has to go: switching Django to PostgreSQL is one ENGINE line — the work is everything around it"

---

## Entry 4 — 2026-10-13 — Dev Dockerfile and Compose stack with PostgreSQL 17 (commits `aa01775`, `18de30b`)

This closes the gap left open in entry 3: settings already expected a
PostgreSQL server, and now the repo can start one — plus the app itself —
with a single `docker compose up`. Two commits a minute apart carry the
same message and land the same stack; this entry documents the final tree.

### The Dockerfile — small, locked, non-root

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked

COPY . .
ARG UID=1000
RUN useradd --create-home --uid ${UID} app
USER app

EXPOSE 8006
CMD ["python", "manage.py", "runserver", "0.0.0.0:8006"]
```

- **Borrowing a binary instead of installing a tool** — `COPY --from=`
  pulls just the `uv`/`uvx` binaries out of Astral's official image. No
  pip install, no extra package manager layer, and the version is pinned
  (`0.13.0`) so the build is reproducible.
- **Layer ordering is the cache strategy** — only `pyproject.toml`,
  `uv.lock`, and `.python-version` are copied before `uv sync --locked`.
  Docker caches that dependency layer and reuses it on every rebuild
  unless the lockfile changes, even though the app code changes daily.
  Copying `.` first would throw that cache away on every edit.
  `--locked` fails the build rather than silently re-resolving if the
  lockfile and `pyproject.toml` disagree.
- **The venv deliberately lives outside the app folder** —
  `UV_PROJECT_ENVIRONMENT=/opt/venv` matters because Compose (below)
  bind-mounts the host code over `/app`. If the virtualenv were the
  usual `/app/.venv`, the mount would shadow it and the container would
  boot with no dependencies. Putting the environment on its own path
  keeps the mount and the installed packages from colliding.
  `UV_PYTHON_DOWNLOADS=never` stops uv from fetching its own Python —
  the base image's 3.12 is the one true interpreter.
- **`PYTHONUNBUFFERED=1`** makes logs appear in `docker compose logs` in
  real time instead of sitting in Python's buffer; **`PYTHONDONTWRITEBYTECODE=1`**
  stops `.pyc` writes inside the container (also avoids permission noise
  once the bind mount is in play).
- **Non-root by default** — the image creates an `app` user and switches
  to it (`USER app`). `ARG UID=1000` defaults to the typical first-user
  UID on a Linux host, so files created through the bind mount stay owned
  by the developer instead of root. A compromised dev server should not
  be root in its container.
- **This is a dev image, honestly labelled** — the `CMD` is Django's
  built-in `runserver` on `0.0.0.0:8006`. That is the right tool locally
  (auto-reload with the bind mount), and the wrong tool in production,
  where a real WSGI server (Gunicorn/uWSGI) belongs. Port 8006 is also
  what Compose publishes.

### `.dockerignore` — the build context is an attack and bloat surface

```
.git
.venv
.env
.env.*
!.env.example
__pycache__/
*.py[cod]
.pytest_cache/
htmlcov/
```

Everything listed is either huge, useless in an image, or dangerous.
`.env` is the important one: without this line, `COPY . .` would bake the
real secrets file into an image layer. The `!.env.example` exception
mirrors the `.gitignore` pattern from entry 2 — the template stays, the
secrets stay out.

### docker-compose.yml — two services, one contract

```yaml
services:
  db:
    image: postgres:17
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: .
    env_file: .env
    environment:
      - POSTGRES_HOST=db
    ports:
      - "8006:8006"
    volumes:
      - .:/app
    depends_on:
      db:
        condition: service_healthy

volumes:
  pgdata:
```

- **One `.env` feeds both containers** — the same `POSTGRES_DB` /
  `POSTGRES_USER` / `POSTGRES_PASSWORD` variables entry 3 wired into
  Django are exactly the variables the official `postgres` image uses to
  bootstrap its database and superuser on first start. A single source
  of truth means the app and the database can never disagree about the
  password. (The postgres image only applies them when the data volume
  is empty — change the password later and you must change it in the
  database too, or recreate the volume.)
- **`POSTGRES_HOST=db` is the 12-factor payoff** — `.env.example` sets
  `POSTGRES_HOST=localhost`, which is correct when Django runs on the
  host and Postgres is port-forwarded — but inside Compose, `localhost`
  means *the api container itself*, where no database is listening.
  Compose's built-in DNS resolves service names, so `db` is the database.
  The `environment:` block overrides the `env_file:` value for just this
  topology — same image, same `.env`, no code change. This is entry 3's
  env-var design doing exactly the job it was built for.
- **Healthy, not just started** — a plain `depends_on: [db]` only waits
  for the container to *start*; Postgres then still needs seconds to
  initialise and accept connections, and Django crashing with
  "connection refused" on a cold boot is the classic symptom.
  `condition: service_healthy` holds the api back until the db
  healthcheck passes: `pg_isready` every 5s, 3s timeout, 10 retries —
  roughly a 50-second budget. This is the same idea Kubernetes later
  formalises as readiness probes (direct CKAD crossover).
- **The `$${...}` double dollar is not a typo** — Compose itself
  interpolates `${VAR}` in a compose file, which would substitute the
  *host's* (probably empty) variables at parse time. `$$` escapes that,
  so the literal `${POSTGRES_USER}` reaches the container and is expanded
  by the shell *inside* it, where `.env` values actually live.
- **Named volume `pgdata`** — database files live in a Docker-managed
  volume mounted at Postgres's data directory, so data survives
  `docker compose down`, rebuilds, and image updates. It is only
  destroyed by an explicit `docker compose down -v` — persistence with
  an intentional delete, not an accidental one.
- **Bind mount `.:/app` is the dev-loop trade** — host edits are live in
  the container (and `runserver` auto-reloads), at the cost of the baked
  image code being shadowed while developing. Production will drop this
  mount and run only what `COPY` put in the image.

### Honest gaps — what these commits do not do yet

- **No migration evidence** — nothing in these commits runs
  `manage.py migrate` against the Compose database (no entrypoint script
  and no recorded run). The stack *can* start; the first migration is
  still the verification that proves the whole chain end to end.
- **No `.env` bootstrap step** — both services require a real `.env`
  (`env_file: .env`); a fresh clone must copy `.env.example` to `.env`
  first or Compose fails immediately. Worth a line in a README.
- **Dev-only server** — `runserver`, a bind mount, and `DEBUG` from the
  local `.env` are all correct for development and none of them should
  survive into the production images the later projects build.

### Article angles

- "`depends_on` lied to you: why `service_healthy` + `pg_isready` ends the Django/Postgres startup race"
- "`localhost` is not the database: service-name DNS and the one-line `POSTGRES_HOST=db` override"
- "The `$$` that saves your healthcheck: escaping variable interpolation in Compose files"
- "Put the venv outside the code: how `UV_PROJECT_ENVIRONMENT=/opt/venv` makes bind mounts and uv play nicely"
- "Copy the lockfile first: Docker layer caching is a dependency-management decision"

---

## Entry 5 — 2026-10-21 — A custom User model with roles (commit `2dc2737`)

### Why a custom user model at all — and why now

Django's single most repeated piece of advice: **create a custom user model
at the start of the project, even if it behaves identically to the built-in
one.** The reason is asymmetry of cost. Pointing Django at your own model on
day one is two lines. Swapping it later — after migrations have run and other
models have foreign keys to the user — means resetting the database and
regenerating migrations, because every reference to the user model is baked
into migration history. This commit pays that reset *now*, while the database
holds nothing worth keeping (and its message says so: "reset DB"), so the
project never has to pay it with real data in the tables.

### The code — `jobs/models.py`

```python
class User(AbstractUser):
    class Role(models.TextChoices):
        COMPANY = "company", "Company"
        CANDIDATE = "candidate", "Candidate"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices)

    @property
    def is_company(self):
        return self.role == self.Role.COMPANY

    @property
    def is_candidate(self):
        return self.role == self.Role.CANDIDATE
```

- **`AbstractUser`, not `AbstractBaseUser`** — subclassing `AbstractUser`
  inherits the complete built-in user (username, password hashing, staff /
  active flags, groups and permissions machinery, the default manager) and
  lets you *add* fields. `AbstractBaseUser` is the bare-password-only base
  you pick when you want to rebuild everything, including the manager and
  auth plumbing. For this API, extension beats reinvention.
- **The wiring is two places** — `AUTH_USER_MODEL = 'jobs.User'` in settings
  (note the format is `app_label.ModelName`, not an import path) and `"jobs"`
  in `INSTALLED_APPS`. From then on Django itself treats `jobs.User` as *the*
  user everywhere: `request.user`, foreign keys via
  `settings.AUTH_USER_MODEL`, the admin, and migrations — which is why the
  generated `0001_initial.py` for the jobs app contains the whole user table
  (it depends on `auth` app migration `0012`, since groups/permissions live
  there) and this model becomes the swappable target other apps will point at.
- **`Role` as `models.TextChoices`** — a typed enumeration nested in the
  model. It stores plain strings (`"company"`) in a regular varchar column —
  no database enum type — while code refers to `User.Role.COMPANY` instead of
  scattering the raw string `"company"` through views and permission classes,
  where a typo would silently never match. The second element of each tuple
  is the human-readable label Django uses in forms and admin. Validation
  note: `choices` is enforced by forms/serializers and `full_clean()`, *not*
  by a database constraint — the column itself will accept any string, so API
  input must be validated at the serializer layer (which is where the
  register endpoints in Night 5 will do it).
- **`email` overridden as `unique=True`** — the stock `AbstractUser` email
  field is *not* unique; two accounts could share one address. Overriding
  the field in the subclass is enough — the migration shows the unique
  constraint landing in the schema.
- **`is_company` / `is_candidate` as `@property`** — call sites read
  `user.is_company` (no parentheses, no string comparison) and take no extra
  query, because `role` travels with the already-fetched user row. These two
  properties are the seam the Night 9–10 permission classes
  (`IsVerifiedCompany`, `IsCandidate`, …) will hang off: the rule "companies
  post jobs" becomes a readable boolean instead of string matching repeated
  across views.

### Design call — one User with a role, not separate user types

The project brief sketches Company and CandidateProfile as models of their
own. This commit chooses the common alternative for *identity*: a single
user table with a role discriminator, because authentication, tokens, and
permissions all operate on one principal. It does not close the door on
profiles — the natural next step is `OneToOne` profile models pointing at
this user when company/candidate-specific fields appear (company name,
skills, resume), which keeps identity unified and profile data separate.
Job and Application models (the rest of Night 4) are not in this commit yet.

### Honest gaps — worth knowing before Night 5 builds on this

- **Login is still by username, not email.** Making `email` unique does not
  change `USERNAME_FIELD` (still `"username"` on `AbstractUser`). If the API
  should authenticate by email, that is a deliberate extra step:
  `USERNAME_FIELD = "email"`, removing/relaxing `username`, and a custom
  user manager — best decided *before* the JWT endpoints land in Night 5.
- **`role` has no default and is not in `REQUIRED_FIELDS`.** Code paths that
  create users must always pass a role explicitly; in particular
  `createsuperuser` does not know about `role`, so a superuser created
  today ends up with an empty role unless `REQUIRED_FIELDS` is extended —
  harmless for an admin account, confusing if forgotten.
- **The commented-out scaffold block is still at the top of
  `settings.py`** (including the old insecure key string) — flagged in
  entry 3, still worth deleting before a scanner ever runs on this repo.

### Article angles

- "Do it on day one: why Django begs you to subclass the user model before your first migration"
- "The reset is the lesson: what actually breaks when you swap AUTH_USER_MODEL late"
- "TextChoices over stringly-typed code: enums that store as plain text"
- "Unique email is not email login: USERNAME_FIELD and the half-finished auth change"
