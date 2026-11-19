# Wake Record Schema

Default write schema version: `1`

Supported read schema versions: `1`, `2`, `3`, `4`, `5`, `6`, `7`

Wake records are durable runtime records stored as JSON. They are operational state, not source artifacts. Schema version `1` remains the default for the existing timer, file, process, CLI, and plugin writers. Schema version `2` is reserved for capability-gated signal records backed by the root-local signal journal. A schema-v1 record whose predicate claims `type: signal`, an unknown version, or a malformed schema-v2 record is held rather than evaluated through the legacy predicate path.

## Signal Record Version 2

A signal record adds the required top-level fields `arm_id`, `journal_uuid`,
and `record_revision`. Its predicate has `type: signal`, contract version `1`,
the same `arm_id`, source and source-instance routing, occurrence or state
semantics, bounded `eq`/`in` clauses, verification policy, and its durable
registration anchor. IDs use the runtime's restricted safe identifier grammar;
path separators and dot segments are invalid.

The journal lives at `signals/journal.sqlite3` beneath the resolved wake root.
Registration commits a prepared arm and exact JSON outbox payload, durably
publishes and verifies revision 1 under `pending/`, and only then marks the arm
published. A match reservation and exact revision-2 firing payload commit in
one SQLite transaction. Publication uses a unique temporary file, file and
directory synchronization, atomic replacement, and pending-directory
synchronization after removal.

Revision 2 firing records include a bounded `trigger_match` with the stable
match token, receipt identity and local sequence, sanitized evidence reference
and attributes, verification state and method, match time, and evidence digest.
Dispatch revalidates the complete record against the applied outbox payload,
published arm, journal identity, lifecycle, and reservation before any target
transport is called.

Signal publication requires a recent managed-reader capability bound to the
exact root, process ID, process start identity, boot ID, reader generation, and
schema support. Static schema output describes binary support but is not
runtime authority. Missing, corrupt, mismatched, stale, or unsupported
authority fails closed. Opening a missing journal for daemon polling or CLI
inspection does not create it.

Cancellation and dispatch share a root-and-wake lifecycle lock. Terminal
tombstones prevent stale pending or firing copies from restoring eligibility;
archived signal evidence is deleted only after durable terminal fencing and
pin release. Startup reconciliation is bounded and may repair exact outbox
payloads, but never derives live authority from JSON alone.

## Required Top-Level Fields

New legacy timer, app-server, file and process records require qualified Stable
Time UTC before publication. Missing UTC holds creation with
`stable_time_creation_unqualified`; it does not substitute the guest clock.
Legacy relative timers round the accepted raw upper UTC bound upward to a whole
second before adding the duration, so serialization cannot make them due early.
Their metadata keeps the existing whole-second representation. Explicit trusted
host-supplied creation times remain supported. This does not change the separate
native intent clock domains, absolute timestamp parser or protective cancellation.

- `schema_version`: integer schema version.
- `id`: stable wake id.
- `created_at`: UTC timestamp.
- `updated_at`: UTC timestamp; legacy or untimed native records may use `null` when no UTC observation is available. Schema2 retains its required timestamp contract.
- `cwd`: creating working directory.
- `target`: dispatch target object.
- `predicate`: trigger predicate object.
- `prompt`: wake instruction text.
- `status`: wake status.
- `attempts`: dispatch attempt count.
- `max_attempts`: bounded retry limit. Schema-v2 signal registrations default
  to `3`; supported callers may select an integer from `1` through `100`, and
  the selected value participates in idempotency identity.
- `safety_deferrals`: optional count of tmux pane-safety preflights that
  deferred delivery before any prompt paste.
- `max_safety_deferrals`: optional independent pane-safety retry bound. It
  defaults to `3` when the first unsafe-pane result is recorded.
- `ack_timeout_seconds`: ack wait limit.
- `next_attempt_at`: UTC timestamp for the next dispatch attempt or predicate check.
- `events`: ordered audit events.

