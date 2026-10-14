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
