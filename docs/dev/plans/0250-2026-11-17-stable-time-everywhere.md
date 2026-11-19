# 0250 | StableTime integration and timing requirements

State: OPEN
Owner: root
Parent: #695 remaining Python gate; operator correction applies across Codex Wake.
Integration: feat/native-expiry-695; base098f409a8de5d7010984189127bf4f10e12fb1d3.
WIP3. Reuse owned checkout; preserve workingdaemon, credentials and unrelatedlanes.

## Contract (replacement policy; current authority)

Use the existing StableTime service and supported client/API for actions that
need reasonably correct elapsed time, deadlines, freshness or UTC. Interpret
observations at their documented service measurement instant with their supplied
uncertainty. Never extrapolate trusted time with a WSL clock or silently use
unreliable guest time for those actions. Do not require an application-specific
host-counter bridge or separate local counter process to consume service data.

Ordinary OS waits, caller polling limits and incidental log timestamps do not
need additional StableTime calls or qualification gates. Their timeouts are
protective/advisory, not proof that an authorization or original wake expiry
has elapsed. Preserve actual permission, lease, freshness and expiry owners.
Pause only the action that needs unavailable reliable time. Distinguish service
outage, transport/configuration failure and auxiliary client/helper failure.

The former all-clock-call migration and zero-raw-call acceptance criterion are
superseded. Existing inventory counts are historical discovery aids, not remaining
work counts. Existing source validation receipts remain historical evidence;
they do not establish compliance with this replacement policy. Existing durable
unknown outcomes and deadlines must not be reset during correction.

## Current State

The approved timing-policy packet and #695 acceptance are complete on the
integration branch. Python clients and Native final admission consume supported
StableTime service-measurement evidence without a private counter bridge.
Ordinary transport waits retain protective OS budgets; actual permission,
lease, freshness and expiry owners retain qualified evidence and immutable
anchors. The shared refresh watcher publishes structured clock observations.

Exact Native e7286ffdc3 complete-package/UID1017 behavior passes, and both Python
collections cover2,806 unique cases:2,805 pass plus one opt-in systemd skip.
Python3.12's three Windows failures pass unchanged focused reruns; their original
failures remain retained. Rust libtest compilation is the documented deferred
nonblocking validation-cost gap, not a unit-test pass. Current evidence is
[service-instant-closeout.json](../evidence/issue0695/service-instant-closeout.json).

This plan remains OPEN for independent GR01-SAMPLE/GR01-LIVE-WINDOW. Their
expired/uncertain live request is not replayed or renewed by #695 closure.
No working-host deployment or additional provider effects occurred.

Below are historical execution sections under the superseded universal rule;
0250-execution.json records corrective ticket states and current acceptance.

## Bounded execution graph

ST01 shared strict measurement interface (root, running, no blockers): reuse
native_clock/host_counter rather than duplicate credentials orservice protocol.
Prove WSLclock discontinuity cannot affect measurement and unavailable authority
refuses without rawclock fallback. Immutable hostcounterepoch continuity owns
elapsed evidence; qualified UTC bounds own calendar/expiry decisions.

ST02 runtime bypass audit (worker, running, no blockers): classify all existing
rawtime measurement calls by owner/purpose and migrationdependency; identify
bootstrap cycles and persisted clockdomains before adaptation. Read-only return;
not a claim of completed migration.

ST03 claimant/background adoption (pending, blocked ST01+ST02): replace real
freshness/observation/supervisor measurements and prove original publicmutation
case with strict sharedclock; legacy/future/stale/unqualified evidence refused.

ST04 remaining runtime/script adoption (pending, blocked ST01+ST02): migrate all
measurement paths without broad search-replace changing time domains. Static
inventory must have no undocumented production WSLmeasurement bypasses. Focused
checks by causally affected owner; no duplicated comprehensive suite/review.

GR01 Grok readiness diagnosis (worker, running, no blockers): reconcile current
installed profile, stale catalog and qualifiedtime logic with deployedP233
acceptance. Read-only; no login/refresh/inference, quota reset, servicechanges,
credentialcopies or new provider spend without existing exact effect authority.
Preparation of a concrete bounded repair/requalification may proceed locally.

## Acceptance and limits

Deliver one validated integration branch. Focused publicseam red/green first;
reuse native9af/package5 and previous review, do not rebuild/reviewagain.
GlobalAGENTS already updated; source migration remains incomplete until ST04.
No workinghost activation or premature closure695/628. Parent validation still
requires an explicitly authorized comprehensive pass after source convergence.
Memorywrite forbidden absent explicitrequest; retain canonical evidence instead.