Default event appends and authorized status moves use qualified Stable Time UTC,
or `at: null` with `time_status: "not_observed"` when UTC is unavailable. A move
uses one observation for both its `updated_at` and event timestamp. It preserves
the original creation time, trigger, deadline and identity. Untimed native intent
events keep their existing null-time shape without acquiring UTC. These metadata
operations do not grant dispatch authority or replace the separate signal-journal
terminal fence. Schema2 moves require UTC and hold before publication with
`signal_move_time_unqualified` instead of writing a null timestamp that its
existing decoder would reject; its cancellation/terminal-fence path is unchanged.

The daemon uses fresh qualified lower UTC bounds for legacy readiness and retry
decisions, holds a new signal match while expiry is uncertain, and preserves a
match already reserved by the journal. `time_held` in a poll result counts legacy
pending or firing records held by time admission; zero counts retain the existing
output shape. Relative native intents continue through their own qualified
counter domain even when UTC is unavailable. This does not establish a new
transport-side final-send guarantee for legacy targets.

Signal-journal preparation leases use the lower UTC bound to prove previous
ownership expired and anchor a new fixed lease. Continuation requires the fresh
upper bound to remain before that original expiry. Unknown or ambiguous time
holds new timed work, while inspection of an existing current-schema journal
remains available. New journal and migration timestamps require qualified time;
no schema or terminal-retirement timestamp contract changes here.

### Legacy cancellation audit time

Operator cancellation of schema-1 and schema-4 wakes uses qualified Stable Time
UTC when available. If UTC is unavailable or unqualified, cancellation remains
available: `updated_at` and the new cancellation event's `at` are `null`, and that
event carries `time_status: "not_observed"`. This is the same explicit unknown-time
shape used by network-time cancellation; a WSL timestamp or an old timestamp is
never substituted. Original creation time, trigger, deadline, target, identity and
attempt counters remain unchanged. These audit fields do not establish expiry,
authorize dispatch, renew a deadline or change terminal-state checks.

## Status Vocabulary

Active statuses:

- `pending`
- `firing`

Terminal statuses:

- `submitted`
- `failed`
- `cancelled`
- `expired`

Archived status:

- `archived`

Status directory names match these values, except archived records live in `archive/`.

## Target Variants

Tmux target:

```json
{
  "transport": "tmux",
  "tmux_socket": "/tmp/tmux-1000/default",
  "pane": "%11",
  "thread_id": "thread_abc",
  "client_pid": 12345,
  "client_start_time_ticks": 987654
}
```

`thread_id` is the durable Codex delivery identity. Creation resolves that
exact thread to one pane and stores the Codex TUI client PID plus Linux process
start-time ticks. The stored pane is then only a location hint. Dispatch reads
the exact thread's current name and cwd through app-server, searches the
captured tmux session, and pastes only when one pane has the same thread
metadata and the same live client-process identity. This prevents a reused
pane with the same title and cwd from inheriting delivery authority. The
original pane and a relocated pane are handled identically after selection.
Zero matches selects app-server fallback for the same `thread_id`; multiple
matches fail closed. Records created by older releases without `thread_id`
also fail closed because their pane location cannot prove delivery identity.

App-server target:

```json
{
  "transport": "app-server",
  "endpoint": "stdio://",
  "thread_id": "thread_abc",
  "codex_cmd": "/home/you/.local/bin/codex",
  "retry_active_writer": true
}
```

Only `stdio://` app-server dispatch is implemented in schema version `1`.
`codex_cmd` is optional and may be absent. When present, it is a validated
Codex CLI command or absolute path used by the daemon to launch local stdio
app-server dispatch. Generated service and supervisor configuration preserves
stable symlink spellings and rejects paths tied to version-managed Node
installations.

