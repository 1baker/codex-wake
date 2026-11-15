# Ticket 669: background wake routing

Status: PASS on installed dev30 after the preserved dev28 failure below.
Both due events and cleanup were demonstrated through the deployed OAuth/MCP
boundary. The coordinator owns ticket closure and final integration.

The opt-in `scripts/connector_background_wakes_acceptance.py` uses one disposable
native conversation with persisted setup history and one owned TUI on the actual
default tmux socket. It registers two separate interval schedules through the
public OAuth/MCP connector. Both explicitly select `session_mode=background`,
45-second cadence, count=1, missed=skip with 120-second maximum lateness,
overlap=skip and a 120-second delivery window. These bounds apply to the new
dev30 intents; the cancelled dev28 intent retains its original bounds. The first due event must use the
original live attachment. The script then closes only its owned tab; the second
due event must use the same saved UUID without creating another visible tab.

Each case requires one completed schedule occurrence, accepted native delivery,
exact persisted selected route (`existing_tab` or `background`), one matching
native user message carrying its wake ID, and the final reply in that same native
turn. Both schedules are cancelled with the current revision. The disposable
thread is archived, the separate exact-target OAuth grant is revoked and checked
for HTTP 401, and the owned TUI process is checked for exit. Raw synthetic runtime
receipts and provenance stay in the user state directory outside Git.

The script adapts readiness from ticket 666 at
`1de611fa91a6a17114b2d0ea82920f45c5b880a7`. It creates no fixture framework and
changes no product code, permission policy, trust configuration or deployment.

## Route prerequisites

Installed dev28 `wake_mode_runtime.py` selects `LiveWakeRestorer` only for
`reopen_live` when absent. Background mode selects the same saved conversation
with `resume_policy=same_thread`, then sends native `turn/start` for that UUID
through the app server. It does not require the visible-restoration profile.
`permission_wake.decorate_policy` preserves the version 1 wake policy while the
common policy store is inactive; activating that store is a separate action and
is not part of this script.

Both routes still require a complete, unambiguous recipient observation. A live
recipient requires one `metadata_matched` attachment; an absent recipient must
have no attachment. The coordinator owns the observed session inventory deadline
repair and any qualification/deployment. No runtime bypass is authorized.

## Local preparation checks

Frozen source base: `882aae8007e71cc2641c66a742e340e6cf007310`.

- `python -m py_compile scripts/connector_background_wakes_acceptance.py`: PASS.
- Installed dev28 Python `scripts/connector_background_wakes_acceptance.py --help`:
  PASS; imports and argument parser only, no native/OAuth effects.
- `git diff --check`: PASS.

These preparation checks do not prove live routing. Hosted GitHub Actions is
intentionally skipped under the operator's CI cost policy. No hosted environment
is used; the eventual opt-in run must identify the installed prefix and receipt.

Memory disposition: forbidden; the task explicitly excludes memory writes.

## Live-slot preflight, 2026-11-15 UTC

The coordinator released the sole live slot with dev28 unchanged. Installed
`read_monitor_health(controller)` returned no health record (`{}`), and
`probe_managed_reader_capability(controller)` returned `None`. The script now
checks the same readiness fields used by schedule receipts before creating any
native target or grant. Its opt-in invocation exited with
`persistent_monitor_not_ready`; zero targets, grants and schedules were created.
The private receipt is
`~/.local/state/codex-wake/connector-background-wakes/live-preflight-20261115.json`.

This is an unmet runtime prerequisite, not a demonstrated background routing
failure. Neither due case ran. No global worker was started because doing so
could dispatch unrelated pending wakes. The coordinator owns monitor activation
and any service restart. No session-observation timeout defect is established
by this preflight.

## Armed due event and observed failure, 2026-11-15 UTC

The coordinator established a bounded dev28 monitor after verifying the execution
root had no wake records. This lane did not start, stop or restart that worker.
Monitor preflight then passed: PID 2023716, loop mode, schema 8 and both recurring
schedule/session-mode capabilities.

One owned conversation was seeded and retained throughout:
`01a1dd22-3cca-7311-8456-7459b6d1c007`. Preparation exposed a readiness discrepancy:
exact-target local discovery reported complete/unbound while a full authoritative
observation reported complete, both sources available, and exactly one
`metadata_matched` native TUI attachment with matching conversation name/cwd.
A separate bounded read measured `tmux_inventory(None,3)` raising
`SharedSourceError: tmux observation timed out` at 3.0126 seconds, while timeout 10
succeeded at 5.0581 seconds over 45 panes. These observations establish a
readiness discrepancy; this lane made no product change or timeout bypass.

The acceptance script now uses full source-qualified observation for its own
readiness checks and retains the exact source statuses before cleanup. Its
private persistent native client disables idle keepalive pings; the first probe
had lost that connection during the attachment wait. It reuses the same owned
seeded UUID rather than creating replacement conversations.

The actual public OAuth/MCP background schedule was armed with the monitor ready:

- Schedule: `schedule_0ec5819c2f82cc3ca5a78174bc308746`.
- Due occurrence: `wake_intent_02863446ff24424fbc5ff657f53c5c00`.
- Explicit policies matched the bounded setup above.
- Before due, full observation proved one original TUI attachment, PID 2105646,
  and both app-server/tmux sources available.
- At due, the schedule entered `attention` with `recipient_ownership_unknown`.
  The retained wake had qualified network UTC with state `due`, zero attempts,
  no native delivery, and runtime observation `unavailable`.
