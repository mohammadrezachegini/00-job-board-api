# Technical Notes — 00-job-board-api

Deep-dive explanations of the code and the engineering decisions in this
project, kept in enough detail to be turned into LinkedIn articles later.
One entry per piece of work, newest last.

Entries 1–20 are archived in `docs/technical-notes-archive-1.md`.

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

---

## Entry 24 — 2026-11-01 — Event publishing + the worker (commit `9d210da`)

### Producer: publish on commit, only on real change

```python
# views.py — inside set_status
old_status = application.status
serializer.save()  # (validated ApplicationStatusSerializer)
if application.status != old_status:
    publish_status_changed(application, old_status)

# jobs/events.py
def publish_status_changed(application, old_status):
    body = {"type": "application.status_changed",
            "event_id": str(uuid.uuid4()),
            "application_id": application.id,
            "old_status": old_status,
            "new_status": application.status}
    def send():
        try:
            get_queue().send(body)
        except (BotoCoreError, ClientError):
            logger.exception("Could not queue ...")
    transaction.on_commit(send)
```

- **The event choice is the notification-worthy one.** The brief's
  producer fired on application *submitted*; this implementation
  fires on *status changed* — the moment a candidate actually cares
  about — and the view's `old != new` guard means a no-op PATCH emits
  nothing. Event shape is self-describing (`type`, plus old/new
  status) and carries a `uuid4 event_id`: the dedupe key any future
  consumer will need, minted at the source.
- **`on_commit` again** (entry 22's discipline, second use): the
  event is published only if the status update actually commits — no
  "your application moved to interview" for a transaction that rolled
  back.
- **The honest trade-off:** if SQS is unreachable at commit time, the
  failure is logged and the status change *still succeeds* — the
  event is lost. That's the dual-write problem; the strict fix is a
  transactional outbox table (event row written in the same
  transaction, relayed by a poller). For a notification-grade event
  in this phase, log-and-continue is a defensible choice — made
  consciously, it should stay documented as the known gap it is.

### Worker: a boring loop, correctly boring

```python
# worker/run_worker.py — standalone process, Django bootstrapped
signal.signal(SIGTERM, stop); signal.signal(SIGINT, stop)   # running = False
while running:
    close_old_connections()
    for message in queue.receive():          # batch 10, 20 s long poll
        try:
            handle(message)
        except Exception:
            logger.exception("...; it will be retried"); continue
        queue.delete(message)
```

- **Delete only after success.** The at-least-once contract in one
  branch: handled → deleted; failed → left in the queue, returns
  after the 30 s visibility timeout, retried; third failure → SQS
  redrive moves it to the DLQ provisioned in entry 23. The chain
  designed across two commits now closes end to end.
- **Graceful shutdown with matching numbers.** SIGTERM flips a flag;
  the loop finishes its current batch and exits. Compose grants
  `stop_grace_period: 30s` — deliberately longer than the 20 s long
  poll, so a shutdown signal never has to kill mid-receive. Small
  numbers, chosen to fit each other.
- **Idempotency: safe today by handler design.** The handler is a
  structured log line — processing the same event twice is harmless,
  so no dedupe table exists yet (and none is needed *for this
  handler*). Duplicates are still possible (crash between handle and
  delete → redelivery), and the `event_id` is logged with every
  handling, so the moment a side-effecting handler lands (a real
  email), the dedupe design — a processed-events table keyed on
  `event_id` — slots into ground already prepared. Claiming more
  idempotency than this would be overstatement; claiming less would
  miss that the key is already flowing.
- **Strictness on unknown types**: an unrecognized `type` raises,
  retries three times, and DLQs. Correct posture — a message that can
  never succeed should surface in the DLQ as schema drift, not be
  silently dropped.
- Two gaps for the hardening phase: an exception in `receive()`
  itself (SQS unreachable) is not caught in the loop, so the worker
  exits — and the Compose service declares no `restart:` policy, so
  it would stay down; and there is no health signal yet (the brief's
  touched-file healthcheck) for an orchestrator to notice a wedged
  worker. Both are Phase 5 material, noted now so they're findable.

### Status

Phase 3's queue story is complete: interface + DLQ provisioning
(entry 23), producer on commit, worker with retry/DLQ semantics and
graceful shutdown. Remaining: ops endpoints and hardening
(Phase 3 finish / Phase 5), the my-applications list and close
action (Phase 2 leftovers), a README sync for Phase 3, entry 8
cleanups.

### Article angles

- "Delete on success, retry on failure: the at-least-once contract in twelve lines"
- "The dual-write problem in your own codebase: on_commit publishing vs the outbox pattern"
- "Idempotency is a property of the handler, not the queue"
- "Graceful shutdown arithmetic: stop_grace_period must exceed your long poll"
- "Unknown message types should DLQ, not disappear: strict consumers surface schema drift"

---

## Entry 25 — 2026-11-04 — The worker sends email; the dedupe debt comes due (commit `63fab44`)

### From log line to side effect

```python
# worker/run_worker.py
def handle_status_changed(body):
    try:
        application = Application.objects.select_related(
            "job__company", "candidate__user").get(id=body["application_id"])
    except Application.DoesNotExist:
        logger.warning("Application %s no longer exists; skipping (event %s)", ...)
        return                      # returns normally → message DELETED
    send_status_changed_email(application, body["new_status"])

# jobs/emails.py
def send_status_changed_email(application, new_status):
    ...
    subject = _one_line(f"Your application for {application.job.title}: {status_label}")
    body = render_to_string("emails/status_changed.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [candidate.email],
              fail_silently=False)
```

Everything entry 24 predicted now applies. Design decisions inside
the handler, almost all of them right:

- **Failure taxonomy stays consistent.** A *gone* application is a
  permanent condition → log, return, delete the message (retrying a
  deleted row into the DLQ would be pure noise). A *send failure* is
  transient → `fail_silently=False` raises inside the handler → the
  loop's existing path retries, then DLQs. A garbage status value
  raises in `Application.Status(...)` → same retry/DLQ path. Three
  failure kinds, three deliberate outcomes, no new machinery.
- **The email speaks from the event, not the database.** The status
  in the subject and body is the event's `new_status` (rendered as a
  human label — "Interview", not "interview"), so two rapid changes
  produce two truthful emails in event order rather than two emails
  both describing the final state.
