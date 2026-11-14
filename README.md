# Codex Wake

Codex Wake adds durable time/condition triggers, tracked agent-to-agent exchanges,
recovery visibility and visible Byobu tab lifecycle to native Codex. Native Codex owns conversations, ordinary
messages, turns and task status. Use native messaging directly for an immediate
agent exchange; use Wake when a follow-up must survive the initiating turn or
when you explicitly need a tracked exchange.

When a user gives an existing Codex agent token/time limits, Codex Wake0.17.3
provides MCP enrollment and an independent watcher: request checkpoint,
then pause the current native goal and interrupt its exact active turn. Limits
persist across replacement goals until an explicit user reset. Start with the
[existing-session workflow](skills/codex-wake/references/existing-goal-limits.md).
Governor activation and interventions must be explicit to both the operator and
model. In builds with the new governor controls, send **Deactivate governor** in
the selected conversation to disable its scope without another confirmation;
**Reactivate governor** explicitly restores it. Deactivation survives continuation,
delegation and restart, preserves accounting, and resumes nothing. See
[governor controls and offline host access](docs/governor-control.md) for capability
requirements; these source changes do not upgrade an installed runtime.

Each new conversation needs its own approved host grant; reusing a tab or CWD
does not transfer a previous conversation's resource authority.
Host setup and qualified accounting are required; polling and publication make
token stops sampled, with unknown maximum overshoot. Installation alone does not enroll a session or provide an OS process-termination
guarantee.

An initial accounting scan timeout refuses enrollment without persisting a stop
latch. Once enrolled, accounting loss retains the normal bounded winddown and
stop behavior; retrying enrollment never clears an established stop.

For memory, swap, CPU and task controls, use separate
[dedicated executor containment](docs/agents/strict-objectives.md). Its ordinary
caller first-launch MCP bootstrap remains a separate documented limitation.

The package provides:

- `native after|at|file` for an exact thread, with expiry and explicit same-thread resume.
- `native reconcile` for uncertain submission and `native migrate` for earlier candidate records.
- `sessions list|show|resolve|current|watch|open|close` for discovery and visible tab lifecycle.
- `sessions configuration|spawn|refresh|handoff` for approved worker tasks, resource reloads and fresh-context continuation.
- Durable records, installed polling, registered-root supervision, cancellation and archival.
- Tracked requests and correlated replies, work claims, completion receipts and generation-safe recovery.
- Optional `codex-wake-mcp`: 27 tools for existing-session resource limits, wake controls, session discovery, host-approved spawn, refresh and handoff, and authorized agent exchanges.
- Explicit legacy tmux and app-server delivery, advanced signals and tracked mailboxes.

Native queue acceptance is separate from execution and acknowledgment. Busy or
unavailable threads hold until expiry; ambiguous submissions are reconciled and
never blindly replayed or silently sent through another transport.

See [migration and capabilities](docs/dev/native-workflow-migration.md) for the
qualified support boundary and rollback procedure.

## Agent-to-agent communication

Use Wake when a request needs a durable ID, an exclusive work claim, a correlated
reply, or a follow-up after the sender's turn ends. The accepted A2A workflow
includes unattended native request/reply, worker restart, explicit same-saved-thread
reopening, and recovery that preserves uncertain work without replay.

Start with the [agent-to-agent guide](docs/agent-to-agent.md): operator setup,
human tab addressing, CLI and MCP request/reply, receipt meanings and limitations.
Agents can discover the workflow through the bundled `$codex-wake` skill.
The [MCP setup and tool reference](docs/a2a-mcp.md) exposes the same authorized
mailbox operations; installing the server does not enroll threads or start workers.

## Requirements

- Python 3.11+
- Official Codex 0.162.1 is the native client version qualified by Plan0127.
- `tmux`/Byobu for visible tab lifecycle and legacy pane delivery.
- Hook support for legacy tmux acknowledgment; native queue delivery needs no hook.
- `uv` for the recommended user-scoped install path

## Install

From a checked-out repo:

```bash
bash scripts/install.sh
```

The supported installer also installs and activates Bash/Zsh completion. Use
`--no-completion` to opt out. Plain `uv tool install` or `pip install` remains
supported for package installation; follow it with `codex-wake completion install`
for shell setup. See [completion installation](docs/agents/shell-completion.md).

After the first release tag exists, a fresh machine can install from GitHub:

```bash
bash scripts/install.sh --source git+https://github.com/CochranResearchGroup/codex-wake.git@v0.15.1
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
bash scripts/install.sh --source "git+https://github.com/CochranResearchGroup/codex-wake.git@$tag"

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

## CLI output

Commands show readable tables and details by default. Add `--json` to the leaf
command for scripts, for example `codex-wake accounts list --json`. See
[CLI output](docs/agents/cli-output.md) for compatibility and protocol exceptions.

## Accounts and native daemons

Use Wake to create isolated accounts, explain shared configuration, manage exact
account daemon instances, and import completed saved conversations into another
account. See the [account and daemon workflow](docs/agents/accounts-and-daemons.md)
for public commands, target pins, supported rollback and transfer limits.
The [generated command reference](docs/agents/command-reference.md) and
[coverage report](docs/agents/command-coverage.json) describe the first migrated
CLI/API/MCP slice and its explicit exceptions.

The [everyday shortcuts](docs/agents/account-shortcuts.md) add `open ACCOUNT`,
`resume ACCOUNT`, recent browsing and frozen recent-conversation copies.

## Tab formatting

Manage named terminal sessions, frozen tab relocation and opt-in routing with the
[terminal session workflow](docs/agents/terminal-sessions.md).

Use `codex-wake tabs format enable --workspace WORKSPACE` for type/activity badges
and state-sensitive highlights on owned Byobu/tmux and Windows psmux tabs.
`tabs format rollback --workspace WORKSPACE` restores original settings in one
command; `tabs format reenable --workspace WORKSPACE` reapplies saved preferences.
See the [formatting workflow](docs/agents/tab-formatting.md) for automatic updates,
manual-style holds, rendering fallbacks and CLI/API/MCP controls.

## Local WSL session control

Use the [local controller workflow](docs/agents/local-session-control.md) for WSL,
native PowerShell, REST and local MCP clients with automatic same-user setup.
The command and operation owners share durable prompt delivery, four output
modes, qualified slash actions, exact TUI health and voluntary self-limits.

## Native Usage

Choose the exact thread UUID returned by `sessions resolve` or `sessions open`.
Tab names and numbers are discovery conveniences; durable work targets a thread.
For session selectors use `thread:UUID`, `19:wake`, `tab:wake`, `pane:%N` or
`window:@N` (decimal IDs from discovery). Qualify the tmux session when names/numbers are ambiguous. Native
scheduling and `open --resume` take the UUID without the `thread:` prefix.

```bash
codex-wake sessions resolve '19:wake' --json
codex-wake sessions open --new --cwd /absolute/project --name worker --tmux-session SESSION
codex-wake sessions open --resume THREAD_UUID --name worker --tmux-session SESSION
codex-wake native after THREAD_UUID 45m -- "Inspect the migration log and continue."
codex-wake native file --ttl 2h THREAD_UUID /absolute/project/.codex/events/tests.done -- "Read the test result."
codex-wake native at --resume-missing THREAD_UUID "2026-10-12T17:30:00-05:00" -- "Inspect release readiness."
codex-wake native reconcile WAKE_ID
codex-wake sessions close thread:THREAD_UUID
```

### Choose an agent lifecycle operation

| You want to… | Human CLI | Agent MCP tool |
|---|---|---|
| Inspect approved settings and remaining resources | `sessions configuration` | `wake_sessions_configuration` |
| Give a separate worker a bounded task | `sessions spawn` | `wake_sessions_spawn` |
| Reload selected skills or MCP resources in the same conversation | `sessions refresh` | `wake_sessions_refresh` |
| Continue an objective in a fresh conversation | `sessions handoff` | `wake_sessions_handoff` |

Start with the [lifecycle quickstart](docs/agent-lifecycle.md#quickstart).
Pre-release: [strict objective execution controls and limits](docs/agents/strict-objectives.md).
For a user-supplied resource budget, read the packaged
[resource-limit workflow](skills/codex-wake/references/resource-limits.md).
An operator configures the approved host profile and caller access first.
Refresh and handoff require a checkpoint; handoff supports a new tab or the same
pane. Receipts distinguish readiness, task admission and completed work.
Fresh context preserves the objective's remaining budget and original deadline.

Native scheduling retains the original request when trusted time is unavailable.
Use a stable key for each automated follow-up so retries return the same wake:

```bash
codex-wake native after --idempotency-key monitor-run-42-next --json THREAD_UUID 3h -- "Inspect the monitoring result."
codex-wake status --json
codex-wake show WAKE_ID --json
```

An active schema6-capable worker on that root retries qualification on its normal
poll interval. Registration does not start or upgrade a worker. Receipts report
`requires_worker_schema=6`; older workers hold the request. `status` exposes
pending-time and missed-deadline alerts. A successful registration means the
intent persisted; queue acceptance and completed execution have separate receipts.

For relative delays, the configured authenticated StableTime service can supply
host-counter evidence even while UTC is unavailable. Same-epoch elapsed bounds
preserve not-before and expiry; this evidence is never described as UTC. Default
interval tolerance is 2% of the delay, bounded to 1s–5m; use `--time-tolerance 1s`
for a stricter request. Contract1.0 UTC qualification remains below100ms. Contract2.0 accepts authenticated finite bounds under request tolerance; best-effort UTC never authorizes dispatch. Absolute
`at` deadlines and optional `--stop-at ISO_TIMESTAMP` require qualified UTC.

If no clock is admissible at registration, the original relative origin and
expiry cannot be established. The request stays retained with an actionable
alert; recovery does not restart its delay or extend its expiry. Reconcile that
original request before choosing a replacement with a new intent key.
Lost counter continuity holds the original anchor; it is
never reset silently. A previously captured UTC anchor can recover its original
deadline. Reuse a key only for the identical request; changed content conflicts,
and terminal or archived requests retain their identity. Without a key, only
identical active retained requests coalesce. See
[the schema contract](docs/dev/wake-record-schema.md#schema6-native-scheduling-intent-and-time-recovery)
for compatibility, clock continuity and cleanup behavior.

New versus resume is explicit. An existing exact attachment is reused unless
`--extra-attachment` is requested. Ordinary close refuses active, unknown or
pending work. `--force` preserves conversations and durable work and reports
what is affected; cancellation and archival are separate commands. Supply
`--bus-root` for custom mailbox stores when checking close safety.

A running Wake0.9 scheduler must own the chosen root for native execution. Native
registration does not start a scheduler. End the initiating turn after arming
its follow-up; a foreground wait is not a suspension proof.

Agents should follow the [A2A response standard](skills/codex-wake/references/a2a-responses.md):
questions/work requests receive a delivered sender reply; notices/final results
normally end locally. TUI output alone does not deliver a reply. Third-party
handoffs require explicit authority and a separate correlated send.

## Legacy Compatibility Usage

The following basic commands require an explicit `--legacy-tmux` choice.
Existing persisted records keep their transport. Advanced signal interfaces
remain supported while their native replacements are unqualified.

Agents can use the bundled `$codex-wake` skill for workflow guidance and wake
cycle examples. The skill lives at `skills/codex-wake/` in this repo and can be
installed into user skill roots when agents need to schedule their own wake
cycles.

Wake after a duration:

```bash
codex-wake after --legacy-tmux --require-monitor 45m -- "Continue the migration. First inspect .codex/events/migration.log."
```

Wake at an absolute timestamp:

```bash
codex-wake at --legacy-tmux --require-monitor "2026-05-18T17:30:00-05:00" -- "Check whether the release branch is ready."
```

Wake when a marker file exists:

```bash
mkdir -p .codex/events
(
  pytest -q > .codex/events/pytest.log 2>&1
  touch .codex/events/pytest.done
) &
codex-wake file --legacy-tmux --require-monitor .codex/events/pytest.done -- \
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