`retry_active_writer` is an optional boolean. Missing or `false` means an
active writer causes terminal wake failure after preflight. `true` permits
bounded requeue under the record's `max_attempts` and app-server backoff
schedule. Neither policy permits `turn/start` while the thread is active.

OpenClaw Gateway target:

```json
{
  "transport": "openclaw_gateway",
  "gateway": {
    "url": "ws://127.0.0.1:18789",
    "token_env": "OPENCLAW_GATEWAY_TOKEN"
  },
  "openclaw": {
    "agent_id": "main",
    "session_key": "agent:main:slack:channel:c0ahqqcg7j4",
    "channel": {
      "provider": "slack",
      "workspace": "default",
      "channel_id": "C0AHQQCG7J4",
      "thread_ts": "1779729958.218239"
    }
  },
  "dispatch": {
    "deliver": false,
    "timeout_seconds": 120,
    "gateway_timeout_ms": 180000
  },
  "openclaw_cmd": "/home/you/.local/bin/openclaw"
}
```

`openclaw_gateway` targets require a durable `agent:<agent_id>:...`
`session_key`. Channel fields are evidence and validation aids, not a
substitute for the session key. Gateway auth fields name environment variables;
they must not store token or password values. Dispatch sends a short
`WAKE_TRIGGER_ID=...` handoff prompt that points the OpenClaw agent back to the
durable wake record instead of embedding the original prompt text.

## Predicate Variants

Wall-clock predicate:

```json
{
  "type": "not_before",
  "due_at": "2026-05-18T21:15:00Z"
}
```

File-exists predicate:

```json
{
  "type": "file_exists",
  "path": ".codex/events/pytest.done"
}
```

File-changed predicate:

```json
{
  "type": "file_changed",
  "path": ".codex/events/build.log",
  "registered_exists": true,
  "registered_mtime_ns": 123,
  "registered_size": 456
}
```

Process-done predicate:

```json
{
  "type": "process_done",
  "pid": 12345,
  "registered_start_time_ticks": 987654,
  "registered_boot_id": "optional-linux-boot-id"
}
```

For `process_done`, `registered_start_time_ticks` and `registered_boot_id` are optional best-effort identity fields. Older PID-only records remain valid and fall back to PID liveness.

## Optional Fields

Current optional fields include:

- `context_paths`: paths the resumed agent should inspect.
- `evidence_paths`: log, marker, or evidence paths related to the wake.
- `last_error`: terminal failure detail.
- `previous_status`: status before archival.
- `archived_at`: archive observation timestamp, or unknown UTC. Legacy schema1/4
  operator archival remains available without time authority and records null
  timestamps plus an event with `time_status: not_observed`.
- `archive_time_bounds`: optional archival UTC evidence for timed schemas,
  `{basis: qualified_utc, lower: number, upper: number}`, or
  `{basis: not_observed, lower: null, upper: null}`. These bounds describe the
  archive operation's observation; they never renew a wake or its original
  scheduling anchor. Retention compares qualified current UTC lower against
  this retained upper plus the requested age, without rounding interval edges.
  Missing current UTC or an unqualified legacy archive age holds cleanup with
  an explicit error before deletion. Bare schema1/2/4/5 historical timestamps
  are retained as metadata and cannot supply qualified age. Older schema3
  network archives used an accepted upper truncated to whole seconds; its next
  whole second is a conservative upper for retention. Signal cleanup still
  requires durable terminal fencing and released retention pins. Untimed
  schema6/7/8 archival keeps its existing unknown-time cleanup policy.

  Older cleanup executables do not understand these evidence requirements. Keep
  them quiesced before adopting this retention policy on a root; source validation
  does not authorize mixed-reader deployment or working-root adoption.
- `dispatch_result`: accepted app-server `thread_id` and `turn_id` metadata
  when returned; for OpenClaw Gateway dispatch, sanitized Gateway metadata
  such as `run_id`, `status`, `summary`, `session_id`, provider/model, payload
  counts, and text summaries. It must not store raw assistant transcript text.
