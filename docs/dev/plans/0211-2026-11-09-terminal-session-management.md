# Terminal session management and criteria-based tab relocation

State: CLOSED
Owner: primary / ecochran76
Work item: #526; implementation #527–#534; draft PR #535
Branch: feat/terminal-sessions-526
Domain authority: GLOSSARY.md

## Current tracker reconciliation | P255

Issue #526 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Current State

All seventeen decisions are implemented. Tickets #527–#534 are integrated,
validated and tracker-closed; parent #526 remains the open discussion authority.
Exactly one Standards/Spec review accepted four findings; one bounded TDD
remediation pass resolved all four. Post-review focused checks pass 82 tests each
on Python 3.11/3.12. The exact rebuilt package passed installed Linux and native
PowerShell workflows and independently qualified native psmux lifecycle/cwd.
See evidence/plan0211/review/final-report.md and ledger.json for exact identities,
commands, earlier diagnostic failures, capability limits and cleanup receipts.
Initial implementation performed no production mutation or provider prompts.
Subsequent explicit operator authorization merged PR535 as bae92f9 and deployed
the exact qualified wheel. See evidence/plan0211/deployment.json.

Graphiti discovery: skip; supplied current conversation, deployed source and its
canonical receipts provide the decisions needed for this bounded interview.
Memory disposition: forbidden; no explicit memory-write request.

## Scope and non-goals

Specify session create/list/show/update/delete, human-readable discovery and
selection, moving tabs by explicit selection or criteria, and saved categories.
Keep CLI/API/MCP behavior equivalent; qualify Byobu/tmux and psmux independently.
Implementation and disposable fixture effects are authorized. Do not change
production layouts, launch real bots, stop unrelated sessions, merge or deploy.
Stock Codex remains independent.

## Confirmed requirements

- Session CRUD is required, alongside existing tab management.
- Development and bot tabs can occupy distinct named terminal sessions.
- Tab relocation supports arbitrary categories or selection criteria.
- Users should not need opaque workspace IDs for ordinary use.
- A logical group/view is distinct from moving tabs between terminal sessions.

## Verified starting capabilities

Read-only source check: discovery already retains native session names as labels;
local CLI accepts unique labels for source and destination. Current listing still
obscures that affordance. TabLifecycle provides tab CRUD and same-server tmux moves,
not terminal session CRUD. Moving the final tab is refused; closing the last tab
removes the native session. No durable empty-session abstraction exists. Native
psmux cross-session moves are explicitly unsupported because sessions have separate
servers and repeating window/pane IDs; no conversation restart may be substituted
and described as moving a running tab. Evidence: tab_workspace_discovery.py,
tab_commands.py, tab_lifecycle.py and tab_psmux_bridge.py in deployed source cb7cf62.

## Settled decisions — round 1

Operator accepted all five recommendations:

1. Names are the ordinary interface; omitted selection infers the current terminal
   session, ambiguity offers an interactive picker, and scripts can select explicitly.
2. A saved session definition survives having no tabs. Recreate its native container
   when needed; distinguish running and empty states.
3. Plain delete removes an empty session. Populated deletion requires an explicit
   destination for its tabs or an explicit instruction to terminate them.
4. Moves preserve panes, processes and conversations, including running turns, and
   do not switch focus by default. Unsupported continuity is reported, not simulated
   by restarting or copying conversations.
5. Saved categories support preview/apply relocation and optional continuous routing.
   Enable continuous routing explicitly per rule.

Architectural consequence: saved session identity/lifecycle is distinct from native
container liveness; see docs/adr/0003-saved-terminal-session-lifecycle.md.

## Settled decisions — round 2

Operator accepted all six recommendations:

6. Session names are unique within a terminal server; qualify host/backend when
   ambiguous. Rename preserves identity and references. Reusing a retired name
   never redirects old rules to the replacement session.
7. Editable metadata includes description, labels, default directory, launch
   profile/command and formatting preferences. Launch defaults affect new tabs;
   updates do not restart existing tabs or change their accounts.
8. Select explicit tabs, saved groups and custom labels; combine criteria with
   AND/OR/NOT, exact matches and patterns. Unknown traits match only explicit
   unknown criteria.
9. Preview freezes a bulk selection. Apply rechecks identities, preserves completed
   moves and reports moved/failed/uncertain outcomes. Reconcile uncertainty before
   retry; undo completed moves only where original destinations remain compatible.
10. First matching routing rule by explicit priority wins. Conflicting equal-priority
    rules hold the tab and explain the conflict.