For a restart-correct process-exit wake, use the supported `process-exit`
recipe. The process must already be alive, belong to the current effective UID,
and remain the exact `(boot_id, pid, start_time_ticks, owner_uid)` identity:

```bash
codex-wake process-exit --require-monitor --idempotency-key build-process \
  "$PID" -- "The process exited. Read .codex/events/build.log and continue."
```

This observes only fixed `/proc` identity/state fields. It does not promise an
exit code or exact exit time, does not kill or signal the process, and treats a
PID reuse, boot change, foreign owner, missing baseline, or uncertain read as
unavailable/invalid rather than as an exit. A fresh daemon rechecks the same
durable identity before publishing one occurrence.

For a configured user-systemd unit transition, first create the exact,
non-wildcard allowlist entry, then arm a state transition:

```bash
codex-wake systemd-unit source configure --source build-state \
  --unit build.service --target-state active --target-state failed \
  --poll-timeout 5 --enabled
codex-wake systemd-unit becomes --require-monitor --source build-state \
  --state active --idempotency-key build-active -- \
  "build.service became active; inspect the recorded build evidence."
```

The observer uses only the current user's session manager and a fixed,
read-only call plan (`GetUnit`, safe `Id`/`ActiveState`, and manager-owner
rechecks). Missing units, reconnects, manager-generation changes, and
observation gaps are unavailable/rebaselined; an already matching baseline is
not a transition. Codex Wake cannot start, stop, restart, reload, enable,
disable, mask, create units, select the system manager, or issue arbitrary
D-Bus calls. Configure and arm from the same user account that owns the unit.

Create an app-server-targeted wake instead of a tmux-targeted wake:

```bash
codex-wake app after --require-monitor thread_abc 45m -- "Resume this thread through app-server."
codex-wake app after --require-monitor --codex-path "$(command -v codex)" thread_abc 45m -- "Resume this thread through app-server."
codex-wake app after --require-monitor --retry-active-writer thread_abc 45m -- "Resume when this thread is idle."
codex-wake app at thread_abc "2026-05-19T17:30:00-05:00" -- "Check the release state."
codex-wake app candidates
codex-wake app candidates --cwd "$PWD" --json
codex-wake app candidates --cwd "$PWD" --validate --only-idle --json
codex-wake app status thread_abc
codex-wake app status --resume thread_abc
codex-wake app status --json thread_abc
```