- `route_selection`: sanitized delivery-routing evidence. Its `outcome` is
  `original_pane`, `relocated_pane`, `app_server_fallback`,
  `ambiguous_match`, or `no_target`; it may include pane IDs and bounded error
  text but never raw pane or transcript content.
- `visibility_result`: sanitized tmux operator-visibility evidence when checked.
- app-server target `codex_cmd`: optional command path for launching local
  stdio app-server dispatch.
- app-server target `retry_active_writer`: optional boolean enabling bounded
  retry when preflight observes an active writer; absence means fail-fast.
- OpenClaw Gateway target `openclaw_cmd`: optional command path for launching
  local Gateway dispatch through the OpenClaw CLI.

Event objects may also include extra metadata such as accepted app-server turn
identifiers or `created_by` provenance. The OpenClaw plugin uses
`created_by: "openclaw-plugin:codex-wake"` on the initial `created` event.
An `unsafe_pane` event includes privacy-safe `pane_safety` metadata with a
stable `rule_id`, the bounded active-region policy, total and inspected
non-empty line counts, and the matched offset within that region. It must not
include the matching line or any other raw pane text.

Pane-safety deferrals are preflight results, not delivery attempts. They do
not increment `attempts` or emit `dispatch_attempt`; persistent unsafe state
fails after `max_safety_deferrals` so the record cannot requeue indefinitely.
These optional fields preserve schema compatibility and do not change the
schema version.

## Tmux Visibility Result

Tmux-submitted records may include a `visibility_result` object:

```json
{
  "transport": "tmux",
  "pane": "%11",
  "checked_at": "2026-05-23T16:30:00Z",
  "privacy": "raw_pane_text_not_stored",
  "classification": "visible_prompt_observed",
  "pre_capture": {
    "line_count": 45,
    "wake_marker_present": false
  },
  "post_capture": {
    "line_count": 46,
    "wake_marker_present": true
  },
  "post_marker_new": true
}
```

Classification values:

- `visible_prompt_observed`: the wake marker was absent before dispatch and
  present after ack.
- `ack_observed_visibility_unproven`: the hook ack was observed, but pane
  marker evidence did not prove a new visible prompt.
- `visibility_check_failed`: ack was observed, but post-ack tmux capture failed.

`visibility_result` deliberately stores counts, booleans, and classification
only. It must not store raw pane text or transcript content.

## Derived Ack Files

Ack files under `.codex/wake/acks/*.submitted` are derived evidence written by the Codex hook. They are not authoritative wake records and do not change the wake record schema version.

Ack files currently include:

- `wake_id`
- `submitted_at`
- `turn_id`
- `session_id`

## Compatibility Policy

Schema version `1` allows additive optional fields. A schema bump is not required for:

- adding optional top-level metadata
- adding optional predicate metadata with a fallback path
- adding event metadata
- adding derived diagnostic output outside the wake record
- adding CLI commands that read existing records without changing required fields

A schema bump is required for:

- renaming or removing required fields
- changing existing field meaning incompatibly
- making an optional field required for existing predicate records
- changing the status vocabulary or status directory layout incompatibly
- changing target transport semantics incompatibly
- changing predicate semantics so existing records would fire or fail differently without an explicit migration

Any schema bump must include a release note, validation evidence, and a migration or compatibility plan.

Schema version `2` does not replace or migrate ordinary schema-v1 records.
Mixed roots continue to evaluate valid v1 predicates when signal authority is
unavailable. Existing writers, including the OpenClaw plugin, remain on v1.
Managed downgrade must refuse active or recoverable v2 state; this contract
does not claim that an arbitrary unmanaged legacy process can be prevented
from reading files outside the managed-runtime boundary.

## Network Deadline Record Version 3

Explicit `after --network-time` and `at --network-time` writers add schema 3,
`time_policy` (version 1, network-first, plain-ntp-explicit-opt-in), and the
creation `time_observation`. Only `not_before` predicates are supported. Default
writers remain schema 1. New readers validate the policy and hold unknown
versions. Existing schema-2 signal authority is unchanged.