- **The database load is only for addressing and context** —
  recipient email, candidate name (`first_name or username`), job
  title, company name — fetched in one `select_related` query.
- **Subject hygiene**: `_one_line()` collapses whitespace/newlines
  out of the user-controlled job title before it becomes a header —
  header-injection defence in depth alongside `send_mail`'s own
  guard. The text template sets `{% autoescape off %}` correctly for
  a plain-text (non-HTML) email.
- **Backend is configuration**: `EMAIL_BACKEND` from env, defaulting
  to Django's console backend — emails appear in worker logs locally,
  and SES/SMTP becomes an env change, not a code change (the same
  portability seam pattern as entries 17/23: endpoint/credentials in
  env, code untouched). `DEFAULT_FROM_EMAIL` likewise.

### The debt, now with a user-visible consequence

Entry 24 said: the log-only handler made duplicates harmless, and
dedupe becomes necessary the moment a side-effecting handler lands.
That moment is this commit, and dedupe is **not** here — no
processed-events table, no new migration. Today's exposure, stated
plainly:

- If the worker crashes (or is stopped mid-batch) after `send_mail`
  succeeds but before `queue.delete` runs, the message is redelivered
  and the candidate gets the **same email twice**. Same result if
  handling ever exceeds the 30 s visibility timeout.
- Mitigations that exist: the sends are fast, batches are small, and
  every handling logs its `event_id`, so a duplicate is traceable in
  logs after the fact. Nothing *prevents* one.
- The fix is the design already sketched in entry 24: a
  processed-events table keyed on `event_id`, written in the **same
  transaction** as the handler's effect where possible (for email,
  the practical form is: record-then-send with the unique constraint
  deciding who sends — accepting the inverse edge: crash between
  record and send loses one email instead of duplicating one; pick
  the failure you prefer, consciously).

This is the top functional gap in the project as of this entry —
ahead of the cosmetic serializer items in entry 8 — because its
failure mode reaches a real user's inbox.

### Status

Phase 3 functionally complete: cache (22), queue + DLQ (23),
producer + worker (24), real notification handler (25). Open, in
rough priority: event-id dedupe; the two Phase 2 leftovers
(my-applications list, close action); ops endpoints (health/ready —
planned programme items, not yet started) and worker restart policy;
entry 8 cleanups; README Phase 3 sync.

### Article angles

- "Your first side effect changes everything: when at-least-once stops being free"
- "Permanent vs transient failures: why a deleted row should delete the message too"
- "Record-then-send vs send-then-record: picking which failure you prefer"
- "Email from env: Django's backend setting as a portability seam"
- "Header injection hides in user content: sanitizing subjects built from job titles"

---

## Entry 26 — 2026-11-04 — Idempotent worker: claim-first inside the send transaction (commit `cbc4b81`)

### The mechanism

```python
class ProcessedEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True)   # migration 0006
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

def claim_event(event_id, event_type):
    try:
        with transaction.atomic():                 # savepoint when nested
            ProcessedEvent.objects.create(event_id=event_id, event_type=event_type)
    except IntegrityError:
        return False
    return True

def handle_status_changed(body):
    with transaction.atomic():                     # outer transaction
        if not claim_event(body["event_id"], STATUS_CHANGED):
            return                                 # duplicate → skip, message deleted
        application = ...get(...) or return        # gone app: still claims, still commits
        send_status_changed_email(application, body["new_status"])
    # commit happens here — then the loop deletes the queue message
```

### What it guarantees, case by case

- **Redelivery after success** (the common case — crash or shutdown
  between commit and queue delete, visibility expiry): the claim row
  is committed, the second `create` hits the unique constraint, the
  handler skips, the message is deleted. No second email. ✓
- **Send failure**: `send_mail` raises → the outer transaction rolls
  back → *the claim vanishes with it* → the retry re-claims and
  re-sends cleanly. This is why the claim lives inside the send
  transaction rather than being committed first: a claim-first-commit
  design would convert every transient SMTP failure into a silently
  swallowed event. ✓
