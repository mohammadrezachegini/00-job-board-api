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

### Addendum — 2026-10-21 — the race the first version did not survive

Two pushes landing seconds apart (the assistant's paired journal +
technical-notes commits) exposed a flaw: two workflow runs could overlap,
each generating the changelog from the commit that triggered it, and the
slower run's final `git push` was then rejected as non-fast-forward
because the branch had moved — that run died with exit code 1. The
changelog itself was never wrong: whichever run won regenerated it from
the *full* history, so the file stayed complete (verified — top entry
current after the failed run). Failure, but self-healing.

Fix (workflow v2): check out the branch at its *current* head rather
than the triggering commit, and wrap generate → commit → push in a
retry loop that fetches, resets to the newest head, and regenerates on
every attempt — a generated file should always be rebuilt from the
latest state instead of merged. The same refresh moved
`actions/checkout` to v5 (the v4 line targets the deprecated Node 20
runtime) and pinned the runner to `ubuntu-24.04` instead of the moving
`ubuntu-latest` label. Lesson worth an article by itself: in CI, a push
is not the end of the world state — the branch can move under a running
job, and jobs that commit back must be written to expect it.

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

---

## Entry 6 — 2026-10-21 — Company & CandidateProfile: profiles done right (commit `6c728f5`)

Entry 5 ended with a prediction: identity stays in one user table, and
profile data would arrive as separate models pointing at it. This commit is
that step, and the interesting part is *how each field earns its place*.

### One-to-one profiles — `jobs/models.py`

```python
class Company(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="company"
    )
    ...

class CandidateProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
    )
    skills = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    ...
```

- **`OneToOneField` is a foreign key with a unique constraint** — that is
  the whole mechanism. It guarantees at the *database* level that one user
  has at most one company profile, which a plain `ForeignKey` cannot say.
  The reverse accessor comes from `related_name`: `user.company` and
  `user.candidate_profile` read naturally everywhere (serializers,
  permission classes, templates) instead of the generated
  `company_set`-style names a default relation would produce.
- **Referencing `settings.AUTH_USER_MODEL`, not `User` directly** — importing
  the concrete model into the same app's models file works, but the settings
  reference is the swappable pattern Django recommends: if the user model
  ever moves, every relation follows the setting instead of an import.
- **`on_delete=models.CASCADE`** — deleting a user deletes its profile. For
  identity-owned data that is the correct direction; the reverse (deleting
  a profile) leaves the account intact.
- **`blank=True` on website / description / headline / location** — optional
  at the form/serializer layer. Note `blank` (validation) vs `null`
  (database): these string fields correctly omit `null=True`, so empty
  means `""`, never a mix of NULL and empty string representing the same
  thing — a classic Django modeling trap avoided.

### The two fields that are really future features in disguise

- **`Company.is_verified = BooleanField(default=False)`** — default *off*
  means a freshly registered company cannot post until someone verifies it.
  That is precisely the state the Night 9 permission class
  `IsVerifiedCompany` will test. A boolean default is also a small security
  posture: the failure mode of forgetting to set it is "too restrictive",
  never "accidentally trusted".
- **`CandidateProfile.skills` as a PostgreSQL `ArrayField`** — this is the
  payoff of the Night 3 database switch. Skills live as a native Postgres
  array in a single column — no join table, no comma-separated string
  parsing — and Postgres can query inside it (`contains`, `overlap`
  lookups), which is exactly what Night 11's match scoring needs when it
  compares a job's required skills against a candidate's. Details that are
  right: the element type carries its own `max_length=50`, and
  `default=list` passes the *callable* — writing `default=[]` would share
  one mutable list across every row that relies on the default, one of
  Python's most famous footguns, neatly avoided. The trade, honestly: the
  project gives up database portability for this column — `ArrayField`
  does not exist on SQLite/MySQL — a deliberate bet placed when Postgres
  was chosen.

### Admin that does operational work — `jobs/admin.py`

- **Extending `UserAdmin`, not replacing it** — the custom class subclasses
  Django's `UserAdmin`, so password handling, permission widgets, and the
  change-password flow all survive. It then *appends*:
  `list_display`/`list_filter` gain `role`, the existing `fieldsets` get a
  "Job board" section exposing `role` on the change form, and
  `add_fieldsets` gains `email` + `role` on the add form — which closes the
  gap flagged in entry 5 (admin-created users previously got no role and a
  non-unique email prompt).
- **`CompanyAdmin.list_editable = ("is_verified",)`** — the verification
  flag can be flipped inline from the company list, next to a
  `list_filter` on the same field. That is an ops workflow in three lines:
  filter to unverified companies, tick, save. `search_fields` uses
  `user__email` — the double-underscore lookup that searches *across* the
  relation into the user table.
- Migration `0002_candidateprofile_company` carries both models; schema
  and code land in the same commit, so a fresh clone migrates cleanly.

### Honest gaps

- **A naming typo worth fixing while it is cheap:** CandidateProfile's
  timestamp is `create_at` while Company's is `created_at`. Inconsistent
  field names leak into serializers, ordering clauses, and every query
  written later; renaming it now costs one migration, renaming it after
  the API ships costs a breaking change. (Cosmetic sibling: the admin
  class is spelled `JobBoradUserAdmin` — harmless, but the kind of thing
  worth catching in review.)
- **Nothing enforces "role matches profile type" yet.** The schema allows a
  candidate-role user to own a `Company` row and vice versa — integrity
  rules like that belong in the registration serializers (Night 5), where
  the role is known, or in model `clean()`; today they are simply absent,
  which is fine as long as Night 5 remembers them.
- **Job and Application are still missing** — they are the larger half of
  Night 4 (foreign keys both ways, application status, the resume field
  that Night 12 will wire to S3).

- **Correction (same night, commit `289e2e5`):** the `create_at` typo was
  renamed to `created_at` in the model — but the commit contains no rename
  migration, and `0002` still creates the column as `create_at`. Until a
  `RenameField` migration is generated (makemigrations asks "did you
  rename…?" — answering yes preserves the column and its data; remove+add
  would drop it) and applied, the model and the schema disagree and any
  CandidateProfile query fails against the real column name. A rename is
  only finished when the migration lands in the same state as the code.

- **Follow-up (2026-10-22, commit `21bf705`):** the rename migration did
  land — `0003_rename_create_at_candidateprofile_created_at` is a single
  `RenameField` operation depending on `0002`, exactly the
  data-preserving outcome described above, and the drift is closed. The
  same commit is also a documentation lesson: its message claims Job and
  Application models that the diff does not contain. A changelog
  generated from commit messages (entry 1) inherits the accuracy of the
  messages — it is a mirror, not a fact-checker — so the permanent
  history now mis-describes this commit. Write messages from `git diff
  --staged`, not from the task you meant to do.

### Article angles

- "OneToOne is a promise the database keeps: modeling profiles in Django"
- "Your boolean default is a security decision: default-deny with is_verified"
- "Native Postgres arrays in Django: ArrayField, and the match-scoring door it opens"
- "default=list, never default=[]: the mutable-default trap in a real model"

---

## Entry 7 — 2026-10-22 — JWT auth with SimpleJWT (commit `82f3a42`)

### What a JWT setup actually consists of

Three pieces in this commit, each in its natural place:

```python
# config/settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# jobs/urls.py, mounted at api/ in config/urls.py
path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
```

- **The token model** — a JWT is a *signed, self-contained* credential:
  header, payload (claims like `user_id`, `token_type`, `exp`), and a
  signature made with the server's secret (here Django's `SECRET_KEY` —
  the env-var one from entry 3, so the fail-fast secret discipline turns
  out to be load-bearing for auth too). The server stores **no session**:
  any instance can verify any token by checking the signature and expiry,
  which is exactly why tokens suit an API that will later run as multiple
  containers behind Kubernetes — no shared session store to keep in sync.
- **Two tokens, two jobs** — the *access* token (15 minutes) is the one
  sent on every request as `Authorization: Bearer <token>`; short life
  limits the damage if it leaks, because it cannot be revoked — a signed
  JWT is valid until it expires, server amnesia cuts both ways. The
  *refresh* token (1 day) does one thing: obtain a fresh access token
  from the refresh endpoint without re-entering credentials. The client
  guards the refresh token like a password.
- **`JWTAuthentication` as the default authentication class** — DRF runs
  it on every request: parse the header, verify signature/expiry, load
  the user named by the token's `user_id` claim. Because the project
  swapped `AUTH_USER_MODEL` (entry 5), that lookup resolves to
  `jobs.User` automatically — the earlier foundation paying off with zero
  extra wiring. Note what SimpleJWT did **not** need:
  `rest_framework_simplejwt` is absent from `INSTALLED_APPS`, and that is
  correct — the app is only required for the optional token-blacklist
  feature; the obtain/refresh views and authentication class work from
  the dependency alone.
