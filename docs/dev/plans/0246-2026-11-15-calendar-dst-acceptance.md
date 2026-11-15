# 0246 — Installed calendar/timezone/DST acceptance (#691)

State COMPLETE. Installed12valid/8rejection replay cases accepted; no product change.
Evidence: docs/dev/evidence/0246-calendar-dst.md. Owner root/ecochran76, WIP1. Branch test/calendar-dst-691.
Base91b80b09; one owned checkout protects unrelated dirty primary. Remove after
exact remote custody. Existing installeddev37 is the delivery target.

Verify local08:00/20:00 versus43200-second intervals across spring/fall, gap
skip/shift_forward, fold first/second/both, multiple-time UTC ordering in a
repeated hour, restart/replay idempotency at each boundary, original occurrence
IDs/due/expiry/count and cancellation. Reject absent/invalid timezone/DST choices.
Use literal independently worked2027 Chicago/New_York UTC vectors and record
actual installed IANA database version/hashes and process TZ environments.

This is deterministic installed-API replay, NOT live authenticated-clock or DST
arrival/provider proof. Logical clock input has an explicitly synthetic protocol
shape. No monitor, dispatcher, native endpoint, real thread, host-clock/TZ change,
production policy/service or provider effect. Use a random synthetic UUID and
missing private endpoint in isolated roots; scope permissions there and deny on
cleanup. Each step uses a fresh installed-package process; no source shadowing,
new fixture project/mock server or speculative matrix. Existing actual native
execution acceptance remains separate.

Read current coverage first. Add regression/fix only for a demonstrated gap;
product changes require red/green, review/local gates, exact UID1017 package
qualification, merge/install and renewed acceptance. No paid hosted CI. Without
product changes run only meaningful focused checks and installed replay.

Definition of done: installed cases accepted with truthful replay boundaries,
canonical evidence/ROADMAP/RUNBOOK aligned, source reviewed and merged, #691 closed,
owned roots/checker/checkout cleaned after exact remote custody. Preserve replay
receipts outsideGit. Memory writes forbidden without explicit ask.