- **Concurrent duplicates** (two workers, or an overlap while a slow
  send outlives the visibility timeout): the unique index serializes
  the claim — one transaction wins, the other blocks, then raises
  IntegrityError and skips; if the winner rolls back, the blocked
  create proceeds. The database arbitrates, not application luck. ✓
- **The savepoint detail matters**: `claim_event` wraps its `create`
  in its own `atomic()` precisely so the IntegrityError can be caught
  *inside* the outer transaction without poisoning it — Django
  forbids queries after an error in a transaction unless a savepoint
  absorbed it. Same pattern as the application-create savepoint in
  entry 11, recognised and reused. ✓
- **Gone application**: claimed and committed as processed, message
  deleted — yesterday's permanent-vs-transient taxonomy preserved
  under the new machinery.

### The edge that remains, honestly stated

Email cannot join a database transaction. If the process dies
*after* `send_mail` succeeds but *before* the outer commit lands,
the claim rolls back, the message returns, and one duplicate email
goes out. The window shrank from "send → queue delete" (network
latency, whole event loop) to "send → local commit" (milliseconds),
and cannot shrink further without changing the failure you prefer:

- **This design** (claim + send, one transaction) prefers: duplicates
  are nearly impossible; lost emails require the send itself to fail,
  which the retry path covers.
- **The alternative** (commit claim first, then send) prefers: never
  duplicate; accepts that a crash between commit and send loses the
  email silently, forever, with the processed-table insisting it was
  handled.

Effectively-once here is a choice of which rare failure you'd rather
explain, and the commit title documents that the choice was seen
("within the send transaction"), not stumbled into.

Two maintenance notes for later, neither a defect today: the
ProcessedEvent table grows one row per event forever — pruning rows
beyond the queue's maximum retention (14 days for SQS) is a safe
future cleanup; and holding the transaction open across an external
SMTP call means a future slow real-mail send also holds a DB
connection and the claim row's lock — fine at this scale, worth
remembering at larger ones.

### Status

Phase 3 is now complete *with* idempotency — the arc runs 22 (cache),
23 (queue + DLQ), 24 (producer + worker), 25 (email handler), 26
(dedupe). The dedupe gap flagged as the project's top functional debt
in entry 25 was closed the same night it opened. Remaining queue:
ops endpoints (health/ready/metrics — Phase 4 programme items),
worker restart policy, the Phase 2 leftovers (my-applications list,
close action), entry 8 cleanups, README Phase 3 sync, and now a
ProcessedEvent pruning policy someday.

### Article angles

- "Effectively-once is a preference, not a property: claim-in-transaction vs commit-first"
- "Savepoints let you catch IntegrityError safely inside a transaction — Django's quiet superpower"
- "Let the unique constraint arbitrate: dedupe without locks, flags, or race windows"
- "Your dedupe table needs a retention policy the day you create it"
- "A commit message that names the trade-off ('within the send transaction') is documentation"

---

## Entry 27 — 2026-11-04 — README catches up: Phase 3, documented with its test evidence (commit `d3477b9`)

The Phase 3 README sync (same pattern as entry 21) is complete and
accurate across every surface checked against entries 22–26:

- **Status line** now reads "Phase 3 (background worker) complete,"
  with ops endpoints, structured logs, tests and cloud deployment
  honestly deferred to later phases.
- **Architecture diagram** shows the cached search, the
  `job-board-status` queue redriving to its `-dlq` after 3 failures,
  and the worker claiming `event_id` and sending the email.
- **Feature and env sections** cover the cache (60 s TTL, on-commit
  invalidation, `X-Cache`, Redis-down behaviour), the worker,
  `REDIS_URL` / `SQS_*` / `EMAIL_*` variables, `ProcessedEvent` in the
  model list, and the `cloud/queue.py` seam in the project layout.
- **Design decisions** restate the load-bearing ones precisely:
  side effects only after commit (both invalidation and publishing),
  "messages carry IDs, not personal data" (the worker re-reads state
  from the database), idempotency as a unique `event_id` claimed in
  the send transaction, one image / two process types.
- **Most valuable: the manual-checks list is evidence, not vibes.**
  It records testing cache invalidation *not* firing on a rolled-back
  save, messages waiting out a stopped worker, a poison message
  reaching the DLQ, and the two simulations that prove entry 26's
  design — crash after send, before delete → redelivered copy skipped,
  no second email; mail-server failure → claim rolled back, retry
  sent the email. Exactly the cases the dedupe design turns on.
- **"What Broke" grows honestly**: Phase 3 adds the invalidation
  function that was defined but never wired to `on_commit` (found by
  checking the cache version before/after a save — a debugging-method
  lesson worth the space it takes) and the missing `LOGGING` config
  (INFO-level API logs don't exist yet; flagged as Phase 4 work,
  which matches the ops backlog). Phase 2's list also gains his own
  catches from that phase (filter `lookup_expr` 500, `url_path`
  404, empty status accepted with 200 — the last being the origin of
  the strict status serializer in entry 13).

