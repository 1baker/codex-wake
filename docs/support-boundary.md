# Support Boundary

This document defines what `codex-wake` productization supports, what is
manual-only, and what evidence is required before claiming a wake worked.

## Supported Product Paths

Supported productized paths:

- install the CLI from a public Git tag with `uv tool install`;
- install `codex-wake-hook` into repo or user Codex hook config;
- run one monitored wake root through a repo-scoped `codex-waked` service;
- run many explicit wake roots through `codex-wake-supervisor.service`;
- schedule tmux wakes from a pane that has `TMUX_PANE` and `TMUX`;
- schedule Codex app-server wakes with a real resumable thread id;
- schedule OpenClaw Gateway wakes with a real agent/session key;
- install/update the OpenClaw plugin from a public `codex-wake` tag or
  generated package artifact.

Unsupported as product evidence:

- a wake JSON file without monitor readiness;
- `codex-waked --no-dispatch` or `supervisor run --no-dispatch` as delivery
  proof;
- placeholder ids such as `thread_abc`, `noop-smoke-test`, or copied sample
  OpenClaw session keys;
- tmux wakes created without a captured pane/socket target;
- OpenClaw Slack channel ids treated as Codex app-server thread ids;
- ack files treated as proof that an operator-visible pane changed;
- source-tree linked OpenClaw plugin paths treated as durable install evidence.

## Required Evidence

For every unattended wake, record:

- wake id;
- wake root;
- target transport;
- trigger predicate;
- monitor readiness source;
- final wake status;
- dispatch-specific proof.

Dispatch-specific proof:

- tmux: hook ack plus `visibility_result.classification` or direct pane
  inspection when claiming operator-visible success;
- Codex app-server: `app_server_preflight`, `dispatch_result.turn_id` when
  available, `submitted`, `ack_observed`, or transcript/turn readback;
- OpenClaw Gateway: `openclaw_gateway_preflight`,
  `openclaw_gateway_dispatch_result`, `dispatch_result.run_id`,
  `dispatch_result.session_id`, and Slack/transcript readback when
  human-visible proof is required.

## Manual-Only Cases

The local repair candidate supports exact-existing-owner tmux delivery only
with process, foreground terminal and rollout identity verification. Require a
persistent loop monitor; one-shot polling does not dispatch owner records.
Short unowned stdio turns must finish within the bounded 30-second operation
budget. Acceptance alone does not establish completion or visible response.
This candidate is not a published release and must be verified through its
isolated installed executable before adoption.

Tmux is manual/operator-visible unless the operator captures pane visibility
evidence. The product can verify that a target pane and hook ack exist, but the
operator must still confirm the prompt landed in the intended active Codex pane
when visibility matters.

Live OpenClaw and app-server smokes require local credentials, sessions, and
readback surfaces. CI should not run those checks.

## Cleanup Boundary

`codex-wake cleanup` is dry-run by default and only targets archived records.
It does not delete active wake records, terminal records before archive, ack
files, logs, monitor health, or supervisor registry entries.

Use `docs/runtime-state-lifecycle.md` for the full state classification.
