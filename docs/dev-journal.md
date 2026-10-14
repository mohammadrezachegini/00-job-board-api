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
