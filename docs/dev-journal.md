# Dev Journal — 00-job-board-api

Narrative log of how this project is being built, written in plain English.
The automatic commit-by-commit record lives in `docs/changelog.md`.
This journal is updated as new work is pushed.

## 2026-10-12 — Project started

- First commit: Django project scaffold created with `uv` — `manage.py` and a
  `config/` package (settings, urls, wsgi, asgi).
- Stack chosen in `pyproject.toml`: Python 3.12+, Django 5.2, Django REST
  Framework, and psycopg (PostgreSQL driver).
- `.gitignore` added in the second commit.

## 2026-10-13 — Documentation automation connected

- Repository connected to the assistant (read access and normal file writes
  verified; workflow files under `.github/workflows/` need a separate GitHub
  permission the assistant's app does not have, so the workflow file itself is
  added manually by the repo owner).
- `docs/changelog.md` seeded — from now on the changelog workflow regenerates
  it automatically from commit messages on every push.
- This dev journal created; it will be updated as new work lands.
- Evening: the repo owner pushed `.github/workflows/changelog.yml` himself
  (commit `506097c`, "ci: add changelog workflow") — the one file the
  assistant's app cannot write. The workflow ran on that same push: about
  15 seconds later the Actions bot committed `468fb51`
  ("docs: update changelog") with the regenerated changelog listing all
  5 commits, and it did not loop. Documentation automation is now live:
  every future push updates the changelog automatically, and this journal
  gets a new entry as work lands.
- Later that evening (commit `75eb0d1`): Night 3's core work — settings
  now read everything from environment variables through a small custom
  `env()` helper that fails fast on missing required values, the database
  switched from SQLite to PostgreSQL, DRF was registered in
  `INSTALLED_APPS`, and a committable `.env.example` template was added.
  Technical breakdown in `docs/technical-notes.md`, entry 3. Still open
  from Night 3: the Docker Compose file for PostgreSQL and the first
  migration run against it.
- Still later that evening (commits `aa01775` and `18de30b`, both
  "Add dev Dockerfile and Compose stack with PostgreSQL 17"): Night 3's
  missing half landed. The project now has a development `Dockerfile`
  (Python 3.12 slim, dependencies installed with `uv` from the lockfile,
  app running as a non-root user on port 8006), a `docker-compose.yml`
  that starts PostgreSQL 17 alongside the API, and a `.dockerignore`
  that keeps `.env`, `.git`, and caches out of the image. The database
  container has a healthcheck, and the API waits until the database is
  actually healthy — not just started — before it boots. Inside Compose
  the API is pointed at the database by its service name (`db`) instead
  of `localhost`, the code folder is mounted into the container so edits
  show up live, and database data lives in a named volume (`pgdata`) so
  it survives container restarts. Technical breakdown in
  `docs/technical-notes.md`, entry 4. Still open: the first migration
  run against the Compose PostgreSQL is not shown in these commits.
- 2026-10-21 (commit `2dc2737`, "Add custom User model with company/candidate
  roles; reset DB"): the accounts foundation lands. A new `jobs` app holds a
  custom `User` model that extends Django's built-in user with a `role` field —
  every account is either a company or a candidate — plus small `is_company` /
  `is_candidate` helper properties for the permission checks coming later.
  Email is now unique per account. Settings point Django at this model
  (`AUTH_USER_MODEL`), and the database was reset with a fresh initial
  migration, which is the standard price of swapping the user model. This is
  the first piece of Night 4's model work; the Job and Application models are
  still to come. Technical breakdown in `docs/technical-notes.md`, entry 5.
- 2026-10-21, an hour later (commit `6c728f5`, "Add Company and
  CandidateProfile models with admin"): the two profile models land, one per
  role, each linked one-to-one to a user account. A company gets a name,
  website, description, and an `is_verified` flag (off by default — this is
  the flag the verified-company permission will check in Night 9). A
  candidate gets a headline, location, and their skills stored as a real
  PostgreSQL array, ready for the match scoring in Night 11. Both models are
  registered in the Django admin, with the user admin extended so staff can
  see and set roles, and verify companies straight from the list view.
  Migration `0002` included. Remaining for Night 4: the Job and Application
  models. Technical breakdown in `docs/technical-notes.md`, entry 6.
- 2026-10-21, later (commit `be15a45`, "updated changelog.yaml"): the
  changelog workflow got its hardening update. That evening's paired doc
  pushes had exposed a race in version 1 — two runs overlapping, one dying
  with exit code 1 when its push was rejected because the branch had moved
  (the changelog itself stayed correct, since the winning run rebuilds it
  from the full history). Version 2, pushed by the repo owner, checks out
  the branch at its current head and retries generate-commit-push up to
  three times from the newest head, moves to `actions/checkout@v5` (the v4
  line rides the deprecated Node 20 runtime), and pins the runner to
  Ubuntu 24.04 instead of the moving `ubuntu-latest` label. First run
  under v2 landed the bot's changelog commit about 18 seconds after the
  push. Full diagnosis in `docs/technical-notes.md`, entry 1 addendum.
- 2026-10-21, minutes later (commit `289e2e5`, "Fix soem typos"): the
  `create_at` typo on CandidateProfile is renamed to `created_at` in the
  model, matching Company. Caught in review the same night: the rename
  migration has not been generated yet — migration `0002` still defines
  `create_at`, so model and database schema are temporarily out of sync
  until `makemigrations` (answering yes to the rename prompt, so it becomes
  a data-preserving RenameField) and `migrate` are run and pushed. The
  cosmetic `JobBoradUserAdmin` class-name typo in admin.py was left as is.
- 2026-10-22 (commit `21bf705`): the missing rename migration lands —
  `0003_rename_create_at_candidateprofile_created_at`, a data-preserving
  `RenameField`. Model and schema are back in sync and the typo fix from
  the night before is now genuinely complete. Recorded honestly: the
  commit message says "Add Job and Application models with
  unique-application constraint", but the commit contains only the rename
  migration — verified by reading the tree: no Job or Application model
  exists in the repo yet, and no unique constraint. Those models are
  presumably still local or yet to be written; Night 4 remains open on
  exactly that piece. Side effect worth knowing: the auto-generated
  changelog copies commit messages verbatim, so it now credits this
  commit with work it does not contain — one more reason messages are
  written from the diff, not from the plan.
- 2026-10-22 (commit `82f3a42`, "Add JWT auth (SimpleJWT)"): authentication
  plumbing lands — the first half of Night 5. SimpleJWT is added as a
  dependency, DRF is configured to authenticate with JWTs and to require
  authentication by default, and the token endpoints are live at
  `POST /api/auth/token/` and `POST /api/auth/token/refresh/` (access
  tokens live 15 minutes, refresh tokens 1 day), matching the project
  brief's API layout. Still missing for Night 5: the
  `register/company/` and `register/candidate/` endpoints — there are no
  views or serializers yet. And Night 4's Job and Application models are
  still outstanding; tonight's work jumped ahead to auth. Technical
  breakdown in `docs/technical-notes.md`, entry 7.
