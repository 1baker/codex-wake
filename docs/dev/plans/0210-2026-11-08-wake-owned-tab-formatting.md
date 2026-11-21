# Wake-owned tab formatting

State: CLOSED
Owner: primary / ecochran76
Work item: #517; implementation #518–#524
Branch: feat/tab-formatting-517
Base: 3a02f9dc9e59eef8151cc6015f19a6cd4b22e2de
Domain authority: GLOSSARY.md

## Current tracker reconciliation | P255

Issue #517 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Current State

Spec #517 and tickets #518–#524 were published with native dependency links.
All seven implementation tickets are validated and tracker-closed on the integration
branch. Runtime source 4a5aa6d passed 73 focused tests on each Python 3.11/3.12
and exact installed Byobu/psmux public CLI, API and MCP acceptance, including native
PowerShell. One broad review and one bounded TDD remediation pass are complete;
all four findings are resolved. Earlier full-suite failures and their targeted
repairs remain recorded as composite qualification, not a clean single full run.
See the execution ledger and review/final-report.md for exact evidence.
Stock Codex, native sessions and real workspace formatting are preserved.
PR #525 merged as cb7cf62 and its exact qualified wheel is deployed under
operator authorization. Nine launchers and the local HTTP listener select the new
release; stock and 30 native process generations are preserved. Deployment receipt:
`docs/dev/evidence/plan0210/deployment.json`. Real workspaces remain undecorated
until enabled; existing MCP clients reload individually. Parent spec #517 stays open.

## Settled operator decisions

- Wake owns observation, classification and updates; terminal backends render
  published metadata. Observation, activity, health and error remain independent.
- One WSL service manages Byobu/tmux and native Windows psmux through adapters.
- Qualify WSL-hosted operations first. A Windows-native service is a later
  roadmap milestone, sharing core/contracts and remaining available without WSL.
- Retain stock Codex, user tab names, conversations and unrelated terminal state.
- Operator requests highlight colours that vary by both tab type and observed
  state; selected-tab styling is not restricted to the existing fixed teal.
- Operator accepted state precedence: fresh current error, then health warning,
  then waiting; otherwise use type/activity colour. Entirely stale observations
  receive neutral grey. Other traits remain visible in badges/symbols.
- Plan future Claude Code, custom/open coding harnesses, custom models and local
  serving through Ollama. These are future adapters, not first-milestone
  implementation or claims of already supported combinations.
- Operator accepted compact default labels: type, profile, activity and existing
  name. Model/provider badges and styling rules are optional; full details are
  available on demand.
- Automatically decorate owned tabs, with global/per-workspace opt-out. Preserve
  manual names and conditionally restore previous styling. Formatting never
  moves tabs, restarts agents or starts model work.

## Scope and non-goals

Define visual encoding, installation/ownership/reversal and both-backend runtime
qualification for Wake-owned tab formatting. Backend-independent policy should
allow future Windows hosting. This delivery does not implement the Windows
service, modify production formatting, restart production services or
submit provider/model work. Physical tab rearrangement is a separate policy.

## Pre-implementation evidence (historical)

- Byobu6.11 and tmux3.4 installed. Live formats show index/name with selected-tab
  highlight; no Wake formatting projection exists in the current bridge.
- tmux supports per-window user options, format substitution, normal/current
  formats/styles and status refresh. Byobu's final user include is
  $BYOBU_CONFIG_DIR/.tmux.conf (installed profiles/tmuxrc lines25–30).
- Current psmux upstream has corresponding options/styles/format and refresh
  mechanisms. Installed executable SHA bbe825a30f7cddc91b043084049143a381aba5f7e9e36e4d0bb587e296d262ca
  matches existing native lifecycle qualification; source/version equivalence
  and native formatting are not yet qualified.
- Finite Windows bridge currently exposes snapshot/discover/capture/visible_screen/
  swap/lifecycle/attach_saved, without formatting read/write/unset/readback or
  presentation restoration. Extending it requires a finite typed operation.
- Installed psmux isolation/inheritance, escaping, active/inactive rendering,
  Unicode widths, refresh, restart persistence, theme coexistence and restoration
  remain runtime acceptance axes. No native psmux command was executed for this
  fact pass; production namespaces were untouched.

Sources: src/codex_wake/tab_psmux_bridge.py, controller_tab_adapters.py;
docs/dev/evidence/plan0209/514/windows-psmux-pass.json;
https://man.openbsd.org/tmux.1 ;
https://github.com/psmux/psmux/blob/master/src/server/options.rs ;
https://github.com/psmux/psmux/blob/master/src/server/option_catalog.rs ;
https://github.com/psmux/psmux/blob/master/src/format.rs ;
https://github.com/psmux/psmux/blob/master/src/cli.rs .

## Open decision frontier

No unresolved product questions. Operator approved publication and implementation.
Runtime compatibility findings are acceptance evidence, not new product decisions.

## Acceptance target and definition of done