Relative creation rounds the accepted upper UTC bound upward to whole seconds.
Absolute `due_at` preserves fractional precision. Evaluation and direct dispatch
require a fresh accepted lower bound to reach the original deadline and retry
anchor. Uncertainty holds effects without rewriting the predicate. Cancellation
uses the shared lifecycle lock and records `updated_at: null` plus a cancellation
event with `at: null` and `time_status: not_observed`. Archive timestamps require
accepted time and retention deletion uses its lower bound.

Old unmanaged readers are not qualified for this version and must be quiesced
before using their roots. See [candidate release and rollback](release-notes/0.8.0-network-time.md).

## Native Record Version 4

Native time/file writers use schema4 so earlier releases hold these records
instead of treating an unfamiliar target as tmux. The required target fields
are `transport: native`, exact `thread_id`, local Unix `endpoint`, resolved
`codex_cmd`, `expires_at` and workflow `resume_policy`. Basic `not_before` and
`file_exists` predicates use the existing evaluator. Native submission intent,
queue acceptance and observed execution are separate fields; acceptance is
neither acknowledgment nor business completion.

Current readers retain support for earlier candidate schema1 native records.
`codex-wake native migrate WAKE_ID` previews promotion; `--apply` saves the
original under `migration/WAKE_ID.schema1.json` and changes only schema_version.
The command cannot submit, cancel, replace a thread or translate transport.
Uncertain effects retain their nonce and reconciliation state.

Rollback to an older release holds schema4 records unchanged. Preserve them
until restoring a capable reader; do not downgrade them to tmux or restore an
old candidate-native schema1 backup into an older live scheduler. Migration
backups are private operational state, not repository fixtures.

## Schema5: native network-time deadlines

New native after/at/file registrations use schema5 with the existing native target,
network-first time policy and bounded arming observation. Old readers1–4 hold this
version. Existing schema4 remains guest-timed; no record is silently migrated.
Relative creation/file TTL use the conservative upper bound; absolute deadlines
preserve fractional precision. Fresh bounded evidence gates due, retry and expiry;
uncertainty holds effects. Read-only native reconciliation and cancellation remain
available without trustworthy time and report unknown timestamps.

## Schema6: native scheduling intent and time recovery

Schema6 is used when StableTime is configured, acquisition fails, or native
creation requests `--idempotency-key`, `--time-tolerance`, `--stop-at` or `--json`.
Other healthy native writers retain schema5; existing records are not migrated.
Versions1–5 hold schema6. Rollback must preserve these records and restore a
compatible worker before automatic recovery can continue.

`scheduling_intent` stores canonical root, content fingerprint, optional stable
key, exact normalized schedule, TTL, tolerance, optional UTC stop, original
counter/UTC anchors and `origin_state`. Recipient endpoint, executable, thread,
prompt and cwd remain in the record. A root-scoped key is bound to all those
request fields: retries reuse the exact record; a different request conflicts.
Implicit deduplication covers identical active retained requests only. Automated
chains should supply a key per logical successor, including terminal retries.

`time_recovery.state` distinguishes `pending`, `pending_time`, `due` and
`missed_deadline`; reason, mode, conservative bounds and availability alerts
remain inspectable through show/list/status. A missed deadline changes record
status to failed. Qualification retries use the active worker's bounded poll
interval and a shared clock acquisition per pass, not a new scheduler. Clock
failures do not consume native delivery attempts. Uncertain submissions retain
their original nonce and reconcile exact native evidence without resending.

The authenticated service contract1.0 retains its strict UTC qualification
(maximum error below100ms, NTS-verified independent operators, bounded freshness).
An unavailable response with a valid host measurement, continuity epoch and
rate policy permits elapsed-only relative scheduling. The native QPC handoff
must match frequency, advance monotonically and stay within service maximum age.
Relative elapsed lower/upper bounds include one tick of quantization and the
maximum captured/current rate error. They never manufacture UTC. Per-wake
tolerance bounds the interval width, not service qualification.