## Bootstrap transport boundary

`host_counter` cannot request the shared measurement clock while acquiring its
QPC sample: that would recurse through `native_clock.snapshot`. Its Linux LP64
timerfd is an explicit, relative kernel blocking-I/O fuse, never a UTC sample,
elapsed measurement, freshness result or authorization deadline. No guest clock
value is read. One retained client fuse covers connect, send, retries and the
entire response frame; progress never rearms it. Request and producer frame
fuses likewise cover the whole frame, and a malformed or late producer is
retired without replay. Unsupported timerfd acquisition holds before bridge
startup; there is no clock or platform fallback. Fixed idle accept and owned
child cleanup waits remain blocking primitives. Actual counter qualification,
epoch/rate continuity and UTC handoff age remain with the existing authenticated
Stable Time and QPC validators. A kernel fuse firing proves only transport
refusal, never that an authority deadline elapsed.

## Current bounded continuation

ST04-COLLECTOR (owner collector_stable_deadlines, running; blockers validated
ST01/ST04-APP-TRANSPORT) owns local_session_events launch, RPC and stream deadlines.
Acceptance: original qualified deadline, refusal before new input on clock loss,
uncertain/no replay after possible input, exact protective ownership preserved.

GR01-SAMPLE (root, preparation running; blockers validated GR01/ST01) qualifies
the selected Grok build's existing thread/sample route before live use. It captures
one response on an ephemeral fork; model tool calls are not dispatched by Core.
This is a narrow candidate, not full coding or mixed-provider qualification.
The old packet adapter unconditionally refused and its schema inspection used
Native9af instead of the selected Grok sourcea5806e; that earlier categorical
capability inference is withdrawn. Preserve original receipts and append correction.
Require selected executable acceptance, eligible parent/turn pins, bounded startup
effects, qualified external deadline and consumed unknown attempts before spending
the approved fresh allowance. No new Native build or working-daemon adoption.

## Creation and wait batch closeout

The current batch in0250-execution.json closes ST04-CREATION,
ST04-CONTROLLER-WAITS, ST04-LOCAL-WAITS and ST04-LOCAL-ACTOR on the integration
branch. One review from5d291917 to frozenf0556ea0 accepted one Spec P1 boundary
finding; one bounded TDD pass adds final wait authorization before publication.
See docs/dev/evidence/issue0695/st04-current-batch-review.md. ST04-COLLECTOR was
validated in the preceding batch. GlobalST04 and #695 remain OPEN; this closeout
does not establish full Python, installed runtime, activation or live Grok proof.

## Daemon, event metadata and signal lease batch

ST04-DAEMON-UTC, ST04-RECORD-EVENTS and ST04-SIGNAL-LEASES are validated and
closed repo-local on the integration branch. Default legacy scheduling uses
qualified lower UTC; missing UTC holds legacy work with additive time_held
reporting while relative native counter intents continue. Signal expiry holds
new matching on uncertainty and preserves already reserved matches. Events and
legacy moves use qualified-or-unknown metadata; schema2 moves retain their
required timestamp and hold before publication rather than becoming unreadable.
Lease reclaim and continuation use lower/upper bounds without renewing ownership.
The journal schema and terminal-fence contract remain unchanged.

Combined92 focused checks pass on Python3.11/3.12; final27 causal checks pass on
both after integration guards. Earlier review/remediation are preserved without
a new broad review. See issue0695/st04-daemon-signal-validation.json under
docs/dev/evidence. GlobalST04/fullPython/runtime/activation remain open.
The stale Grok parent lookup is resolved by the retained takeover receipt; the
current live gate is the expired allowance and uncertain sample, not a missing
parent. No new live work is authorized by this source continuation.

## Acknowledgement wait and monitor batch

ST04-ACK-WAIT and ST04-MONITOR are validated/closed repo-local. A positive
acknowledgement wait uses one retained qualified counter deadline, acquired before
paste, and rechecks after receipt observation. Missing time before paste holds
without an attempt; loss after possible paste retains an unknown outcome and
prohibits replay while allowing later receipt reconciliation. Zero wait stays an
untimed inspection. Monitor metadata uses qualified lower UTC or null/not_observed;
freshness requires conservative qualified bounds. Integrated49 focused checks
PASS on Python3.11/3.12. See issue0695/st04-ack-monitor-validation.json.
Global ST04 and #695 remain open; legacy transport metadata/final-send admission
and signal-v2 terminal timestamps still need separate adoption. No broad review,
full suite, Native build, live provider effects or deployment occurred.

