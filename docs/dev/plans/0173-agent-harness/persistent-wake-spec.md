# Persistent wakes and Wake-owned recurring schedules

State: CLOSED
Owner: ecochran76
Design: confirmed by operator 2026-11-13
Implementation: authorized; ticket breakdown and test seams approved
Work item: #610 / children #611–#616
Integration branch: docs/persistent-wake-design
Base: e8c79a79da0b0482e2403e634394c70f5c66e333

## Current tracker reconciliation | P255

Issue #610 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Current State

All six implementation tickets #611–#616 are CLOSED. One two-axis review and one
bounded TDD remediation resolved all seven findings. PR #618 merged as a16b4de4;
0.22.0.dev20 is installed with compatible supervised scheduling heartbeats.
See persistent-wake-deployment.md for exact evidence and live-provider limits.
No production schedules were created.

## Problem Statement

A recurring check must have explicit behavior when its Codex UI, process, or
Byobu session closes. Durable one-shot intent and model re-arming do not provide
an independently durable recurring schedule or explicit session restoration.

## Solution

Expose explicit per-schedule session modes and Wake-owned durable recurrence.
The operator and scheduling agent agree cadence, end, missed-run, overlap and
delivery policies. Continue the exact conversation through the selected route,
recover after interruptions as declared, and expose truthful active/held outcomes.

## User Stories

1. As an operator, I want to select a mode explicitly for each schedule, so that closure behavior is deliberate.
2. As an operator, I want to use this-session-only wakes, so that future checks stop when the recipient exits.
3. As an operator, I want to detach Byobu without cancelling wakes, so that terminal disconnection does not end work.
4. As an operator, I want to restore my exact conversation visibly, so that checks can run after I close Codex.
5. As an operator, I want to restore the latest verified harness and directory, so that continuation matches my last working environment.
6. As an operator, I want to continue in the live TUI or background app server, so that checks do not require an open tab.
7. As an operator, I want to recover continuing schedules after reboot, so that session closure does not erase recurrence.
8. As an scheduling agent, I want to register recurrence owned by Wake, so that scheduling does not depend on model re-arming.
9. As an operator, I want to agree cadence and clock semantics explicitly, so that twice daily has the intended meaning.
10. As an operator, I want to choose an explicit end condition, so that schedules do not silently become perpetual.
11. As an operator, I want to choose downtime and maximum-lateness behavior, so that missed checks recover predictably.
12. As an operator, I want to choose overlap behavior and queue bounds, so that long checks do not create uncontrolled backlog.
13. As an operator, I want to keep one execution owner per conversation, so that foreground and background checks cannot race.
14. As an operator, I want to hold uncertain ownership, so that unverified absence does not launch duplicate work.
15. As an operator, I want to see restoration failures in attention, so that unavailable runtime settings are actionable.
16. As an operator, I want to inspect original occurrence identities and deadlines, so that misses and failures remain explainable.
17. As an operator, I want to revise future schedule behavior, so that edits preserve historical evidence.
18. As an operator, I want to cancel future and queued checks, so that cancellation does not silently interrupt running work.
19. As an operator, I want to count scheduled occurrences including skips, so that failures do not extend the schedule.
20. As an operator, I want to receive an explicit registration receipt, so that saved state is distinguishable from active monitoring.
21. As an operator, I want to reconnect to a background conversation or wait, so that opening a tab preserves its running check.
22. As an operator, I want to retain original task authority and resource limits, so that restoration cannot expand permission.
23. As an agent, I want to inspect and manage authorized schedules through supported interfaces, so that ordinary Codex sessions can use the capability.

## Implementation Decisions

- One schedule authority, Codex Wake, computes stable per-occurrence identities;
  retries never mint a second occurrence or reset original due/expiry anchors.
- Require an explicit mode on new schedule registrations: this session only,
  re-open session live, or background. Existing legacy wakes retain their frozen
  behavior; do not silently migrate or cancel them.
- Session-only cancellation requires verified recipient exit or pane/tab loss.
  Detach/disconnection and uncertain ownership do not prove session closure.
- Live reopening resumes the exact conversation with latest verified harness and
  cwd; background prefers its existing live TUI, otherwise the app server.
  Reuse qualified inventory, launch, permission and dispatch mechanisms.
- Persistent schedule state, revisions and occurrences survive monitor restart;
  continuing modes also recover after reboot through the existing supervised loop.
- Registration explicitly selects cadence, applicable timezone/DST behavior, end,
  downtime recovery/max lateness, overlap bounds and occurrence delivery window.
- Busy conversations wait without interrupt. All schedules targeting one
  conversation share execution exclusion. Uncertain delivery reconciles without
  replay or route fallback.
- Missing harness/cwd or ambiguous ownership holds the check with original
  deadline and operator attention. No repeated launch until resolution.
- Edits affect future checks through revisions; cancellation prevents future and
  queued delivery while preserving running checks and uncertain submission history.
- Count-based end counts planned occurrences, including skips/expiry. Successful
  result counts are not part of this contract.
- Registration and inspection separate retained/inactive, active, attention,
  submitted and completed outcomes. Monitor readiness must be observed.
- Runtime continuation preserves task authority and resource allowance. Unsupported
  routes remain explicit; source tests do not claim installed/live qualification.

## Testing Decisions

Proposed seams for confirmation: the existing operator CLI and native-self MCP
registration/control interfaces, plus the daemon's poll/dispatch boundary for
restart and delivery. Public terminal lifecycle and app-server adapters establish
route ownership; do not introduce another test framework or fixture project.

Use existing unittest harness and minimal temporary state. Test observable
registration, cancellation, occurrence identity, exact-recipient selection,
restart recovery, queue bounds and no duplicate submission. Known literal clock
examples establish cadence/DST expectations independently of implementation.
Prior art includes wake policy, native intent, route permission, daemon and tab
lifecycle tests. Use a small failing behavioral case before each substantive fix.
Keep red/green commands in the execution ledger. Run applicable local release
checks; no paid/hosted CI. No private sessions or provider effects in default tests.

## Out of Scope

Fresh-conversation substitution, new provider support, codex-bots implementation,
success-count completion, unrelated policy/worktree cleanup, production schedule
creation, deployment, live terminal manipulation, and expanded runtime permissions.

## Further Notes

The accepted interview in the HF-20 draft records detailed semantics. This spec
supersedes its earlier open recurrence-ownership question, not unrelated backlog.
Final integration gets one Standards/Spec review against the recorded base and
one bounded TDD remediation pass; do not restart broad review loops. Ticket
closure requires integrated, locally validated acceptance evidence, distinct from
merge, deployment, and live-runtime acceptance.
