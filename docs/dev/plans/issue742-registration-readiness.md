# Issue 742: truthful route readiness

Owner: ecochran76 / primary. State: SOURCE_VALIDATED. Priority: high.
Tracker: https://github.com/CochranResearchGroup/codex-wake/issues/742
Branch: fix/issue-742-registration-readiness. Base: cbd799b9.

This bounded follow-up covers registration readiness and recurring-schedule skill
routing. The separate issue-742-idle-tab-loss branch owns actual tab placement;
its two unmerged commits are not included or modified here.

Seams:
- Public native registration CLI: catches a healthy monitor falsely implying
  missing-tab restoration; does not prove a successful terminal launch.
- Public schedule register/show CLI: exposes restoration blockers independently
  of monitor health; does not establish future runtime availability.
- Existing scheduler polling regressions prove recurrence survives restart and
  route holds without worker self-rearming.

TDD: each new CLI regression failed with armed=True, then passed after its
minimal correction. The first run used system Python without websockets and was
an environment error, not a behavioral red; installed-package Python supplied
the existing dependencies. Command prefix: PYTHONPATH=src:tests, interpreter
from the installed 0.22.0.dev44 package. Exact selections:
- unittest test_recurring_schedules.RecurringSchedules.test_live_schedule_is_not_armed_without_missing_tab_restoration
- unittest test_wake_session_modes.WakeSessionModes.test_live_registration_exposes_missing_restoration_before_claiming_armed

Focused: 52 tests passed across test_wake_session_modes, test_wake_mode_runtime,
test_recurring_schedules, test_recurring_calendar, test_wake_live_restore.
No hosted CI, production events, daemon replacement or tab destruction.
Runtime application/qualification is distinct from source validation. Installed
older code remains until an exact merged release is qualified and deployed.

Adjacent validation: 35 delivery/policy/route-permission tests passed. An extra
selection named a nonexistent test_recurring_schedule_mcp module and produced
one discovery error; no behavioral failure or automatic retry was hidden.
Undefined-name Ruff checks, source compilation and git diff --check passed.

Live monitor migration uses the existing installed durable scheduler, not this
unreleased patch. Exactly one clock schedule is enabled; prior one-shot was
cancelled after armed readback. Detailed tenant identities/prompts stay private.
Live tab reconstruction remains unqualified and no daemon was replaced.

Public control/MCP checks: 26 passed. Skill validator first exposed an existing
1045-character description (limit1024); concise routing description now includes
recurring monitoring and validates. Total selected behavioral tests:113 passed.

PR782 review (base cbd799b9, standards and spec axes):
- Standards: one nonblocking readability finding accepted; replaced nested
  conditional expressions in schedule status with an explicit decision chain.
- Spec: no blocking findings for this bounded readiness/skill follow-up. Full
  issue742 closed-tab placement acceptance belongs to the separate lane and is
  not claimed. Registration inspection remains read-only and preserves peer
  uncertainty holds. No daemon grants or route fallbacks are silently added.
