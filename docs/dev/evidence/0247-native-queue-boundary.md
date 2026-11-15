# P247 — Native queue cancellation and expiry boundary (#694)

Qualification passed with native expiry unqualified. Native enforcement remains
open in [#695](https://github.com/CochranResearchGroup/codex-wake/issues/695).
No product deployment, native upgrade or busy-policy promotion occurred.

The real installed Wake 0.22.0.dev37 prefix was
`~/.local/share/codex-wake/releases/0.22.0.dev37-df30d4f`, using native 0.169.0.
The working native executable SHA256 was
`b452ca20f838a8855a88a41050ee4a694033fff4ea3ecdad5633e6e0e8d13f2b`.
Source checkpoint `921abd0d`, review base `b2b0dd98`.

An owned native turn ran a bounded 120-second command. Kernel PID, start ticks,
argv and native inProgress history established busy execution. Three queue adds
returned distinct IDs and matching client UUIDs. The cancellation candidate was
deleted and read back absent before idle. The deadline candidate remained queued
after authenticated UTC lower bound crossed its host-only deadline, then was
deleted before release. Only the positive control remained at release; it
naturally dequeued and completed exactly once. Complete native history contained
setup, blocker and control inputs, with neither deleted input delivered.
Control turn `01a1e11e-9149-7ae2-b33b-1f51bc410318` completed with
`CW694_CONTROL_COMPLETED`. All seven write operations had observed responses;
there were no unknown outcomes or cleanup errors.

Fresh schema generated from the actual working executable exposes no expiry
field in queue add or queued submission. No deadline was communicated to native:
retention beyond a host-only deadline is a capability gap, not violation of a
native expiry promise. Host deletion cannot qualify autonomous expiry during
watcher outage. #695 requires persisted absolute deadlines and atomic native
dequeue enforcement, restart/clock semantics and actual outage qualification
before bounded Wake admission can be enabled.

The installed Wake delivery adapter still rejects busy_policy=queue before I/O
with not_sent / busy_policy_unsupported; forbidden I/O collaborators verified
this boundary. Separately, SessionInputs.policy=queue already supports explicit
unbounded operator input. This qualification neither disables that surface nor
claims external OAuth authorization or all public cancellation routes were tested.

Run01 failed before any queue add because accepted blocker history was not yet
visible. The runner now waits for that observation. A fresh recipient/run02
passed; the original failure remains retained. Standards and specification
review against the fixed base found this one P2 observation-timing defect,
corrected and verified by the real failing/passing runs. No product repair or
fixture framework was introduced.

Local checks passed: Ruff 0.14.2 `check --select F821,F822,F823 src scripts tests
.codex/hooks`; `python -m py_compile scripts/native_queue_acceptance.py`;
`python scripts/native_queue_acceptance.py --help`;
`python scripts/check_policy_wiring.py`; `git diff --check`.
Hosted CI was skipped under the cost policy. These focused local checks and
actual installed native execution do not represent a hosted multi-platform
matrix; no product package changed, so no reinstall was needed.

Private receipts and raw native history are retained outside Git under
`~/.local/state/codex-wake/nativequeue-0247/`, notably run01/receipt.json,
run02/receipt.json, native-schema-current.json and final-audit.json.
Both owned recipients were archived, private TUI/server generations ended and
sockets removed. Both scratch directories were copied with byte parity to the
private evidence directory and removed after gate-process termination checks.
Independent final audit confirmed original native/browser/test-daemon start
ticks, native executable hash and production config/permission hashes unchanged.
No default-pane census claim is made. Memory disposition: forbidden, because
this packet prohibits memory writes without an explicit request.
