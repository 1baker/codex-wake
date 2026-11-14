# Unified Wake control surface design interview

State: CLOSED
Owner: ecochran76 / root
Scope: design interview; no implementation or runtime effects

## Current State

Operator requested a next specification gathering and deepening wake functions,
tab functions, structured programming, session/account controls and session/harness
read/write. CLI/API/MCP must form a coherent hierarchy, usable by external
connectors managing "my tabs". Round1 decisions below confirmed by operator;
all19decisions and shared understanding confirmed. Approved specification and
eleven-ticket implementation graph now own execution.
Existing GLOSSARY.md remains terminology authority. Preserve the separate Grok
in Codex design0233 and existing runtime/permission contracts.

## Scope

Define the resource model, ownership/discovery, transport parity, read/write and
event semantics, lifecycle controls and migration needs before deriving a spec.

## Non-goals

No code changes, live session control, automatic deployment or new permissions
through this interview. No duplicate glossary or unapproved command taxonomy.

## Confirmed decisions

- D1: "My tabs" means the operator's Byobu environment, including the main
  session ("dev tabs"), other sessions such as codex-bots, their tabs and children.
  It is not a new name for all saved conversation history.
- D2: A connector may act as the authenticated operator or with a subset of the
  operator's permissions. Existing identity and permission boundaries remain.
- D3: CLI/API/MCP share a coherent hierarchical resource/action contract, stable
  identifiers and result/event semantics, with harness capability discovery.
  Existing clients retain compatibility paths.
- D4: Deepen existing structured programming rather than assuming it must be
  newly invented. Operator specifically names foreach, if/then/else, select/case,
  while and semantic functions. Exact implementation mapping is being inspected.

- D5: Connector navigation is environment → terminal sessions → tabs → panes.
  Conversations, runtime/harness, account and parent/child agent relationships
  are explicit links. Placement changes do not change ancestry; conversations
  may exist without a visible attachment.
- D6: Permitted readers may attach to an already running conversation regardless
  of who submitted the turn, observing events/status/completion/final answers.
  Structured resumable subscriptions carry cursors and explicit gaps. Rendered
  TUI capture/stream is a separate advertised capability.
- D7: Discover and execute supported native slash commands and represent menus,
  choices, confirmations, follow-up input, results and cancellation as durable
  interactions. Unsupported commands are explicit, never silently model prompts.

- D8: Add first-class select/case and bounded while; preserve existing control
  structures and expose unknown/error/cancellation/exhaustion paths and bounds.
- D9: Semantic functions support declared typed outputs beyond Boolean predicates,
  with typed inputs, permitted effects and resource limits. Condition evaluation
  does not itself authorize actions.
- D10: Busy-session input behavior is explicit: reject/queue/steer/interrupt then
  submit, subject to capabilities and composer-draft protection. Durable handles
  distinguish retained input, submission, execution and completion. No silent
  behavior substitution.
- D11: Foreground/background transitions preserve conversation identity, work,
  permissions and resource accounting. Attachment open/close, turn interruption,
  runtime stop and history deletion are separate operations. Uncertain ownership
  fences duplicate execution.

- D12: Canonical resource families: environment (sessions/tabs/panes/agents/
  conversations), wakes (triggers/schedules/deliveries), programs (functions/
  definitions/runs), accounts (profiles/authentication/configuration), harnesses
  (capabilities/builds/runtimes), operations (status/events/results/cancellation),
  connectors (identities/grants/connections). History belongs to conversations;
  daemon controls belong to harness runtimes. Physical navigation and resource
  links share stable identities; existing entry points retain compatibility.
- D13: Connector grants can represent full operator access or a subset restricted
  by environment/account/resource/action, with separate metadata/content/input/
  administrative rights. Grants are inspectable and revocable. Revocation blocks
  future access/actions without claiming already-submitted effects are undone.
- D14: Bulk operations freeze membership, expose resolved targets, recheck each
  identity and permission, and retain per-target success/failure/uncertainty.
  Retries reconcile original effects instead of duplicating successful ones.
- D15: Runs pin definition/function versions/inputs/execution policies and survive
  disconnect/restart. Reconnection observes the same run. Changes affect future
  runs, uncertain effects reconcile and retries follow explicit policy.

- D16: Configurable observation retention, resumable cursors, explicit gaps/
  truncation and current snapshots when replay is unavailable. Structured events,
  rendered terminal output and receipts are distinct. Stream loss is neither
  completion nor authorization to resubmit. Credentials/hidden reasoning excluded.
- D17: One connector may manage permitted registered environments across hosts.
  Every resolved target includes host identity and routes through the owning host;
  unavailable hosts never retarget similarly named local resources.
- D18: Explicit terminal paste/key input is supported with separate permission
  and exact pane identity, including shells/unsupported harness controls/TUIs.
  Structured operation failures never silently fall back to terminal input.
  Terminal delivery does not prove semantic execution succeeded.
- D19: Cover all operator Byobu tabs. Deep structured support targets Codex and
  the existing Grok adapter; other shells/harnesses expose terminal controls and
  truthful capabilities. Connector acceptance traverses discovery/children,
  existing-turn observation, input/interactions, programs/wakes and reconnect/
  original-result retrieval, identifying actual route and outcome at each step.

## Existing implementation baseline

Read-only inventory identifies call/branch/wait/foreach/end flow nodes;
branch implements if/then/else with an unknown path. Select/case has no first-class
node and while cycles are currently rejected. Foreach has snapshotted membership,
new_session/sequential/fork modes and bounded concurrency/join behavior.
Named/versioned semantic functions currently return Boolean predicates, support
typed inputs, deterministic expressions and allowlisted nested calls. Conditions
have known/unknown/error/timeout outcomes and cumulative limits. Native semantic
execution currently uses explicit estimated-metering opt-in and inherited tools;
exact enforcement and observation-only isolation are not qualified.
Sources: controller_flows.py, controller_flow_foreach.py, controller_conditions.py,
controller_condition_native.py. Existing work is the baseline, not a new feature
claim; absent first-class constructs and capability limits must be addressed.

## Decision frontier

All19interview decisions and shared understanding confirmed. The operator
subsequently approved the public seam, eleven-ticket graph and implementation.
See0234-2026-11-14-unified-control-spec.md and its execution ledger; this interview record
adds no live-effect authority.
Exact schemas, command verb spellings and retention sizing remain specification
work constrained by these decisions, not new authority or implicit policy choices.

## Architectural decision

See docs/adr/0007-unified-connector-control-contract.md. GLOSSARY.md preserves the
distinction between the Byobu environment, terminal sessions/tabs/panes,
conversations, runtime instances, presentation attachments and coding harnesses.

## Acceptance criteria

Resolve all interview branches, record approved definitions in GLOSSARY.md,
record qualifying architectural trade-offs sparingly, and obtain confirmation
of shared understanding before converting the design to implementation work.

## Definition of done

Confirmed design with traceable decisions, unresolved gaps explicitly named and
one agreed basis for the next specification. Implementation remains separate.
