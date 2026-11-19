# Manage the Byobu environment through one control contract

Canonical families are `environment`, `wakes`, `programs`, `accounts`, `harnesses`,
`operations` and `connectors`. The same dotted operation IDs become nested CLI
verbs and MCP names prefixed `wake_` with underscores. Existing entry points remain
callable compatibility routes with their original owners and permission rules.

Start with `codex-wake environment capabilities` or the generated
[contract](unified-control-contract.json). Registration is distinct from current
harness readiness. Local/private and protected routes retain their own admission
and schemas; native MCP preserves its original verified caller requirements.
The portable controller client gets operation/tool names from generated pure data.

## Navigate my tabs

`codex-wake environment snapshot` returns terminal sessions, tabs, panes and
independent agent-family links. `environment children RESOURCE_ID` follows physical
or logical children. Empty saved sessions remain visible; background conversations
need no visible pane. Moving a tab does not reparent its bot. Every target retains
host/environment and generation evidence; similarly named resources never substitute
for an unavailable host. Narrow connector grants filter the visible projection.

The saved user controller remains the default for environment/account controls.
Existing project wake roots and legacy command root rules are preserved. Supply
`--wake-root ROOT` when composing operations against one explicit configured root.

## Read conversations and terminal output

`environment conversations observe` accepts an exact existing conversation and
turn, producing a durable observation handle. Use `observation output/result` with
that handle and cursor to reconnect. It never resumes the thread or submits a
prompt. The current Codex adapter uses read-only native snapshots, including
structured tool/turn state and final answers, with `native_thread_snapshot`
provenance, explicit history gaps and `live_notification_stream=false`.

`environment panes capture/observe/output` is a separate rendered-terminal route.
It uses bounded snapshots and cursors with explicit retention/gaps; it does not
claim lossless native notifications or infer completion from terminal text.
Native reasoning items are excluded; terminal reads require qualified safe privacy
and content permission. Unknown privacy, stale identity or revoked rights refuse.

## Write deliberately and follow the original result

`environment conversations input submit` requires `policy` equal to `reject`,
`queue`, `steer` or `interrupt_then_submit`, plus a stable idempotency key. Busy
policy is never silently substituted. Native input does not overwrite a composer
draft. Inspect the original input handle with `input result`; retained queue input
and acknowledged steering are distinct from executing/completed turns. A lost
reply retains uncertainty and is not permission to submit again.

`environment conversations slash list/run/result/respond/cancel` uses supported
native mappings and durable interactions. Codex has qualified `/status` and
`/rename`; unqualified native pickers remain unsupported. Existing Grok structured
adapters retain their capabilities. No failed slash action becomes a model prompt
or terminal keystroke. Explicit `environment panes paste/keys` is separately
permitted, pinned to actual pane/server/process and broker custody. Literal paste
has no implicit Enter; explicit key actions are distinct. Delivery is not semantic
success and unknown/private drafts remain protected.

`environment conversations presentation background/foreground` supports explicit
`park_live`/`restore_live` routes for a qualified single-pane conversation. It
reports `parked_live_tui`/`foreground_live_tui`, preserving the original pane/process
and park receipt. A multi-pane/unknown binding is refused. Headless detach and
unqualified popup protocols are unsupported; no daemon stop, history deletion,
new conversation or resource renewal is substituted.

## Accounts, harnesses and wakes

Account profile/authentication/configuration/store operations retain exact owner
and credential handling. Harness builds/runtimes and conversation history reuse
existing lifecycle owners. CLI-native login stays local; discovery does not imply
remote credential access. History read/resume/import retains original ownership.

`wakes intents after/at/file` and `wakes schedules register/list/show/revise/cancel`
reuse existing durable owners. Recurrence requires explicit mode/cadence/end/
missed/overlap policies. Revision affects future work and cancellation does not
undo running/uncertain effects. Program-callable protected wake actions recheck
current actor/target permission; mutation receipts redact stored content without
`content.observe`. Compatible monitor readiness remains distinct from retention.

## Programs and bulk work

