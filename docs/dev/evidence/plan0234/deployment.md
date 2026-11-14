# Unified control deployment

Operator authorized review, merge and deployment on2026-11-14. PR644 merged as
`8e5f6f7cd0245d53b30f2d27d50b0c46f6a79d95`. Published head/base and the prior single
review/TDD resolution packet were rechecked; no second broad review was run.
Hosted paid CI skipped under repository policy.

Exact merged wheel SHA256
`e9274b034ffb06e0555f911b991eec1a3453ddca5b1191db2d824b0858883c76`.
Installed immutable prefix: `~/.local/share/codex-wake/releases/0.22.0.dev21-8e5f6f7`.
All344Python members match merged source/wheel/install; all31dependencies match
the prior dev20 prefix. Local Ruff undefined-name, compileall and policy checks PASS.

Separate Linux UID1017/Python3.12.3 installed-wheel selection:
`python -m unittest test_unified_bulk test_unified_connectors test_unified_contract test_unified_transports test_unified_environment test_local_session_observation test_unified_terminal test_unified_session_input test_unified_session_presentation test_unified_wakes -q`
ran41tests in22.950s, OK with1skip. The historical legacy-reader test lacked Git
history in installed-only state; source acceptance ran that exact baseline test.
Initial runs lacked a codex command on the test user's PATH. The corrected run
used an explicit test-only codex symlink to /bin/true for unarmed synthetic schedule
registration. Native/provider boundaries remain injected; this is not live provider
acceptance. Setup failures and ResourceWarning retained. Shared-kernel limitation
applies; no native Codex binary/package upgrade occurred.

All9stable launchers switched. Tab monitor PID1566005 and matching snapshot
generation0e5c8146f94b400fbbb4d8cc12b6e149; settings byte-identical. Supervisor
PID1566975 uses the new prefix. Local HTTP controller PID1613041 uses the new
prefix and still returns401 anonymously. Fresh actual stdio MCP initialize/list
advertises511tools, including all checked unified observation/input/bulk/grant/wake
operations. Existing client MCP connections retain imported code until normal
reconnect; no shared/client refresh was performed.

All24native process generations matched immediately after cutover. A later
readback found23originals plus one other native process; PID1565210 had exited
later, without attribution. No native process control was issued. Separate UID1017
process census empty after tests; temporary test state removed.

The supervisor stop retained an interrupted native-lifecycle poll hold. Inspection
found no firing-directory claims and two pending records explicitly held before
submission, attempts0, with no operation ID; files were unchanged since the hold.
The exact poll token was reconciled through the supported command, without
resubmitting effects. Final17root registrations retained; the two older
agent-browser/im-receipts reconciliation holds remain intact. No new hold remains.
No production schedules or connector grants were created, and no native daemon
was restarted. Other services and unrelated worktrees were preserved.

Rollback custody retains dev20, exact launcher preimages and supervisor drop-in
preimage. Restore links/drop-in and restart only affected wake services; existing
records/journals remain authoritative. No state deletion or history migration.
Raw receipts: `~/.local/state/codex-wake/unified-0234-deploy/` outside Git.
This proves deployed package/catalog/controller identity, not live provider, native
push, headless detach, universal slash support or all registered host acceptance.
Parent623 remains open as directed; all eleven implementation children remain closed.
Memory disposition forbidden: explicit user memory-update request absent.