App-server dispatch fails visibly by default if preflight finds that the
target thread already has an active writer. Add `--retry-active-writer` only
when delayed delivery remains useful; the wake then retries with bounded
backoff under the record's existing three-attempt limit. In either mode,
Codex Wake does not call `turn/start` while the thread is active.

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
codex-wake --wake-root .codex/wake service install --codex-path "$HOME/.local/bin/codex"
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
codex-wake service install --codex-path "$HOME/.local/bin/codex"
codex-wake service status
codex-wake service logs --lines 50
codex-wake service stop
codex-wake service uninstall
```

App-server wake dispatch requires a running persistent Codex daemon with the
supported Unix WebSocket control transport. Check daemon presence with
`codex app-server daemon version`; executable resolution alone does not prove
this readiness. The discovered socket must be absolute and owned by the current user in a
private directory owned by that user. A current-user-owned leaf alias under a
private owned directory is supported only when its absolute target is a canonical
socket in a separate private owned directory. Ancestor aliases, alias chains,
foreign ownership, dangling targets and nonprivate containing directories fail
closed. The WebSocket client connects to the verified canonical socket path.
Codex Wake only discovers and connects to this existing daemon. It never starts,
replaces or stops it. Missing or unsupported daemon readiness fails before a new
turn starts; unattended app-server delivery has no standalone-server fallback.

The dispatcher closes only its owned WebSocket connection after `turn/start` returns.
The persistent daemon owns the turn beyond that connection, including long
turns. Absolute RPC deadlines bound writes and protocol response waits, not agent work.
The maintained WebSocket client caps incoming messages at32MiB and closes within
one second. The raw `codex app-server proxy` copies bytes and does not translate
newline JSON into the WebSocket protocol; it is not used by dispatch.
`submitted` and `ack_observed` prove turn acceptance; verify the exact thread and
turn transcript separately for completion. Do not automatically retry an original
wake whose external outcome is uncertain.

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
installing shell, and `--codex-path` can be used to persist an explicit stable
path. Persisted Codex and OpenClaw commands must be regular executable files.
Paths inside version-managed Node installations (for example
`~/.nvm/versions/node/...`) are rejected because a Node upgrade can invalidate
them when supplied explicitly and are not auto-persisted from `PATH`. Point the
option at a stable wrapper or symlink such as
`~/.local/bin/codex` or `~/.local/bin/openclaw`; the stable spelling is kept
instead of being dereferenced to its current versioned target. Detection follows
the versioned install layout, so relocated NVM, FNM, asdf, Volta, and mise data
roots are covered without rejecting ordinary stable custom paths. Lifecycle
commands such as status, logs, stop, uninstall, enroll, and unenroll do not
require the original launch executable to remain installed.

`product-readiness --json` is the productization-level report. It normalizes
CLI, hooks, skill installs, repo service, user supervisor, enrolled roots,
monitor health, signal capability and per-source health, app-server dispatch readiness, OpenClaw Gateway RPC readiness,
OpenClaw plugin readiness, and tmux availability into `ready`, `not_needed`,
`warning`, `manual_only`, or `blocked` outcomes. An inactive repo-scoped service
is `not_needed`, rather than a warning, when the active user supervisor is
enrolled for the same wake root and monitor health is ready. Gateway auth is
reported by variable name and presence only; secret values are not emitted.
Signal source readiness is a separate fact from target dispatch readiness. A
healthy filesystem or GitHub source does not imply that tmux, app-server, or
OpenClaw dispatch is ready.

Export deterministic, bounded signal support evidence without prompts,
credentials, raw provider payloads, or file contents:

```bash
codex-wake --wake-root .codex/wake support export \
  --output signal-support.json --max-wakes 50 --max-bytes 262144 --json
```

Ack evidence proves that Codex submitted the wake prompt in the target session.
It does not by itself prove that a new turn was visible in the pane the operator
was watching. For tmux dispatches, check `visibility_result` on the wake record:
`visible_prompt_observed` means the wake marker newly appeared in captured pane
scrollback after ack, while `ack_observed_visibility_unproven` means the hook
ack was real but operator-visible display was not proven.

Before a tmux paste, Codex Wake inspects only a bounded active pane region for
recognizable approval, confirmation, running-tool, or foreign-shell surfaces.
An unsafe preflight records privacy-safe rule and region metadata, requeues
under its own three-deferral bound, and does not consume a delivery attempt.
Raw pane text and matching lines are never stored.

Inspect and manage wakes. For a persistent emergency hold use
`codex-wake pause --all-roots`; inspect with `pause-status`, optionally cancel
eligible wakes with `cancel --all --all-roots`, and separately request owned-turn
interruption with `interrupt --all-roots`. Only explicit `resume` releases the
hold. See [wake emergency controls](docs/wake-emergency-controls.md) for scope,
worker upgrade requirements and agent grants.


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
python scripts/product_smoke.py --public-tag v0.6.0 --json
```

The safe smoke verifies installed CLI version reporting, schema output,
product-readiness output, `codex-waked --once --no-dispatch`, monitor-check
execution, a provider-free filesystem signal lifecycle, an installed
fixture-backed GitHub lifecycle, GitHub source readiness dimensions, support
export, retirement, and
`supervisor run --once --no-dispatch`. Pass `--upgrade-wheel dist/*.whl` to
force-install a candidate wheel and restart the daemon between signal
registration and observation; for upgrade evidence, start the named binaries
from a distinct baseline install and record both wheel hashes. Live Codex app-server and
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
- GitHub readiness is read-only and reports configuration, credential capability,
  source health, checkpoint, replay lag, terminal failure, disabled, and
  unsupported states. It never reads or prints credential values or provider
  payloads.

GitHub CI sources are managed with the supported commands
`codex-wake github-ci source configure`, `list`, and `show`; arm a completion
wake with `codex-wake github-ci completed`. The default credential reference
is `GH_CLI`, resolved at read time with `gh auth token --hostname github.com`.
The same default applies to `github-webhook binding configure`. Run `gh auth
login` as the same user that runs the service, and explicitly configure each
repository, workflow, ref, conclusion, and webhook binding. Access to a
repository through `gh` does not configure it automatically. Provider writes
still require explicit reconciliation or cleanup commands. The webhook HMAC
secret remains separate.

For a limited token or headless service, pass `--credential-ref NAME` to source
and binding configuration. Configure the daemon service with
`--github-credential-file PATH` to render an owner-only systemd
`EnvironmentFile=` containing the referenced credential environment variables.
The `GH_CLI` backend uses the same-user `gh` credential store; it is a
convenience, not credential isolation. Service installations requiring isolation
must use an explicit limited token and restrict access to the user's `gh`
store. The resolver first uses the service's `PATH`, then checks standard
Linuxbrew and Homebrew executable locations when `gh` is absent from that
`PATH`. Check the installed unit environment and executable availability before
starting an unattended `GH_CLI` source. Existing explicit references remain
compatible.
The poller uses positive-only evidence: `GITHUB_COVERAGE_UNPROVEN` is an
expected coverage warning, not proof of complete history. No public listener or
live GitHub delivery is claimed by the provider-free smoke.

