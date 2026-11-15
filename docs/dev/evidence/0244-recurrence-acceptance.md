# Installed recurrence acceptance — #685

Status: ACCEPTED after independent cleanup reconciliation. Product is the existing
qualified dev37 from PR683/f9c953e4; this slice changes no package code, version,
shared service or native daemon. It adds one opt-in acceptance script and evidence.

Installed prefix: `~/.local/share/codex-wake/releases/0.22.0.dev37-df30d4f`.
Wheel SHA256: df30d4f8439dafd41f526072b4347eedf76f160395972da029c99833ecdbd27b.
The script verifies its interpreter/package prefix and uses installed public
ScheduleStore/poll_schedules APIs, the supported monitor CLI and actual native
protocol. Explicit host-operator principal and isolated policy scopes are not an
external OAuth permission test. No source shadowing, fake time, fake native reply,
manually edited wake record, or new fixture framework is used.

## Actual results

One new disposable saved recipient with a uniquely matched private TUI received
one setup input. A finite background schedule with interval30s, count3, latest
missed policy, skip overlap and180s delivery/lateness bounds then produced three
distinct occurrence IDs. Each retained its exact original due/expiry and matched
one native input by wake and submission IDs, one completed turn and exactly
CW685_CADENCE_COMPLETED. Attempts1 per wake. The schedule reached exhausted at
next_index3 before explicit cancellation. Queue acceptance is distinct from the
independent full native history completion proof; no acknowledgment was invented.

Six isolated classification roots then used count4, interval4s, finite180s bounds
and the same explicitly selected background mode. These roots had no dispatching
monitor. Missed cases were registered before due, left unpolled across all four
real due slots, then activated with qualified network UTC. This establishes
initial activation after real unmonitored downtime, not a second reboot or
long-running service-restart test. Overlap cases polled continuously in one
actual process generation, retained a real first pending wake, and classified
subsequent occurrences without dispatch.

| Policy case | States before cancellation, indexes0–3 |
| --- | --- |
| Missed skip | skipped, skipped, skipped, skipped |
| Missed latest | coalesced, coalesced, coalesced, pending |
| Missed catch_up limit2 | skipped, skipped, pending, queued |
| Overlap skip | pending, skipped, skipped, skipped |
| Overlap latest | pending, coalesced, coalesced, queued |
| Overlap queue limit2 | pending, skipped, queued, queued |

Every case preserved original occurrence IDs, due times and absolute expiries.
Only the allowed pending wakes were emitted; each overlap root had exactly one
wake record. Native history retained exactly four user inputs total (setup plus
three cadence inputs): classification added zero. All seven schedule cancellations
and retained occurrence anchors were re-read in fresh installed-package processes.

## Failure preservation and cleanup reconciliation

The original run01 receipt remains state=failed with all seven cases passed and
one cleanup error: monitor stop unconfirmed. The cadence monitor had already
stopped successfully before classification. A redundant final stop of its now
unloaded transient unit returned nonzero, causing the false cleanup-failure label.
No behavioral assertion failed and no native input was retried.

A separate read-only reconciliation proves the original monitorPID198926 /
generation10157774 ended, its unit inactive/MainPID0, the private server/TUI
original generations ended and socket absent. All seven schedules are canceled,
isolated policies are defaultdeny revision2, and there are no pending/firing
wake records. Three accepted submitted delivery records remain retained without
synthetic acknowledgments. The owned recipient was archived. An initial policy
readback used the wrong JSON envelope; corrected policy.global readback performed
no mutation. Both diagnostic facts are retained in the private reconciliation.

The final runner tracks successful prior monitor stop, skips the redundant stop,
and captures exceptional stop outcomes while continuing other cleanup and writing
the receipt. This source correction does not relabel the original receipt or
replay the acceptance. Its exception path is reviewed, not fault-injected; no
proxy fixture test or repeat of successful provider effects was introduced.

Final independent census: native2082, browser379435 and unrelatedUID1017 daemon3287769
retain their original generations; all43 operator panes present at this packet's
baseline match exactly. Production connector configuration and common permission
policy hashes are unchanged. No shared controller restart or ingress change.
Private target/history/commands/run01 receipt and separate reconciliation remain
outsideGit under user state cadence-0244.

## Review and local validation

Fixed point8b429c807c17af610da95e14df85137552530d89; frozen acceptance source
20e9b3af36eebd763f446b352b8f4c8e8f0f3e09. Diff command:
`git diff 8b429c807c17af610da95e14df85137552530d89...20e9b3af36eebd763f446b352b8f4c8e8f0f3e09`.

Standards and Spec reviewed separately in the primary context. Standards sources:
AGENTS.md and policies0002–0006,0014–0017; no CONTRIBUTING/CODING_STANDARDS file.
Fowler smell baseline considered; no speculative abstraction or new framework
recommended for a single opt-in runner. One accepted P2 at monitor cleanup:
redundant stop can misreport failure, and an uncaught stop exception can prevent
remaining cleanup/receipt. Both addressed by stop custody plus exception capture.
Spec source: issue685 and plan0244. No accepted missing requirement or scope creep;
classification coverage is explicitly bounded to pending overlap and initial
unmonitored downtime. No native busy-turn queue, calendar/DST, host reboot, soak,
or public OAuth claim. Standards accepted1/P2 resolved; Spec accepted0.

Focused commands: pinned Ruff0.14.2 `check --select F821,F822,F823 src scripts tests
.codex/hooks`, `python -m py_compile scripts/recurrence_acceptance.py`, installed
Python `scripts/recurrence_acceptance.py --help`, `python scripts/check_policy_wiring.py`,
and `git diff --check`: PASS. Initial syntax error and missing bare ruff/uvx commands
were corrected before live execution; the checker ran from a task-owned venv.
No broad core-suite rerun or UID package installation: package files are unchanged.
Hosted paid CI excluded; this host's syntax/lint checks do not cover a hosted
Python3.11/3.12 matrix. Tier: focused plus opt-in live installed acceptance.

Memory disposition: forbidden — no explicit memory write request.
