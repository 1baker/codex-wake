# Unified hierarchical control for the Byobu environment

State: CLOSED
Owner: ecochran76 / root
Work item: #623
Design: Plan0234, nineteen operator-confirmed decisions
Base: 1aa498674a4907f93b5216a4a98dd75a22c6ecec

## Current State

All eleven child tickets are validated and CLOSED. Canonical CLI/API/MCP control,
connector attenuation, observation/input/presentation and bounded programs are
source-delivered. One two-axis review and one bounded TDD pass resolved all accepted
findings; evidence: docs/dev/evidence/plan0234/{validation,review}.md.
PR644 merged8e5f6f7c and dev21 deployed under subsequent operator authorization;
see docs/dev/evidence/plan0234/deployment.md. Parent623 remains open as directed.
No new production schedules/grants or provider turns.

## Problem Statement

Managing "my tabs" currently requires learning disconnected wake, terminal,
conversation, account, harness and program surfaces. External connectors cannot
uniformly discover relationships, observe arbitrary existing turns, manage input
and interactions, or resume the original effects across disconnects. Terminology
and authority routes differ, and supported capabilities are difficult to discover.

## Solution

Provide a coherent hierarchical contract for the operator's Byobu environment,
including dev tabs, other terminal sessions, codex-bots and children. Expose the
same resource/action semantics through CLI/API/MCP, retaining old interfaces.
Deepen existing programming and native controls, preserving exact identity,
permissions, original-effect custody and honest capability/result reporting.

## User Stories

1. As an operator, I want to discover my complete Byobu environment across registered hosts, so that I can manage dev tabs, codex-bots and their children together.
2. As an connector author, I want to navigate terminal sessions, tabs and panes through one hierarchy, so that I do not learn different transport models.
3. As an operator, I want to see conversation, harness, runtime, account and agent-family links, so that placement and ancestry are unambiguous.
4. As an operator, I want to move a child tab without changing its agent parent, so that organization does not alter responsibility.
5. As an connector author, I want to resolve selectors to host-qualified immutable target generations, so that a renamed or replaced tab is not accidentally controlled.
6. As an operator, I want to observe background conversations without a visible pane, so that closing a presentation does not erase work.
7. As an connector author, I want to discover supported actions and typed argument/result schemas, so that I can adapt to each harness.
8. As an existing client, I want to retain compatibility entry points, so that the hierarchy does not break my integrations.
9. As an operator, I want to grant a connector my authority or a restricted subset, so that access matches my intent.
10. As an operator, I want to restrict metadata, content, input and administrative rights separately, so that observation does not silently grant control.
11. As an operator, I want to inspect and revoke connector grants, so that future access can be stopped without falsifying past effects.
12. As an connector author, I want to route requests to the owning registered host, so that an offline target never becomes a similarly named local target.
13. As an operator, I want to attach to an already running conversation from any permitted source, so that I can observe turns started by people, wakes or other clients.
14. As an operator, I want to read structured turn and tool events with ordered cursors, so that I can follow actual execution.
15. As an operator, I want to read end-of-turn status and the saved final answer, so that stream loss is not mistaken for completion.
16. As an operator, I want to read rendered TUI snapshots and incremental output separately, so that I can inspect what the terminal displays.
17. As an connector author, I want to resume observation after reconnect with explicit gaps and snapshots, so that bounded retention is truthful.
18. As an operator, I want to configure observation retention without retaining credentials or hidden reasoning, so that useful observation respects content boundaries.
19. As an operator, I want to send a prompt with explicit reject, queue, steer or interrupt-then-submit policy, so that busy behavior is deliberate.
20. As an operator, I want to protect an existing composer draft, so that automation does not overwrite unfinished human input.
21. As an connector author, I want to distinguish retained input, submission, running and completion, so that acceptance does not masquerade as execution.
22. As an operator, I want to discover and run supported slash commands, so that I can control the harness through typed actions.
23. As an operator, I want to read, answer and cancel menu/choice/confirmation interactions, so that interactive controls work across transports.
24. As an operator, I want to receive explicit unsupported outcomes without prompt or keystroke fallback, so that a failed control does not start unintended work.
25. As an operator, I want to explicitly paste text or send keys to an exact permitted pane, so that shells and other TUIs remain manageable.
26. As an operator, I want to see terminal delivery separately from semantic success, so that input acknowledgment is not exaggerated.
27. As an operator, I want to move a conversation between foreground and background, so that identity, active work and cumulative accounting survive presentation changes.
28. As an operator, I want to separately close an attachment, interrupt a turn, stop a runtime or delete history, so that lifecycle effects are intentional.
29. As an operator, I want to manage account profiles, authentication and configuration in one family, so that account ownership remains explicit.
30. As an operator, I want to inspect harness capabilities, builds and runtime lifecycles, so that compatibility and readiness are discoverable.
31. As an operator, I want to read/resume/import conversation history through the conversation resource, so that saved records retain exact ownership.
32. As an operator, I want to use triggers, schedules and deliveries through the wake hierarchy, so that existing durable timing policies remain intact.
33. As an program author, I want to compose wake and session actions as typed callable operations, so that structured programs can manage real work.
34. As an program author, I want to use first-class if/then/else, select/case, foreach and bounded while, so that control flow expresses the intended task.
35. As an program author, I want to route unknown, error, timeout, cancellation and exhaustion explicitly, so that uncertainty is not silently treated as false.
36. As an program author, I want to define versioned semantic functions with typed inputs and results, so that predicates, classifications and extracted objects can be reused.
37. As an operator, I want to declare semantic function effects, tools and limits, so that evaluation alone does not grant action authority.
38. As an operator, I want to freeze bulk target membership and inspect per-target outcomes, so that partial failure does not hide successful or uncertain effects.
39. As an operator, I want to retry by reconciling original effect identities, so that successful actions are not duplicated.
40. As an program author, I want to pin definitions, function versions, inputs and execution policies per run, so that later edits cannot mutate admitted work.
41. As an operator, I want to resume durable runs after connector or process loss, so that reconnection observes original work.
42. As an operator, I want to use deep structured Codex and existing Grok controls with terminal support elsewhere, so that unsupported harness semantics remain honest.
43. As an connector author, I want to complete one documented discovery-to-reconnect management journey, so that the public contract is usable in practice.