### Generic HTTP/JSON completion wakes

Use `http-json` for services that already expose a stable JSON job-status
resource. The service does not need a Codex Wake plugin or callback. Configure
the fixed URL and standard JSON Pointers, then arm a normal wake:

```bash
codex-wake http-json source configure \
  --source auracall-response \
  --url http://127.0.0.1:8080/v1/runs/resp_123/status \
  --state-pointer /status \
  --event-id-pointer /id \
  --completed-at-pointer /completedAt \
  --selector /kind=response \
  --terminal-value succeeded \
  --terminal-value failed \
  --terminal-value cancelled \
  --enabled

codex-wake http-json source check auracall-response --json
codex-wake http-json completed --source auracall-response --require-monitor
```

The same commands work with any fixed HTTP(S) endpoint returning a JSON object.
Selectors use RFC 6901 JSON Pointer syntax and exact string equality. The
reader performs only `GET`, follows no redirects, caps time and response bytes,
pins the resolved address for the connection, and stores only the selected
event ID and terminal state. Loopback is allowed by default. Public addresses
require `--allow-non-loopback`; private, link-local, multicast, wildcard, and
mixed DNS answers remain blocked. URLs containing credentials, queries, or
fragments are rejected.

For bearer authentication, configure an uppercase environment-variable name
with `--credential-ref NAME`. The value is resolved only at request time and is
not included in configuration readback, readiness, wake records, or support
exports. Plain HTTP credentials are allowed only for a loopback destination.

Use `http-json source list|show|check|remove` for local lifecycle operations.
`check` performs one bounded read without creating a wake. A successful HTTP
read is source evidence only; monitor readiness, submission acknowledgement,
and visible delivery remain separate states. Removal fails while the source has
pending or firing wakes; cancel those wakes first.

## Development

Run the unit test suite:

```bash
cw_test_root=$(mktemp -d)
XDG_CONFIG_HOME="$cw_test_root/config" XDG_STATE_HOME="$cw_test_root/state" \
  CODEX_WAKE_STABLE_TIME_CONFIG='' PYTHONPATH=src \
  python -m unittest discover -s tests -p 'test_*.py'
```

The unit-test command isolates Wake registry/mailbox discovery from installed user
state and disables automatic use of a user-installed StableTime client
configuration so host services do not override fixture time or pending-work inventory. Keep the configured trusted
clock enabled for opt-in installed/native qualification scripts.

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
For repository maintenance, see [source-bound local validation and receipt summaries](docs/agents/source-bound-validation.md) and [guarded Git worktree cleanup](docs/agents/worktree-cleanup.md).

### Live session discovery

Use `codex-wake sessions list --json` for live daemon threads and Codex TUI
candidates. Address Byobu tabs with `sessions resolve 17:wake`, literal names
with `tab:NAME`, split panes with `17.1`, or exact identities with
`thread:FULL_ID`. Duplicate names require qualification. `sessions show REF`
includes binding evidence; `sessions current` validates the invoking thread
claim and rejects an inherited conflicting pane.

`sessions watch REF --duration 5m --json` pins the initial thread and emits
metadata changes as JSONL. Reads use the existing daemon locator and never
start/resume/subscribe to a thread. Missing sources produce partial inventory
and exit 5; they never prove absence or uniqueness. Metadata matching is not
a runtime attestation or delivery permission. `--require-attested` currently
reports unsupported. Override existing endpoints with `--app-server unix://PATH`
and `--tmux-socket PATH`; use `--tmux-session` to qualify multiple sessions.


### Explicit local mailboxes

Initialize a private bus with `codex-wake a2a configure --bus-root PATH`.
The JSON result gives an operator capability file; keep that file private.
Enroll a root and a live thread with `a2a enroll ROOT --thread 17:wake
--bus-root PATH --operator-capability FILE`. Its result gives a private actor
capability. Separate roots require explicit `--allow-cross-root` at configuration.
Existing identity-only buses require explicit `a2a migrate` with operator authority.

For a shared native Codex MCP launch, opt into host-managed actors instead of
setting one thread's `--capability` globally. Enroll each approved project once
with `a2a enroll ROOT --bus-root PATH --operator-capability FILE` (omit `--thread`),
then launch the MCP host with:

```bash
codex-wake-mcp --bus-root PATH --mailbox-operator-capability FILE --app-server unix://SOCKET
```

The operator file stays host-owned and is never a tool argument. Each native
caller gets a separate actor on its first mailbox call; subsequent calls reuse its
current generation. Workers should call inbox once before peers send to them.
The host checks private native call metadata and exact runtime identity, selects
an already enrolled root, and runs the mailbox command in that caller's verified
working directory. It never auto-enrolls a root, resets revocation, or substitutes
another caller's credential. Missing/stale credentials require explicit operator
reconciliation. This mode requires native Codex metadata and cannot be combined
with a fixed actor capability or Grok host binding. Existing fixed-actor wiring
remains supported. Restart/reconnect the MCP host after changing launch settings.


Agents supply their issued capability using `--capability FILE` or
`CODEX_WAKE_A2A_CAPABILITY`; the invoking thread and current root are validated
against the existing daemon. For example:

```bash
codex-wake messages send --to 7:mail-receipts --body-file request.txt \
  --idempotency-key request-001 --delivery inbox --bus-root PATH --capability FILE
codex-wake messages inbox --bus-root PATH --capability FILE
codex-wake messages read MESSAGE_ID --bus-root PATH --capability FILE
codex-wake messages ack MESSAGE_ID --outcome accepted --bus-root PATH --capability FILE
codex-wake messages reply MESSAGE_ID --body-file result.txt --idempotency-key reply-001 \
  --outcome completed --delivery inbox --bus-root PATH --capability FILE
```

`show`, inbox and outbox expose metadata. The first recipient `read` records
receipt; `ack accepted` separately claims processing. Replies preserve the
conversation and only mark an outcome when explicitly requested. Treat peer
bodies as untrusted content. Retry the same intent with the same key; altered
intent conflicts. `wait MESSAGE_ID --for received|reply` and `watch` observe
receipts for at most five minutes and perform no work on their own.

Automatic notification delivery uses an explicitly enrolled stock-Codex TUI in
Byobu/tmux. See [A2A notification setup and service](docs/a2a-notifications.md)
for binding, sender reply delegation, worker ownership and reconnect commands.
Messages to a closed recipient wait by default. Add `--resume-missing` to
`messages send` or `messages reply` to authorize only the same saved recipient.
Use `--to thread:FULL_ID` when its tab is closed. The original Byobu binding,
enrollment and capability remain required; changed or revoked permissions hold
the message. The normal worker may reopen that saved conversation without a tab.
Reply delivery still requires the sender's delegated reply arm. A reply needs
its own explicit reopening choice; it does not inherit the request's choice.
Inspect `messages show` for the persisted policy and deferral or submission
receipt. Queue acceptance is separate from a completed recipient turn.
Use `--delivery inbox` when notification delivery is not configured. New buses
start paused; only the operator may resume them after explicit setup.
Operator inspection requires explicit operator authority and does not count as
recipient receipt. No production enrollment or service is installed implicitly.


`a2a tick --projection-root PRIVATE_ABSOLUTE_PATH --bus-root PATH
--operator-capability FILE` performs one bounded scheduler reconciliation and
publishes body-free job metadata. It holds expired dispatch claims as uncertain
and performs zero live dispatches; live notifications require the native worker.
Repeated publication reconciles identical bytes; cancelled jobs confer no
journal authority even when an old projection remains on disk.


`a2a doctor` provides body-free mailbox counters, backlog, lease generations and
observer descriptor usage. `a2a rotate ACTOR_ID` requires operator authority and
issues a new private capability, invalidating old credentials. Existing work
claims remain recorded and require reconciliation across capability generations.

`a2a retention` previews eligible bodies and their pins. Apply only the exact
returned fingerprint with `--apply-fingerprint VALUE`; eligibility is rechecked
atomically. Bodies require thirty days since terminal resolution and no pending
signal, uncertain attempt, open claim or active conversation. Metadata/dedup
history remains intact. Current receipt source integration conservatively holds
unprojected pins; pruning removes logical rows without erasing backups or pages.
All operator commands require `--bus-root PATH --operator-capability FILE`.

Mailbox schema 2 requires explicit `a2a migrate`; older readers refuse it rather
than attempting a downgrade. `a2a compact` previews eligible terminal envelopes
and, after ninety days from creation, expired tombstones. Apply the returned
fingerprint with `--apply-fingerprint VALUE`. The same thirty-day terminal and
uncertainty/projection pins apply; retained replies also pin their ancestors.
Compaction preserves exact identity, digest, correlation and receipts through the
ninety-day horizon. New replies require a retained full envelope. After retirement,
a hashed key marker refuses reuse with `idempotency_horizon`; use an explicitly new
key for a new intent. Refusal markers count toward the message capacity and are
reported by `a2a doctor`. Immutable operator events remain attributable.

Logical pruning does not recover disk pages. For explicit physical recovery,
pause the bus and run `a2a reclaim-space --apply`; it records request/completion
receipts and file-byte measurements. Busy readers or an interrupted operation
require reconciliation of the returned receipt. This operation preserves logical
mail data and does not activate backups or qualify binary downgrade.

For an already-armed receipt wake, the daemon can restore an explicitly
delegated observer with `--a2a-receipt-authority FILE`. The operator prepares
this private mode-0600 JSON file from independently verified bus/actor/message
authority; paths and capabilities are never discovered from the wake arm.
All paths must be absolute and free of symlinks. The file pins one wake root,
contains no raw secrets, and permits at most 100 grants / 64 KiB:

```json
{
  "schema_version": 1,
  "wake_root": "/absolute/wake/root",
  "grants": [{
    "source_instance": "mailbox-<32 hex digits>",
    "bus_root": "/absolute/private/bus",
    "bus_id": "local",
    "operator_capability": "/absolute/private/operator-capability.json",
    "actor": {
      "bus_id": "local",
      "namespace": "<verified runtime namespace>",
      "thread_id": "<exact enrolled thread>",
      "root": "/absolute/enrolled/root",
      "generation": 1,
      "actor_id": "<exact enrolled actor>"
    },
    "message_id": "<exact existing message>"
  }]
}
```

Replace placeholders with the exact existing identities and receipt source
instance. The operator capability delegates inspection; the observer's pinned
actor value does not authenticate the daemon as that actor. Mailbox transactions
use SQLite `mode=ro` and cannot send, read-as-recipient, acknowledge, or reply. Removing
the grant or revoking/rotating its actor fences even an already-created runner.
Missing, invalid, stale or cross-root authority keeps the receipt wake pending.