- **`IsAuthenticated` as the default permission** — the security posture
  flips from the framework default: instead of "open unless a view
  protects itself", every future endpoint requires a logged-in user
  unless it explicitly opts out (`AllowAny`). Deny-by-default means a
  forgotten permission declaration fails *closed* (a 401 for everyone)
  rather than open (the whole internet) — the same default-deny instinct
  as `is_verified = False` in entry 6. The register endpoints, when they
  land, will be the deliberate exception.
- **The obtain view authenticates by `USERNAME_FIELD`** — still
  `username` on this user model (see entry 5's open question). The token
  endpoints therefore take username + password today; switching login to
  email is still possible, still cheaper now than after clients exist.

### Honest gaps

- **Night 5 is half done.** Token obtain/refresh exist; the register
  endpoints from the brief (`register/company/`, `register/candidate/`)
  do not — no serializers or views have been written (`jobs/views.py` is
  still the stock stub). Registration is also where the role ↔ profile
  integrity rules flagged in entry 6 (a company-role user gets a Company
  row, a candidate gets a CandidateProfile) must be enforced.
- **No refresh rotation or blacklist.** With SimpleJWT defaults, the
  same refresh token is reusable for its whole 1-day life; a stolen one
  is a 1-day skeleton key. `ROTATE_REFRESH_TOKENS` + the blacklist app is
  the standard hardening and a natural later entry.
- **Nothing proves it end-to-end yet** — no test or recorded call shows a
  token being obtained and used against a protected endpoint. The
  Night 8 smoke test is where that proof belongs.
- **Night 4 is still open** — Job and Application models remain unwritten;
  auth was built ahead of them. Register endpoints can proceed (the
  profile models exist), but Night 6's job CRUD has nothing to stand on
  until the Job model lands.

### Article angles

- "Sessions don't scale, signatures do: why APIs authenticate with JWTs"
- "Access vs refresh: the two-token pattern and the 15-minute compromise"
- "Default-deny in DRF: one settings line that fails closed"
- "Your SECRET_KEY is now your auth infrastructure: env discipline meets JWT signing"

---

## Entry 8 — 2026-10-23 — Registration endpoints (commit `f9b17a0`)

### One base serializer, two doors

Registration is split by role at the URL level — `auth/register/company/`
and `auth/register/candidate/` — with a shared
`BaseRegistrationSerializer` (a plain `serializers.Serializer`, not a
ModelSerializer, because the input spans two models) carrying the common
contract, and one subclass per role adding only its profile fields:

```python
class BaseRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    ...
    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value
```

Details worth stealing:

- **The role is assigned by the server, never taken from the request.**
  `role` is not a serializer field at all — each subclass's `create()`
  passes `role=User.Role.COMPANY` / `CANDIDATE` itself. This closes the
  classic mass-assignment escalation: there is no payload a client can
  send that makes it anything other than the role of the door it walked
  through, and `is_staff` / `is_verified` are equally unreachable.
- **Email uniqueness is enforced twice, correctly.** PostgreSQL's unique
  constraint on the email column is case-*sensitive*, so
  `Alice@x.com` and `alice@x.com` would both satisfy the database.
  The serializer closes the gap: it lowercases the address and checks
  `email__iexact`. Because every stored address is normalized to
  lowercase at this single entry point, the DB constraint becomes
  effectively case-insensitive behind it. Username gets the same
  `__iexact` treatment.
- **Passwords go through Django's validators**
  (`password_validation.validate_password` in `validate_password`), so
  the project's `AUTH_PASSWORD_VALIDATORS` — length, common-password,
  numeric-only, similarity — apply to API signups exactly as they do in
  the admin. The field is `write_only` and `trim_whitespace=False`
  (trailing spaces are legal password characters; silently trimming them
  would store a different password than the user typed). Creation goes
  through `User.objects.create_user`, so hashing is Django's, never
  hand-rolled.
- **User + profile creation is `@transaction.atomic`.** A registration
  writes two rows that must exist together or not at all; if profile
  creation fails, the user row rolls back instead of leaving an
  account with no profile that would fail every subsequent request in
  confusing ways. All-or-nothing is the only sensible shape for a
  two-row invariant.
- **The deliberate exception to entry 7's default-deny.** Both views are
  `CreateAPIView`s with `permission_classes = [AllowAny]` *and*
  `authentication_classes = []`. The second line is the subtle one:
  without it, a request carrying a stale/invalid Bearer token would be
  rejected by the global `JWTAuthentication` before the view ever ran —
  a logged-out-in-spirit user couldn't re-register because their old
  token is malformed. Empty authentication classes mean "don't even try
  to authenticate here", which is what a public signup endpoint wants.
- **The response is a whitelist.** `to_representation` returns only
  `id`, `username`, `email`, `role` — the password cannot leak through
  the serializer's output because it is never in it.

### Pitfalls found in review (small, real)

- **Length mismatches between serializer and model.** The serializer
  accepts `location` up to 200 chars but the model column is
  `varchar(100)`, and `skills` entries up to 100 chars against a
  `varchar(50)` array element. Values in the gap pass validation, then
  fail at the database with a `DataError` — a 500 where a 400 belongs.
  Fix: align the serializer to the model (`location` 100, skills child
  50). Rule of thumb: serializer limits should never exceed the column
  they feed.
- **`validate_email(delf, value)`** — a typo'd first parameter name.
  Harmless (Python passes the instance positionally, whatever it's
  called, and the body never uses it), but it will confuse every future
  reader; it should be `self`.
- The uniqueness pre-checks are inherently racy (check-then-create is
  never atomic by itself) — acceptable here because the database unique
  constraints are the real backstop, with the checks existing to produce
  friendly 400s instead of raw integrity errors.

### Status

Night 5 is complete per the brief: JWT config, token + refresh endpoints,
and both registration endpoints. Night 4's Job and Application models
remain the one open foundation item — and Night 6's job CRUD needs the
Job model, so they are the natural next session.

### Article angles

- "Never let the client pick its own role: registration design against mass-assignment"
- "Case-insensitive email uniqueness: why the DB constraint alone is not enough"
- "Two rows or none: @transaction.atomic and the user+profile invariant"
- "Serializer vs model validation: the 500 hiding in a length mismatch"

---

## Entry 9 — 2026-10-23 — Job and Application models (commit `05f4cbc`)

### The last two models, and the shape of the domain

```python
class Job(models.Model):
    class JobType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JobType.choices, default=JobType.FULL_TIME)
    required_skills = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Application(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWING = "reviewing", "Reviewing"
        INTERVIEW = "interview", "Interview"
        OFFERED = "offered", "Offered"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name="applications")
    cover_letter = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "candidate"], name="unique_application_per_job"),
        ]
```

Decisions that matter:

- **The unique constraint lives in the database, not in code.**
  `UniqueConstraint(fields=["job", "candidate"])` makes "one application
  per candidate per job" a property of the data itself. An application
  check (`if exists: error`) would be racy — two concurrent requests can
  both pass the check and both insert. A DB constraint cannot be raced;
  the second insert simply fails. Put invariants in the layer that can
  actually guarantee them: validation produces friendly errors,
  constraints produce truth.
- **`Application.candidate` points at CandidateProfile, not User.** An
  application is something a *candidate profile* does; pointing at the
  profile makes non-candidate applications structurally impossible
  rather than merely checked-for, and it puts `candidate.skills` one hop
  away for Night 11's match scoring (`job.required_skills` vs
  `application.candidate.skills` — both `ArrayField(CharField(50))`, the
  symmetry is deliberate and consistent, unlike the registration
  serializer's 100-char skills slip noted in entry 8).
- **Status as `TextChoices` with a naming refinement.** The pipeline
  values are `submitted/reviewing/interview/offered/rejected` — the
  brief's `applied` became `submitted` and `hired` became `offered`,
  which is arguably the more precise word (an offer precedes a hire;
  the company controls the offer, not the acceptance). Stored values
  stay stable, labels stay human.
- **`is_open` as a boolean flag, defaulting True.** Closing a job is a
  state change, not a deletion — applications and history survive a
  closed job, and Night 6's close action and "companies act only on
  their own jobs" rules key off this flag plus ownership.
- **CASCADE everywhere, consistently.** Delete a company and its jobs
  and their applications go with it; the domain has no orphaned
  postings. Both models order by `-created_at` (newest first is the
  only order any list in this product will want) and carry full
  `created_at`/`updated_at` timestamps.
- **Admin with `list_select_related`.** Both new admins prefetch their
  relations (`company`, `job__company`, `candidate__user`), so the
  changelist doesn't fire a query per row — the N+1 trap avoided in the
  one place developers usually forget it. Search crosses relations too
  (`company__name`, `candidate__user__username`).

### Status

Migration `0004_job_application` completes a clean four-migration
chain. **Night 4 is complete, and with it the foundation stretch
(Nights 3–5) is done**: models, auth, and registration all in place.
Next is Night 6 — Job CRUD endpoints, where these models meet the
permissions work (`IsCompany`, `IsVerifiedCompany`) that the earlier
entries have been quietly preparing flags for.

### Article angles

- "Database constraints are the only validation that can't be raced"
- "Model the actor, not the account: why Application points at the profile"
- "Status machines with TextChoices: naming the pipeline honestly"
- "list_select_related: killing the admin's N+1 before it starts"

---

## Entry 10 — 2026-10-23 — Job endpoints (commit `cdb8ae2`)

### A ViewSet assembled from mixins — including what was left out

```python
class JobViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = JobSerializer

    def get_queryset(self):
        queryset = Job.objects.select_related("company")
        if self.action == "list":
            queryset = queryset.filter(is_open=True)
        return queryset

    def perform_create(self, serializer):
        if not self.request.user.is_company:
            raise PermissionError("Only company users can create jobs.")
        serializer.save(company=self.request.user.company)
```

- **The missing mixin is the design.** There is no
  `DestroyModelMixin`, so no DELETE route exists at all. Jobs are never
  erased — they are closed (`is_open=False`), preserving applications
  and history (entry 9). You cannot call an endpoint that was never
  built; absence beats a permission check.
- **Action-aware querysets.** `get_queryset` filters `is_open=True`
  only for `list` — the public catalogue shows open jobs, while
  `retrieve` can still fetch a closed job by id (a candidate reviewing a
  job they applied to needs exactly that). `select_related("company")`
  rides along so list rendering doesn't N+1.
- **The company comes from the token, never the payload.** The
  serializer exposes `company` as a read-only field flattened to the
  company's *name*, and `perform_create` injects
  `request.user.company` server-side. A client literally cannot post a
  job as someone else — there is no writable field to attack (the
  registration lesson from entry 8, applied again).
- **Pagination is global**: `PageNumberPagination` with `PAGE_SIZE=20`
  in `REST_FRAMEWORK` — every future list endpoint inherits it.

### Three findings from review (ordered by severity)

1. **Wrong exception type → 500 instead of 403.** `perform_create`
   raises Python's builtin `PermissionError`. DRF's exception handler
   translates `rest_framework.exceptions.PermissionDenied`, Django's
   `PermissionDenied`, and `Http404` — the builtin is none of those, so
   it escapes as an unhandled error: a candidate posting a job receives
   a 500 stack trace, not a clean 403. One-line fix: raise DRF's
   `PermissionDenied`. (The deeper fix is a permission class — Night
   9's `IsCompany` — so the check runs before the view, declaratively.)
2. **Update has no ownership check.** For `update`/`partial_update` the
   queryset is unscoped and there is no object permission, so *any*
   authenticated user — a candidate, or a rival company — can PATCH any
   job: retitle it, rewrite it, or close it via `is_open`. Tonight this
   is the one real authorization hole in the API. Fixes, either layer:
   scope the queryset for write actions to
   `company__user=self.request.user`, or add a `has_object_permission`
   ownership class (again, Night 9 territory — but this one shouldn't
   wait for a public deployment).
3. **Brief deviations, both plausibly deliberate:** browsing requires
   authentication (the global `IsAuthenticated` default), while the
   brief specifies a public job list; and there is no dedicated
   `POST /jobs/{id}/close/` `@action` — closing currently happens by
   PATCHing `is_open`, which works but is less explicit than the
   brief's verb-style endpoint and inherits finding 2's hole.
   Edge case in the same area: a company-role user with no Company
   profile (e.g. created in the admin) hits
   `RelatedObjectDoesNotExist` in `perform_create` — another 500
   instead of a 4xx.

### Status

Night 6 is built and functional for the happy paths; the hardening
above (403 fix, ownership, close action, public browse decision) pairs
naturally with Night 9's custom permissions, where `IsCompany` and
`IsVerifiedCompany` will move these checks out of the view entirely.

### Article angles

- "The endpoint that doesn't exist can't be abused: designing by omission"
- "PermissionError is not PermissionDenied: DRF's exception handler, precisely"
- "perform_create and the server-side injection pattern"
- "Why your list endpoint and your detail endpoint want different querysets"

---

## Entry 11 — 2026-10-24 — Application endpoints (commit `88ea9ca`)

### Applying, done in layers

```python
class ApplicationViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = ApplicationSerializer
    queryset = Application.objects.select_related("job__company", "candidate__user")

    def perform_create(self, serializer):
        if not self.request.user.is_candidate:
            raise PermissionDenied("Only candidate users can create applications.")
        try:
            with transaction.atomic():
                serializer.save(candidate=self.request.user.candidate_profile)
        except IntegrityError:
            raise ValidationError({"job": "You have already applied for this job."})
```

The duplicate-application defence is built **three layers deep**, and each
layer exists because the one above it has a known hole:

1. **Serializer `validate()` pre-check** — looks up an existing
   (job, candidate) application and raises a friendly field error. This
   is the layer users normally see. It is also *racy*: two simultaneous
   requests can both pass it.
2. **The database `UniqueConstraint`** (entry 9) — the layer that cannot
   be raced. The losing request's insert raises `IntegrityError`.
3. **The translation** — `perform_create` catches that `IntegrityError`
   and re-raises DRF's `ValidationError`, so the race's loser still gets
   the same clean 400 as everyone else, never a 500. The inner
   `transaction.atomic()` block matters here: on PostgreSQL an error
   poisons the surrounding transaction ("current transaction is
   aborted"), and the atomic block's rollback-to-savepoint is what makes
   it safe to catch the error and keep responding.

Two more pieces of the same discipline: **`validators = []`** in the
serializer's Meta disables DRF's automatic `UniqueTogetherValidator` —
necessary, because that validator needs `candidate` among the writable
fields, and here `candidate` is deliberately read-only (injected from
the token, like `company` in entry 10). The auto-validator is replaced
by the manual layers above, not just removed. And `validate_job`
rejects closed jobs at the field level, while `status` is read-only —
an applicant cannot set their own status to `offered`.

Also fixed from entry 10: `JobViewSet.perform_create` now raises DRF's
`PermissionDenied`, so non-companies get a proper 403 instead of a 500.

### Findings (ownership is the theme)

1. **The applicants list has no ownership check.** The new
   `GET /jobs/{id}/applications/` action calls `get_object()` on the
   unscoped job queryset — *any* authenticated user, candidate or rival
   company, can enumerate who applied to any job. Applicant lists are
   among the most sensitive data in this system (they reveal people's
   job searches). This needs `job.company.user == request.user`
   enforcement — the single most important fix currently outstanding.
2. **Application detail is unscoped too.** `RetrieveModelMixin` over
   the full queryset means any logged-in user can read any application
   by id (an IDOR). The queryset should scope by role: candidates see
   their own, companies see applications to their own jobs.
3. **The brief's my-applications list is missing.** Night 7 calls for
   `GET /applications/mine/`; the viewset has create + retrieve only.
4. **The "fix typos" half of the commit title didn't land.** Verified
   in the current files: `validate_email(delf, …)` still reads `delf`,
   and the entry 8 mismatches are unchanged — candidate `location`
   still allows 200 chars into a 100-char column, `skills` items 100
   into a 50-char column. Harmless tonight, a 500 the first time a user
   types a long location.
5. Entry 10's update-ownership finding also still stands (any
   authenticated user can PATCH any job). Findings 1, 2, and 5 are the
   same root cause — object ownership hasn't been modelled yet — and
   they are exactly what Night 9's permission classes
   (`IsCompany`, `IsCandidate`, ownership) are for. Until then they
   are known, documented holes, fine for a local dev build, blockers
   for anything public.

### Status

Night 7 is **mostly** complete: apply, closed-job rejection,
duplicate→400 (double-enforced), and application detail work; the
my-applications list, ownership scoping, and the deferred serializer
cleanups remain. Next per plan is Night 8 — the end-to-end smoke test —
which would be a good moment to see several of these findings fire (or
not) against a running stack.

### Article angles

- "Friendly check, honest constraint, clean translation: error handling in three layers"
- "Why catching IntegrityError needs a savepoint: PostgreSQL's aborted transaction"
- "validators = [] is a decision, not a deletion: replacing DRF's auto UniqueTogetherValidator"
- "IDOR in your own API: the ownership checks nobody writes on the first pass"

---

## Entry 12 — 2026-10-24 — The Phase 1 README, and what the smoke test caught (commits `c23809b`, `1f47139`)

The README itself is good portfolio craft — architecture diagram, an
endpoint table that matches the built routes exactly, an env-var
reference, design decisions stated as decisions, and a status line that
does not oversell ("Owner-only rules and verified-company checks are
planned for Phase 2" — precisely the open findings from entries 10 and
11). But its most valuable section is **"What Broke and How I Fixed
It"**, because those five bugs share one property: *none of them crash
on the happy path.* They are silent failures, and only the end-to-end
smoke test — exercising the negative paths on purpose — exposed them.

### A small taxonomy of silent failures

1. **Dead code by indentation.** Two serializer validators were
   indented inside `class Meta`, so DRF never called them: closed jobs
   accepted applications, and only the PostgreSQL unique constraint
   (the layer from entries 9/11 that cannot be talked out of its job)
   kept duplicates out. The diagnostic clue deserves framing: *the
   shape of the error body* — a plain string means the view raised it,
   a per-field list means the serializer did. When an expected
   serializer error arrives in view shape, the validator isn't running.
2. **A defensive default that hides typos.** `getattr(user,
   "candidateprofile", None)` — one missing underscore, and the
   duplicate check quietly received `None` and stood down. `getattr`
   with a default is a deliberate "this may legitimately not exist"
   tool; used on an attribute that must exist, it converts a loud
   `AttributeError` into a silent logic-off switch. Prefer direct
   attribute access for must-exist relations and let it crash in dev.
3. **An env var typo nobody reports.** `PYTHONBUFFERED` for
   `PYTHONUNBUFFERED` in the Dockerfile: Python ignores unknown
   variable names, so the only symptom was buffered logs — the absence
   of behaviour, the hardest class of bug to notice.
4. **Convention-based wiring.** The `@action` was named `application`,
   so the route was `/jobs/{id}/application/` and the documented URL
   404'd — in DRF, the method name *is* the URL segment unless `url_path`
   overrides it. No configuration was wrong; a name was.
5. **A wrong enum member, found only on execution.** `User.Role.Company`
   for `User.Role.COMPANY` — Python doesn't check attribute names until
   the line runs, and that line runs only when a company signs up.
   Static happy-path testing (server starts, a GET returns 200) would
   never have touched it; the smoke test's register-a-company step did.

### The lesson the phase teaches

Every one of these survived "the code looks right" and "the server
starts". They fell to a *scripted story*: register, log in, post, apply,
apply again, apply to a closed job, read the list back. That is Night
8's smoke test doing exactly its job, and it retroactively justifies
the project's recurring pattern — defense in depth (entries 9 and 11)
meant the dead validators degraded the experience (wrong error shape,
constraint errors instead of friendly ones) instead of corrupting data.

Two follow-ups worth doing: check the smoke script into the repo
(`scripts/smoke.sh`) so the story is re-runnable after every change,
not just pasted in the README; and fix the README's clone URL, which
reads `…/job-board-api.git` — the repo is `00-job-board-api`, so the
copy-paste currently 404s.

### Status

Phase 1 (core app: models, auth, registration, jobs, applications) is
documented and smoke-verified end to end. Open items carried forward:
ownership/verified-company permissions (Phase 2 / Night 9), the
my-applications list, status updates, the entry 8 serializer cleanups,
and the smoke script check-in. Next per plan: Night 9 permissions.

### Article angles

- "Bugs that don't crash: a taxonomy of silent failures"
- "Read the error shape: what a DRF response body tells you about which layer raised it"
- "getattr with a default is a loaded foot-gun: silent None vs loud AttributeError"
- "The smoke test is a story, not a checklist: scripting the negative paths"

---

## Entry 13 — 2026-10-27 — Permission classes: IsVerifiedCompany, IsCandidate (commit `8314a99`)

### Authorization moves to the door

```python
class IsVerifiedCompany(BasePermission):
    message = "Only company accounts can do this."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.is_company:
            return False
        company = getattr(user, "company", None)
        if company is None or not company.is_verified:
            self.message = "Your company account is not verified."
            return False
        return True

class IsCandidate(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated
            and user.is_candidate
            and hasattr(user, "candidate_profile")
        )
```

Wired per-action, the idiomatic DRF way:

```python
def get_permissions(self):
    if self.action == "create":
        return [IsAuthenticated(), IsVerifiedCompany()]
    return super().get_permissions()
```

Why this shape is better than the inline checks it supersedes:

- **Permissions run before the view.** An unauthorized request is
  rejected before any handler code, serializer, or query executes —
  fail fast, and fail *outside* the business logic. The inline
  `perform_create` checks from entries 10–11 still exist as a second
  layer (the commit title says "replace"; in fact they were kept and
  are now simply unreachable on the guarded paths — defence in depth,
  though worth a comment in the code so a future reader doesn't think
  them primary).
- **The verified-company gate is a business rule, not just a role
  check.** `IsVerifiedCompany` chains three conditions — authenticated,
  company role, `company.is_verified` — tying back to the boolean that
  has been sitting on the Company model since entry 6, flipped only in
  the Django admin (`list_editable`, entry 6). Consequence worth
  stating plainly: a newly registered company can log in and browse,
  but **cannot post a job until an admin verifies it** — a deliberate
  trust gate, and the 403 message says exactly that ("Your company
  account is not verified." vs the generic "Only company accounts can
  do this." for wrong-role callers; two audiences, two messages).
- **`getattr`/`hasattr` used correctly this time.** Entry 12's war
  story was `getattr` hiding a typo'd relation name. Here absence is
  *legitimate* — a company user might genuinely have no profile row —
  and Django's `RelatedObjectDoesNotExist` subclasses `AttributeError`,
  so `getattr(user, "company", None)` and
  `hasattr(user, "candidate_profile")` are precisely the right tools.
  Same tool, opposite verdicts: the difference is whether "missing" is
  a valid state or a bug.
- **`message` as a mutable attribute** works because DRF builds fresh
  permission instances per request via `get_permissions()`; the
  tailored message never leaks across requests. (It would be a bug in
  a singleton; it is a feature here.)

### What Night 9 still owes (the ownership half)

Nothing in this commit is object-level: there is no
`has_object_permission` anywhere, so the three findings carried since
entries 10–11 stand unchanged —

1. any authenticated user can still PATCH any job (update is gated
   only by login);
2. the applicants list still answers any authenticated caller;
3. application detail is still readable by id, unscoped.

These need an ownership permission (object's `company.user` must equal
`request.user`) applied to update + the applications action, plus
queryset scoping on application retrieve. The my-applications list is
also still unbuilt. Role gates say *what kind of user* you are;
ownership says *which rows are yours* — the API now has the first and
still needs the second before any public exposure.

### Article angles

- "has_permission vs has_object_permission: the two questions every API must answer"
- "Per-action permissions with get_permissions: one viewset, several doors"
- "Verification as a state machine of one boolean: the admin-flipped trust gate"
- "getattr redemption: when a defensive default is the correct design"

---

## Entry 14 — 2026-10-28 — Object permissions: IsJobOwner, IsApplicantOwner (commit `88b6f6f`)

### The second question: which rows are yours?

Entry 13's classes answer "what kind of user are you?" at the door
(`has_permission`, runs before the view). This commit adds the second,
per-object question via `has_object_permission`, which DRF runs inside
`get_object()` — after the row is fetched, before the handler touches
it:

```python
class IsJobOwner(BasePermission):
    message = "Only the company that posted this job can do this."

    def has_object_permission(self, request, view, obj):
        company = getattr(request.user, "company", None)
        return company is not None and obj.company_id == company.id

class IsApplicantOwner(BasePermission):
    message = "You don't have access to this application."

    def has_object_permission(self, request, view, obj):
        profile = getattr(request.user, "candidate_profile", None)
        if profile is not None and obj.candidate_id == profile.id:
            return True
        company = getattr(request.user, "company", None)
        return company is not None and obj.job.company_id == company.id
```

Wiring matters as much as the classes:

- `JobViewSet.get_permissions()` now routes `update`, `partial_update`,
  **and the `applications` action** through `IsJobOwner`. The action
  inclusion is the payoff of entry 11's worst finding: the applicants
  list calls `self.get_object()`, which triggers the object check, so
  the list is owner-only without a line of code inside the action
  itself. Entry 10's "anyone can PATCH any job" and entry 11's
  "anyone can enumerate applicants" are both **closed**.
- `ApplicationViewSet` routes `retrieve` through `IsApplicantOwner` —
  entry 11's unscoped-detail (IDOR) finding is **closed**. The class
  encodes the domain's two legitimate readers in one place: the
  candidate who sent the application *or* the company whose job
  received it. Everyone else gets 403.
- **Comparisons use `_id` attributes** (`obj.company_id`,
  `obj.candidate_id`, `obj.job.company_id`) rather than fetching the
  related objects — the foreign-key values are already on the row, so
  the check costs no extra queries beyond the job lookup the
  application check needs.
- Job *detail* stays readable by any authenticated user (not routed
  through IsJobOwner) — deliberate: candidates must be able to read
  jobs they don't own. Ownership restricts *writing* and *applicant
  data*, not reading the catalogue. That asymmetry is the product
  rule, expressed in one `get_permissions` branch.

Two honest notes:

- **403, not 404, for other people's rows.** A non-owner probing an
  existing job's applicants learns that the job exists (403) rather
  than getting a camouflaging 404. That is stock DRF behaviour and the
  project's brief explicitly wants 403s; some APIs choose
  existence-hiding 404s instead — a trade-off to make consciously if
  this ever faces the public internet.
- **Names drifted slightly**: the commit title says
  `IsApplicationOwner`; the class is `IsApplicantOwner`. Trivial, but
  in a codebase where entry 12 showed names *are* wiring (actions,
  relations), consistency is worth the rename at some point.

### The dev helper: a manual test harness with exactly the right cast

`scripts/dev-helper.sh` provides `token()` (fetch a JWT for a local
user) and `login_all()`, which loads tokens for six seeded users —
companies acme/globex/initech, candidates dana/sam/riya (riya of the
README smoke test). You cannot test ownership with one user: the cast
*is* the test design — company B's token against company A's job is
the case that proves the boundary. (Small slip inside it: the header
comment says `source scripts/dev-helpers.sh`, plural; the file is
`dev-helper.sh`.) It is a manual harness, not automated tests —
`jobs/tests.py` is still the stock stub, and per the README the pytest
suite is Phase 5 work.

### Status

**Night 9 is complete**: role gates (entry 13) + ownership (this
entry). The API's authorization story is now coherent end to end —
default-deny, verified companies post, owners edit, applicants are
visible only to the two parties involved. Carried forward: the
my-applications list (Night 7 leftover), company-side status updates
and the dedicated close action, and entry 8's serializer length
cleanups + `delf`.

### Article angles

- "Two permission questions: has_permission guards the door, has_object_permission guards the row"
- "The applicants list is the crown jewels: scoping your most sensitive endpoint"
- "403 or 404 for other people's data? The existence-leak trade-off"
- "You can't test ownership with one user: casting a dev environment"

---

## Entry 15 — 2026-10-28 — Application status endpoint (commit `974be03`)

### One door for status changes

```python
@action(detail=True, methods=["patch"], url_path="status")
def set_status(self, request, pk=None):
    application = self.get_object()
    serializer = ApplicationStatusSerializer(application, data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(ApplicationSerializer(application, context=...).data)
```

with a dedicated serializer whose only field is the point:

```python
class ApplicationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = ["status"]
        extra_kwargs = {"status": {"required": True}}
```

Design points:

- **A separate write serializer for a separate privilege.** The main
  `ApplicationSerializer` keeps `status` in `read_only_fields` — the
  candidate-facing create/read paths *cannot* move a status, even by
  accident. The status endpoint uses its own one-field serializer, so
  the request contract is exactly "one status value, nothing else":
  there is no field through which a caller could also rewrite the
  cover letter or re-point the application at another job. Read
  contract and write contract evolve independently.
- **`required: True` on a PATCH is deliberate.** PATCH normally means
  "any subset may change"; here the subset has exactly one member, so
  requiring it turns an empty body into a clear 400 instead of a
  silent no-op success. The model's `TextChoices` give value
  validation (and a helpful choices list in the error) for free.
- **The permission generalised instead of duplicating.** `IsJobOwner`
  now unwraps the object — `obj.job if isinstance(obj, Application)
  else obj` — then applies the same `company_id` comparison. One class
  guards jobs *and* applications-to-jobs, routed by `get_permissions`
  for the `set_status` action; `get_object()` fires the object check
  before the serializer runs. The alternative (an
  `IsApplicationJobOwner` clone) would have doubled the surface for
  the exact bugs permissions exist to prevent.
- **The response is the full read representation**, not the one-field
  write shape — clients get the updated application as they would see
  it anywhere else, `updated_at` bumped by `auto_now`.

Notably absent, and fine for now: **transition rules**. Any status can
move to any other (a rejected application can be set straight to
offered). A real hiring pipeline might constrain that
(submitted → reviewing → interview → offered/rejected); the model
stores no history, so a status audit trail would be a bigger feature
(and later phases have a notifications/worker story it would feed).
Flagged, not blocking.

### Status

Phase 2's endpoint set is nearly complete: permissions (entries
13–14) + status (this entry). Remaining known items: the
my-applications list (candidates still can't enumerate their own
applications), the dedicated job close action, and entry 8's
serializer hygiene (`delf`, the two length mismatches). Next in the
plan come match scoring, resume upload, and search/filters.

### Article angles

- "One field, one serializer, one door: designing privileged mutations"
- "Generalise the permission, don't clone it: polymorphic object checks"
- "PATCH semantics vs required fields: turning no-ops into 400s"
- "Status machines without transition rules: when YAGNI is the right call"

---

## Entry 16 — 2026-10-28 — Skill match scoring (commit `5e57769`)

### Fifteen lines, zero framework

```python
# jobs/matching.py — no Django imports at all
def normalize_skills(skills):
    return {skill.strip().lower() for skill in skills if skill and skill.strip()}


def match_score(required_skills, candidate_skills):
    required = normalize_skills(required_skills)
    if not required:
        return None
    matches = required & normalize_skills(candidate_skills)
    return round(100 * len(matches) / len(required))
```

```python
# serializers.py
match_score = serializers.SerializerMethodField()

def get_match_score(self, obj):
    return matching.match_score(obj.job.required_skills, obj.candidate.skills)
```

- **Pure functions in their own module.** `matching.py` knows nothing
  about models, requests, or DRF — it maps two lists of strings to a
  number. That makes it the most testable code in the project (Phase
  5's pytest suite can cover it exhaustively in milliseconds, no
  database), reusable from anywhere (a future ranking query, the
  worker), and honest about its contract. Business logic that can live
  outside the framework should.
- **Normalization is the actual feature.** Raw list comparison would
  score `"Python"` vs `"python "` as a miss. Lowercasing, stripping,
  dropping blanks, and set-ifying both sides means the score measures
  skills, not typing habits — and set intersection makes duplicates
  on either side harmless. This is where the matching quality lives;
  the arithmetic is one line.
- **`None` for no requirements — the right call, currently
  undocumented.** A job listing no required skills has no denominator;
  returning 100 would claim a perfect match that means nothing, 0
  would slander every applicant. `null` ("not applicable") is the
  honest value, and it propagates to JSON as `null`. The brief asked
  for the choice to be *documented* — a docstring on `match_score` or
  a README line is still owed. (One arithmetic nuance: Python's
  `round` uses banker's rounding, so exact .5 percentages round to
  even — cosmetically irrelevant at this scale.)
- **Computed, never stored.** `SerializerMethodField` derives the
  score at read time from the two `ArrayField`s (whose symmetric
  `CharField(50)` design from entries 6/9 exists precisely for this).
  A stored score would rot the moment a candidate edits their skills
  or a company edits the job; a computed one is always current. The
  cost is trivial arithmetic per row, and the relevant relations are
  already `select_related`'d in both querysets that serialize
  applications, so lists don't pay N+1 queries for it.
- **Visible on every application representation** — applicants list,
  application detail, even the status-update response — because all of
  them render through `ApplicationSerializer`. Candidates see their
  own score too; harmless, arguably a feature (it tells them what to
  learn), and the company-facing screening use was the brief's point.

### Status

Match scoring completes the Phase 2 feature arc: permissions
(entries 13–14), status (15), scoring (16). Still outstanding: the
my-applications list, resume upload, search & filters, the dedicated
close action, and the entry 8 serializer hygiene items. 

### Article angles

- "Business logic that fits in 15 lines and imports nothing: pure modules in a Django app"
- "Normalization is the feature: why matching quality lives in strip().lower()"
- "null beats 100: honest semantics for undefined scores"
- "Computed vs stored: deriving values that can never go stale"

---

## Entry 17 — 2026-10-30 — S3 storage backend via LocalStack (commit `27e7c68`)

### Emulate the cloud, configure the real thing

```python
# settings.py
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")            # required
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", "us-east-1")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", "") or None        # ← the seam
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = True

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3.S3Storage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
```

```yaml
# docker-compose.yml (excerpt)
localstack:
  image: localstack/localstack:2026.10.4
  environment: [SERVICES=s3, ...]
  volumes: ["./localstack/init/ready.d:/etc/localstack/init/ready.d:ro"]
  healthcheck: awslocal s3api head-bucket --bucket $AWS_STORAGE_BUCKET_NAME
api:
  depends_on:
    db: {condition: service_healthy}
    localstack: {condition: service_healthy}
```

- **The endpoint URL is the whole portability story.** django-storages
  + boto3 talk to anything that speaks the S3 API; `AWS_S3_ENDPOINT_URL`
  decides where that is — `http://localstack:4566` in dev, empty
  (→ `None`) against real AWS. *No code changes* between laptop and
  cloud, which is exactly the seam Phase 4's Azure Blob swap and
  Project 01's real deployment will reuse. LocalStack gives that a
  free, offline, resettable stand-in: S3 only (`SERVICES=s3`) keeps it
  light.
- **Bucket lifecycle is Compose's job.** A `ready.d` init script
  (`awslocal s3 mb s3://$AWS_STORAGE_BUCKET_NAME`, fail-fast shell
  options) creates the bucket once LocalStack is ready; the same env
  var names the bucket in settings, the init script, and the
  healthcheck — one source of truth. The healthcheck is a
  `head-bucket` against the *actual bucket*, and `api` waits for
  `service_healthy` on both infrastructure services, so the first
  upload can never race bucket creation.
- **Private by default, again** (the project's recurring posture):
  `AWS_DEFAULT_ACL = None` (objects are not public), signed URLs via
  `AWS_QUERYSTRING_AUTH` (access is a capability with an expiry, the
  right shape for resumes), and `FILE_OVERWRITE = False` so two
  candidates uploading `resume.pdf` get distinct stored names instead
  of one silently replacing the other.
- Scope honesty: this commit is the **backend only** — there is no
  `resume` FileField yet (migrations still end at `0004`) and no
  upload endpoint or type/size validation. Those are the feature's
  next steps; the storage layer they will stand on is ready.

### Findings

1. **Env-var name drift in `.env.example`.** It defines
   `AWS_S3_REGION` but settings read `AWS_S3_REGION_NAME`; it defines
   `LOCAL_STACK_AUTH_TOKEN` but Compose expects
   `LOCALSTACK_AUTH_TOKEN`. Both fail *silently* today — the region
   falls back to a default that happens to equal the intended value —
   which is entry 12's silent-failure pattern in configuration form:
   the day someone changes the region in `.env`, nothing happens, and
   nothing says why. Names are contracts; the example file is the
   contract's documentation.
2. **Check the auth token's home.** `docker-compose.yml` appears to
   carry a literal LocalStack auth-token value, and `.env.example`
   carries a token-shaped value too (both are masked in my tooling, so
   I cannot tell placeholders from real values). If either is real:
   it belongs in `.env` (gitignored), not in a committed file —
   especially not in `.env.example`, whose entire purpose is to be
   copied and shared. This is precisely what the Gitleaks step in
   Project 01 will scan for.
3. **Init script idempotency.** `s3 mb` errors when the bucket
   already exists (e.g. a container restart that preserves
   LocalStack's state); with `set -e` the script then fails on every
   subsequent boot. A `head-bucket || mb` guard makes it a true
   no-op-when-done, matching the Ansible idempotency standard from
   Nights 1–2.

### Article angles

- "One env var is the whole cloud strategy: endpoint-URL portability with django-storages"
- "LocalStack in Compose: healthcheck on the bucket, not the process"
- "Private by default for user files: ACL None, signed URLs, no overwrites"
- "Configuration drift is a silent failure too: .env.example as contract documentation"

---

## Entry 18 — 2026-10-30 — Resume upload (commit `d6c618e`)

### A deliberate divergence from the brief

The brief put `resume` on CandidateProfile with a profile upload
endpoint. This commit puts it on **Application** instead:

```python
# models.py
resume = models.FileField(upload_to=resume_upload_path,
                          validators=[validate_resume], blank=True)

def resume_upload_path(instance, filename):
    extentsion = Path(filename).suffix.lower()
    return f"resume/job-{instance.job_id}/{uuid.uuid4().hex}{extentsion}"
```

and the serializer makes it `required: True` even though the model
allows blank. The trade is worth naming: per-application resumes let a
candidate tailor the file to the job (what real applicants do), at the
cost of re-uploading per application and having no single "current
resume" on the profile. The model/API split is also deliberate —
`blank=True` keeps admin and fixtures flexible, while the API contract
says an application without a resume is incomplete. Two layers, two
audiences, again (entries 8/11).

### Validation in three layers, cheapest first

```python
# validators.py
MAX_RESUME_SIZE = 5 * 1024 * 1024
RESUME_SIGNATURES = {".pdf": b"%PDF-", ".docx": b"PK\x03\x04"}

def validate_resume(file):
    extension = Path(file.name).suffix.lower()
    if extension not in RESUME_SIGNATURES:
        raise ValidationError("Only PDF and DOCX files are allowed.")
    if file.size > MAX_RESUME_SIZE:
        raise ValidationError("Resume file size should not exceed 5 MB.")
    file.seek(0)
    header = file.read(len(RESUME_SIGNATURES[extension]))
    file.seek(0)
    if header != RESUME_SIGNATURES[extension]:
        raise ValidationError("Invalid file signature.")
```

- **Extension allowlist** — necessary, nowhere near sufficient: anyone
  can rename `malware.exe` to `malware.pdf`.
- **Size cap** from `file.size` metadata, before reading a single byte
  of content.
- **Magic-byte signature** — the file must actually *begin* as what
  its name claims: `%PDF-` for PDF, `PK\x03\x04` (the ZIP container
  signature) for DOCX. The `seek(0)` before *and after* reading is the
  detail that makes it correct: the storage layer must receive the
  stream rewound, or S3 gets a truncated file starting mid-header.
- The validator hangs on the **model field**, not just the serializer,
  so every write path — API, admin, shell, future worker — enforces
  the same rules. Validation that lives only in one view is validation
  with a back door.
- Honest limit: the DOCX check proves "is a ZIP", not "is a Word
  document" — a renamed plain ZIP passes. Proving more means opening
  the archive and checking for `word/document.xml`; proportionate to
  add if uploads ever become less trusted, overkill for this phase.
  (And a cosmetic sighting: the local variable `extentsion` joins
  `delf` in the harmless-typo collection.)

### Stored names are a security decision

`upload_to` discards the user's filename entirely: files land at
`resume/job-<id>/<uuid4 hex>.<ext>` in the bucket. That one function
removes whole bug classes — no collisions between users, no path
traversal or hostile characters from filenames, no leaking the
original filename (which often contains the candidate's full name) —
and UUID names are unguessable, a second layer under the signed URLs
from entry 17. The response exposes the file through the serializer's
FileField, which produces a signed, expiring URL from the S3 backend:
the company opens a resume via a capability link, not a public path.

### Status

The Phase 2 feature list is now complete in substance: permissions,
ownership, status, match scoring, resume storage + upload. Remaining
smaller items: search & filters, the my-applications list, the close
action, match-score documentation, and the entry 8 hygiene cleanups.

### Article angles

- "Extension checks are a lie: magic-byte validation for uploads"
- "seek(0) twice: the file-pointer hygiene nobody tells you about"
- "Throw away the filename: upload_to as a security boundary"
- "Profile resume or per-application resume? Modelling what applicants actually do"

---

## Entry 19 — 2026-10-30 — Presigned resume downloads (commit `9b20ee8`)

### Don't hand out URLs in representations; mint them on demand

Entry 18's design had a quiet flaw worth fixing, and this commit fixes
it: the application serializer embedded the resume's signed URL in
every representation. A URL in a response is a bearer capability —
whoever holds it (logs, caches, a forwarded screenshot, the wrong
reader of the applicants list) can download the file until it expires,
with no further authorization check. The new shape:

```python
# serializers.py — resume is write-only now; responses carry a boolean
extra_kwargs = {"resume": {"required": True, "write_only": True}}
has_resume = serializers.SerializerMethodField()   # bool(obj.resume)

# views.py — a dedicated, permission-gated minting endpoint
@action(detail=True, methods=["get"])
def resume(self, request, pk=None):
    application = self.get_object()                # IsApplicantOwner fires here
    if not application.resume:
        raise NotFound("This application has no resume.")
    return Response({
        "url": resume_download_url(application),
        "expires_in": settings.RESUME_URL_EXPIRE_SECONDS,   # 300
    })
```

- **Authorization happens at minting time.** The URL exists only
  because a request just passed `IsApplicantOwner` (entry 14) — the
  candidate who owns the application or the company that owns the job.
  Representations share freely; capabilities don't leak through them.
- **Five minutes, on purpose.** `RESUME_URL_EXPIRE_SECONDS = 300` is
  long enough to click, short enough that a leaked link is nearly
  worthless. The response states the expiry (`expires_in`) instead of
  letting clients guess — contracts should say their own limits.

### The two-endpoint problem, and why presigning is local

```python
# storage.py
@lru_cache
def _public_s3_client():
    return boto3.client("s3",
        endpoint_url=settings.AWS_S3_PUBLIC_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"))

def resume_download_url(application):
    return _public_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": ..., "Key": application.resume.name,
                "ResponseContentDisposition":
                    f'attachment; filename="resume-{application.id}{ext}"'},
        ExpiresIn=settings.RESUME_URL_EXPIRE_SECONDS)
```

```python
# settings.py
AWS_S3_ENDPOINT_URL        = env("AWS_S3_ENDPOINT_URL", "") or None
AWS_S3_PUBLIC_ENDPOINT_URL = env("AWS_S3_PUBLIC_ENDPOINT_URL", "") or AWS_S3_ENDPOINT_URL
```

- **Presigned URLs are computed locally** — SigV4 signing is pure
  cryptography over the request parameters; boto3 never calls S3 to
  mint one (the commit title's "validate S3 signatures locally" point).
  Consequence: the signature binds the *host* the URL will be used
  against, so the host baked in at signing time is part of the
  credential.
- Hence **two endpoint settings**. Storage operations from inside
  Compose use `http://localstack:4566` — a hostname only containers
  can resolve. A URL signed for that host is dead on arrival in the
  developer's browser. The public client signs for
  `AWS_S3_PUBLIC_ENDPOINT_URL` (e.g. `http://localhost:4566`), falling
  back to the internal endpoint when unset — which is exactly right
  for production, where both are `None` and real S3 is the only host.
  This is the single most common LocalStack integration bug, solved
  at the right layer: configuration, not code branches.
- **`ResponseContentDisposition: attachment`** makes the browser
  download rather than render inline, under a sanitized name
  (`resume-42.pdf`) — the UUID storage key from entry 18 stays an
  internal detail, and recruiters' download folders stay readable.
- `@lru_cache` on the client factory: boto3 clients are thread-safe
  and comparatively expensive to construct; one per process is the
  right granularity.

### Status

Resume flow is now complete end to end: validated upload (entry 18)
→ private storage (entry 17) → owner-gated, short-lived download
(this entry). Remaining smaller items: search & filters, the
my-applications list, the close action, match-score documentation,
entry 8 cleanups.

### Article angles

- "A URL in your API response is a bearer token: mint capabilities, don't embed them"
- "The LocalStack presign trap: why your signed URL 404s from the host"
- "SigV4 presigning is local math — and the host is part of the signature"
- "expires_in: saying your contract's limits out loud"

---

## Entry 20 — 2026-10-30 — Search, filters, ordering (commit `e860e22`)

### Three backends, one list endpoint

```python
filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
filterset_class = JobFilter
search_fields = ["title", "description", "company__name"]
ordering_fields = ["created_at", "title"]
ordering = ["-created_at"]
```

```python
class JobFilter(django_filters.FilterSet):
    location = django_filters.CharFilter(lookup_expr="icontains")
    skills = django_filters.CharFilter(method="filter_skills")

    class Meta:
        model = Job
        fields = ["job_type", "location", "skills"]

    def filter_skills(self, queryset, name, value):
        skills = [s.strip().lower() for s in value.split(",") if s.strip()]
        if not skills:
            return queryset
        return queryset.filter(required_skills__overlap=skills)
```

- **Each tool does its own job.** django-filter handles structured
  filtering (`?job_type=full_time&location=van`), DRF's `SearchFilter`
  handles free text (`?search=` → icontains OR-ed across title,
  description, and company name), `OrderingFilter` whitelists sortable
  fields (`?ordering=title`) over a sane default (`-created_at`). The
  three compose in a single request — filter AND search AND order —
  because each backend only narrows or arranges the queryset.
  `ordering_fields` as a whitelist matters: clients can sort by what
  is offered, not by arbitrary columns.
- **Skills filtering is a PostgreSQL conversation.** `?skills=python,django`
  becomes `required_skills__overlap=[...]` — the array overlap
  operator (`&&`): jobs requiring **any** of the listed skills.
  ANY-match is the right discovery semantic (ALL-match hides a job
  needing python+go from a python developer), and it is worth stating
  consciously, because `__contains` (ALL) is one word away and means
  something very different. An empty `skills=` degrades to unfiltered
  rather than erroring.
- **The invariant that makes it work: normalize at write.** Array
  overlap is exact element comparison — a job stored with `"Python"`
  would *never* match a query for `"python"`. So
  `JobSerializer.validate_required_skills` canonicalizes on the way
  in (strip, lowercase, drop blanks, de-duplicate order-preservingly
  via `dict.fromkeys`), the filter canonicalizes the query identically,
  and `matching.normalize_skills` (entry 16) canonicalizes at scoring
  time. Three call sites, one rule, and the database stays clean
  enough for exact operators. Write-time normalization beats
  read-time forgiveness: fix the data once, query it cheaply forever.
  One asymmetry remains — candidate skills from registration aren't
  normalized at write. Scoring doesn't care (it normalizes in
  memory), and nothing queries candidate skills by array operators,
  so it is cosmetic today; the day a "candidates matching X" query
  appears, it becomes a bug of exactly the shape this commit fixed
  on the job side.

### Status

Job discovery is complete per the brief. The candidates' side of the
brief's search night — a my-applications list with a `?status=`
filter — is still unbuilt: `ApplicationViewSet` has no list action at
all, making the my-applications list the longest-carried open item in
the project (first flagged in entry 11). Also still open: the job
close action, Redis caching (planned Oct 29, no commit yet), the
match-score docstring, and entry 8's cleanups.

### Article angles

- "Normalize at write, query exactly: making PostgreSQL array operators usable"
- "ANY vs ALL: the one-word difference between overlap and contains"
- "Three filter backends walk into a viewset: composing DRF query features"
- "Ordering whitelists: the sort parameter is an attack surface too"

---

## Entry 21 — 2026-10-31 — README updated for Phase 2 (commit `f83b78f`)

A short entry for a documentation habit worth keeping: at the phase
boundary, the README was rewritten to match the system as built —
status ("Phase 2 (business logic and permissions) complete"), an
updated one-line description naming permissions, match scoring, S3
resumes and search, and the honest remainder (worker, operations
endpoints, tests, cloud deployment still to come). Documentation
updated at the moment the work lands ages well; documentation updated
"later" describes a system that no longer exists. (One lag: the Redis
caching in entry 22 landed the same evening, after this README pass —
the next sync should add it.)

---

## Entry 22 — 2026-10-31 — Redis caching with versioned keys (commit `0ce85a6`)

### Cache invalidation: don't delete keys, retire a generation

```python
# jobs/cache.py
JOB_LIST_VERSION_KEY = "jobs:list:version"

def job_list_cache_key(request):
    params = sorted(request.query_params.lists())
    digest = hashlib.sha256(f"{request.get_host()}|{params}".encode()).hexdigest()
    return f"jobs:list:v{_current_version()}:{digest}"

def invalidate_job_list():
    def bump():
        try:
            cache.incr(JOB_LIST_VERSION_KEY)
        except ValueError:
            cache.add(JOB_LIST_VERSION_KEY, int(time.time()), timeout=None)
        except RedisError:
            logger.warning("Could not invalidate the job list cache", exc_info=True)
    transaction.on_commit(bump)
```

Three decisions carry the design:

- **A version counter instead of key deletion.** Filter/search/page
  combinations make the keyspace unbounded — you cannot enumerate
  what to delete. Instead every list key embeds a generation number;
  invalidation increments the generation and every old key becomes
  unreachable garbage that its 60-second TTL reaps. Delete-by-oblivion:
  O(1), race-free, no key scans in production Redis.
- **The counter starts at `int(time.time())`, not 1.** If Redis is
  flushed or restarted, a counter restarting at 1 could collide with
  surviving keys from a previous life (or another environment sharing
  the instance). An epoch-seconds starting value makes generations
  monotonically unique across incarnations — a one-line defence
  against a failure mode most implementations never think of.
  `cache.add` (set-if-absent) makes the lazy initialisation
  race-safe between workers.
- **Invalidation waits for commit.** Signals fire on save, but the
  bump is registered with `transaction.on_commit`: if the surrounding
  transaction rolls back, the cache is *not* invalidated for a change
  that never happened; if it commits, no reader can refill the cache
  with pre-commit data in the gap. Signals without `on_commit` are
  the classic source of "the cache shows data that doesn't exist /
  doesn't show data that does" bugs.

### Signals watch the neighbours too

`jobs/signals.py` hooks `post_save`/`post_delete` for **Job and
Company** (wired in `AppsConfig.ready()`). Company is the perceptive
inclusion: the job list payload embeds `company.name`, so a company
rename changes list content without any Job row changing. Watching
only the model you cache is the standard miss; watching the models
whose data *appears in* the cached payload is the correct rule.
Known limit: bulk `QuerySet.update()` bypasses signals entirely —
the 60 s TTL is the backstop, which is exactly why TTL and versioning
are both present.

### Graceful fallback: the cache may die, the API may not

```python
def list(self, request, *args, **kwargs):
    try:
        key = job_list_cache_key(request)
        cached = cache.get(key)
    except RedisError:
        logger.warning("Job list cache unavailable", exc_info=True)
        return super().list(request, *args, **kwargs)
    if cached is not None:
        response = Response(cached); response["X-Cache"] = "HIT"; return response
    response = super().list(request, *args, **kwargs)
    if response.status_code == 200:
        try: cache.set(key, response.data, timeout=settings.JOB_LIST_CACHE_SECONDS)
        except RedisError: logger.warning(...)
    response["X-Cache"] = "MISS"
    return response
```

Every Redis touch is wrapped; failures log and degrade to plain
database reads. Only 200s are cached (an error must never become the
cached answer), the paginated payload is cached per exact query
string (each filter/search/page combination its own entry), and the
`X-Cache: HIT/MISS` header makes the whole mechanism externally
provable — the brief's acceptance test is literally "make the same
request twice and diff the headers." Keys deliberately exclude the
user: the job list payload is identical for every authenticated
reader, so one entry serves all — safe *because* the serializer has
no per-user fields, a property to re-check if that ever changes.

Infrastructure notes: Redis 7.4 (alpine) joins Compose with a
`redis-cli ping` healthcheck, `REDIS_URL` comes from env with the
usual fail-fast, and Django's built-in `RedisCache` backend + the
`redis` client are used — no django-redis dependency needed for this
scope. Also visible in Compose now: LocalStack publishes
`127.0.0.1:4566` (loopback only — the public presign endpoint from
entry 19 made reachable from the host, without exposing it to the
network) and runs with `S3_SKIP_SIGNATURE_VALIDATION=0`, so local
signature behaviour matches real AWS instead of silently accepting
anything.

### Status

Phase 3 Step 1 (brief Night 15) is complete: Redis in Compose,
versioned job-list caching, signal + on-commit invalidation, graceful
fallback. Remaining known items: the my-applications list and close
action (Phase 2 leftovers), the background worker + idempotency
(Phase 3's next steps), match-score docstring, entry 8 cleanups.

### Article angles

- "Don't delete cache keys — retire a generation: versioned invalidation"
- "transaction.on_commit: the signal handler's missing half"
- "Start your counter at time.time(): cache generations across Redis restarts"
- "Cache the payload's dependencies, not just its model: why Company signals matter"
- "Graceful fallback as a design rule: the cache may die, the API may not"

---

## Entry 23 — 2026-10-31 — Queue interface + SQS with DLQ (commit `a127b5c`)

### A provider-neutral seam, drawn before the worker exists

```python
# cloud/queue.py
@dataclass(frozen=True)
class QueueMessage:
    id: str
    body: dict            # already JSON-parsed at the boundary
    receipt_handle: str

class Queue(ABC):
    @abstractmethod
    def send(self, body: dict) -> str: ...
    @abstractmethod
    def receive(self, max_messages: int = 10, wait_seconds: int = 20) -> list[QueueMessage]: ...
    @abstractmethod
    def delete(self, message: QueueMessage) -> None: ...

class SQSQueue(Queue): ...   # boto3 against AWS_SQS_ENDPOINT_URL

@lru_cache(maxsize=1)
def get_queue() -> Queue:
    return SQSQueue(settings.SQS_QUEUE_NAME)
```

- **The interface hides the provider's vocabulary.** Callers will
  think in `dict` bodies and `QueueMessage`s; SQS-isms (MessageId,
  ReceiptHandle, JSON string bodies) exist only inside `SQSQueue`,
  which serializes on send and parses on receive. That boundary is
  the entire Phase 4 strategy (Azure Service Bus = one new class
  implementing three methods) purchased in advance, cheaply. (The
  brief sketched a `Protocol`; an ABC was used instead — structural
  vs nominal typing. ABC enforces the contract at instantiation and
  reads clearly; the cost is that the future Azure class must
  explicitly inherit. Equivalent for this codebase, worth choosing
  consciously.)
- **Eager URL resolution in `__init__`** — `get_queue_url` fails fast
  if the queue doesn't exist, and Compose's healthcheck (extended to
  `sqs get-queue-url`) guarantees it does before the API starts. The
  `lru_cache`d `get_queue()` factory mirrors the storage client
  pattern from entry 19: one client per process, built once.
- **Defaults encode the right polling shape**: batches of 10 and
  20-second long polling — the worker step won't busy-spin against
  the queue.

### The DLQ is created first, on purpose

```bash
# localstack/init/ready.d/create-queues.sh
dlq_url=$(awslocal sqs create-queue --queue-name "${SQS_QUEUE_NAME}-dlq" ...)
dlq_arn=$(awslocal sqs get-queue-attributes --queue-url "$dlq_url" ...)
# main queue: VisibilityTimeout 30, RedrivePolicy {deadLetterTargetArn, maxReceiveCount: 3}
awslocal sqs create-queue --queue-name "${SQS_QUEUE_NAME}" --attributes file:///tmp/queue-attributes.json
```

A message that keeps failing gets received, returns after the 30 s
visibility timeout, and after **3 receives** SQS itself moves it to
the dead-letter queue — poison messages stop blocking the line but
are preserved for inspection instead of vanishing. Wiring this at
provisioning time (not "later, when there's a worker") means the
failure path exists before the first message ever flows. Unlike the
bucket script, `create-queue` is naturally idempotent — same name
and attributes returns the existing queue — so restarts are boring.
Compose adds its own fail-fast: `${SQS_QUEUE_NAME:?set ...}` refuses
to start with a clear message when the variable is missing, and
`SERVICES=s3,sqs` scopes LocalStack to exactly two services.

Notes for the worker step that follows:

- The interface has **no visibility-extension method** yet. If a
  handler ever runs longer than 30 s, its message reappears
  mid-processing and gets handled twice — the idempotency rules of
  the next step are the real defence, and a
  `change_message_visibility` method is the escape hatch if needed.
- `receive()` parses every body as JSON in one comprehension: one
  malformed (non-JSON) message in a batch would raise and take the
  whole batch down with it. Own-code producers always send JSON, so
  the exposure is small — per-message error isolation belongs in the
  worker loop.
- Two region settings now exist — `AWS_S3_REGION_NAME` (storage,
  presigning) and the new `AWS_REGION` (queue). Both are read
  correctly, but they can silently disagree; one shared region
  variable would remove a config-drift foot-gun (entry 17's family).

### Status

Queue infrastructure is ready: interface, SQS implementation, DLQ
with redrive, healthcheck gating. Next: the producer side (publishing
application events on commit) and the worker itself with idempotent
handlers.

### Article angles

- "Buy the port before the ship: provider-neutral interfaces in a Django monolith"
- "Dead-letter queues: designing the failure path before the first message"
- "ABC vs Protocol in Python: choosing your contract style on purpose"
- "maxReceiveCount and visibility timeouts: the two numbers that define your retry policy"