## Implementation Decisions


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


- One canonical resource/action registry owns discovery, schemas, compatibility
  mappings and generated transport naming. It dispatches into existing behavioral
  owners rather than duplicating their state, authorization or lifecycle rules.
- Canonical families are environment, wakes, programs, accounts, harnesses,
  operations and connectors. Dotted operation names, nested CLI verbs and MCP
  names derive from the same entry; old routes remain supported aliases.
- Results preserve underlying evidence: unsupported/unavailable, admitted/queued,
  running/completed/failed/cancelled and uncertain effects remain distinct.
- Local operator and delegated connector routes share semantics while retaining
  independently verified identity. Model arguments cannot supply operator role.
- Existing clock/session modes, frozen occurrence identity, permission policy,
  task scope and cumulative limits remain authoritative. No default authority
  expansion, uncertain replay or replacement executor is introduced.
- Observation attaches to an exact existing conversation/turn; terminal streams
  have separate cursors and completeness from native structured events. Content
  access is checked on every page/subscription resume, including after revocation.
- Program selection/case preserves declaration order with one selected arm and an
  explicit default. While checks its condition on each iteration under finite
  iteration and inherited cumulative limits; unknown/errors have typed routes.
- Semantic function schemas validate outputs and preserve Boolean compatibility;
  inference effects require declared scope and supported native capability. Exact
  metering or isolation must not be advertised when only estimates are qualified.
- No action silently substitutes foreground/background mode, input policy, host,
  harness or terminal fallback. Explicit unsupported capability is a result, not
  a successful implementation claim for an advertised supported action.

## Testing Decisions

- Primary seam: real public operation dispatch as used by CLI/controller. Verify
  observable results and durable identities through public inspection, not private
  storage assertions. Exercise generated API/MCP schemas and routing for parity.
- Use existing unittest runner, existing deterministic adapter injection and narrow
  private roots. Do not create fixture projects, mock frameworks or coverage-only
  deliverables. Keep native/provider effects outside the default lane.
- Reuse flow/condition, local session/slash, tab/terminal, permissions/hosts and
  wake regression tests. Add one vertical red/green behavior at a time only for
  a named acceptance criterion or consequential regression risk.
- Focused checks have a 120-second per-command budget; presubmit selections have
  a 600-second per-command budget. Record exact selection/source/environment,
  first failures, timings and skipped live/provider risks. Hosted paid CI skipped.
- One final two-axis broad review against the operator-approved fixed point;
  adjudicate findings and run one bounded TDD remediation pass, then focused
  blocker/critical-regression checks. Do not restart broad review loops.
- Connector journey proves hierarchy/permissions, existing-turn observation,
  explicit input and interaction, program/wake composition, original-result
  retrieval after reconnect, and refusal on stale target/revocation/unavailable
  host. Inject only the external native/provider boundary and label that scope.

## Out of Scope

- Merge, deployment, working-host restarts, native daemon upgrades or real provider
  turns without separate authorization; production schedules and grants unchanged.
- A new general-purpose language, replacement runtime, implicit cross-host launch,
  universal native slash support or exposing private credentials/hidden reasoning.
- Changing the separately active Grok-in-Codex implementation lane or its provider
  internals. Consume existing Grok capabilities and report unsupported ones.
- Deleting compatibility interfaces, state/history, unrelated worktrees or parents.

## Further Notes

The interview and ADR supply design authority. The implementation ledger records
exact dependencies, custody and validation; tracker closure is separate from Git
integration, installed qualification and runtime acceptance. Close child tickets
only when their public acceptance criteria are validated; leave the spec parent
open. The final output is one validated integration branch, not a live release.
