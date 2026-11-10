# Codex Wake

> **About this copy:** this is a personal fork of [CochranResearchGroup/codex-wake](https://github.com/CochranResearchGroup/codex-wake). The original project's documentation continues below.

**In one sentence:** Codex Wake lets an AI agent set an alarm for itself ("wake me in 30 minutes" or "when this file appears"), and then resumes it in its terminal tab when the time comes.

**Who it is for:** People who run long Codex jobs and want the agent to come back to a task by itself.

**How it works:**

```mermaid
flowchart LR
    Agent[Agent] -->|wake me at ...| Rec[(Saved wake request)]
    D[Wake service] -->|watches clock / files| Rec
    D -->|time is up| Tab[Resumes the agent's terminal tab]
```

---


Codex Wake is a local wake spooler for TUI-bound Codex agents. It lets an agent register a durable wake request, lets a deterministic daemon wait for the trigger, and resumes a Codex TUI pane by submitting a short wake prompt.

The current package supports:

- `codex-wake after`, `codex-wake at`, and `codex-wake file`
- durable JSON wake records under `.codex/wake/`
- `codex-waked` polling and dispatch
- monitor readiness checks and `--require-monitor` scheduling gates
- a user-scoped supervisor for explicitly registered wake roots
- tmux pane injection with `UserPromptSubmit` hook ack
- terminal-state archival with `codex-wake archive`
- experimental stdio app-server targeted wake records
- experimental OpenClaw Gateway targeted wake records
- OpenClaw plugin registration through `codex_wake_schedule`

## Requirements

- Python 3.11+
- `tmux` for TUI-bound wake dispatch
- Codex CLI with hook support
- `uv` for the recommended user-scoped install path

## Install

From a checked-out repo:

```bash
uv tool install --force .
```

After the first release tag exists, a fresh machine can install from GitHub:

```bash
uv tool install git+https://github.com/CochranResearchGroup/codex-wake.git@v0.5.0
```

Verify the installed commands:

```bash
command -v codex-wake
command -v codex-waked
command -v codex-wake-hook
codex-wake --help
codex-waked --once --no-dispatch --wake-root /tmp/codex-wake-empty
```

## Public Install Quickstart

Use a released public tag and make the wake root monitor-ready before
scheduling unattended wakes:

```bash
tag=<release-tag>
uv tool install --force --reinstall "git+https://github.com/CochranResearchGroup/codex-wake.git@$tag"

codex-wake hook user install
codex-wake hook user check

codex-wake supervisor install
codex-wake supervisor enroll --wake-root "$PWD/.codex/wake" --repo-root "$PWD"
codex-wake supervisor status --all

codex-wake --wake-root .codex/wake monitor check --json
codex-wake --wake-root .codex/wake product-readiness --json
```

From this repo checkout, run the release smoke harness against the installed
commands:

```bash
python scripts/product_smoke.py --json
```

For OpenClaw Gateway wakes fired by the user supervisor, import the Gateway
auth environment into the user systemd manager before scheduling:

```bash
systemctl --user import-environment OPENCLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_PASSWORD
systemctl --user restart codex-wake-supervisor.service
```

The support boundary and false-positive cases are documented in
`docs/support-boundary.md`.

## Hook Setup

Codex Wake needs a `UserPromptSubmit` hook so the daemon can confirm that its pasted wake prompt was actually submitted and so Codex receives the full wake context from the trigger JSON.

For an installed tool, let Codex Wake write the repo-local hook config:

```bash
codex-wake hook install
codex-wake hook check
```

For a hook that should be available from user scope, install the same handler in
Codex's user hook file:

```bash
codex-wake hook user install
codex-wake hook user check
```

The user hook commands write or check `$CODEX_HOME/hooks.json` when `CODEX_HOME`
is set, otherwise `~/.codex/hooks.json`.

`hook check` verifies the repo-local config and reports ack evidence from
`.codex/wake/acks/`. If no ack exists, the active TUI hook-loaded state is
reported as `unknown_without_ack`; that is not proof that tmux injection failed.
Codex may show the hook source under `UserPromptHooks` during `/hooks` review.
It also reports whether the same `codex-wake-hook` command is present in both
the project hook file and the user hook file at `$CODEX_HOME/hooks.json` or
`~/.codex/hooks.json`. If both sources are installed, Codex may run both and
inject duplicate wake context for the same submitted prompt.

This writes or checks this `.codex/hooks.json` shape:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "codex-wake-hook",
            "timeout": 5,
            "statusMessage": "Checking wake trigger"
          }
        ]
      }
    ]
  }
}
```

Codex may require a one-time `/hooks` review before a new repo-local hook runs. Codex Wake reports that prerequisite, but it does not bypass Codex hook trust. If `/hooks` does not list this repo hook source, the active TUI has not loaded the repo hook file; restart or resume Codex in this repo, then review hooks before testing wake ack behavior.

## Basic Usage

Run these commands inside a tmux pane that is hosting the Codex TUI you want to wake. `codex-wake` captures `TMUX_PANE` and the tmux socket from the environment.

Agents can use the bundled `$codex-wake` skill for workflow guidance and wake
cycle examples. The skill lives at `skills/codex-wake/` in this repo and can be
installed into user skill roots when agents need to schedule their own wake
cycles.

Wake after a duration:

```bash
codex-wake after --require-monitor 45m -- "Continue the migration. First inspect .codex/events/migration.log."
```

Wake at an absolute timestamp:

```bash
codex-wake at --require-monitor "2026-05-18T17:30:00-05:00" -- "Check whether the release branch is ready."
```

Wake when a marker file exists:

```bash
mkdir -p .codex/events
(
  pytest -q > .codex/events/pytest.log 2>&1
  touch .codex/events/pytest.done
) &
codex-wake file --require-monitor .codex/events/pytest.done -- \
  "Pytest finished. Read .codex/events/pytest.log and continue from the failing tests."
