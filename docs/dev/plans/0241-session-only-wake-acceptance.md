# Ticket #667: this-session-only wake lifecycle

Scope: approved spec #663, ticket #667. This lane owns only its opt-in live
acceptance script and this evidence summary. The integration owner maintains
ledger 0241, product repairs, deployment and issue closure.

Source base: `882aae8007e71cc2641c66a742e340e6cf007310`.
Initial installed acceptance prefix:
`~/.local/share/codex-wake/releases/0.22.0.dev28-1fb9180`.

The script addresses one newly seeded native conversation, resumes its exact
executable in an owned tmux session on the existing supported server, then uses
a separately scoped OAuth grant through the deployed HTTPS MCP endpoint. Tokens
remain in memory. Receipts and synthetic native metadata stay outside Git.

Declared experiment: `session_only`; interval starts 45 seconds after definition,
30-second cadence; count two; missed policy skip with maximum lateness 15 seconds;
overlap skip; delivery window 15 seconds. Missing mode must be refused before
registration. A detached tmux client must leave the schedule enabled. Destroying
only the owned recipient session must cancel the schedule with `session_closed`;
observation past the first due event must show no occurrence or new native input.
The script cancels its exact schedule on failure, archives its conversation,
revokes its grant and removes its own session. It never restarts native services.

Run explicitly with the installed prefix's Python:

```sh
PREFIX/bin/python scripts/connector_session_only_acceptance.py --run-live
```

## Evidence status

Historical dev28/dev29 status was **BLOCKED**, not passed; the dev30 acceptance below supersedes that status. Initial attempts exposed setup
constraints rather than proving scheduler behavior: native attachment requires
matching native conversation name and actual pane working directory; remote
resume must not override permissions. Two initial unattached-recipient attempts
were cleaned up without a schedule or grant. Subsequent locator/read failures
were retained privately; another probe was interrupted at the coordinator's
serialization boundary and its conversation/session were cleaned up. No passing
scheduler claim follows from these attempts.

Private receipts are under
`~/.local/state/codex-wake/connector-acceptance-spec/session-only-*.json`.

Focused local checks: `python -m py_compile
scripts/connector_session_only_acceptance.py` passed. Installed-prefix Python
`--help` passed. System Python lacks installed connector dependency `httpx2`;
therefore the actual live command uses the installed environment. This opt-in
network/native acceptance is outside the default local test lane. Hosted GitHub
CI was not run under the repository CI cost policy.

## Serialized deployed result

With a persistent uniquely named native client, the exact disposable conversation
was seeded, named, resumed in its own default-server tmux session, and observed as
`metadata_matched` from real exact-thread metadata and native tmux inventory.
The protected `wake_wakes_schedules_register` operation correctly refused missing
`session_mode` with `explicit_schedule_fields_required`. The full explicit request
then failed with `MCPError: session_owner_unverified`. No schedule was admitted.
Private evidence: `session-only-1565a1b8.json` under the directory above; the earlier
`session-only-0b40d1f0.json` retains the initial expected-refusal handling failure.
The exact owned UUID is retained privately for `--reuse-thread` qualification;
this option verifies the expected disposable name and scratch directory.

Observed cleanup: temporary grant revoked; disposable thread archived; owned tmux
session absent; no monitor or scheduler process launched; no admitted timer. The
script's native connection closed. The original default tmux session was retained.
Two initial standalone temporary-directory trust entries created by this lane
were removed exactly; other trust entries were preserved.

The initial exact-thread narrowing repair proposal is withdrawn: it could hide
other loaded conversations with matching names/directories and weaken ambiguity
checks. A shared repair requires causal evidence while preserving full candidate
uniqueness and process ownership fences. No product change is justified yet.
At that checkpoint, detachment survival, closure cancellation and past-due
non-delivery were unverified because registration did not complete.

Memory disposition: `forbidden`; the coordinator explicitly prohibited memory
writes. A private non-write receipt records this boundary outside Git.

## Same-recipient read-only diagnostic

Private receipt `session-only-diagnostic-1d489be6.json` retains the full real
snapshots. The same archived disposable recipient was restored using a persistent
native connection and an owned default-server tmux session. The diagnostic used
the connector service's PATH and no TMUX variable. No grant or schedule was created.