- Native history contained zero inputs matching the scheduled synthetic prompt.
- The public registration target retained `endpoint=unix://` and no captured
  session origin/socket. Its failing runtime observation did not retain raw
  source availability; no precise dispatch-time source cause is asserted here.

Cleanup was verified: public schedule cancelled, wake cancelled, disposable
thread archived, owned TUI absent, and temporary OAuth grant revoked with HTTP
401 readback. The product also emitted its own attention notice
`attention_46edc7d7954e489488e4732df150b076`; under explicit coordinator authority,
this exact owned notice was closed through the installed `AttentionQueue.close`
owner method with revision/fingerprint checks and a cancellation/zero-input
reason. Readback confirmed status `closed`, revision 2, and retained history
events `requested`, `closed`. No other notice changed.
The closed-tab due case did not run after the live-path failure. Ticket 669 stays
open. The coordinator stopped further baseline probes and owns the product
repair, qualification and deployment before retest.

Private evidence directory:
`~/.local/state/codex-wake/connector-background-wakes/`:

- `live-two-cases-20261115.json`: first preparation failure and cleanup gap.
- `live-same-target-20261115.json`: already-unarchived precondition refusal;
  same UUID subsequently archived successfully.
- `live-seeded-target-20261115.json`: seeded-target readiness discrepancy.
- `live-mismatch-source-20261115.json`: full live source and process evidence.
- `tmux-budget-readback.json`: bounded 3/10-second observation contrast.
- `live-authoritative-readiness-20261115.json`: actual armed due case and cleanup.
- `live-failure-reconciliation-20261115.json`: exact wake, zero native inputs and
  cleanup readback.
- `attention-cleanup-20261115.json`: exact owned notice before/after/readback;
  original audit history retained.

Local `py_compile` and `git diff --check` passed after script changes. These are
preparation checks, and the live outcome is FAIL, not acceptance. Hosted CI was
not invoked. Memory disposition remains forbidden under the task boundary.


## Qualified dev30 retest: PASS, 2026-11-15 UTC

Installed prefix:
`/home/ecochran76/.local/share/codex-wake/releases/0.22.0.dev30-c7d7279`.
The coordinator qualified and deployed batched process discovery and the full
15-second ownership observation budget separately. Native daemon PID 2082 and
endpoint identity remained unchanged. This lane made no product, deployment,
common-policy or account changes.

Before the run, installed monitor health showed PID 2318910, loop mode, reader
schema 8 and both schedule/session-mode capabilities; managed-reader probing
passed. The run reused the same owned seeded/archived UUID from the prior
private ownership manifest. No new conversation was created. Both schedules
used new intent keys, interval 45 seconds, count 1, missed skip with maximum
lateness 120 seconds, overlap skip and delivery window 120 seconds. The earlier
cancelled schedule and its zero-effect evidence were not revised.

| Case | Public schedule | Persisted native route | Native inputs | Correlated final reply | Visible attachments |
| --- | --- | --- | --- | --- | --- |
| Original live TUI | `schedule_1bb861ba7f4259c744e333a9bfa0a906` | `existing_tab` | 1 | `CW669_LIVE_36506e05` | 1, original PID 2398819 |
| After closing owned tab | `schedule_0bc902f66c79a8a19062a75370c5c66c` | `background` | 1 | `CW669_CLOSED_67f7033c` | 0 |

The public OAuth/MCP schedule shows reported one completed occurrence per case.
The retained native wake records proved the selected routes. Each exact native
turn contained one corresponding user message with the wake identity and its
expected final agent reply. The live recipient was preserved; after the owned
tab closed, the saved conversation retained the same UUID and the second route
created no visible attachment. Final history contained exactly two new wake
inputs in total.

Native correlation:

- Live wake `wake_intent_75acb93d77094539828ffa87c1c912d5`, turn
  `01a1dd3e-6966-71f1-a642-1458e5a13fda`, message
  `01a1dd3e-6f2f-7693-84d4-40b8f8f6349f`.
- Closed wake `wake_intent_7bf396e4151340eba6d92d5ba775dbc3`, turn
  `01a1dd3f-2d3e-7882-8f39-5bbaa6dcf6b4`, message
  `01a1dd3f-2def-7303-8969-a623c5564c53`.

Cleanup readback passed: both schedules cancelled, own thread archived, own TUI
process absent, separate grant revoked and rejected with HTTP 401, and empty own
scratch cwd removed. Inspection of notices for this exact conversation found only
the earlier notice, already closed at revision 2; no open owned alert remained.
The coordinator retains ownership of the transient monitor and service lifecycle.

Private evidence:
`~/.local/state/codex-wake/connector-background-wakes/live-dev30-two-cases-20261115.json`
and `dev30-pass-summary.json`. The receipt records the installed prefix, branch
source commit and exact script SHA-256; runtime data remains outside Git.

Validation command (live_or_soak, no retries of admitted intents): installed
dev30 Python `scripts/connector_background_wakes_acceptance.py --run-live
--reuse-owned-thread 01a1dd22-3cca-7311-8456-7459b6d1c007 --receipt <private-path>`:
PASS. `python -m py_compile scripts/connector_background_wakes_acceptance.py` and
`git diff --check`: PASS. This is an installed Linux OAuth/MCP/native acceptance,
not hosted CI; no GitHub Actions runs were requested. Earlier failed attempts
remain documented above and are not represented as passing.

Memory disposition: forbidden; the task excludes memory writes. A private
machine-readable non-write receipt is retained separately.
