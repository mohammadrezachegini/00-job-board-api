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
- 2026-10-31 (commit `f83b78f`, "Update README for Phase 2"): the
  README catches up with reality — status line now reads Phase 2
  complete, and the feature list covers permissions, match scoring,
  S3 resumes and search. Keeping the public documentation in sync at
  phase boundaries is part of the build, not an afterthought.
- 2026-10-31 (commit `0ce85a6`, "Cache job list in Redis"): Phase 3
  opens with response caching for the job list. Redis joins the
  Compose stack; list responses are cached for 60 seconds under a
  versioned key, writes bump the version (only after the database
  transaction commits), and if Redis is down the API quietly falls
  back to the database — the cache is an accelerator, never a
  dependency. Responses carry an `X-Cache: HIT/MISS` header so the
  behaviour is provable from outside. Technical breakdown in
  `docs/technical-notes.md`, entry 22.
- 2026-10-31 (commit `a127b5c`, "Add SQS queue + DLQ in LocalStack and
  cloud.queue interface"): the background-work foundation lands.
  LocalStack now also emulates SQS, with two queues created at
  startup: the main notifications queue and a dead-letter queue that
  receives any message that fails processing three times. Application
  code talks to a new provider-neutral `cloud.queue` interface — a
  small abstract class with a message dataclass — so swapping SQS
  for Azure Service Bus later means one new implementation, not a
  rewrite. The producer, worker and message formats come next.
  Technical breakdown in `docs/technical-notes.md`, entry 23.
- 2026-11-01 (commit `9d210da`, "Publish status changes to SQS on
  commit; add worker service"): the queue from entry 23 gets its
  producer and consumer. When a company changes an application's
  status, the API publishes an `application.status_changed` event —
  after the database commit, and only when the status actually
  changed. A new worker service polls the queue, handles events
  (today: a structured log line), deletes only on success, and shuts
  down gracefully on SIGTERM, finishing its current batch. Failed
  messages return for retry and land in the DLQ after three attempts,
  exactly as provisioned. Technical breakdown in
  `docs/technical-notes.md`, entry 24.
- 2026-11-04 (commit `63fab44`, "Worker sends status-change emails
  (console backend); skip deleted applications"): the notification
  pipeline is real. On a status-change event, the worker loads the
  application, renders a plain-text email from a template, and sends
  it to the candidate — locally the mail lands in the worker's console
  log, because the email backend is an environment variable. If the
  application no longer exists, the worker logs and skips instead of
  retrying forever. One debt is now live and logged in entry 25: with
  a side-effecting handler, duplicate delivery can mean a duplicate
  email until event-id deduplication lands. Technical breakdown in
  `docs/technical-notes.md`, entry 25.
- 2026-11-04 (commit `cbc4b81`, "Idempotent worker: claim event_id in
  ProcessedEvent within the send transaction"): the dedupe debt from
  entry 25 is paid the same night. A new ProcessedEvent table records
  each handled event's id. The worker now claims the event — inserting
  its id — inside the same transaction that sends the email, so a
  redelivery after a successful send is recognised and skipped, and a
  failed send rolls the claim back so the retry can work. Duplicate
  emails now survive only in a crash window a few milliseconds wide.
  Technical breakdown in `docs/technical-notes.md`, entry 26.
- 2026-11-04 (commit `d3477b9`, "Update README for Phase 3"): the
  README catches up with Phase 3 — status line, architecture diagram
  (cache, queue, DLQ, worker), feature list, env table and project
  layout all describe the system as it now is. Its manual-checks list
  records the crash-after-send and mail-failure simulations used to
  prove the idempotency design, and the "What Broke" section gains
  two honest Phase 3 entries. Brief note in `docs/technical-notes.md`,
  entry 27.
- 2026-11-05 (commit `7e465b8`, "Add /healthz and /readyz with
  bounded dependency checks; resilient worker; restart policy"):
  Phase 4 opens with operability. `/healthz` answers "is the process
  alive" and `/readyz` actually checks PostgreSQL, Redis and the
  queue, reporting each with its timing — only the database can mark
  the service not-ready, matching how the app already degrades
  gracefully without cache or queue. The worker stops dying on queue
  outages: failed receives now retry after a pause, failed deletes are
  logged for the redelivery that idempotency already makes safe. Both
  services get a restart policy. Technical breakdown in
  `docs/technical-notes.md`, entry 28.
- 2026-11-05 (commit `b0cf235`, "Add /metrics via django-prometheus"):
  the API now exposes Prometheus metrics at `/metrics` — request
  counts and latency histograms per view, plus per-connection
  database query metrics, collected by middleware wrapped around the
  whole request stack. Next to `/healthz` and `/readyz`, that
  completes the classic probe-and-metrics surface an orchestrator
  (and Project 02's Prometheus/Grafana stack) expects. Technical
  breakdown in `docs/technical-notes.md`, entry 29.
- 2026-11-05 (commit `73a91c5`, "Structured JSON logs to stdout"):
  logging grows up. Both the API and the worker now emit one JSON
  object per line to stdout — level, logger, timestamp, message —
  with the event id, application id and queue message id attached as
  real fields on the log lines that have them, so logs can be
  filtered and traced instead of grepped by hope. Verbosity is set by
  a LOG_LEVEL environment variable, and noisy AWS library loggers are
  capped at warnings. This closes the gap the Phase 3 README itself
  confessed (no LOGGING config). Technical breakdown in
  `docs/technical-notes.md`, entry 30.
- 2026-11-05 (docs maintenance): `docs/technical-notes.md` outgrew the
  GitHub write tool's size limit, so entries 1–20 moved to
  `docs/technical-notes-archive-1.md` (with a pointer left in the main
  file). Entries 29–30, which were held locally for this split, are
  now published in the main notes file.
- 2026-11-06 (commit `8fe0d61`, "All config from env"): settings are
  now fully environment-driven and strict. The env reader treats empty
  values as missing and fails fast on absent required variables; new
  typed helpers parse booleans and lists properly, so DEBUG defaults
  to off and allowed hosts defaults to localhost instead of the old
  scaffold wildcard. Two long-standing cleanups landed in the same
  pass: the two region variables were unified into one AWS_REGION,
  the leftover scaffold block containing an old insecure key string
  was deleted, and the LocalStack auth token moved out of the
  committed Compose file into its own ignored env file. Technical
  breakdown in `docs/technical-notes.md`, entry 31.
- 2026-11-06 (commit `4cb2e82`, "Multi-stage Dockerfile, non-root
  user, gunicorn"): the image grows up. A builder stage installs
  dependencies into a virtualenv with uv; the runtime stage copies in
  only Python, the venv and the code, runs as a non-root user, and
  serves the app with gunicorn instead of the development server —
  its own logs formatted with the same JSON config as the app's.
  Local development is untouched: Compose overrides the command back
  to runserver with the code bind-mounted. With this, Phase 4's
  build-and-operate list is complete. Technical breakdown in
  `docs/technical-notes.md`, entry 32.
- 2026-11-06 (commit `00e0f7e`, "Update README for Phase 4"): the
  README catches up with Phase 4 — status line, architecture diagram,
  operations features, environment table (including the gunicorn
  knobs and why workers stay at 1), a production-image runbook, and a
  manual-checks list with measured numbers: readiness answering in
  about a second against a frozen dependency, a 343 MB image, a
  half-second graceful stop. Brief note in
  `docs/technical-notes.md`, entry 33.
- 2026-11-06 (commits `8f81ce0` + `31be719`, pytest setup and first
  unit tests): Phase 5 opens. pytest with pytest-django and coverage
  is wired into the project, the Docker build gained a dedicated test
  stage (never deployed) behind a Compose profile, and the first
  real test suite landed in `jobs/tests/`: hand-built factory
  fixtures plus focused unit tests for the match scorer, the resume
  validator and the models — including boundary cases like a resume
  of exactly 5 MB and one byte over. API tests come next. Technical
  breakdown in `docs/technical-notes.md`, entry 34.
- 2026-11-06 (commit `58c883a`, "Permission tests"): the authorization
  rules from Phase 2 get their proof. Fourteen tests in
  `jobs/tests/test_permissions.py` cover the four permission classes
  directly — including the exact wording of each denial message — and
  then an API-level who-can-do-what matrix: a fixed cast of users
  (anonymous, candidate, unverified company, two verified companies)
  is run against every protected endpoint with the expected status
  code for each. Two test-speed fixtures ride along: an in-memory
  cache per test, and a fast password hasher so creating test users
  stays cheap. Technical breakdown in `docs/technical-notes.md`,
  entry 35.
- 2026-11-06 (commit `6de9e76`, "API tests"): the behavioural suite
  lands — 36 tests across registration and the JWT flow, jobs, and
  applications. Registration role-locking, case-insensitive duplicate
  rejection, token-type confusion, skill normalization, filters,
  pagination, duplicate applications, the hidden resume path, and the
  publish-exactly-once-on-change rule are all pinned at HTTP level.
  Phase 5's test pyramid now has its unit, permission and API layers.
  Technical breakdown in `docs/technical-notes.md`, entry 36.
- 2026-11-06 (commit `ee20616`, "S3 and SQS tests with moto"): the AWS
  seams get integration tests against moto's in-process fakes. Resume
  uploads are proven to land in S3 privately, rejected uploads to
  store nothing, presigned links to point at the stored file; the
  queue does a full send/receive/delete round trip; and the event
  producer is proven to publish only after commit — a rolled-back
  status change publishes nothing, and a queue outage is logged, not
  raised. One honest wart is documented by its own test: a duplicate
  application rejected by the database race still leaves its uploaded
  file behind in the bucket. Technical breakdown in
  `docs/technical-notes.md`, entry 37.
- 2026-11-06 (commit `f803c0d`, "Worker, email, cache and readiness
  tests"): the last untested surfaces get their suites — 33 tests.
  The worker's dedupe promises are now proven automatically (a
  duplicate event sends no second email; a failed send releases its
  claim so the redelivery works), the email's content and
  header-safety are pinned, the cache contract (hit, miss,
  invalidation after commit, outage fallback) is tested at HTTP
  level, and the readiness rules — database critical, the rest
  advisory, liveness ignoring everything — are locked in. Phase 5's
  behavioural coverage is complete; what remains is the coverage
  target and the README sync. Technical breakdown in
  `docs/technical-notes.md`, entry 38.
- 2026-11-07 (commits `a2b2ece` + `0624461`, OpenAPI): the API now
  documents itself. drf-spectacular generates an OpenAPI schema at
  `/api/schema/` with a Swagger UI beside it, public like the probes.
  A second pass makes the schema *true*: operations the generator
  could only guess at (registration responses, the applicants list,
  the status action, the resume link) are declared explicitly, the
  computed fields carry real types (match score is an integer that
  can be null), and eight schema tests fail the build if the
  documentation drifts from the code again. Technical breakdown in
  `docs/technical-notes.md`, entry 39.
- 2026-11-07 (commit `00525e7`, "Update README for Phase 5"): the
  README catches up with Phase 5, and with it the phase closes. The
  status line now reads Phase 5 (tests and docs) complete; the old
  "tests are planned" section is replaced by a real Testing section:
  203 tests, run with one command (`docker compose run --rm test`),
  100% line coverage against the enforced 80% gate, about 6 seconds,
  needing only PostgreSQL — Redis faked in memory, S3/SQS faked with
  moto. A per-area table says what each suite proves, and the README
  records that key areas were checked by breaking the code on
  purpose and watching exactly the expected tests fail. The OpenAPI
  endpoints and the test service are folded into the architecture
  diagram, features, tech stack, project structure and design
  decisions, and a few wordings are corrected to match the code
  (cache invalidation happens on commit; the applicant-owner
  permission is `IsApplicantOwner`). Technical breakdown in
  `docs/technical-notes.md`, entry 40.
- 2026-11-11 (commits `e5b0e5f` + `819ece6`, Phase 6 — Azure
  portability): the app now runs on either cloud behind one switch,
  `CLOUD_PROVIDER`. On Azure, resumes go to Blob Storage (Azurite
  locally) and events to Service Bus (the official emulator locally,
  with its own SQL Server sidecar), while AWS keeps S3 and SQS. The
  emulator's queue is configured to behave like the SQS one — same
  lock time, same redelivery limit. The Service Bus health ping got
  special care: the Azure SDK can hang forever logging in to a frozen
  broker, so the ping runs in a thread with a hard wait limit.
  Technical breakdown in `docs/technical-notes.md`, entry 41.
- 2026-11-11 (commit `4f0fd0b`, Phase 6 — Azure tests): the Azure
  path gets its proof. Against real Azurite, the resume lands in
  Blob Storage, stays private, downloads through a read-only SAS
  link whose bytes match exactly, and a tampered link is refused
  with 403; a rejected upload still stores nothing on this cloud
  too. Beside it, settings tests prove each cloud starts with none
  of the other's variables set — and fails fast when one of its own
  is missing. Technical breakdown in `docs/technical-notes.md`,
  entry 42.
- 2026-11-11 (commit `9c7d2d0`, follow-up to the Azure tests): the
  test run is quiet again. The new Azurite tests surfaced a
  deprecation warning that comes from inside django-storages — its
  Azure backend still calls the old `datetime.utcnow()` that
  Python 3.12 warns about. It is library code, not ours, so instead
  of fixing it the suite now hides exactly that one warning from
  exactly that one module in `pyproject.toml`, with a comment
  saying to remove the filter once django-storages fixes it
  upstream. Every other warning still shows. Technical breakdown
  in `docs/technical-notes.md`, entry 43.
- 2026-11-11 (commit `557de36`, Phase 6 — Service Bus queue tests):
  the Azure queue adapter gets 17 unit tests against hand-built
  fake SDK objects. They pin the lazy connection, the key-free log
  URL, sender/receiver reuse and discard-on-error, the receive →
  complete-on-the-same-receiver flow, and the deadline behaviour:
  sends give up after their limit with an error that honestly says
  the message may still arrive, and a ping against a frozen broker
  times out, fails fast while stuck, then recovers. Technical
  breakdown in `docs/technical-notes.md`, entry 44.
- 2026-11-11 (commits `3e9e230` + `9f2ca9a`, Phase 6 closed): two
  finishing touches. A newer gunicorn tried to open its control
  socket in the app user's home directory — which doesn't exist,
  because the container user was deliberately made minimal — so the
  socket is now disabled in `gunicorn.conf.py` (the process is
  managed by Docker/Kubernetes signals anyway). The README then
  closes Phase 6: status banner, both clouds in the architecture
  diagram, and the terminal checks updated with the Azure runs.
  Technical breakdown in `docs/technical-notes.md`, entry 45.
- 2026-11-12 (commit `53f4008`, "Setup: bootstrap.yml with the
  dev-toolchain role (v0.1.0), requirements.yml, ansible.cfg,
  inventory"): the project can now set up its own developer
  machine. A small Ansible playbook at the repo root, `bootstrap.yml`,
  runs against the local machine itself and applies one role —
  `dev-toolchain`, pinned at version v0.1.0 and fetched from its own
  GitHub repository with `ansible-galaxy` — passing it the list of
  tools this project needs: Python 3.12, Docker, the PostgreSQL and
  Redis command-line clients, the AWS CLI with LocalStack and
  `awslocal`, Azurite for Azure, and pre-commit. Two small config
  files support it: `ansible.cfg` points Ansible at the downloaded
  roles and the inventory, and `inventory.ini` names just localhost,
  using the system Python. Instead of a README page of manual install
  steps, a fresh Ubuntu machine is readied with two commands.
  Technical breakdown in `docs/technical-notes.md`, entry 46.