## Signal cancellation and input/output custody packet

ST04-SIGNAL-CANCEL preserves readable schema2 records and durable terminal fences
when stopping without UTC. ST04-INJECTOR-METADATA requires qualified default UTC
before legacy transport work and holds Native4 expiry uncertainty. ST04-HOST-STDIN
retains a qualified frame deadline through input acceptance. ST04-OUTPUT-FRAMES
retains a positive wait across generator suspension and preserves untimed
inspection/established terminal-page drainage. ST04-GROK-EVENT-WAIT retains its
original custody wait and refuses an unqualified final connection without replay.
No live Grok allowance is renewed. Actor acquisition remains its separate
pre-custody UTC gate; unvalidated targets are not mutated for diagnostics.

Fresh source inventory at ffa2ac25 found305 direct raw measurements in83
production files,29 callable bindings and16 legacy wrapper calls. This is a
static candidate inventory before the packet, not current reachability or proof
of a completed migration. Tabs/terminal contracts are the largest coupled debt;
OpenClaw remains parked. Prior broad review is preserved without repetition.
Final packet evidence owns exact checks, retained failures and closeout states.

## Supported service decision contract

Python admission and authorization reads use fresh StableTime observations at
`basis: service_measurement`. Bounds and counters describe that service instant,
not client receipt or provider send. The existing epoch/frequency/rate policy
supports elapsed comparisons between service observations without WSL clock
extrapolation. An observation earlier than a retained local sample holds; no
anchor is reset or silently converted. Existing persisted deadlines remain fixed.

The bounded caller audit found no separate unconditional receipt-current UTC
requirement in the reviewed Python owners. Native Plan0248 owns final transport
send admission against the original expiry. Its handoff must retain the original
service counter and bounds, so Native can account for elapsed handoff once.
Python must not preadvance the same bounds and cause a second advancement there.
Default Python clients therefore no longer need the auxiliary counter process.
The explicit pure handoff conversion remains for compatibility, without starting
that helper. A source change is not installed Native acceptance or deployment.

## Native qualification boundary

The frozen Native final-send implementation and its clock-producer wire still
include the legacy private counter-source contract. This packet removes Python
sampling helpers; it does not replace that Native producer/consumer protocol or
prove the advertised counter socket is live. Runtime/service-source replacement
and qualification stay in #695. The original expiry envelope, host qualification
refusal, and no-replay protections remain mandatory before any deployment.
Other transport-only wait gates outside the owned files remain owner-specific
reconciliation work, not a renewed all-clock-call migration.

## Approved #695 best-effort closeout packet | 2026-11-18

The operator accepts fresh service-instant evidence at final admission and the
observation-to-send suspension/delivery limitation. Plan0248's best-effort
revision is current timing authority; old final-send/current-upper claims are
superseded. Root owns Python wirev2 and plan/evidence; Native worker owns the
existing Rust clock consumer/tests; read-only reconciliation identifies exact
remaining acceptance gates. No private bridge, no WSL extrapolation, no expiry
renewal, and no uncertain replay. Legacy wirev1 is refused by the new consumer.

Only newly invalidated focused compile/package/runtime stages may be run;
previous broad review is retained. No working daemon replacement or renewed
Grok inference window. #695 closure requires the acceptance matrix, current
Python validation and causally affected Native qualification; passing source
checks alone does not close the issue.

## Native validation seam reconciliation | 2026-11-18

Exact Native e728 complete package and installed UID1017 API journeys are the
acceptance seam for the revised clock consumer. They prove real service-point
admission, preparation expiry/history exclusion, pending cancellation, unknown
hold, original identities/deadlines across restart, eligible controls, and
legacy/receipt-claim reader rejection without model input. Unchanged nonqueue
and updater/ownership paths retain their prior qualified evidence.

The three-test Rust libtest target never ran: two900s and one600s compilation
fuses ended in its existing dependency graph, without compiler diagnostics or
test assertions. Record it as an unexecuted, deferred validation-cost gap; never
as a pass. This changes the validation layer, not the accepted behavior. It does
not invalidate the compiled package or observed public API results. No further
same-target retry is authorized by this packet. Required Python3.11/3.12 complete
local validation remains open; this reconciliation does not waive that gate.

Compatibility: reader wirev2 requires the matching successor Native consumer.
Mixed old/new reader-consumer pairs hold bounded work; they never fall back to
unbounded submission. Existing admitted wirev1 records remain reconcilable.
Keep package/helper identities pinned together and qualify them before host
activation; no stored expiry or original submission identity is rewritten.
