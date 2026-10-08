# App-Server Mode

Status: MVP stdio transport implemented
Verified: 2026-05-23 with Codex CLI 0.133.0

## Contract

Codex Wake supports an app-server target record shape for controlled dispatch:

```json
{
  "target": {
    "transport": "app-server",
    "endpoint": "stdio://",
    "thread_id": "thread_...",
    "codex_cmd": "/home/you/.nvm/versions/node/v24.14.0/bin/codex"
  }
}
```

`codex_cmd` is optional. When present, dispatch uses that validated Codex CLI
command for `codex app-server --listen stdio://`. When absent, dispatch checks
`CODEX_WAKE_CODEX_CMD` and then falls back to `codex` from the daemon process
environment.

The implemented path starts or uses a stdio app-server client and sends:

1. `initialize`
2. `thread/resume`
3. `turn/start`

The local owner-delivery repair candidate keeps the private client alive until
the matching `turn/completed` event. Its total operation budget is 30 seconds,
with at most two additional seconds for a best-effort deadline interrupt.
Completion, interruption and uncertain delivery are recorded separately from
acceptance. A held native writer lock or existing resume client refuses stdio
before another writer is launched. Use stdio only for short, unowned turns,
not for a long task in a live managed TUI.

Older records send the canonical short prompt and still need the wake hook:

```text
WAKE_TRIGGER_ID=<wake-id>
Resume the scheduled wake task.
```

In plain English: this identifies the wake; an older record relies on the hook
to supply its saved instructions.

New CLI records set the optional `inline_payload` target field and send the
bounded saved instructions directly. The hook still writes its receipt, but
does not duplicate an exact inline payload. `submitted` continues to mean
accepted, not finished. Inspect `delivery.state` and the matching turn evidence.

## Exact existing-owner TUI mode

The repair candidate adds `--tmux-thread-id` and `--owner-pid` to the time and
file/process commands. Capture `TMUX` and `TMUX_PANE` from the actual native
client, not an unrelated tool shell or a saved pane label.

```bash
codex-wake after --require-monitor --tmux-thread-id EXACT_UUID --owner-pid NATIVE_PID 1m -- "Check the saved task and report its outcome."
```

In plain English: this schedules work in that existing Codex client. It will
not create another writer. The command changes local wake state; the monitor
can submit the task only after verifying the same foreground owner is idle.

Owner mode verifies process lifetime, resume UUID, captured remote endpoint,
pane ancestry and foreground terminal on each dispatch. It requires an empty
composer and terminal lifecycle evidence, then repeats both checks before a
bracketed paste and one submit. Payloads are capped at 8 KiB. No global hook
installation, host restart or direct inference connection is required.

The exact rollout provides acceptance and terminal-turn receipts through a
bounded reader with saved inode and offset. A sending boundary is durable
before paste; any uncertain or crashed submission is never replayed. A live
foreign monitor is not stolen by a one-shot poll. Only a persistent loop may
dispatch owner-mode records; `--once` does not submit them. Idle waiting expires
after three hours and logs only its state transition.

Completion and pane visibility are separate. The answer's joined completion
token is intentionally absent from the input prompt, preventing an echoed
prompt from falsely proving a visible answer. A completed canary with no pane
readback remains `completion_visibility_unproven`.

## CLI

Use explicit app-server commands for time-based wakes:

```bash
codex-wake app after thread_abc 45m -- "Resume this thread through app-server."
codex-wake app after --codex-path "$(command -v codex)" thread_abc 45m -- "Resume this thread through app-server."
codex-wake app at thread_abc "2026-05-19T17:30:00-05:00" -- "Check the release state."
```

The older `--app-server-thread-id` option on time commands remains available for compatibility, but the `app` subcommands are the clearer operator surface.

When `turn/start` is accepted, Codex Wake records available response metadata in `dispatch_result`, including `thread_id` and `turn_id` when returned by app-server.

Inspect an app-server thread without starting a turn:

```bash
codex-wake app candidates
codex-wake app candidates --cwd "$PWD" --json
codex-wake app candidates --cwd "$PWD" --validate --only-idle --json
codex-wake app status thread_abc
codex-wake app status --resume thread_abc
codex-wake app status --codex-path "$(command -v codex)" --resume thread_abc
codex-wake app status --json thread_abc
```

For service-fired app-server wakes, install the repo service from an
environment that can resolve `codex`, or pass an explicit path:

```bash
codex-wake service install --codex-path "$(command -v codex)"
codex-wake doctor
codex-wake doctor --json
```