```bash
codex-waked --once --no-dispatch --wake-root /absolute/wake/root \
  --a2a-receipt-authority /absolute/private/receipt-authority.json
```

This qualifies configured replay and firing after process restart. The receipt
arming CLI and actual long agent suspension remain unfinished; receipt firing
does not establish delivery. Generic A2A receipt dispatch remains held as
unqualified. No bus, enrollment, actor, or service is created by this option.

Arm an exact receipt from an existing private observer grant with:

```bash
codex-wake a2a arm-receipt --wake-root /absolute/wake \
  --receipt-authority /absolute/receipt-authority.json \
  --source-instance mailbox-EXACT_INSTANCE_FROM_GRANT \
  --condition reply --idempotency-key request-42-reply \
  --expires-at 2026-10-04T18:00:00Z \
  --prompt 'Inspect the exact receipt evidence.' \
  --tmux-pane '%17' --tmux-socket /absolute/tmux/socket
```

The selected wake root must have an active managed reader advertisement. The
command uses the existing grant for read-only mailbox inspection and writes
Wake state; it does not create grants or authenticate as the pinned actor.
Reuse all arguments, including the absolute expiry, for an idempotent retry;
changed intent under the same key is refused. The resume cwd is the actor's
explicitly enrolled root. The command reports `dispatch_qualified: false`.
Generic receipt dispatch remains held; a pending arm or no-dispatch firing does
not establish actual agent suspension or delivery. An expired timestamp creates
an arm that the reader can retire as expired. Use `codex-waked --once
--no-dispatch --wake-root ... --a2a-receipt-authority ...` for bounded observation.

After exact receipt occurrences have been durably mirrored, an operator may
reconcile their mailbox projection rows:

```bash
codex-wake a2a ack-projections --bus-root /absolute/bus \
  --operator-capability /absolute/bus/operator.json \
  --wake-root /absolute/wake \
  --receipt-authority /absolute/receipt-authority.json \
  --source-instance mailbox-EXACT_INSTANCE_FROM_GRANT --limit 100
```

The operator capability grants mailbox write authority independently of the
read-only observer grant. The command checks the exact bus, actor generation,
conversation and every immutable committed occurrence against the mailbox.
Missing or compacted occurrences keep their retention pins; a source checkpoint
or a fired wake alone is insufficient. It reports acknowledged/scanned counts
and an attributable operator receipt. Repeating acknowledgement does not change
previously published rows. An uncertain commit returns `reconciliation_required`
and a receipt pointer; inspect that receipt before retrying. This clears only
projection pins: body pruning still requires the existing retention preview/apply
guard, and active claims/conversations retain their other pins. Observers cannot
write or prune. No automatic body removal or physical secure erasure is implied.

### Versioned mailbox backup preparation

Pause the bus, then use `codex-wake a2a backup --bus-root /private/bus
--operator-capability /private/operator.json --snapshot /private/new-snapshot`
to create a private, versioned SQLite online snapshot. Its parent must already
be owner-only (0700) on a qualified local filesystem; the snapshot directory must
be new and outside the bus root. The copy includes committed WAL contents,
message bodies, token digests, receipts, actor generations and unresolved attempts.
It does not export capability secret files. Files are0600; protect the snapshot
as private bus data. Copy/verification have ten-second and one-GiB bounds.

`a2a verify-backup` takes the same arguments and reads the snapshot without
activation. It checks the manifest commitment, schema, integrity, foreign keys,
original canonical identity, pause and request provenance, and independently
supplied current operator authority. Verification currently requires the original
readable bus; it is preparation evidence, not recovery of a corrupted source.
An older snapshot may contain revoked actor authority or omit later outcomes.
`activation_qualified` is always false. No root rebinding, downgrade, replacement,
resume or notification replay occurs. Copied-root writer refusal remains active.

A failed copy or completion audit returns `backup_incomplete` and the committed
request receipt pointer. Keep the directory and receipt for reconciliation;
partial artifacts are refused and repeated creation never overwrites an existing
snapshot. A verified snapshot can exist even if completion audit failed.

`a2a restore-backup --apply` uses the same bus/operator/snapshot arguments.
It accepts only a paused, readable original bus whose complete non-audit
canonical state still equals the verified snapshot. Actor revocation/rotation,
new receipts/messages, clock/state changes or other canonical changes refuse
restoration. Later audit events are preserved. A cooperative exclusive lifecycle
lock fences upgraded BusStore connections (one-second wait); SQLite online backup
commits into the existing canonical inode. The bus stays paused and notification
intent is preserved. Copy/verification are bounded to ten seconds and each
source/stage to one GiB. Private stage files are retained as operator evidence.

Stop old binaries and raw SQLite writers independently before this maintenance;
they do not participate in the connection lock. This command qualifies only
state-equivalent same-root activation, not corrupt-source recovery or arbitrary
rollback to older authority/outcomes. `restore_incomplete` preserves its request
receipt and stage for explicit inspection before retry; it never resumes or
replays notifications automatically.

### Damaged-source recovery under a persistent hold