A shared, explicitly confirmed visual contract and reversible ownership rules,
with bounded backend qualification criteria and all frontier decisions recorded.
Update domain terms only when a new term is actually resolved. Use ADRs only
for consequential, surprising tradeoffs. Specification/ticket publication and
implementation follow their separately invoked stages.

Next action: integrate validated worker results serially, then schedule remaining ready tickets.

## Interview steering: type/state highlights

Operator asked for highlight colour itself to vary by type and state. Confirmed
preference recorded. Accepted precedence: type/activity supplies the base; fresh
error overrides health warning, which overrides waiting. An entirely stale
observation uses neutral grey; a stale individual trait must not suppress a
fresh independently observed error. Type and other dimensions remain in badges.
The badge grammar and exact palette remain under interview. Bold/underline or another supported independent cue keeps
selection obvious. Text/symbols duplicate meaning rather than relying on colour
alone. Exact palette and backend rendering remain unsettled; state precedence is confirmed.

## Future harness/model/provider support

Future adapter families include Claude Code and user-supplied/open harnesses;
future model/provider support includes custom models and local serving through
Ollama. Classify them separately: coding harness, harness build, profile, reported
model identity, inference provider and execution host. For example, a qualified
custom harness could report a Qwen model served through Ollama. This is a data
shape example, not a claim that every harness supports every provider.

Use extensible identifiers, display labels and capability declarations rather
than baking the first few harness names/model combinations into rendering.
Unknown or unsupported identity/health/control remains explicit. Models and
providers may be absent, change by turn, or be configured without actual use;
retain provenance/freshness and distinguish configured selection from observed
usage. Detection of a local model server alone does not prove a tab uses it.

Current APIs sometimes use provider for a harness/runtime adapter. Preserve
those existing contracts; normalize explicitly at adapter boundaries rather
than silently reinterpreting legacy provider fields as inference providers.

Operator-confirmed defaults: keep harness/profile/activity compact
on tabs; optional model/provider badges and selected-tab details; allow explicit
style/group rules to use reported model/provider when available. Qualify each
adapter's observation and control capabilities independently. Merely declaring a
custom adapter or model does not grant prompt/slash/lifecycle/health capabilities.
No new model server, GPU workload, harness or provider call is started by this
interview or by passive observation.

## Refresh, mixed panes and manual override decisions

Operator accepted immediate reliable event updates with a roughly five-second
bounded polling fallback and twenty-second stale threshold. Selection remains
native and immediate; rendering launches no probes or model work. Expiry must
still work after Wake loss; exact backend mechanism requires qualification.

Mixed-pane tabs display a mixed-type badge and the highest-priority fresh
attention state across panes, with individual pane details available. Unsupported
health remains unknown; ordinary shells are not classified as unhealthy.

When a user changes affected styling, Wake yields for that scope, continues
observations and requires explicit decoration resume. Manual tab renaming remains
available without pausing observation or fighting the new name.

## Persistent controls, qualification and rollback

Operator accepted persistent display settings and equivalent CLI/API/MCP controls
for enable, pause, resume, reset and inspect. Pane/model/provider details remain
available on demand without crowding default labels. Reconnecting clients regain
decoration while respecting manual overrides. Unsupported rendering falls back
to supported colours and plain-text badges; selection and staleness stay visible.

Installed Byobu/tmux and psmux acceptance must cover mixed panes, state changes,
Wake failure, reconnect, manual overrides and reversible restoration before
claiming formatting support for each backend.

Operator additionally requires one-command rollback and one-command re-enable.
Rollback disables automatic decoration/reapplication and restores original
settings captured before first decoration, including whether each affected
option was absent, inherited or explicitly set. The durable baseline is scoped
to backend/namespace identity and must not be overwritten by refresh, restart,
reconnect or re-enable. Touch only settings Wake manages; preserve unrelated
settings, tab names, sessions and processes. Restoration is read back and reports
partial failures explicitly; repeat rollback is safe. A missing baseline must
produce an explicit failure rather than fabricated defaults or a success claim.
Re-enable reapplies the saved Wake display policy without replacing the original
baseline. Both commands work through CLI/API/MCP and require no hand editing or
service restart. Exact command spelling belongs to the specification stage.

Explicit rollback restores the saved original values even where affected styles
were subsequently edited manually; automatic cleanup still yields to manual
changes. Capture only the values/scopes Wake will change, so restoring originals
does not entail replacing entire theme files or unrelated terminal configuration.
Acceptance includes repeated rollback/re-enable, daemon restart, inherited and
unset options, both backend namespaces, partial failure and exact readback.

## Execution ledger

Canonical spec: https://github.com/CochranResearchGroup/codex-wake/issues/517
Ticket custody, edges, validation and review counters: docs/dev/evidence/plan0210/ledger.json.
Primary owns #518. All other tickets initially wait for its validated integration.
Maximum three substantive implementation lanes; integration is serialized.
Exactly one broad review and one bounded TDD findings pass. Checkpoint after each
validated ticket or material blocker; no merge/deployment authority in this task.
