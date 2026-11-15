# 0242 — Bounded native history reconciliation (#674)

State COMPLETE. Owner ecochran76/root. Branch fix/native-history-pages-674.
Base main eb14ec93 (PR676 merged). Preserve dirty primary and unrelated checkouts.

Outcome: reconcile exact historical native submissions through supported paged
history under one total observation deadline, without writing native input,
replaying uncertain effects, changing authority, or inventing terminal metadata.
Existing public CodexRuntimeAdapter.reconcile/native_evidence are the test seams.
Minimal synthetic native responses at their protocol boundary only; no fixture
framework. Exact input/client/message/turn identity, duplicate rejection, complete
pagination and honest summary coverage are acceptance invariants. Unsupported
paging may use legacy reads only on explicit capability refusal, never malformed
or incomplete pages. Keep original record/journal custody.

Stages: reproduce whole-history failure with valid pages; qualify safe native
schema semantics; red/green repair; focused local checks and independent review;
exact package qualification under UID1017, PR merge and approved installation;
read-only actual native history reconciliation with zero input calls. Record
commands/source/artifact identity and preserve failures. Hosted paid CI excluded.
No native daemon restart/upgrade, no operator-session interruption, no provider
turn or replay of the original incident. Cleanup after remote exact custody.

Follow-on approved packet: persistent wakes across complete owned Byobu container
loss and owned monitor restart, then repeated cadence/missed/overlap behavior.
Track separately; no host reboot or disruption of unrelated services is implied.
Original native daemon and pending work remain preserved. Existing whole-container
recreation capability must be checked before choosing bounded scenarios.

Definition of done: #674 observable criteria met, qualified deployed read path,
closed tracker/evidence, owned checkout/resources cleaned after follow-on evidence publication; follow-on acceptance
gets its own attributable outcomes. Memory writes forbidden absent explicit ask.