One precision nit, recorded here rather than litigated: the README's
"a redelivered message **never** sends a second email" is a hair
stronger than the code's guarantee — entry 26 documents the residual
pre-commit crash window. The checks list itself claims only what was
tested; if the README is ever quoted in an interview, "recognized
and skipped" is the defensible phrasing.

**Status: Project 00's Phase 3 is closed — feature-complete,
idempotent, and documented end to end.** Remaining backlog: Phase 4
ops (health/ready/metrics, structured logs, LOGGING config), worker
restart policy, Phase 2 leftovers (my-applications list, close
action), entry 8 serializer hygiene, ProcessedEvent pruning policy.

---

## Entry 28 — 2026-11-05 — Health vs readiness, a resilient worker loop, restart policy (commit `7e465b8`)

### Two probes, two different questions (`cloud/health.py`)

```python
def healthz(request):                      # liveness
    return JsonResponse({"status": "ok"})  # checks NOTHING

CHECKS = [
    ("database", _check_database, True),   # SELECT 1 — critical
    ("cache",    _check_cache,    False),  # SET+GET round-trip — advisory
    ("queue",    _check_queue,    False),  # get_queue().ping() — advisory
]

def readyz(request):                       # 200 when ready, 503 when not
    ... per-check {status, critical, ms}, failures logged with exc_info ...
```

- **Liveness checks nothing on purpose.** `/healthz` proving only
  "the process responds" is the correct semantics: if liveness
  consulted dependencies, a sick database would make the orchestrator
  restart healthy app processes in a loop. Readiness is where
  dependency truth belongs, and it's expressed precisely: each check
  reports status, criticality and measured milliseconds, and the
  response is 503 only when a **critical** check fails.
- **The criticality table encodes the architecture's own degradation
  philosophy.** Database = critical (nothing works without it).
  Cache = advisory — entry 22 already designed the API to serve from
  the database when Redis dies, so readiness honestly mirrors that.
  Queue = advisory — publishing failures are log-and-continue by
  entry 24's choice, so a dead queue degrades notifications, not the
  API. A readiness endpoint that contradicts the app's actual failure
  behaviour would be theatre; this one agrees with it.
- **The cache check does a real round-trip** — `set` then `get` with
  read-back comparison — catching serialization and config failures a
  bare ping would bless. Errors are exposed as exception *type names*
  only (no internals in the body), failures log with `exc_info`, and
  both views are `@never_cache` + GET-only: a health answer must be
  live, never a cached artefact (a trap this very API, which caches
  job lists, is well placed to appreciate). The views are plain
  Django, outside DRF's JWT defaults — probes carry no tokens, by
  design. (`SQSQueue.ping()` is a new one-call addition behind the
  entry 23 interface — the abstraction absorbed the probe without
  touching callers.)
- One honest bound on "bounded": check latency is *measured and
  reported*, but there is no explicit per-check timeout in the view
  itself — bounding rides on the underlying clients' defaults, and
  the checks run serially. A wedged dependency could hold a probe
  open longer than an orchestrator's patience; a future hardening
  pass could wrap each check with its own deadline.

### The worker loop grows scar tissue — correctly

Entry 24 logged two gaps; this commit closes both, and adds a third
guard nobody had listed:

```python
try:
    messages = queue.receive()
except (BotoCoreError, ClientError):
    logger.exception("Could not receive messages; retrying in 5 s")
    time.sleep(5); continue                  # outage ≠ death

... handle ...
try:
    queue.delete(message)
except (BotoCoreError, ClientError):
    logger.exception("...; it will be redelivered")   # and that's now SAFE
```

The delete-failure path is where the entries compose: before entry
26, a lost delete meant a potential duplicate email, so swallowing
the error would have been risky; with idempotent handling, "let it
redeliver" is the calm, correct response. Resilience here isn't one
commit's virtue — it's Phase 3's design decisions paying Phase 4's
bills. Compose adds `restart: unless-stopped` to **both** api and
worker: crash-recovery and daemon-restart survival, while a manual
stop stays stopped — the right default for a dev/ops portfolio stack.

### Status

