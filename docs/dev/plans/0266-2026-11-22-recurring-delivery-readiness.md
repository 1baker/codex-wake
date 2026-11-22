# Plan 0266 | Recurring wake delivery readiness

State: OPEN
Owner: primary / ecochran76
Work item: #755
Branch: fix/issue-755-wake-delivery
Target: origin/main

## Current State

Installed supervisor source is eecf5554. Read-only native replies matched both
pending enabled schedule recipients and reported idle. The supervisor has no
bounded native policy configured. The current hold is
`bounded_native_backend_not_qualified`. The historical busy observation is
not evidence of present activity.

## Scope

Keep monitor arming visible. Surface occurrence delivery holds alongside
arming. Treat an explicitly unqualified backend as a pre-submission hold.
Defer recipient rechecks for 30 seconds using trusted UTC when available.
Retain original occurrence deadlines and uncertain submission reconciliation.
No working policy activation, replay, restart, or existing tab changes.

## Acceptance

Verify the scheduler can observe an unqualified backend without creating an
intent or incrementing attempts, retains the next check across polls, and
shows the held occurrence through public schedule status. Existing native
dispatch, permission, uncertainty and expiry checks must pass.

## Completion

The source correction is one bounded implementation slice. #755 remains
open for dedicated busy-to-idle and persistent-busy runtime evidence. The
working bounded backend configuration remains a separate delivery gap.

Local Python 3.12 validation passed 64 tests across wake mode, native
delivery, recurring schedules, permissions, and native intent recovery.
The focused regression initially observed an attempt for the known hold.
The first wider run exposed expiry precedence regressions. The corrected
dispatch preserves the original time and expiry decisions before
checking backend qualification. Pinned Ruff and diff checks passed.

## Busy status provenance

Wake opens a fresh app-server connection and uses the exact recipient's
`thread/read` status. Native 0.171 reports active for running work, waiting
for approval, or waiting for input. Wake preserves the native state and
allowlisted wait flags in the held occurrence. With qualified UTC, it also
records an upper time bound after the observation. A previous active
observation does not establish that the recipient is active now.

The target regression failed when the approval flag was discarded. The
native delivery, wake mode, and recurring schedule selection passed all 41
tests after preserving it through the public receipt path.
