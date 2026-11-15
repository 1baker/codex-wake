# Native busy-turn scheduler overlap — #688

Functional acceptance: PASS. Owned cleanup and task mutation boundaries: PASS.
Global operator-pane snapshot: changed, attribution unestablished; see below.
Product remains installed dev37, unchanged; no package or shared-service restart.

## Actual installed behavior

Three independent finite background schedules used interval20s/count4, latest
missed policy/maxlateness240s and deliverywindow240s. One actual native command
waited on a release file under the disposable recipient's owned cwd, with a120s
hard monotonic timeout. This was real native tool execution, not a fake busy
flag, simulated reply, advanced clock or manually edited journal. During later
slots, the runner observed the same native inProgress turn, exactly one added
user input, and the actual scoped command PID/arguments/start generation.
Network-qualified UTC observations accompany indexes1,2,3. The host released
only the owned gate after all four occurrences were classified.

| Policy | States while first turn busy | Final states | Completed native inputs |
| --- | --- | --- | --- |
| skip | submitted, skipped, skipped, skipped | completed, skipped, skipped, skipped | 1 |
| latest | submitted, coalesced, coalesced, queued | completed, coalesced, coalesced, completed | 2 |
| queue limit2 | submitted, skipped, queued, queued | completed, skipped, completed, completed | 3 |

Every completed occurrence matched one exact wake/submission/user/turn identity,
one attempt, native completed status and the expected final-answer marker.
Completed native commandExecution records identify the scoped wait program and
case nonce. Commentary is retained and is not confused with the final answer.
Original occurrence IDs, due times, absolute expiries and finite counts remain
unchanged. No later input entered while the first native turn was busy. Retained
work ran only after release. This qualifies scheduler-level deferral, not direct
admission to the native busy queue; that capability remains not_qualified.

Skip is accepted from run02 plus a read-only reconciliation of its original
completed turn. Latest and queue passed together in run03. Original failed
receipts are not rewritten as full-run passes, and accepted skip was not repeated.

## Diagnostic failures retained

An initial empty thread/start request timed out at10s before returning an ID.
No prompt or schedule was sent. Exact-cwd saved metadata and all77 loaded-thread
metadata reads found no matching thread, with0read errors. Its empty allocation
outcome remains unknown rather than being invented or replayed. A separately
identified fresh setup used a30s bound and returned in7.423s; only known fresh
recipients received inputs. No native daemon restart was attempted.

Run01 exposed a runner assumption: in-progress full history does not yet contain
the persisted commandExecution item. The actual command ran; cleanup released it
and the original turn completed. The runner now checks live PID/argv/generation
plus native inProgress and correlates the persisted tool record after completion.

Run02 established all skip behavior, then its runner incorrectly required all
agentMessage items to equal one reply. Native emitted valid commentary plus an
exact phase=final_answer marker. Read-only original-turn reconciliation verified
one input, completed command, all three busy observations and the skip outcomes.
The runner now checks the final-answer phase, and a policy selector lets the
remaining independent cases run without repeating accepted effects.

The final predicate waits for classified states rather than assuming the first
identity-persistence write is already classified. No original intent, uncertain
submission or terminal journal was cleared. There is no fixture project, new
mock server, product-code change or deployment in this packet.

## Cleanup and preservation boundaries

All four owned monitor units are inactive/MainPID0. All known private servers,
TUI generations and seven gate-command generations ended; their sockets are
absent. Schedules are canceled, isolated policies are defaultdeny revision2,
known disposable recipients archived, and there are no pending/firing wake
records. Accepted submitted records and diagnostic journals remain retained
without synthetic acknowledgments. Command metadata/source and native receipts
are retained under user-state busy-0245 outsideGit.

Native2082, browser379435 and unrelated test-native3287769 retain original
process generations. Production connector configuration and common permission
policy hashes match baseline. Every recorded terminal mutation addresses a
manifest-declared private socket. Native command traces contain only the owned
wait program; no task command closes a default-server pane.

The global default terminal snapshot nevertheless changed from43 to41 panes:
windows@62/pane%62/PID1605825 and@108/pane%108/PID1995471 disappeared. Remaining
panes match; no new default panes appeared. Cached metadata places these in a
different project. That is context, not actor attribution. One disappearance was
observed after owned acceptance processes had stopped. A bounded journal lookup
found no attribution. The operator was asked whether these closures were theirs
or another task's; no answer is assumed. Full global-pane preservation is NOT
claimed. This observation is kept separate from the verified functional results,
owned cleanup and private-only task mutation boundary. No unrelated pane is
recreated, killed or modified to force the snapshot to match.

## Review and local checks

Fixed point f5fedda9e9a92c18c8cf711d94123f948ee4aa19. Frozen final live source
54734d56 (run03), earlier acceptance source0caf75f8 (run02). Diff review command:
`git diff f5fedda9e9a92c18c8cf711d94123f948ee4aa19...54734d56`.

Standards and Spec reviewed separately in primary context, using AGENTS.md and
policies0002–0006,0014–0018, issue688 and plan0245. No CONTRIBUTING or
CODING_STANDARDS file. Standards: no consequential accepted violation. Shared
runner-shape duplication is a maintenance judgement; a new framework/refactor is
not required for this bounded test. Spec: two accepted P2 runner evidence errors
(live versus persisted tool evidence; commentary versus final-answer evidence)
resolved through actual failing CLI runs, minimal corrections and read-only/
remaining-case verification. No new proxy fixtures. The pane-attribution question
is needs_evidence, not an asserted product defect or a blanket preservation pass.
Summary: Standards accepted0; Spec accepted2/P2 resolved; attribution unestablished.

Focused checks: pinned Ruff0.14.2 `check --select F821,F822,F823 src scripts tests
.codex/hooks`, `python -m py_compile scripts/native_busy_overlap_acceptance.py`,
installed Python `scripts/native_busy_overlap_acceptance.py --help`,
`python scripts/check_policy_wiring.py`, and `git diff --check`: PASS.
No broad core-suite rerun or UID package installation: package code is unchanged.
Hosted paid CI excluded. Host Python3.12 checks are narrower than a hosted
Python3.11/3.12 matrix. Tier: focused plus opt-in actual installed acceptance.
No calendar/DST, reboot, soak or external OAuth acceptance claim.

Memory disposition: forbidden — no explicit memory write request.

## Subsequent operator attribution

The operator subsequently stated “i close them”, confirming that they closed the
two pre-existing agent-browser panes discussed above. Recorded on [issue688](https://github.com/CochranResearchGroup/codex-wake/issues/688#issuecomment-6901092538).
The unattributed-closure limitation is resolved by this operator statement; the
original census/receipts remain unchanged. This is operator-confirmed attribution,
not a reconstructed technical audit trail.