Use `a2a recover-backup --apply --accept-unbacked-state-hold` only with the
original `--bus-root`, independently supplied `--operator-capability`, selected
`--snapshot`, and its reviewed `--expected-database-sha256`. This explicitly
acknowledges that newer state may be absent from the backup. Recovery preserves
the old main/WAL/SHM files in an owner-only quarantine and installs the reviewed
image at the original root under fresh operator authority. The result returns
private capability and completion-receipt paths; secret contents are never
printed. Old actor IDs/capabilities/operator secret and leases are fenced.

Recovered bus schema2 refuses prior readers. A private authority anchor survives
future journal damage and prevents revoked operators starting another recovery.
Fresh backups record the actual bus schema and current operator authority; older
snapshots do not grant a revoked key new recovery permission. Quarantine preserves
all source artifacts and known snapshot message IDs, bodies, receipts and unknown
notification intent. It does not prove that newer missing outcomes were recovered.

The recovered bus stays paused with `recovery_hold=true`. Participant operations,
scheduler acquisition and resume are refused. This packet provides no hold release
or automatic notification replay; gap reconciliation is a separate required step.
Stop old binaries/raw SQLite writers independently; the lifecycle lock covers
upgraded clients only. Each file is bounded to one GiB and image verification/copy
to ten seconds; original file commitments are checked before and after quarantine.

If recovery is interrupted, its private intent marker blocks normal connections
and returns `recovery_incomplete` with an attributable receipt pointer. Run
`a2a reconcile-recovery --apply` with the original approval capability and the
same reviewed `--expected-database-sha256` to finish that exact transition.
Changed artifacts, malformed intent, conflicts or partial receipts stay held for
inspection. Reconciliation never discards evidence, clears the gap hold, starts
a different recovery, or silently overwrites another canonical image.

### Inspect external time on WSL

Run `codex-wake time inspect` to collect a bounded network-time report without
changing the clock or mailbox. `codex-wake time inspect --offline` shows source
admission policy without network access. Reports identify the accepted interval,
its host-counter instant, and each source's exclusion reason. Windows PowerShell
interop is required; unavailable acquisition returns uncertainty. Network rounds
are limited to one per 64 seconds across processes, with a two-minute bounded
cache. Cloudflare/NIST/Alastyr observations are explicitly unauthenticated; Netnod/PTB
remain disabled pending time-scale qualification. This inspection command does
not activate deadline effects. See Plan0123 qualification for policy and limits.

### Opt-in network time (0.8.0)

Opt-in `after --network-time` / `at --network-time` wakes use bounded
network-first time; put options before the duration or timestamp. Existing
writers retain their default time policy. `codex-wake time inspect` shows
qualified sources and exclusions; `--offline` shows configuration only.
Cloudflare, NIST and Alastyr are admitted as explicitly unauthenticated plain NTP.
Netnod and PTB remain disabled pending scale qualification.

Mailbox activation is an explicit operator schema migration, never a reset of
an anomalous legacy checkpoint. See the [0.8.0 instructions](docs/dev/release-notes/0.8.0-network-time.md)
for commands, compatibility, migration, rollback and acceptance limits.

Same-conversation self-refresh can use an explicitly approved shared MCP profile.
The MCP request is durable while the agent is active; an independent monitor
waits for all loaded conversations to be observed idle, then reconnects MCP
servers and verifies unchanged goal authority/counters plus selected resources.
Queued is not completed. See the portable [refresh workflow](skills/codex-wake/references/lifecycle.md#shared-mcp-refresh).


Stable-time clock reads automatically reuse one user-owned native counter bridge
at `~/.local/state/codex-wake/host-counter`. Its Unix socket is private; it reads
fresh Windows QPC values and expires after60seconds idle. It needs no additional
configuration. Cold launch failures or malformed/late replies hold clock authority;
it never substitutes guest time or caches an earlier counter as a new sample.

The merged multi-runtime candidate supports the qualified managed Grok route and
Codex/Grok mailbox exchanges. See the [support and recovery guide](docs/dev/multi-runtime-mailbox.md)
and [0.20.0 candidate release notes](docs/dev/release-notes/0.20.0-multi-runtime-wakes.md).
Real-TUI evidence is version/method-specific; publishing and production installation
remain separate from source integration and isolated candidate qualification.

## Managed harness controls

The source now supports [managed conversation inventory](docs/managed-inventory.md),
[semantic observation and bounded waits](docs/agent-observation.md),
[cooperative mutation-resource custody](docs/resource-claims.md),
[approved task briefs and assignment pins](docs/task-briefs.md), and
[explicit wake lifetime/startup policy](docs/wake-policy.md). CLI and MCP use the
same state and authority boundaries. These source additions do not install or
activate new host permissions, lifecycle adapters or production monitors.

### Native harness readiness and historical receipts

Mode-aware native registration reports `harness` separately from `monitor`.
`armed` requires a successful exact-recipient read and no unreconciled peer
history. `held_harness` retains the original intent: inspect its reason rather
than create a replacement. Preflight never resumes/loads a thread or starts a
turn; current activity can change before delivery and is rechecked there.

When a prior accepted submission's CLI executable has been removed, native peer
reconciliation may use the current intent's qualified CLI for read-only access
to the same endpoint and conversation. Exact prompt/terminal evidence is still
required and its receipt remains bound to the original target/submission. One
remote historical read is allowed per admission poll. Missing/ambiguous evidence
stays held; read failures report `peer_reconciliation_unavailable`, distinct
from an actual unfinished check. No old work is resubmitted or marked complete
from age, current idleness, or a different CLI's existence.
