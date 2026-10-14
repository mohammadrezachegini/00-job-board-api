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