```

Wake when a file is created or changes:

```bash
codex-wake changed --require-monitor .codex/events/build.log -- \
  "The build log changed. Read .codex/events/build.log and continue."
```

Wake when a known background process exits:

```bash
long-running-command > .codex/events/job.log 2>&1 &
codex-wake pid --require-monitor "$!" -- \
  "The background process exited. Read .codex/events/job.log and continue."
```

On Linux, `pid` wakes record the process start time from `/proc/<pid>/stat`
and the current boot id when available. The daemon fires if the PID disappears
or if the live PID no longer matches that registered process identity.

Create an app-server-targeted wake instead of a tmux-targeted wake:

```bash
codex-wake app after --require-monitor thread_abc 45m -- "Resume this thread through app-server."
codex-wake app after --require-monitor --codex-path "$(command -v codex)" thread_abc 45m -- "Resume this thread through app-server."
codex-wake app at thread_abc "2026-05-19T17:30:00-05:00" -- "Check the release state."
codex-wake app candidates
codex-wake app candidates --cwd "$PWD" --json
codex-wake app candidates --cwd "$PWD" --validate --only-idle --json
codex-wake app status thread_abc
codex-wake app status --resume thread_abc
codex-wake app status --json thread_abc
```

Create an OpenClaw Gateway-targeted wake for a durable OpenClaw session:

```bash
codex-wake openclaw after \
  --require-monitor \
  --agent main \
  --session-key agent:main:slack:channel:c0ahqqcg7j4 \
  --workspace default \
  --channel C0AHQQCG7J4 \
  --thread-ts 1779729958.218239 \
  --openclaw-path "$(command -v openclaw)" \
  45m -- "Resume this OpenClaw session. Inspect the wake record first."
```

OpenClaw Gateway dispatch requires a real `agent:<agent_id>:...` session key.
It rejects placeholder values such as `noop-smoke-test`. Channel fields are
stored as evidence; the session key is the durable target.

Install the OpenClaw plugin when OpenClaw agents should schedule their own
wakes from live session context. Prefer the `codex-wake` helper because it
materializes a public `codex-wake` tag into user state and asks OpenClaw to
install that copy, rather than linking the live repo checkout:

```bash
codex-wake openclaw-plugin install --tag <codex-wake-tag> --prune-linked-path
openclaw gateway restart
openclaw plugins inspect codex-wake --runtime --json
openclaw gateway call tools.catalog --json \
  --params '{"agentId":"main","includePlugins":true}' | rg 'codex_wake_schedule|codex-wake'