Full `sessions.observe` against the resolved endpoint succeeded at timeout five
seconds (elapsed 5.82 seconds) and thirty seconds (elapsed 5.52 seconds). Both
sources were available, inventory was complete, and the target had exactly one
`metadata_matched` attachment. Thus the proposed five-second deadline cause is
not established. Read-only `bind_mode` on a copied target bound the exact endpoint;
a subsequent copied target using `unix://` failed `session_owner_unverified`.
Post-cleanup the same locator resolved to the identical endpoint and raw daemon
version returned success. This sequential difference does not prove an endpoint
bug or exclude intermittent observation failure. Further diagnosis must retain
full source availability and candidate ambiguity evidence, without a fake owner.
Cleanup again archived the same thread and removed only its owned session.

## Dev29 public retry and actual binder failure capture

The qualified dev29 process-scan batching repair did not complete #667. Running
the opt-in public acceptance with the dev29 installed Python on the same owned
conversation again proved its real attachment and missing-mode refusal, then
received `session_owner_unverified` on complete registration. Private receipt:
`session-only-664d786b.json`. No schedule was admitted; its grant was revoked,
owned session removed, and conversation archived.

A subsequent private recording wrapper ran the real binder on copied arguments
in an AnyIO worker thread, using the connector's full environment and home working
directory. It returned the original inventory unchanged and stopped on the first
refusal. Receipt `session-only-thread-diagnostic-aad9fa08.json` captured the actual
failing observation: elapsed 5.395 seconds, `complete=false`, no target row,
app-server source unavailable with `SharedSourceError`, and tmux source available.
The real reader's `loaded_threads` exception was
`shared metadata read failed: TimeoutError`. This proves the immediate failing
boundary was full native metadata collection; tmux collection succeeded. It does
not prove why the native metadata read exceeded its bound or select a repair.
The child loaded before a proposed lock-comparison edit, so this particular
capture did **not** hold the recurring-schedules lock. No lock-cause claim follows.
No grants, schedules, model turns, new conversations or source changes were made
by the recording diagnostic. The same recipient was archived and its session
removed again. The integration owner retains repair and deployment authority.

## Final dev30 acceptance: PASS

The same owned archived recipient was reused after the coordinator qualified and
deployed dev30. Product source `c7d7279` was exercised through the actual protected
connector and its ready owned monitor. Installed prefix:
`~/.local/share/codex-wake/releases/0.22.0.dev30-c7d7279`.
The acceptance script ran from the lane at `f3deb05f` plus the now-committed PTY
client observation/detachment refinement. Exact command:

```sh
~/.local/share/codex-wake/releases/0.22.0.dev30-c7d7279/bin/python scripts/connector_session_only_acceptance.py --run-live --reuse-thread OWNED_UUID
```

`OWNED_UUID` is retained in the private ownership receipts. No new conversation
or setup model turn was created during this final run. Private passing receipt:
`session-only-d71140b7.json` under the receipt directory above.

- Missing session mode was refused before registration.
- Complete explicit policies registered schedule
  `schedule_641e3d3ba737f8b7ee5fe5499bd21618` as **armed**.
- One real PTY tmux client was created and mapped by its exact PID and nonempty
  terminal name. Detaching only that client proved its attached count changed
  from one to zero; the recipient remained alive and the schedule stayed enabled.
  Other client observations were preserved. In particular, transient command
  clients must not be mistaken for the owned interactive client.
- Destroying only `cw667-session-only` ended the real recipient TUI. The ready
  monitor canceled the schedule with reason `session_closed`.
- Observation through five seconds past the first due time
  `2026-11-15T03:24:54.474551Z` showed `occurrences=[]` and zero new native user
  inputs. The original setup input remained the sole native user message.
- Final cleanup retained a canceled schedule, revoked the temporary grant,
  archived the same test conversation, reaped the owned PTY client, closed its
  file descriptor and removed the owned session. No monitor was started by this
  lane. No occurrence or wake delivery existed to create an owned delivery notice.
  Fresh process/session readback found no owned acceptance/attach process and
  only the retained operator default tmux session. Root-owned services remained
  running under the coordinator's custody.

Two earlier dev30 script checks stopped after armed admission and were cleaned up:
`session-only-76b61715.json` exposed an ambiguous tmux display target, and
`session-only-97d48ff3.json` exposed a transient command-client count. The subsequent
`session-only-9da39732.json` stopped before scheduling while inspecting clients.
These failures remain retained; they are not hidden by the final pass.

Focused checks `python -m py_compile scripts/connector_session_only_acceptance.py`
and `git diff --check` passed. The opt-in deployed acceptance above exited zero.
No default test suite behavior or product source changed in this lane; hosted CI
was skipped under the CI cost policy. The installed Python supplies the actual
connector dependencies and native runtime, unlike system Python or hosted CI.
The integration owner owns ledger reconciliation and ticket closure.
