# Container loss and monitor restart: #681

Status: preparation complete; live acceptance has not run. Plan 0243 and the
coordinator own sequencing and installed-package readiness. This does not close
#681 or qualify missed-event recovery.

The opt-in script `scripts/wake_container_restart_acceptance.py` runs with an
exact immutable installed package's Python. It uses installed
`ScheduleStore.register` with an isolated explicit host-operator principal and
actual native public protocol history pages; it does not exercise the external
OAuth connector. Its input manifest must identify one newly prepared disposable
saved native conversation with one actual setup input, `ticket: 681`,
`disposable: true`, an absolute private `tmux_socket`, `tmux_session` beginning
`cw681-`, exact native `executable`, native `endpoint`, and trusted owned `cwd`.
No production root, permission policy, profile, or grant is changed.

Each of two independent finite requests uses `reopen_live`, a 30-second interval
starting 75 seconds after qualified network UTC, count one, latest missed policy
with 180-second lateness, skip overlap, and a 180-second delivery window. These
explicit settings bound this acceptance; repeated cadence/missed/overlap behavior
remains a separate packet. The first request loses its complete private tmux
server, socket and original TUI generation before due. The second request stays
pending across stop/restart of only the owned monitor. The exact original target,
request, due time and absolute expiry must persist.

The monitor is an owned transient user-systemd unit with `RuntimeMaxSec=1200`,
interval one second, an explicit private socket environment and isolated wake
root. Readiness records both the actual health generation/live process and public
`monitor check`; a stale previous generation cannot satisfy restart readiness.
No existing native daemon, default tmux server or other monitor is restarted.

Acceptance requires exactly one correlated additional native user input per
request, exact wake/submission identity, a completed native turn and the expected
actual answer body from bounded full `thread/turns/list` pages. Restoration must
retain the exact saved UUID, cwd, native executable and private socket/session.
Missing, duplicate, incomplete, uncertain or unsupported evidence fails closed;
there is no effect retry. All launch/delivery journals and exclusive fresh private
receipts remain intact. Cleanup cancels owned schedules, stops the owned unit,
removes only the declared private server, suppresses the owned enrollment,
archives the explicitly disposable thread and denies the isolated authority.

Preparation validation on source base `eb14ec93c82cc7fce5eadaf5d060757f83f134f7`:

- `python -m py_compile scripts/wake_container_restart_acceptance.py`: passed.
- Installed dev34 Python `scripts/wake_container_restart_acceptance.py --help`:
  passed; help exits before package imports and creates no runtime resources.
- `git diff --check`: passed.

Tier: focused preparation only. The hosted matrix did not run under the operator's
CI cost policy. Syntax/help on this host are materially narrower than hosted
Python 3.11/3.12 regression checks and do not prove live behavior. The actual live
command and qualified prefix, source hashes, results, cleanup and any first
failure will be appended after the coordinator's readiness signal.

Memory disposition: `forbidden`; this task explicitly prohibits memory writes.
