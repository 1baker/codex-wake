# P259 | Durable cancellation under delivery contention

State: CLOSED (source acceptance; deployment separate)
Work item: https://github.com/CochranResearchGroup/codex-wake/issues/731
Owner: primary / ecochran76; source worker merge_core
Priority: P1
Branch: fix/durable-cancel-contention-port
Base: b42a8ec09d6360f2be44d06aee75225b3b9ee189
Target: origin/main; source integration only
WIP: one implementation lane

## Scope and acceptance

Port the accepted WAKE-CANCEL-CONTENTION source behavior from original57555440
onto current main. A public CLI cancellation across a real process-held delivery
lock must persist exact authorized intent and return pending/delivery_in_flight.
A later safe monitor poll reconciles it, including after process restart. Pending
acceptance is not interruption proof. Freeze bulk membership, bind original
wake/caller identity, preserve uncertain submissions and terminal successful
delivery, and avoid blocking unrelated wakes.

Use existing CLI/monitor/MCP/lifecycle test seams. Reproduce red on current main
before production edits, then narrow implementation and focused checks. Root
performs one fixed-base Standards/Spec review and adjudicates findings. Definition
of done: passing applicable local checks, exact source/main custody, issue731
closed at source acceptance, and normal task checkout retirement when safe.
Deployment, original history custody and #697/#454 remain separate.

## Custody and non-goals

Reuse the clean existing cancellation checkout; original branch and local archive
retain57555440. A fresh current-main port branch avoids publishing unknown old
historical blobs. Root owns documentation/tracker/merge; worker owns source/tests.
No new checkout or branch-history discard. Original dirty primary remains intact.
No provider calls, production cancellation/monitor/service changes, credential or
history copies, clock redesign, new test framework or paid CI. Source-only tests
are not installed working-host acceptance. Cleanup trigger: verified remote/main
custody and reviewed disposable checkout artifacts; preserve original local refs.

## Current state

Original test setup first failed before reaching contention because its legacy
record omitted explicit fixture creation time; that receipt is retained and is
not the product red. With a fixed historical fixture instant, the existing
cross-process public regression fails at the intended expectation: cancellation
exit5 instead of accepted0. Exact private logs: cancel731/red.log and
red-contention.log under the P257 user-state evidence directory. Implementation
and final focused validation remain in progress.

## Source qualification

Frozen source1612929762df242f5b4861fd7d26d8290b18c7cd passes38 tests each on
Python3.11 and3.12, no exclusions/skips: test_wake_control, test_wake_control_mcp
and test_bounded_native_delivery. First contention red5!=0 is retained; initial
setup error is separate. First38-case run caught a real pending-guard regression
blocking native terminal reconciliation and an old fixture missing explicit now.
Both corrected; final identical selection is green. Ruff0.14.2 undefined names
and whitespace checks pass. No full-suite or working deployment claim.

Modern exact bounded native cancellation still uses the existing native cancel
owner; pending requests permit uncertain-native reconciliation without permitting
a fresh submission. App-server uncertainty remains held. Private version1 atomic
request files live alongside emergency control, not in the wake-record schema.
Older monitors do not consume these requests; activation requires upgrading the
monitor or repeating exact cancellation with the upgraded CLI. Pending acceptance
is not cancellation proof, and successful delivery is never rolled back.

Private full receipts remain under cancel731 in the P257 user-state evidence
directory. Public compact acceptance follows review adjudication.

## Primary review disposition

One fixed-base Standards/Spec review covered b42a8ec0...16129297. Standards:
zero accepted findings. Spec: zero confirmed implementation defects. Existing
positive bounded-native cancellation/lost-reply tests and bulk terminal-history
preservation are included in the38-case selection. One nonblocking coverage
observation remains: no dedicated successful-delivery-between-queue-and-poll race
test; no exhaustive race qualification is claimed. Primary accepted this bounded
source outcome without another review loop or speculative test infrastructure.
Exact main integration/checkout retirement follows the reviewed PR.