11. Manual movement holds automatic routing for the tab until explicitly resumed.
    Pins also prevent automatic relocation.

## Settled decisions — round 3

Operator accepted all six recommendations:

12. codex-bots creates or reuses its dedicated `bots` session and places its own
    bot tabs there. It leaves `default` alone. Repeated launch does not duplicate
    or restart existing bots merely because the session exists.
13. Discover existing native sessions without requiring registration. Show them
    immediately; save management settings when first edited. Preserve running
    tabs and existing native settings unless explicitly changed.
14. Enabling continuous routing previews existing matches and moves them only
    when explicitly included. Require configurable trait stability before later
    state-driven moves. Preserve manual holds across restart and reconcile
    unfinished moves before creating new effects.
15. Delete disables dependent destination rules with a visible explanation.
    Complete the requested drain/termination before deleting; partial success
    retains the session. Keep history and never let old rules silently recreate
    a deleted session.
16. Ordinary CLI lists use readable tables showing session name, backend,
    running/empty state, tab count and activity/health summaries. Interactive
    ambiguity can open a picker. Scripts/API/MCP get structured candidates and
    errors; noninteractive calls never wait for input.
17. Undo preserves subsequent manual placement. Restore only tabs still in the
    placement produced by the original operation, report skipped conflicts,
    and put successfully undone tabs on routing hold.

## Design tree and current frontier

Root: terminal session CRUD and tab relocation.
Settled round1: names/inference, durable empty sessions, explicit populated deletion,
continuity-preserving moves, on-demand and opt-in continuous routing.
Settled round2: scoped names/stable rename, defaults, composable selection, partial
bulk outcomes/conditional undo, rule priority/conflicts, manual routing holds/pins.
Settled round3: launcher reuse, automatic discovery/adoption, routing backfill and
stability, delete dependencies/partial drain, human/machine interfaces, undo conflicts.
Frontier: empty. Specification and tickets are published; implementation and
review remediation are complete. Merge and deployment remain separate.

Backend capability facts remain implementation qualification, not operator
questions or permission gates. First delivery uses the WSL authority and existing
Byobu/tmux capabilities. psmux session operations require independent qualification;
current cross-server whole-tab movement stays explicitly unsupported, with no
replacement process/conversation presented as a successful move. Windows-native
hosting remains a separate roadmap milestone.

## Consolidated intended workflow

- List terminal sessions by recognizable name; discover `default` immediately.
- Create/show/edit/rename/delete named sessions; keep empty saved definitions.
- codex-bots creates/reuses `codex-bots` without disturbing development tabs.
- Preview explicit or criteria-selected tabs, then apply process-preserving moves.
- Save categories/rules and opt into continuous routing where desired.
- Explain conflicts, unknown traits, held/pinned tabs, unsupported backend actions
  and per-tab partial/uncertain outcomes. Reconcile before retry; undo conditionally.
- All controller surfaces share operation semantics. Existing workspace IDs remain
  internal compatibility selectors; ordinary use relies on names/current context.

## Acceptance criteria and definition of done

- All eight implementation tickets integrated and validated at the public controller
  seams and their own native boundaries, with tracker closure readback.
- Exact installed immutable package qualified through WSL CLI, native stdio MCP,
  authenticated HTTP/API/OAuth MCP and native PowerShell. Byobu/tmux movement and
  psmux CRUD qualify independently; cross-server movement remains unsupported.
- Preserve running processes, pane/conversation identity, manual holds, configured
  labels, original formatter baselines and unknown outcomes. Prove recovery without
  blind replay; keep failed receipts and explicit deferred risks.
- Exactly one broad Standards/Spec review against frozen base
  f0798e1ede3104caf591ba0b453fbf553bed569e after all tickets close, then one bounded
  TDD remediation pass and focused verification. No repeated broad review loop.
- Update glossary, operator docs/help/completion, ROADMAP/RUNBOOK and ledger;
  publish a coherent validated integration branch. Merge/deploy remain separate.

## Execution bounds

Primary owns shared schemas/authority/integration and took #527. Delegate other
ready tickets one per agent in isolated worktrees. Maximum three substantive
implementation lanes, serialized shared-file integration, one native Windows
qualification job at a time. Readiness requires every blocker validated on the
integration branch; tracker closure or worker claims alone do not unlock tickets.
Tests are selected by affected public surface, run on local Python3.11/3.12;
no paid hosted CI. Final package acceptance is ticket #534, not a source-only claim.