Absolute deadlines/stops require qualified UTC. Lower bounds must establish
not-before; upper bounds must remain before expiry and stop. Dispatch refreshes
qualification before runtime checks and immediately before native queue admission,
reserving35s for the bounded30s queue handoff. This proves consumer admission
eligibility, not an atomic deadline contract inside the native queue or a
completed turn before expiry; queue acceptance, execution and acknowledgment
remain separate. Counter continuity changes after reboot/suspend hold the
original request unless a captured UTC anchor establishes its original deadline.
No initial clock means the original relative origin and expiry remain unknown.
The record stays held with `relative_origin_unanchored` and an actionable alert;
current clock recovery cannot restart the delay or extend the original expiry.
Earlier private candidate records with a rebased origin are held as unsupported.
Absolute expiry and UTC stop are never bypassed to recover availability.

Schema6 uses one atomic authority file under `pending/` for every unarchived
status, including firing and terminal states. Record status is authoritative;
directory membership is not. Publication is fsynced, and existing lifecycle
locks serialize evaluation, cancellation and pre-effect publication. This avoids
reviving an older pre-effect copy after a crash between status-directory moves.
Archival is an explicit operator action; its UTC timestamp remains unknown.
Automatic age-based cleanup skips the unknown-time archive, preserving stable
retry identity. Creation/events/acceptance also record unknown UTC rather than
using guest time. No guest wall-clock value authorizes timing or retention.

Contract2.0 finite NTS-verified bounds are supported with service freshness up to
300s and bounded QPC handoff. Per-request precision still governs dispatch.
Unbounded/best-effort UTC never supplies dispatch authority. Contract1.0 retains
its below100ms qualification. No relative origin is created after an outage.

## Runtime Intent Version 7 (runtime envelope version 1)

Schema7 adds a separately versioned `target` with `transport: runtime`,
`version: 1`, `runtime: grok`, opaque `session_id`, `binding_id`, pinned
`binding_sha256`, `method: terminal_observation` or host-approved
`native_preferred`, and `policy: wait`. No schema1–6
transport or actor identity is reinterpreted. Older readers hold schema7;
unknown runtime/envelope/method/policy combinations are held by current readers.
Schema7 is allocated against MR-02/e435175, whose highest read version is6.

The original `scheduling_intent` retains canonical root, stable idempotency key,
request fingerprint, original trigger/TTL, qualified UTC/counter anchors and
clock-continuity policy. Shared schema6 eligibility code evaluates time; relative
requests are never rebased on restart or recovered clocks. All events lacking
qualified timestamps remain explicitly unobserved. Schema7 cancellation and
dispatch share the existing wake lifecycle lock and emergency pause guard.

`runtime_delivery` records one durable submission UUID, exact prompt digest,
method, certainty, execution and acknowledgment before terminal input. Ambiguous
input stays uncertain across restarts and expiry; absence of UI evidence never
authorizes replay. An exact accepted marker line in the bound TUI can resolve
terminal observation, but cannot create execution or receiver acknowledgment.
The marker must be a standalone accepted line, never a composer draft. Terminal
frames are projected as hashes; private captures and credentials stay out of Git.

The binding file is operator-enrolled under `runtime-bindings/` with restrictive
ownership/permissions. Its digest is frozen in the intent. Process/boot/start
identity, executable digest, managed-launch session argument, exact pane PID,
qualified minimal UI and a fresh local session-info response precede prompt input.
A user-scoped per-pane lock serializes Wake recipients across roots. Direct user
keystrokes are not atomic with these checks; terminal observation is the actual
guarantee. Queue/interrupt/native Grok receipts remain unsupported/unqualified.

