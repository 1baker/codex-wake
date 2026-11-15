# Clock-based recurring checks

Work item: #615; parent spec: #610.

Use `schedules register --request FILE` with an explicitly agreed clock cadence:

```json
{
  "kind": "clock",
  "times": ["09:00", "17:00"],
  "timezone": "America/Chicago",
  "start_at": "2026-11-13T00:00:00Z",
  "gap_policy": "skip",
  "fold_policy": "first"
}
```

This is the `cadence` field inside the existing complete schedule request. Mode,
end condition, missed-run/max-lateness policy, overlap bounds and delivery window
remain explicit fields of that request. `times` contains distinct local `HH:MM`
values; `start_at` is an inclusive timezone-qualified bound. It is an absolute
instant, not midnight in the cadence timezone: `00:00Z` can include an evening
occurrence on the previous local date. To start at local midnight, provide its
correct UTC offset (for example `2027-03-13T00:00:00-06:00` in Chicago).

`gap_policy` chooses `skip` (omit a nonexistent local clock time) or
`shift_forward` (advance by the timezone transition gap, so a missing 02:30 in
a one-hour gap becomes 03:30). `fold_policy` chooses `first`, `second` or `both`
for a repeated clock time. `both` creates distinct UTC occurrences. Explicit clock
times that resolve to the same UTC instant identify one due instant.

Agree whether “twice a day” means local clock times or elapsed intervals.
For example, Chicago `08:00`/`20:00` stays at those local times, with an 11-hour
spring overnight gap and a 13-hour fall overnight gap. An interval of 43,200 seconds
keeps 12-hour gaps and changes its local clock times across those transitions.

Wake calculates UTC due anchors using the host's installed IANA timezone database.
Persisted occurrences keep their original due/expiry anchors after a restart;
interval schedules retain elapsed-time semantics. This source implementation and
local validation do not establish installed monitor readiness or live delivery.

## Local acceptance evidence

Seam: operator schedule registration/show plus the existing `poll_schedules`
boundary, using real schedule persistence and only injected trusted-clock evidence.
No private sessions, native provider inputs or extra fixture framework were used.

Environment: Python 3.12.13 from the existing development venv, source via
`PYTHONPATH=src`, temporary isolated schedule roots. Red/green command:

```sh
PYTHONPATH=src /home/ecochran76/workspace.local/codex-wake/.venv/bin/python \
  -m unittest discover -s tests -p test_recurring_calendar.py -q
```

Observed red outcomes, each before its implementation: missing calendar module;
fall `both` incorrectly advanced directly to the next day; spring `shift_forward`
incorrectly skipped the day. Final green: four tests passed, covering real
registration, spring gap choices, repeated-hour occurrences, missing explicit DST
choice, and original due/expiry retention across a repeated poll.

Interval regression:

```sh
PYTHONPATH=src /home/ecochran76/workspace.local/codex-wake/.venv/bin/python \
  -m unittest discover -s tests -p test_recurring_schedules.py -q
```

Result: three passed at the ticket base plus this change. No hosted CI ran.

Documentation custody: worker `persistent_clock_615`, branch
`feat/persistent-wake-clock-615`, base `34a1cef677a9c1180f501f8078bcfb98a8902d5a`.
This checkout isolates #615 from concurrent live/background work; retain until
integration and durable custody are verified, then remove through normal worktree
cleanup. It was added after inspecting the registered inventory (122 before,
123 after; other checkouts are outside this worker's custody).

Memory disposition: `not_durable` for this worker checkpoint; the coordinator owns
final integrated closeout and no memory was written.

## Installed calendar replay acceptance (#691)

[Evidence0246](../dev/evidence/0246-calendar-dst.md) records dev37 installed-API
replay under IANA tzdb2026e: local-clock/interval differences, gap/fold choices,
repeated-hour UTC ordering, coincident-instant deduplication, absolute start
bounds, fresh-process persistence/idempotency and invalid-choice rejection.
Synthetic clock inputs were confined to isolated roots with a missing endpoint
and no dispatcher. These results establish calendar/persistence behavior; live
DST arrival, clock authentication and delivery remain separate proof boundaries.