```

`--prune-linked-path` is safe for migration from a prior linked development
install: it removes only linked `plugins.load.paths` entries whose manifest id
is `codex-wake`, writes an OpenClaw config backup, and refreshes OpenClaw's
generated plugin registry. If no linked path is present, it leaves the config
unchanged.

For updates, force-refresh the materialized public-tag source and reinstall:

```bash
codex-wake openclaw-plugin update --tag <codex-wake-tag> --prune-linked-path
openclaw gateway restart
```

For local release-candidate validation, build an npm-pack artifact and install
through OpenClaw's package path:

```bash
codex-wake openclaw-plugin pack --output-dir dist/openclaw-plugin
openclaw plugins install --force npm-pack:dist/openclaw-plugin/<tarball>.tgz
openclaw gateway restart
```

Use a linked plugin only for active local plugin development:

```bash
openclaw plugins install --link ./plugins/openclaw-codex-wake
```

Rollback is explicit:

```bash
openclaw plugins uninstall codex-wake
codex-wake openclaw-plugin install --tag <previous-codex-wake-tag>
openclaw gateway restart
```

The plugin registers `codex_wake_schedule`. It writes schema-versioned
`openclaw_gateway` wake JSON directly, captures the current OpenClaw
`agentId`, `sessionKey`, and channel/thread evidence, and rejects missing or
placeholder session keys. By default, channel metadata is stored as evidence
only; explicit Gateway reply override fields are written only when configured.
The plugin requires recent persistent monitor health by default before writing
a wake record. Set `requireMonitor=false` only for an operator-managed
`codex-waked --once` flow.

## Monitor Readiness

Before relying on unattended wake delivery, verify that a monitor owns the
selected wake root:

```bash
codex-wake --wake-root .codex/wake monitor check --json
codex-wake --wake-root .codex/wake doctor --json
```

`monitor_ready=true` means an active repo-scoped service matches the exact
wake root, or recent persistent daemon/supervisor health was observed. A wake
record without monitor readiness may remain pending forever unless an operator
runs `codex-waked --once`.

For single-repo operation, install or repair the repo-scoped service:

```bash
codex-wake --wake-root .codex/wake service install --codex-path "$(command -v codex)"
```

For multi-repo and OpenClaw usage, use the user-scoped supervisor:

```bash
codex-wake supervisor install
codex-wake supervisor enroll --wake-root "$PWD/.codex/wake" --repo-root "$PWD"
codex-wake supervisor status --all
```

If OpenClaw Gateway auth uses environment-variable references, import those
variables into the user systemd manager before relying on supervisor-fired
OpenClaw wakes:

```bash
systemctl --user import-environment OPENCLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_PASSWORD
systemctl --user restart codex-wake-supervisor.service
```

The supervisor reads explicit root registrations from
`~/.config/codex-wake/roots.d/` and writes monitor health under
`~/.local/state/codex-wake/monitors/`. It does not scan arbitrary workspaces.

Run the daemon once:

```bash
codex-waked --once
```

Run the daemon in polling mode:

```bash
codex-waked --interval 5
```

Manage a repo-local user service:

```bash
codex-wake service install
codex-wake service install --codex-path "$(command -v codex)"
codex-wake service status
codex-wake service logs --lines 50
codex-wake service stop
codex-wake service uninstall
```

Run a readiness report:

```bash
codex-wake doctor
codex-wake doctor --json
codex-wake --wake-root .codex/wake product-readiness --json
```

`doctor` prints the same hook ack evidence as `hook check`, including the latest
ack wake id, submitted timestamp, and session id when available. Use
`doctor --json` when automation needs command, tmux, hook, ack, and service
readiness without parsing text output. The report also includes hook source
overlap fields so operators can see when both project and user hook sources are
enabled for `codex-wake-hook`. For app-server wakes fired by a user service,
`doctor` reports `service_app_server_codex_ready`, the resolution source, and
the Codex CLI command the service can use. `service install` writes
`CODEX_WAKE_CODEX_CMD` into the unit when `codex` is resolvable from the
installing shell, and `--codex-path` can be used to persist an explicit path.

`product-readiness --json` is the productization-level report. It normalizes
CLI, hooks, skill installs, repo service, user supervisor, enrolled roots,
monitor health, app-server dispatch readiness, OpenClaw Gateway RPC readiness,
OpenClaw plugin readiness, and tmux availability into `ready`, `warning`,
`manual_only`, or `blocked` outcomes. Gateway auth is reported by variable name
and presence only; secret values are not emitted.

Ack evidence proves that Codex submitted the wake prompt in the target session.
It does not by itself prove that a new turn was visible in the pane the operator
was watching. For tmux dispatches, check `visibility_result` on the wake record:
`visible_prompt_observed` means the wake marker newly appeared in captured pane
scrollback after ack, while `ack_observed_visibility_unproven` means the hook
ack was real but operator-visible display was not proven.

Inspect and manage wakes:

```bash
codex-wake list
codex-wake list --json
codex-wake status
codex-wake status --json
codex-wake show <wake-id>
codex-wake cancel <wake-id>
codex-wake archive <wake-id>
codex-wake archive --all-terminal
codex-wake cleanup --older-than 30d
codex-wake cleanup --older-than 30d --delete
codex-wake cleanup --archive-terminal --json
codex-wake schema
codex-wake schema --json
```

`status --json` emits compact counts by status, predicate, target transport,
and visibility classification plus the earliest pending or firing
`next_attempt_at`.

`app status` is read-only and does not start a turn. By default it asks local
`codex app-server` for `thread/read` status. Use `app status --resume` to load a
resumable rollout-backed thread first, which mirrors the dispatch preflight
without calling `turn/start`. Add `--codex-path` when the app-server check must
use a specific Codex CLI command instead of ambient `PATH`.

`app candidates` is also read-only. It scans local Codex session rollout
metadata under `~/.codex/sessions`, reads only the `session_meta` line from each
rollout file, and prints recent rollout-backed thread ids. Use `--cwd "$PWD"`
to narrow candidates to the current repo, then check a candidate with
`codex-wake app status --resume <thread-id>` before registering a wake.
Use `--validate` to run that resume-backed status check for every listed
candidate without starting turns. Add `--only-idle` to print only candidates
whose resumed status is `idle`. `app candidates --validate --codex-path ...`
uses the same explicit command for those validation checks.

## Runtime State

By default, Codex Wake stores state under the current repo:

```text
.codex/wake/pending/
.codex/wake/firing/
.codex/wake/submitted/
.codex/wake/failed/
.codex/wake/cancelled/
.codex/wake/expired/
.codex/wake/acks/
.codex/wake/locks/
.codex/wake/archive/
```

`.codex/wake/` and `.codex/events/` are ignored by this repo because they are runtime state, not source.

For the full state classification and command-effect contract, see
`docs/runtime-state-lifecycle.md`.

Cleanup is conservative. `codex-wake cleanup` is dry-run by default and only
targets records already under `.codex/wake/archive/`. Add `--delete` to remove
matching archived records, and `--archive-terminal` to archive terminal records
before cleanup evaluation. Active `pending/` and `firing/` records are never
deleted by cleanup. Use `cleanup --json` for structured dry-run previews and
delete reports.

`codex-wake supervisor status --json` reports registered roots with
`health_status` and `remediation` fields so stale or obsolete roots can be
repaired with `supervisor run --once` or removed with `supervisor unenroll`.

Wake records currently use schema version `1`. The compatibility policy is
additive optional fields; inspect it with `codex-wake schema` or read
`docs/dev/wake-record-schema.md`.

## Product Smoke

Use the tracked smoke harness for productization and release gates:

```bash
python scripts/product_smoke.py --json
python scripts/product_smoke.py --public-tag v0.5.0 --json
```

The safe smoke verifies installed CLI version reporting, schema output,
product-readiness output, `codex-waked --once --no-dispatch`, monitor-check
execution, and `supervisor run --once --no-dispatch`. Live Codex app-server and
OpenClaw Gateway smokes are opt-in because they require real sessions and
operator-visible readback. The full matrix is documented in
`docs/product-smoke-matrix.md`.

## Current Limits

- The tmux path is intentionally narrow: the daemon injects only `WAKE_TRIGGER_ID=<id>` plus a short resume instruction.
- The first hook use in a repo may require manual `/hooks` trust review in Codex.
- The daemon polls; it does not install a system service or systemd timer.
- `not_before`, `file_exists`, `file_changed`, and `process_done` are polled predicates.
- `process_done` falls back to PID liveness on platforms where process identity is unavailable.
- App-server targeting is present for stdio dispatch experiments, but unauthenticated WebSocket dispatch is intentionally not implemented.
- `--no-dispatch` smokes prove polling and state movement only; they are not delivery proof.
- Placeholder app-server thread ids or OpenClaw session keys are rejected as product evidence.

## Development

Run the focused test suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

Run the CLIs from source:

```bash
PYTHONPATH=src python -m codex_wake.cli --help
PYTHONPATH=src python -m codex_wake.daemon --once --no-dispatch
```

Create an app-server-targeted wake instead of a tmux-targeted wake:

```bash
PYTHONPATH=src python -m codex_wake.cli app after thread_abc 45m -- "Resume the scheduled task."
```

Design and validation notes live under `docs/dev/`.