Managed workers advertise read version7 through the existing health contract.
Agent-facing registration requires an active compatible worker; a registration
failure after persistence retains its original intent and reports the worker gap.
This source slice does not upgrade a production worker or create a grant.


### Runtime policy and mailbox binding extensions (MR-04/MR-05)

Queue/interrupt selections are public choices but refuse before retention or input
until their guarantees qualify. Wait remains default. Native Codex wake CLI and
Grok CLI/MCP expose explicit busy-policy selection. No strict dequeue expiry or
owned-turn interruption is inferred from native queue admission.

An operator may add `allow_terminal_fallback: true` to a newly enrolled Grok host
binding through the explicit bind option. Its hash stays frozen in each original
intent. Only definitive `not_sent` + `pre_io=true` + `native_unavailable` evidence
permits that profile's terminal fallback. Uncertain/accepted/missing evidence
never switches methods. The actually selected delivery method and terminal
observation remain inspectable. An older schema7 reader that does not recognize
`native_preferred` holds the record; old direct terminal bindings keep their meaning.

Mailbox actor capabilities and Codex actor namespaces retain their formats.
Grok actor context is a private operator-issued sidecar under `runtime-actors/`,
keyed by the issued actor ID and freezing the binding digest. Capabilities remain
independent authority. Caller validation checks process ancestry and generation,
runtime-inherited session claim, host-bound session context and enrollment root.
Native Grok caller attestation remains not qualified.

The mailbox bindings file recognizes `grok_terminal_notification_v1` alongside
existing owning-client/tmux transports. Old readers refuse the unfamiliar binding
transport. Grok notifications use the same user-scoped pane lock as durable wakes,
then revalidate journal authority and the original expiry/lease window. A terminal
frame hash receipt is transport observation, never an authenticated work receipt.
The existing mailbox claim/receipt protocol may subsequently strengthen that same
message with a real credentialed work claim. Unknown outcomes remain uncertain
and are never retried as if no bytes were sent. No bus schema migration is required.

## Schema8 policy-bearing scheduling intents

See [wake policy](../wake-policy.md#record-compatibility) for the exact fields,
legacy preservation and reader requirements. New native and managed Grok intent
registrations write schema8, retaining base intent version6/7 semantics. Older
records remain unchanged; unknown policy/record versions hold without delivery.

### Held acknowledgement outcomes

Historical firing tmux records may carry `ack_wait_time_held: true` from an
older clock-gated receipt wait. Their submission outcome remains unknown. The
current reader never pastes those records again; it can reconcile an existing
submission receipt into submitted status. Keep this no-replay fence during
correction and before downgrade to readers that do not understand the field.

Ordinary receipt polling uses a protective OS wait and does not need an extra
StableTime observation. Its timeout is not proof that a permission, lease, or
original wake expiry elapsed. Scheduling/retry anchors and genuine expiry checks
keep their own reliable-time requirements. A client/helper failure must not be
reported as a StableTime service outage.

Monitor health `checked_at` can be null with `time_status: not_observed`; such
health is never fresh. No wake record schema revision is introduced here.

### Signal cancellation without an observed timestamp

Schema2 cancellation remains available without qualified UTC. The record retains
its last observed nonempty `updated_at` and sets `updated_at_time_status` to `not_observed`; this retained value is not evidence of cancellation time. The
cancelled event has null `at` and `time_status: not_observed`. The decoder and
identity remain unchanged. A qualified cancellation records its qualified time.

The existing journal schema uses empty text for the unobserved retirement and
pin-release timestamps of this untimed cancellation. Empty text is not UTC or
retention evidence; NULL `released_at` still means the pin is unreleased. Arm
tombstones, terminal lifecycle status and released-pin presence fence replay.
Only cancellation supports untimed retirement: other terminal statuses return
`TERMINAL_TIME_UNQUALIFIED` when no timestamp is supplied. Archival and cleanup
keep their existing qualified-time and retention requirements.
