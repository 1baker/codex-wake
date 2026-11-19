# 0247 — Direct native busy queue cancellation and expiry boundary (#694)

State: CLOSED

State COMPLETE. Owner root/ecochran76; WIP1. Branch test/native-queue-694.
Base b2b0dd98. One owned checkout protects dirty primary; retire after exact remote
custody. Installed Wakedev37/native0.169 unchanged. Working daemon2082 retained.

Qualify exact direct native queue add/list/delete while an owned native turn runs
a bounded120s command, then natural positive-control dequeue/completion after
release. Canceled entries must never become native user input. A separate entry
has an explicit host-observed10s deadline; because the freshly generated native
schema has no deadline field, observe its continued queue retention after that
time and delete it before idle. This is a native expiry capability boundary,
not a promise that a host deletion enforces expiry during watcher outage.

Native queue deadline remains not_qualified unless native dequeue-time enforcement
is demonstrated. No direct busy policy promotion, schema-unknown-field probing,
working native patch/restart/upgrade, production policy/config or operator-pane
mutation. Publish a concrete native-enforcement follow-up if absent. Only fresh
saved recipient/private TUI, exact queued/client IDs and host-qualified UTC.
No mock replies/status/clock or new fixture framework. Persist each operation
intent before I/O; reconcile uncertainty rather than resend. Cleanup removes
only known owned queue entries before gate release, settles/interrupts only own
exact turn if needed, removes private TUI and archives recipient. Preserve all
original failure evidence and unknown outcomes.

Definition of done: actual native cancellation/control proof and honest expiry
boundary, retained Wake pre-I/O refusal checked, relevant focused checks/review,
canonical evidence/ROADMAP/RUNBOOK merged, qualification issue closed and native
follow-up linked where required, owned resources/checkout cleaned after exact
remote custody. No paid CI. Product repairs require red/green and exact package
qualification underUID1017 before working installation; native upgrade is outside
this packet. Memory writes forbidden without explicit ask.

Result: cancellation/control passed; expiry unqualified, implementation #695 open.
Evidence: docs/dev/evidence/0247-native-queue-boundary.md. No runtime change.