Phase 4 step 1 (probes) landed ahead of its scheduled night, plus
the worker-hardening backlog from entry 24 fully cleared. Remaining
in Phase 4: /metrics, structured JSON logging + LOGGING config,
multi-stage Dockerfile (tonight's scheduled step). Carry-overs:
my-applications list, close action, ProcessedEvent pruning,
entry 8 serializer hygiene, match-score null docstring.

### Article angles

- "Health is not readiness: the two questions every probe must keep separate"
- "Your readiness criticality table is your degradation philosophy, written down"
- "A cache check that only pings is lying: round-trip or it didn't happen"
- "Resilient consumers are built in layers: retry the receive, tolerate the delete, dedupe the handling"
- "unless-stopped vs always: restart policies are a small decision with loud consequences"

---

## Entry 29 — 2026-11-05 — /metrics via django-prometheus (commit `b0cf235`)

### The middleware sandwich, done in the documented order

```python
INSTALLED_APPS = [..., "django_prometheus"]
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",   # FIRST
    ... everything else ...
    "django_prometheus.middleware.PrometheusAfterMiddleware",    # LAST
]
DATABASES["default"]["ENGINE"] = "django_prometheus.db.backends.postgresql"
urlpatterns += [path("", include("django_prometheus.urls"))]    # → /metrics
```

- **Placement is the whole ballgame for latency honesty.**
  `Before` sits at position 0 so its timer starts before any other
  middleware runs; `After` sits last so it records after the response
  is fully formed. Everything the stack does — auth, the view, the
  cached-list path from entry 22 — is inside the measurement, not
  outside it. Swapping the order (a common copy-paste slip) produces
  metrics that systematically under-report; this wiring matches the
  library's own contract exactly.
- **What gets measured**: per-view request counts and latency
  histograms (`django_http_requests_*`, `django_http_responses_*`
  families) — histograms, not averages, so p95/p99 are computable at
  query time in Prometheus; and by swapping the DB `ENGINE` to the
  prometheus wrapper backend, per-connection query counts, latency
  and transaction metrics come along without touching application
  code. The dependency is pinned (`django-prometheus>=2.5`) in
  pyproject like every other.
- **Exposure posture mirrors the probes**: `/metrics` hangs off the
  root URLconf next to `/healthz` and `/readyz`, outside `/api/` and
  outside JWT — scrapers don't carry tokens. The standing caveat from
  entry 28 applies unchanged: on any public deployment this surface
  must be network-restricted (ingress rules / bind), because metrics
  leak operational shape (endpoints, rates, latencies) to anyone who
  can reach them. Locally, correct as-is.
- **Deliberately not instrumented** (the commit title scopes itself
  honestly: "request, latency and DB metrics"): the Redis cache
  backend would need the `django_prometheus.cache` wrapper to emit
  hit/miss series — a natural next layer when someone wants to *prove*
  entry 22's cache is earning its keep; model-level metrics are
  available but noisy by default; and the worker, not being an HTTP
  process, exposes nothing — worker observability would ride a
  Pushgateway or a shared textfile exporter, a Project 02-shaped
  problem rather than this one's.

### Status

Phase 4 surface so far: probes (28) + metrics (29). Remaining:
structured JSON logging + the LOGGING config the README already
confessed to missing, and the multi-stage Dockerfile (tonight's
scheduled step). Carry-overs unchanged: my-applications, close
action, ProcessedEvent pruning, entry 8 hygiene, null docstring.
This entry also crosses a tooling threshold — see the delivery note
accompanying it about the notes file's size.

### Article angles

- "Middleware order is a measurement contract: the prometheus sandwich"
- "Histograms or it didn't happen: why averages hide your p99"
- "Instrument by swapping backends: Django's pluggable ENGINE/CACHES seams strike again"
- "Your /metrics endpoint is an information leak you chose on purpose — fence it at deploy time"

---

## Entry 30 — 2026-11-05 — Structured JSON logs, with correlation fields (commit `73a91c5`)

### One config, both processes

```python
# config/settings.py
LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"json": {"()": "pythonjsonlogger.json.JsonFormatter",
        "fmt": "%(levelname)s %(name)s %(message)s",
        "rename_fields": {"levelname": "level", "name": "logger"},
        "timestamp": True,
        "reserved_attrs": [*RESERVED_ATTRS, "request"]}},
    "handlers": {"stdout": {"class": "logging.StreamHandler",
                            "stream": "ext://sys.stdout", "formatter": "json"}},
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    "loggers": {"django":        {..., "propagate": False},
                "django.server": {..., "propagate": False},
                "botocore": {"level": "WARNING"},
                "urllib3":  {"level": "WARNING"}},
}
```

Because the worker bootstraps the same Django settings (`django.setup()`
in `run_worker.py`, entry 24), deleting its old `basicConfig` means
**one logging contract covers both processes** — the same fields,
the same shape, whichever container a line came from. That's what
makes the output ingestible by a real pipeline (Loki in Project 02
eats exactly this: one JSON object per line on stdout, twelve-factor
style, no log files to rotate).

Details that show the config was *considered*, not pasted:

- `rename_fields` produces clean names (`level`, `logger`) instead
  of Python's internal attribute names — the schema a dashboard will
  query is designed, not inherited by accident.
- `reserved_attrs` gains `"request"`: Django attaches the request
  object to some log records, and a JSON formatter meeting a live
  request object would choke or dump garbage; reserving the attribute
  keeps it out of the output. The kind of line that only gets written
  by someone who read the formatter's docs or met the bug.
- `botocore`/`urllib3` are capped at WARNING: an SQS long-poll loop
  at INFO would flood the stream with HTTP traces and bury the lines
  that matter (it would also double-log every queue operation the app
  already logs semantically).
- `propagate: False` on the django loggers prevents double-emission
  through the root handler — one event, one line.
- `LOG_LEVEL` from env, `.upper()`-normalized: `debug` in a `.env`
  file works instead of silently matching nothing.

### The fields are the feature

The formatter alone only restructures the envelope; the real upgrade
is at the call sites, where `extra={}` attaches machine-readable
context that survives as top-level JSON fields:

```python
# jobs/events.py — producer, success AND failure paths
logger.info("Queued %s for application %s (message %s)", ...,
    extra={"event": STATUS_CHANGED, "event_id": body["event_id"],
           "application_id": application.id, "message_id": message_id})

# worker/run_worker.py — failures carry message_id;
# claim/skip/handle lines carry event + event_id
```

This closes a loop opened in entry 24: the `event_id` minted by the
producer is now traceable **across both processes and the queue
between them** — publish line (API), handled line (worker), same id,
filterable in any log tool. Correlation was already flowing through
the message body; now it flows through the observability surface
too. The message strings remain human-readable in the `message`
field, so the logs still read well raw — structure was *added*, not
substituted.

### Status

Phase 4 moves: probes (28), metrics (29), structured logs (30) —
the observability trio is complete. Remaining Phase 4: multi-stage
Dockerfile (tonight's scheduled step). Backlog unchanged:
my-applications, close action, ProcessedEvent pruning, entry 8
hygiene, cache-metrics wiring. NOTE: entries 29–30 exist in the local
notes copy; their push awaits the archive-split decision (entry 29's
delivery note has the size math).

### Article angles

- "Your event_id is a correlation id: mint it once, log it in every process"
- "Structured logging is a schema decision: rename your fields before a dashboard depends on them"
- "Cap your dependencies' loggers or drown: botocore at INFO in a polling loop"
- "One settings module, two processes: shared observability config in a Django monorepo"

---

## Entry 31 — 2026-11-06 — All config from env: fail-fast, typed, unified (commit `8fe0d61`)

This commit closes more long-standing flags per line than any since
Phase 2 — entry 17's name drift, entry 23's dual regions, the
scaffold leftovers from the project's third night — all settled in
one settings pass.

### The reader grows teeth and types

```python
def env(name, default=None):
    """No default = required; empty counts as missing."""
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            raise ImproperlyConfigured(f"Missing required environment variable: {name}")
        return default
    return value

def env_bool(name, default=False):
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")

def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]
```

- **Empty counts as missing.** The old `env()` blessed `""` as a
  value, which is exactly what a half-filled `.env` line or a
  Compose `${VAR}` passthrough produces — a misconfiguration that
  used to surface deep inside boto3 now fails at settings import
  with the variable's name. (The endpoint settings preserve the old
  `or None` idiom *deliberately*: for endpoints, empty is a legal,
  meaningful value — "use real AWS" — so their defaults are `""` and
  convert to None. Distinction kept, not flattened.)
- **Typed parsing kills two scaffold hazards at once.**
  `DEBUG = env_bool("DJANGO_DEBUG", False)` — boolean parsing means
  the string `"False"` no longer evaluates truthy (the classic env
  bug) and the *default is off*. `ALLOWED_HOSTS =
  env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")` — the
  scaffold's `*` wildcard, flagged since the project's third night,
  is gone; hosts are an explicit comma list with a loopback-only
  default. Safe defaults aren't a slogan here; two concrete values
  flipped.
- **The scaffold block is deleted** (`django-insecure` string no
  longer exists in settings.py) — the gitleaks trap noted when the
  file was young is disarmed before any scanner ever runs.

### One region, aliased honestly

```python
AWS_REGION = env("AWS_REGION")          # now REQUIRED — no silent default
AWS_S3_REGION_NAME = AWS_REGION          # django-storages' expected name, bound to the one source
```

Entry 23 warned that `AWS_REGION` (queue) and `AWS_S3_REGION_NAME`
(storage) could silently disagree. The fix keeps both *names* —
django-storages reads the second one — but binds them to a single
source value, so drift is structurally impossible. It also promotes
AWS_REGION to required: a deployment that forgot its region used to
get `us-east-1` by quiet default; now it gets a startup error,
which is the kinder failure.

### The token leaves the committed tree

The LocalStack service no longer carries a literal auth token in
`docker-compose.yml` (flagged in entry 17 as "if real, rotate and
move"). It now reads `env_file: .env.localstack` — a dedicated file
for that one service. The `.gitignore` pattern is the mature part:

```gitignore
.env
.env.*
!.env.example
!.env.localstack.example
```

All real env files are ignored by glob; only the *examples* are
un-ignored and tracked — including a `.env.localstack.example`
template, so a fresh clone knows the file must exist and what
belongs in it. Isolation bonus: the main `.env` (Django secrets, DB
password) is no longer the file the LocalStack container needs, and
vice versa; each service mounts the smallest env it requires.

### Status

Config surface is now: every value from env, required values fail
fast at boot, types parsed, defaults safe, one region, secrets
isolated per service. Phase 4 remaining: multi-stage Dockerfile.
Backlog unchanged elsewhere. The nightly programme has visibly
re-ordered itself (Dockerfile was scheduled before this audit) —
progress is being judged from the repo, per usual.

### Article angles

- "Empty string is not a value: fail-fast env readers"
- "The string 'False' is truthy: why env booleans need a parser"
- "One source, two names: aliasing config instead of duplicating it"
- ".gitignore as a security control: glob the secrets, whitelist the examples"
- "Safe defaults are decisions: DEBUG off and loopback hosts as the factory settings"

---

## Entry 32 — 2026-11-06 — Multi-stage Dockerfile, non-root, gunicorn (commit `4cb2e82`)

### Two stages, separated by what the runtime deserves

```dockerfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY . .
USER app
EXPOSE 8006
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
```

- **The builder never ships.** uv itself arrives pinned from its
  official image (no pip bootstrap); dependencies resolve `--locked`
  (the lockfile is law) and `--no-dev` into a venv at `/opt/venv`,
  outside the source tree so it copies as one clean layer. Only the
  dependency files are copied before `uv sync`, so the expensive
  layer is cached until `pyproject.toml`/`uv.lock` actually change —
  code edits rebuild in seconds. `UV_COMPILE_BYTECODE=1` precompiles
  `.pyc` in the builder; the runtime pairs it with
  `PYTHONDONTWRITEBYTECODE=1` (it couldn't write anyway, and shouldn't).
- **The runtime is the minimum**: fresh slim Python + venv + code,
  running as `app` (uid 1000, no home, nologin shell — a service
  account, not a person). `COPY . .` is safe because `.dockerignore`
  was audited in the same pass: `.git`, `.venv`, and — the critical
  one — `.env` / `.env.*` are excluded, so **no secrets are baked
  into the image** (only the harmless `.env.example` template rides
  along). Root-owned code files are read-only to the app user, which
  is the correct posture for a process that writes only to S3 and
  Postgres.
- **Dev/prod split without forking the stack**: the image's CMD is
  gunicorn, but Compose overrides `command:` back to
  `runserver 0.0.0.0:8006` with the bind mount for live reload — one
  image definition, two honest modes. The worker service continues
  to prove the one-image/two-processes pattern (entry 24).

### Gunicorn, configured like it matters (`gunicorn.conf.py`)

- `bind` from `PORT` (default 8006): the platform can relocate the
  service without a rebuild — the same env-first discipline as
  entry 31, extended to the server itself.
- `gthread` with **workers=1, threads=4**, both env-tunable,
  timeout/graceful-timeout 30 s (matching the Compose stop-grace
  arithmetic from entry 24). The conservative single-worker default
  has a hidden virtue: django-prometheus keeps its registry
  in-process (entry 29), so one worker keeps `/metrics` coherent;
  scaling workers later is a metrics-multiprocess conversation, not
  a silent breakage.
- **The server's logs join the app's schema**: `logconfig_dict`
  forces gunicorn's own access/error loggers through the same
  python-json-logger formatter as the Django config (entry 30), all
  to stdout. Access lines, app lines, worker lines — one JSON shape
  for the pipeline to ingest. Observability consistency extends to
  the process boundary.

### Known next-step (not a defect of this commit)

Under gunicorn, Django's static files (the admin's CSS/JS) are not
served by anything — `runserver` masked that in dev. A production
pass needs whitenoise or a `collectstatic` + file-server story
before the admin is usable behind gunicorn. Application JSON
traffic, the actual product surface, is unaffected.

### Status

**Phase 4 is complete**: probes (28), metrics (29), structured logs
(30), env-only config (31), production image (32). Project 00 now
stands production-shaped locally: it can be probed, scraped, traced,
configured and shipped. Remaining backlog is functional, not
operational: my-applications list, close action, ProcessedEvent
pruning, cache-metrics wiring, entry 8 serializer hygiene,
match-score null docstring, static-files serving under gunicorn —
and Phase 5 tests above all, per the programme.

### Article angles

- "The builder stage never ships: multi-stage Dockerfiles with uv"
- "Layer caching is a copy-order decision: manifests before code"
- "Your .dockerignore is a secrets control — audit it like one"
- "One worker by default: the quiet interaction between gunicorn scaling and in-process metrics"
- "Make the server's logs speak your app's schema: gunicorn logconfig_dict meets Django LOGGING"

---

## Entry 33 — 2026-11-06 — README catches up: Phase 4, with measured evidence (commit `00e0f7e`)

The Phase 4 README sync follows the established pattern (entries 21,
27) and is accurate against entries 28–32 on every surface checked:

- **Status line**: "Phase 4 (operations-ready) complete," with tests,
  the Azure path and deployment honestly deferred.
- **Operations story told precisely**: liveness checks nothing;
  readiness gates only on PostgreSQL; workers stay at 1 *because
  metrics are per-process* — the README states outright (in both the
  env table and design decisions) the rationale entry 32 inferred
  from the defaults. One image, two modes (gunicorn default,
  runserver via Compose override); least-privilege notes match the
  per-service env isolation from entry 31.
- **A production runbook exists now**: `docker run` with `--env-file`,
  debug forced off, loopback-bound port, and a `/readyz` curl as the
  acceptance test — plus the small, real gotcha that `docker run
  --env-file` keeps quotes literally, so values are written bare.
- **The manual-checks list is, again, evidence**: PostgreSQL stopped
  → healthz 200 / readyz 503; dependencies **frozen with
  `docker compose pause`** (a nastier test than stopping — the
  process exists but never answers) → readyz still 200 in ~1 s with
  the failing dependency named; metrics counters verified before/
  after a known request count; production image verified non-root,
  code unwritable, serving all surfaces.
- **Measured numbers recorded**: frozen-dependency readiness improved
  from >90 s to **1.02–1.06 s** once time limits were applied (this
  retroactively fulfils the "bounded" promise in entry 28's commit
  title); image 394 MB → **343 MB** with the multi-stage build;
  graceful production stop **0.50 s** with gunicorn as PID 1.
- **"What Broke — Phase 4" is the most instructive section**: a
  `return` indented inside the loop made readyz check *only* the
  database — invisible until the freeze test showed Redis/SQS state
  changing nothing (the test design caught what code review didn't);
  the worker's queue-error crashes (entry 28's fix) are confessed
  with the operational footnote that a restart policy only bites
  after a fresh `docker compose up`; and Phase 3's missing-LOGGING
  confession is now annotated "Fixed in Phase 4," closing that
  thread in the document where it opened.

**Status: Project 00, Phases 1–4 complete — features, background
work, observability, operations — and the documentation set
(README, journal, these notes) is fully in sync with the code at
this commit.** Next per the programme: Phase 5, automated tests.
Functional backlog for whenever it is picked: my-applications list,
close action, static files behind gunicorn, ProcessedEvent pruning,
cache metrics, entry 8 serializer hygiene, match-score docstring.

### Article angle

- "Freeze your dependencies, don't just stop them: pause-based readiness testing finds the bugs stop-tests miss"

---

## Entry 34 — 2026-11-06 — Phase 5 opens: pytest, a test image stage, first unit tests (commits `8f81ce0`, `31be719`)

### Infrastructure that respects the production image

```toml
[dependency-groups]
dev = ["pytest>=9.2.0", "pytest-cov>=7.1.0", "pytest-django>=4.14.0"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["test_*.py"]
addopts = "--cov --cov-report=term-missing"

[tool.coverage.run]
source = ["jobs", "cloud", "worker", "config"]
omit = ["*/migrations/*", "*/tests/*", "config/asgi.py", "config/wsgi.py"]
```

```dockerfile
FROM builder AS builder-test          # production + dev dependencies
RUN uv sync --locked --no-install-project
FROM python:3.12-slim AS base         # factored out of runtime
FROM base AS test                     # dev venv, CMD ["pytest"] — never deployed
FROM base AS runtime                  # unchanged production image
```

- **Dev dependencies live in uv's dependency-groups**, so the
  production builder's `--no-dev` sync structurally cannot leak test
  tooling into the shipped image. The test environment is a
  *separate stage* fed by a `builder-test` sync and gated behind a
  Compose `profiles: ["test"]` service with `target: test` — tests
  run in a container built like production's sibling, never as an
  afterthought inside it. The refactor of `base` out of the runtime
  stage is the kind of small structural move that keeps a growing
  Dockerfile honest.
- **Coverage is on by default** (`--cov` in addopts, term-missing so
  gaps are visible in every run, not an annual audit) and its scope
  is a decision: app packages *including the worker and cloud seams*,
  omitting migrations and the WSGI/ASGI shims. You measure the code
  you wrote, not the code Django generated.

### Fixtures: factories without a factory library

```python
# jobs/tests/conftest.py — factory fixtures
@pytest.fixture
def make_company(db):
    def _make(username="acme", verified=True, name=None): ...
    return _make
# + make_candidate, make_job, make_application
```

The "factory fixtures" pattern — fixtures returning maker functions
with happy-path defaults and per-call overrides — buys factory_boy's
ergonomics with zero new dependencies: `make_company(verified=False)`
is the whole vocabulary a permissions test needs. Defaults encode
the domain's normal case (verified company, a realistic job title),
so each test body shows only what makes it different.

### The first tests pin behaviour, not implementation

- **matching**: normalization (strip/lower/dedupe), exact scores —
  and two pins with real thought behind them: *empty required skills
  → `None`* (the semantic choice from Phase 2 that never got its
  docstring is now documented by a test, the most executable place
  it could live), and *halves round to even* — Python's banker's
  rounding in `round()` discovered, understood, and pinned so a
  future "fix" doesn't silently change scores.
- **validators**: extension allowlist, content/extension mismatch
  (the magic-byte check), **boundary values** — exactly 5 MB passes,
  5 MB + 1 byte fails — and the file-rewound invariant (the `seek(0)`
  discipline from entry 18, now enforced by test instead of memory).
- **models**: role properties, unique email, job/application
  defaults, the one-application-per-job constraint, ProcessedEvent's
  unique `event_id` (entry 26's dedupe foundation, tested at the
  layer that guarantees it), upload-path randomness + lowercased
  extension, cascade behaviour.
- **smoke**: `/healthz` answers; the test database starts empty —
  the isolation assumption every other test silently stands on, made
  explicit once.

### Status

Phase 5 layer 1 done: harness + unit tests (~23 tests). Next per
the programme: API tests (auth, jobs — tonight's plan), then
applications/permissions, worker tests, and the coverage target the
README has promised (80%+) — the addopts make progress toward it
visible on every run.

### Article angles

- "Test stages, not test containers: multi-stage Dockerfiles grow a sibling, not a wart"
- "Factory fixtures: factory_boy's ergonomics with zero dependencies"
- "Boundary values are where validators live: exactly 5 MB, and one byte over"
- "A test can be a docstring: pinning the None your API returns for empty skills"
- "Banker's rounding will surprise your match scores — pin it before it pins you"
