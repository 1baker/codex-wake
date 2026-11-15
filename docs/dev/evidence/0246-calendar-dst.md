# Installed calendar/timezone/DST replay — #691

Status COMPLETE: deterministic installed calendar/persistence acceptance.
Product remains unchanged dev37. No native/provider inputs, real thread,
dispatcher, shared service restart, host-clock or timezone configuration change.
This is replay coverage; live DST arrival and authenticated-clock behavior are
separate acceptance boundaries.

## Installed boundary and inputs

The opt-in script runs with the installed prefix's Python. Every operation starts
a fresh interpreter, checks codex_wake imports from that prefix, and calls actual
ScheduleStore registration/read/cancel or poll_schedules against persisted roots.
PYTHONPATH is removed and cwd is the isolated root. The child TZ environment
alternates UTC and Pacific/Honolulu with tzset, while each cadence retains its
explicit IANA zone. No sessions/native response is mocked. The synthetic target
UUID has a missing private Unix endpoint; receipts remain unarmed.

Replay supplies an explicitly tagged synthetic UTC protocol shape to the internal
poll_schedules clock seam. Its status=network field satisfies that seam's shape;
it is NOT a claim of authenticated network observation. The receipt records
synthetic_replay=true and replay_only=true. Nothing dispatches those records.
Counts are finite; missed catch_up/overlap queue bounds16, lateness/window604800s
keep the selected multi-day replay focused on calendar computation. Cleanup
cancels the isolated records and denies their temporary permission policies.

Installed0.22.0.dev37, host IANA tzdb header `# version 2026e`:

- America/Chicago file SHA256: feba326ebe88eac20017a718748c46c68469a1e7f5e7716dcb8f1d43a6e6f686.
- America/New_York file SHA256: e9ed07d7bee0c76a9d442d091ef1f01668fee7c4f26014c0a868b19fe6c18a95.

TZPATH and exact zonefile paths/hashes are in the private replay receipt.
Expectations are literal independently worked UTC vectors, not values generated
by the implementation under test.

## Results

All12 valid cases and8 rejection cases PASS. There are36 distinct scheduled
occurrences across153 fresh-interpreter steps, including same-boundary replays,
reads, same-request re-registration and cleanup. Each repeated poll preserved
occurrence IDs, wake IDs, due times and absolute expiries; next_due_at matched
the literal next UTC boundary. Scheduler PID/generation changed across polls.
Finite counts reached exhausted without rearming on repeated registration.
Cancellation retained original anchors in fresh-process readbacks.

| Case | Selected expected UTC anchors |
| --- | --- |
| Chicago08:00/20:00, spring | Mar13 14:00, Mar14 02:00, Mar14 13:00, Mar15 01:00 |
|43200s interval, same start | Mar13 14:00, Mar14 02:00, Mar14 14:00, Mar15 02:00 |
| Chicago08:00/20:00, fall | Nov6 13:00, Nov7 01:00, Nov7 14:00, Nov8 02:00 |
|43200s interval, same start | Nov6 13:00, Nov7 01:00, Nov7 13:00, Nov8 01:00 |
| Chicago02:30 gap skip | Mar15 07:30; no due instant for missing Mar14 local time |
| Chicago02:30 gap shift_forward | Mar14 08:30 (03:30 local), then Mar15 07:30 |
| Chicago01:30 fold first | Nov7 06:30, then Nov8 07:30 |
| Chicago01:30 fold second | Nov7 07:30, then Nov8 07:30 |
| Chicago01:30 fold both | Nov7 06:30 and07:30, then Nov8 07:30 |
| New_York01:00/01:30 fold both | Nov7 05:00,05:30,06:00,06:30 in UTC order |
| Chicago02:30/03:30 gap shift collision | Mar14 08:30 once; Mar15 07:30 and08:30 |
| Absolute UTC start bound | Mar13 00:00Z includes Mar13 02:00Z (previous local date20:00) |

All dates are2027. Clock cases remain at their selected local hours: overnight
elapsed gaps are11hours in spring and13hours in fall. Interval cases remain12hours
apart and shift local clock times. Nonexistent times are omitted or shifted as
explicitly selected; repeated-hour both creates separate UTC occurrence IDs.
Different local entries resolving to one UTC instant share one due instant.
No default timezone/gap/fold choice was silently supplied.

Rejected with no saved schedule: missing timezone, gap or fold field; unknown
zone, gap policy or fold policy; invalid24:00 time; duplicate local clock entry.
All13 roots (12 valid plus the rejection root) completed cleanup: schedules
canceled, retained wake records canceled, permission policies defaultdeny revision2,
and missing native endpoints remain absent. No monitor was started.

## First failure and correction

Run01 remains statefailed. Its first vector used00:00Z while expecting Chicago
local midnight. The installed implementation correctly returned Mar13 02:00Z,
which is the previous local date's20:00 after that absolute bound. No case was
accepted, no wake was emitted and cleanup passed. The runner's intended local-day
cases now specify explicit local-midnight offsets; a separate UTC-bound case
protects the correct absolute-bound behavior. Run02 passed all cases. Product
code was unchanged; no installed effect or unknown delivery was retried.

The agent guide now explains this start-bound distinction and local-clock versus
elapsed-interval meaning. Prior actual native delivery and busy-overlap evidence
remain separate. The operator's subsequent confirmation of prior pane closures
is appended to evidence0245 with its issue-comment source; historical snapshots
are preserved.

## Review and focused checks

Fixed point91b80b09626cf256f71fdb9cb54dd21e2e57fa0a; frozen accepted replay source
cfaffea98b4b3a6ea56380a47af0fdc9f7855248. Review command:
`git diff 91b80b09626cf256f71fdb9cb54dd21e2e57fa0a...cfaffea98b4b3a6ea56380a47af0fdc9f7855248`.

Standards and Spec axes reviewed separately in primary context using AGENTS.md,
policies0002–0006/0014–0017, issue691, plan0246 and persistent-clock contract.
No CONTRIBUTING/CODING_STANDARDS file. No consequential Standards findings;
Fowler heuristic review did not justify a new replay framework or core refactor.
One Spec P2 test-vector error (UTC midnight versus local midnight) was observed
red, minimally corrected, and passed with the separate absolute-bound case.
Synthetic clock scope is explicit; no native/authenticated-time/live-DST claim.
Summary: Standards accepted0; Spec accepted1/P2 resolved. No product repair.

Focused commands: pinned Ruff0.14.2 `check --select F821,F822,F823 src scripts tests
.codex/hooks`, `python -m py_compile scripts/calendar_dst_acceptance.py`, installed
Python `scripts/calendar_dst_acceptance.py --help`, `python scripts/check_policy_wiring.py`,
`git diff --check`, and the installed `--run-replay` invocation: PASS.
No broad suite rerun, new fixture project/mock server, native/provider run or
UID package installation: package files did not change. Hosted paid CI excluded.
This host's Python3.12 checks do not cover a hosted3.11/3.12 matrix.

Private run01/run02 receipts and full subprocess outputs remain outsideGit under
user-state calendar-0246. No original receipt is rewritten. Replay work roots are
canceled/denied before disposal; receipt metadata remains for audit.
Memory disposition: forbidden — no explicit memory write request.