The service unit persists `CODEX_WAKE_CODEX_CMD` when a Codex CLI command can be
resolved. `doctor` reports whether the installed unit or user-systemd manager
environment can resolve the Codex CLI used for app-server dispatch. It reports
only the relevant command-resolution fields, not the full service environment.

Dispatch preflight resumes the target thread, records `app_server_preflight`
status evidence, and only calls `turn/start` when the resumed thread reports
`idle`. If the thread reports `active`, Codex Wake requeues the wake with
backoff instead of starting another turn. Malformed status or non-idle
unhealthy states fail the wake record visibly.

App-server wake targets must be resumable rollout-backed thread ids. A bare
`thread/start` response is not enough if no turn has materialized a rollout for
later resume. Plain `app status` uses `thread/read` and can report `notLoaded`
for a resumable thread in a fresh stdio app-server process. Use `app status
--resume` when checking the same path dispatch will use; it calls
`thread/resume` and reports the resumed status without starting a turn.

`app candidates` scans local Codex session rollout metadata under
`~/.codex/sessions` and reports recent rollout-backed thread ids. It reads only
the first `session_meta` line from each rollout file and does not emit prompt or
transcript body content. Use `--cwd "$PWD"` to narrow the list to a repo, then
run `codex-wake app status --resume <thread-id>` before registering an
app-server wake. `app candidates --validate` performs the same resume-backed
status check for each candidate without starting turns; `--only-idle` filters to
candidates that resume to an idle status.

## Source Verification

Official docs checked on 2026-05-18:

- App-server supports stdio, WebSocket, Unix socket, and off transports.
- WebSocket transport is experimental and unsupported.
- Local WebSocket listeners are appropriate for localhost and SSH forwarding.
- Non-loopback WebSocket listeners require WebSocket auth before remote exposure.

Local Codex CLI checked on 2026-05-18:

- `codex-cli 0.130.0`
- `codex app-server --listen stdio://`
- `codex app-server generate-json-schema --experimental`
- `codex app-server generate-ts --experimental`

Generated schema confirmed:

- `thread/resume` uses `ThreadResumeParams` with `threadId`.
- `turn/start` uses `TurnStartParams` with `threadId` and text `input`.

Local Codex CLI refreshed on 2026-05-20:

- `codex-cli 0.131.0`
- `codex app-server --listen stdio://`
- `codex app-server generate-json-schema --out /tmp/codex-app-schema-p29 --experimental`
- The generated schema now includes v2 schema files under `v2/`.
- `ThreadResumeParams` still requires `threadId` and supports `cwd`; `persistExtendedHistory` is deprecated and ignored but remains accepted for older clients.
- `TurnStartParams` still requires `threadId` and `input`, and supports optional turn-scoped overrides such as `cwd`, model, effort, permissions, and sandbox policy.
- `TurnStartResponse` still returns a required `turn` object.
- `ThreadStatusChangedNotification` exposes `idle`, `active`, `systemError`, and `notLoaded` thread states, which is the likely future basis for safer app-server wake preflight.
- A source-tree stdio initialize smoke succeeded and returned Codex home, platform, and user-agent metadata.

Local Codex CLI refreshed on 2026-05-23:

- `codex-cli 0.133.0`
- Product hardening added explicit Codex CLI command resolution for app-server
  dispatch, service unit persistence through `CODEX_WAKE_CODEX_CMD`, and doctor
  readiness fields for service-side app-server command resolution.

## Current Implementation Boundary

The current implementation is suitable for controlled stdio dispatch against a
known resumable idle thread id. It should not yet be treated as a full
replacement for the tmux path because:

- service-fired app-server dispatch should be checked with `doctor` before a
  wake is queued;
- current dispatch treats `turn/start` acceptance as the app-server
  acknowledgement, while tmux dispatch still relies on the Codex hook ack file;
- app-server dispatch can resume a thread without producing a visible turn in a
  live tmux pane the operator is watching;
- target selection is still an explicit operator or agent decision from local
  rollout-backed thread candidates.

The 2026-05-23 product-hardening lane validated service-fired app-server
dispatch through a temporary user service and a known idle thread id.

## Safety Boundary

Only `stdio://` is implemented in Codex Wake right now. Non-stdio endpoints are rejected during CLI creation and dispatch validation.

WebSocket support is deferred until there is a clear local operator need and a testable auth setup. If implemented, it must enforce one of:

- loopback-only `ws://127.0.0.1:<port>`
- SSH-forwarded loopback
- authenticated `wss://` for non-local access

Do not expose unauthenticated non-loopback WebSocket app-server endpoints.
