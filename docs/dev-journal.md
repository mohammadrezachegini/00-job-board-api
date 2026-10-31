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
- 2026-10-23 (commit `f9b17a0`, "Add company and candidate registration
  endpoints"): Night 5 is complete. `POST /api/auth/register/company/`
  and `POST /api/auth/register/candidate/` are live. Both share a base
  registration serializer (username/email/password with proper
  validation), the server assigns the role itself — a client cannot
  choose or escalate its own role — and user + profile are created in a
  single database transaction, so a failed registration leaves nothing
  half-written. Two small mismatches to fix later, noted in the technical
  notes: the serializer accepts longer `location` and `skills` values
  than the database columns allow. Only Night 4's Job and Application
  models remain from the foundation stretch. Technical breakdown in
  `docs/technical-notes.md`, entry 8.
- 2026-10-23 (commit `05f4cbc`, "Add Job and Application models with
  unique-application constraint" — the title is accurate this time):
  Night 4 is complete. The Job model (company, title, description,
  location, job type, required skills, open flag) and the Application
  model (job, candidate, cover letter, status pipeline) are in, with
  migration `0004`, admin screens for both, and the database-level rule
  that a candidate can apply to the same job only once. With this, the
  whole foundation stretch — settings, Docker, models, auth,
  registration — is done, and Night 6's job CRUD has its model to stand
  on. Technical breakdown in `docs/technical-notes.md`, entry 9.
- 2026-10-23 (commit `cdb8ae2`, "Add job endpoints"): Night 6's job
  endpoints are built — `GET /api/jobs/` (open jobs only, paginated 20
  per page), job detail, company-only creation (the company is taken
  from the login token, never from the request body), and updates. There
  is deliberately no delete: closing a job is a state change, not an
  erasure. Review found three things to harden, detailed in the
  technical notes: a wrong exception type turns the "companies only"
  rejection into a 500 instead of a 403; updates don't yet check that
  the job belongs to the caller's company; and the brief's dedicated
  close action (`POST /jobs/{id}/close/`) plus public browsing aren't in
  yet — those sit naturally with Night 9's permissions work.
  Technical breakdown in `docs/technical-notes.md`, entry 10.
- 2026-10-24 (commit `88ea9ca`, "Add application endpoints"): candidates
  can now apply — `POST /api/applications/` takes the candidate from the
  token, rejects closed jobs, and a duplicate application returns a
  clean 400 ("You have already applied for this job") instead of a
  server error, enforced twice: a friendly pre-check and the database
  constraint caught and translated. Companies can list a job's
  applicants at `GET /api/jobs/{id}/applications/`, and the Night 6
  "500 instead of 403" bug is fixed (DRF's `PermissionDenied` now).
  Still open after this commit, per the technical notes: the
  my-applications list from the brief isn't built yet; the applicant
  list and application detail don't yet restrict who can see them
  (ownership scoping — Night 9's territory, but applicant data is
  sensitive); and two small serializer mismatches from entry 8 remain
  unfixed despite the commit title mentioning typos.
  Technical breakdown in `docs/technical-notes.md`, entry 11.
- 2026-10-24 (commits `c23809b` + `1f47139`, "Add Phase 1 README"): the
  repo gets a proper README — architecture diagram, endpoint table, setup
  instructions, environment variable reference, design decisions, and a
  "What Broke and How I Fixed It" section. Just as important, the README
  records that Phase 1 was verified with a real end-to-end smoke test
  over HTTP (register company → post job → register candidate → apply →
  company reads its applicant list), which is Night 8's core task done in
  substance — and it was the smoke test that surfaced the subtle bugs in
  that war-stories section. The README is honest about scope, too:
  owner-only rules and verified-company checks are openly listed as
  Phase 2 work. One slip: the clone URL in Setup is missing the repo
  name's `00-` prefix. Technical breakdown in `docs/technical-notes.md`,
  entry 12.
- 2026-10-27 (commit `8314a99`, "Add IsVerifiedCompany and IsCandidate
  permissions"): Night 9 begins — role checks move out of the views into
  real DRF permission classes. Posting a job now requires a *verified*
  company: a fresh company account gets a clear 403 ("Your company
  account is not verified.") until an admin verifies it in Django
  admin. Applying requires a candidate account with a profile. The
  checks now run before the view even executes, which is where
  authorization belongs. Still open from the earlier reviews: ownership
  rules (who can update a job, who can see an applicant list) — no
  object-level permission exists yet — and the my-applications list.
  Technical breakdown in `docs/technical-notes.md`, entry 13.
- 2026-10-28 (commit `88b6f6f`, "Add IsJobOwner and IsApplicationOwner
  object permissions; add dev helper script"): Night 9 is complete.
  Ownership has arrived: only the company that posted a job can update
  it or view its applicants, and an application can be read only by the
  candidate who sent it or the company that received it. This closes
  the three authorization holes flagged in the reviews of Nights 6–7.
  The commit also adds `scripts/dev-helper.sh` — shell helpers that log
  in the six local test users (three companies, three candidates),
  which is exactly the cast needed to prove one company can't touch
  another's jobs. Remaining known items: the my-applications list, and
  the small serializer cleanups from entry 8. Technical breakdown in
  `docs/technical-notes.md`, entry 14.
- 2026-10-28 (commit `974be03`, "Add status endpoint (job owner only)"):
  companies can now move an application through the pipeline —
  `PATCH /api/applications/{id}/status/` accepts only a `status` value
  and only from the company that owns the job. The permission class
  from Night 9 was generalised rather than duplicated: `IsJobOwner`
  now understands both Job and Application objects. Status stays
  read-only everywhere else, so this endpoint is the single door for
  changing it. Technical breakdown in `docs/technical-notes.md`,
  entry 15.
- 2026-10-28 (commit `5e57769`, "Add skill match score (matching.py)"):
  applications now carry a `match_score` — the percentage of a job's
  required skills the candidate actually has, computed fresh on every
  response (never stored). Skill names are compared case-insensitively
  with whitespace trimmed, and a job with no required skills returns
  `null` rather than a fake 100. The scoring logic lives in its own
  tiny pure-Python module with no Django imports, ready to be unit
  tested in Phase 5. Technical breakdown in `docs/technical-notes.md`,
  entry 16.
- 2026-10-30 (commit `27e7c68`, "Add LocalStack S3 and django-storages"):
  the resume feature gets its foundation — file storage now points at
  S3 through django-storages, emulated locally by a LocalStack
  container (no AWS account, no cost). The bucket is created by an
  init script, the API waits until the bucket actually exists before
  starting, and the storage settings are private-by-default: signed
  URLs, no public ACL, no silent overwrites. Switching to real AWS
  later is pure configuration — the endpoint URL comes from an
  environment variable. Not yet built: the resume field itself and the
  upload endpoint. Review also found env-var name drift in
  `.env.example` and a token that needs checking — details in
  `docs/technical-notes.md`, entry 17.
- 2026-10-30 (commit `d6c618e`, "Add resume upload with type, signature
  and 5 MB checks"): candidates now attach a resume when applying.
  Design note: the resume lives on the Application, not the profile —
  one tailored resume per application instead of a single shared file.
  The upload is validated three ways (extension allowlist, 5 MB cap,
  and a magic-byte signature check so a renamed file can't slip past),
  stored in the S3 backend from entry 17 under an unguessable
  UUID name, and required by the API on every application. Technical
  breakdown in `docs/technical-notes.md`, entry 18.
- 2026-10-30 (commit `9b20ee8`, "Add presigned resume downloads"):
  resume access is redesigned the careful way. Application responses
  no longer contain a resume URL at all — just `has_resume: true` —
  and the actual file is served through a dedicated endpoint,
  `GET /api/applications/{id}/resume/`, which checks ownership and
  returns a download link that expires in five minutes. The link is
  signed against a separate "public" endpoint setting, which solves
  the classic local-development trap where a URL signed for
  `localstack:4566` can't be opened from the host browser. Technical
  breakdown in `docs/technical-notes.md`, entry 19.
- 2026-10-30 (commit `e860e22`, "Add job search, filters and
  ordering"): the job list is now properly explorable — text search
  across title, description and company name; filters for job type,
  location (partial, case-insensitive) and skills; and ordering by
  date or title. The quiet half of the commit matters just as much:
  job skills are normalised (trimmed, lowercased, de-duplicated) when
  a job is saved, and the skills filter normalises the query the same
  way — so `Python` the posting and `python` the search actually meet.
  Technical breakdown in `docs/technical-notes.md`, entry 20.
