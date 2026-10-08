# Wake Record Schema

Current schema version: `1`

Wake records are durable runtime records stored as JSON. They are operational state, not source artifacts. Schema version `1` is an additive object contract: readers must tolerate unknown fields, and optional fields may be absent.

## Required Top-Level Fields

- `schema_version`: integer schema version.
- `id`: stable wake id.
- `created_at`: UTC timestamp.
- `updated_at`: UTC timestamp.
- `cwd`: creating working directory.
- `target`: dispatch target object.
- `predicate`: trigger predicate object.
- `prompt`: wake instruction text.
- `status`: wake status.
- `attempts`: dispatch attempt count.
- `max_attempts`: bounded retry limit.
- `ack_timeout_seconds`: ack wait limit.
- `next_attempt_at`: UTC timestamp for the next dispatch attempt or predicate check.
- `events`: ordered audit events.

## Status Vocabulary

Active statuses:

- `pending`
- `firing`

Terminal statuses:

- `submitted`
- `failed`
- `cancelled`
- `expired`

Archived status:

- `archived`

Status directory names match these values, except archived records live in `archive/`.

## Target Variants

Tmux target:

```json
{
  "transport": "tmux",
  "tmux_socket": "/tmp/tmux-1000/default",
  "pane": "%11"
}
```

App-server target:

```json
{
  "transport": "app-server",
  "endpoint": "stdio://",
  "thread_id": "thread_abc",
  "codex_cmd": "/home/you/.nvm/versions/node/v24.14.0/bin/codex"
}
```

Only `stdio://` app-server dispatch is implemented in schema version `1`.

The local owner-delivery repair adds optional target and evidence fields without
changing schema-v1 status meanings. New stdio targets may contain
`inline_payload=true` and a `completion_timeout_seconds` value up to 30. Exact
existing-TUI targets retain transport `tmux` and add `owner_thread_id`,
`owner_pid`, `owner_start_ticks`, `owner_remote`, and `rollout_path`.
`delivery.state` distinguishes sending, pasted, accepted, completed,
interrupted, uncertain, and not_sent; `idle_wait` bounds pre-submission waiting.
None is a new directory or a stronger meaning for `submitted`. An uncertain
delivery is failed, inspectable, and never replayed automatically. Completion
and operator-visible response evidence must be checked independently.
`codex_cmd` is optional and may be absent. When present, it is a validated
Codex CLI command or absolute path used by the daemon to launch local stdio
app-server dispatch.

OpenClaw Gateway target:

```json
{
  "transport": "openclaw_gateway",
  "gateway": {
    "url": "ws://127.0.0.1:18789",
    "token_env": "OPENCLAW_GATEWAY_TOKEN"
  },
  "openclaw": {
    "agent_id": "main",
    "session_key": "agent:main:slack:channel:c0ahqqcg7j4",
    "channel": {
      "provider": "slack",
      "workspace": "default",
      "channel_id": "C0AHQQCG7J4",
      "thread_ts": "1779729958.218239"
    }
  },
  "dispatch": {
    "deliver": false,
    "timeout_seconds": 120,
    "gateway_timeout_ms": 180000
  },
  "openclaw_cmd": "/home/you/.local/bin/openclaw"
}
```

`openclaw_gateway` targets require a durable `agent:<agent_id>:...`
`session_key`. Channel fields are evidence and validation aids, not a
substitute for the session key. Gateway auth fields name environment variables;
they must not store token or password values. Dispatch sends a short
`WAKE_TRIGGER_ID=...` handoff prompt that points the OpenClaw agent back to the
durable wake record instead of embedding the original prompt text.

## Predicate Variants

Wall-clock predicate:

```json
{
  "type": "not_before",
  "due_at": "2026-05-18T21:15:00Z"
}
```

File-exists predicate:

```json
{
  "type": "file_exists",
  "path": ".codex/events/pytest.done"
}
```

File-changed predicate:

```json
{
  "type": "file_changed",
  "path": ".codex/events/build.log",
  "registered_exists": true,
  "registered_mtime_ns": 123,
  "registered_size": 456
}
```

Process-done predicate:

```json
{
  "type": "process_done",
  "pid": 12345,
  "registered_start_time_ticks": 987654,
  "registered_boot_id": "optional-linux-boot-id"
}
```

For `process_done`, `registered_start_time_ticks` and `registered_boot_id` are optional best-effort identity fields. Older PID-only records remain valid and fall back to PID liveness.

## Optional Fields

Current optional fields include:

- `context_paths`: paths the resumed agent should inspect.
- `evidence_paths`: log, marker, or evidence paths related to the wake.
- `last_error`: terminal failure detail.
- `previous_status`: status before archival.
- `archived_at`: archive timestamp.
- `dispatch_result`: accepted app-server `thread_id` and `turn_id` metadata
  when returned; for OpenClaw Gateway dispatch, sanitized Gateway metadata
  such as `run_id`, `status`, `summary`, `session_id`, provider/model, payload
  counts, and text summaries. It must not store raw assistant transcript text.
- `visibility_result`: sanitized tmux operator-visibility evidence when checked.
- app-server target `codex_cmd`: optional command path for launching local
  stdio app-server dispatch.
- OpenClaw Gateway target `openclaw_cmd`: optional command path for launching
  local Gateway dispatch through the OpenClaw CLI.

Event objects may also include extra metadata such as accepted app-server turn
identifiers or `created_by` provenance. The OpenClaw plugin uses
`created_by: "openclaw-plugin:codex-wake"` on the initial `created` event.

## Tmux Visibility Result

Tmux-submitted records may include a `visibility_result` object:

```json
{
  "transport": "tmux",
  "pane": "%11",
  "checked_at": "2026-05-23T16:30:00Z",
  "privacy": "raw_pane_text_not_stored",
  "classification": "visible_prompt_observed",
  "pre_capture": {
    "line_count": 45,
    "wake_marker_present": false
  },
  "post_capture": {
    "line_count": 46,
    "wake_marker_present": true
  },
  "post_marker_new": true
}
```

Classification values:

- `visible_prompt_observed`: the wake marker was absent before dispatch and
  present after ack.
- `ack_observed_visibility_unproven`: the hook ack was observed, but pane
  marker evidence did not prove a new visible prompt.
- `visibility_check_failed`: ack was observed, but post-ack tmux capture failed.

`visibility_result` deliberately stores counts, booleans, and classification
only. It must not store raw pane text or transcript content.

## Derived Ack Files

Ack files under `.codex/wake/acks/*.submitted` are derived evidence written by the Codex hook. They are not authoritative wake records and do not change the wake record schema version.

Ack files currently include:

- `wake_id`
- `submitted_at`
- `turn_id`
- `session_id`

## Compatibility Policy

Schema version `1` allows additive optional fields. A schema bump is not required for:

- adding optional top-level metadata
- adding optional predicate metadata with a fallback path
- adding event metadata
- adding derived diagnostic output outside the wake record
- adding CLI commands that read existing records without changing required fields

A schema bump is required for:

- renaming or removing required fields
- changing existing field meaning incompatibly
- making an optional field required for existing predicate records
- changing the status vocabulary or status directory layout incompatibly
- changing target transport semantics incompatibly
- changing predicate semantics so existing records would fire or fail differently without an explicit migration

Any schema bump must include a release note, validation evidence, and a migration or compatibility plan.