`programs definitions` and `programs runs` expose existing durable flows. Nodes
include call, wait, branch, foreach, ordered select, finite while, typed function
and end. Select has explicit default/unknown/error paths. While requires a finite
bound (1–64); expansion is bounded to 1,024 nodes. Definitions and function versions
are pinned per run. Conditions remain Boolean; typed functions can return declared
primitive/JSON results. Unknown/error/timeout is not false. Semantic calls preserve
inherited limits, allowed callees and explicit action rights. Native exact metering
and observation-only tool isolation remain unqualified; estimates require opt-in.

`programs bulk start/status/result/advance/reconcile/cancel` lowers at most16explicit
members into that same flow executor. Each member declares ID, exact target,
operation, arguments and admission-versus-terminal completion. Policies explicitly
select stop/continue, all_success/all_complete, uncertainty hold, and bounded safe
read retries; effect retries are refused. Domain keys are derived and frozen in
top-level/nested owner arguments. Status is metadata; result requires content rights.
Unknown effects without a recoverable original handle stay held.

Bulk and connector administration use the authenticated controller route, including
natural CLI forms with `--controller-endpoint`, `--controller-token-file` and
optional `--controller-transport api|mcp`. No local/model argument can claim an
operator role. The generic `controller remote OPERATION` client also accepts
canonical IDs; it uses the same schemas and original operation handles.

## Connector authority and owning hosts

Connector grants can represent full explicitly approved access or narrowed
scopes/actions/targets. `content.observe` and `terminal.input` are separate from
metadata observation, ordinary control and administration. Grant issuance requires
an authenticated owner with admin; child rights/expiry cannot exceed the parent.
Revocation is checked on subsequent pages/actions and inherited by children; it
does not erase effects already admitted. Original caller identity stays in custody.

Remote management requires explicit registered host capabilities and pinned SSH
execution authority. Legacy registrations remain read-only. The receiver intersects
rights and calls the actual owning operation; unavailable hosts never fall back to
a similarly named local resource. Credentials and token files stay private and are
never operation arguments or captured terminal output.

## Acceptance map

The existing unittest seam covers actual protected HTTP/MCP/CLI program/wake
handles across reconnects, scoped delegation and revocation, arbitrary-turn
snapshot observation, supported slash interactions, native input policies, exact
terminal input/park/restore and bulk original-effect recovery. Private tmux tests
exercise real literal paste/keys and process preservation; native/provider replies
are injected at their external seam. This is source/disposable-package validation,
not live provider, working-host deployment, native push or Windows ownership proof.

Regenerate with `scripts/generate_unified_contract.py` and
`scripts/generate_command_reference.py`; their `--check` modes reject drift.

Delegated credentials require this compatible reader. Codes are stored separately
and access/refresh kinds are versioned so an older controller cannot redeem or
accept them while ignoring restrictions. The authority migrates old pre-release
delegated codes and invalidates unfenced delegated tokens; ordinary existing grants
are preserved. Exact historical-reader qualification is tested against the recorded
Git baseline, with code exchange, access authentication and refresh all refusing.

Delegated program-definition reads and run-state returns require `content.observe` in addition to their base observe/control scope, because definitions and run snapshots contain literal prompts, inputs and child results. This applies equally to compatibility routes; discovery lists `delegated_required_scopes`. Metadata-only bulk status remains redacted.

## Protective local stop and revocation metadata

Remote controller actors require qualified Stable Time UTC for expiry admission.
A missing clock does not extend a grant or authorize a retry. Explicit trusted
clock callbacks remain a local test seam.

The immediate local daemon CLI can stop only its exact confirmed, pinned daemon
through a private per-call capability bound to the owning UID, private Wake root,
full target and original request IDs. This live object is never serialized or
recreated from saved records and grants no other mutation, background or retry
authority. HTTP and MCP retain actor authentication. The daemon owner still
checks confirmation, account/home/build/process pins and its private lock.
A repeated completed or uncertain stop returns its original journal without
resending; changed pins or IDs conflict.

A new protective local-stop record may have `created_at: null` with
`created_at_status: "not_observed"` when qualified UTC is unavailable.
The existing nullable `revoked_grants.revoked_at` SQLite audit column likewise
uses qualified UTC or null: the original issuer/resource/grant revocation latch
and bounded owned cancellation remain available without clock authority. These
metadata exceptions neither create actor expiry values nor admit ordinary work.
Existing journal timestamps, identities, revisions and outcomes remain intact.
