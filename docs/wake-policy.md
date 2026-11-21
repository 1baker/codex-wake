# Wake lifetime and recipient startup

New `native after|at|file` and `grok after|at|file` registrations freeze their
selected policy in schema8. Existing records keep their original behavior.
Changing configuration does not change an existing scheduling intent, including
when the caller retries its original idempotency key.

The initial defaults are persistent lifetime, owner-end retirement, and
`create_load_run` startup. Persistent preserves the existing independent durable
intent behavior. All defaults are configurable through the local operator CLI:

```sh
codex-wake --wake-root ROOT wake-policy show
codex-wake --wake-root ROOT wake-policy configure --operator \
  --lifetime persistent --owner-end retire --startup create_load_run
```

Each new registration may choose `--wake-lifetime conversation|task|persistent`,
`--owner-id ID`, `--owner-end retire|hold|retain`, and
`--recipient-startup active_tab|background_saved|create_load_run`. Task lifetime
requires an owner ID. Conversation lifetime defaults to the exact target's
`codex:THREAD` or `grok:SESSION` owner ID. Persistent lifetime has no owner.

```sh
codex-wake --wake-root ROOT native after --json \
  --idempotency-key report-reminder --wake-lifetime task --owner-id daily-report \
  --recipient-startup create_load_run THREAD 1h -- 'Continue the daily report'
```

Lifetime and startup are independent. `active_tab` requires a fresh qualified
attachment and does not permit loading a saved recipient. `background_saved`
permits the existing qualified exact-conversation saved-resume route.
`create_load_run` permits existing qualified loading and task-startup operations;
it is the preferred policy, not a promise that a particular runtime can create a
tab or launch a new conversation. The initial Codex path can load the exact saved
conversation. A missing Grok binding or an unqualified launch stays unavailable
with an explicit policy outcome and no guessed substitute. Later lifecycle
tickets add new execution capabilities behind this declared policy.

An exact-conversation target never silently becomes a fresh conversation. A
fresh task launch needs its own declared task/recipient authority. The default
does not reset a deadline, resource allocation or outstanding effect.

## Explicit owner completion

Only verified explicit owner completion applies owner-end policy. Closing a tab,
losing a process or restarting the monitor does not complete an owner.

```sh
codex-wake --wake-root ROOT wake-policy owner-complete --operator \
  --owner-kind task --owner-id daily-report --event-id report-finished-1
```

The local CLI is in the existing OS-user operator trust domain; `--operator` is
never a model-controlled MCP property. MCP verifies native private call metadata; task scope additionally requires exact
delegation in host policy. Neither caller identity nor task delegation proves
completion. The current MCP owner tool reconciles an exact completion event
already recorded by the explicit local operator action; a model cannot mint that
event. Qualified automatic runtime/task-acceptance event adapters are separate
capabilities and are not inferred from an idle or active conversation.

`retire` cancels future pending owner-bound delivery by default. `hold` keeps it
pending with `owner_completed_review_required`; `retain` leaves original expiry
and cancellation in force. Independent persistent wakes are unaffected. History
and uncertain submissions are preserved. An uncertain effect is reconciled and
never resubmitted just because the owner finished.

Completion and effect admission share a root policy lock, then the existing wake
lock. A private completion journal survives a crash during the record sweep;
evaluation and dispatch reapply it. Missing or corrupt required owner state holds
delivery. The journal stores owner events, not a second copy of wake policy.

## MCP and readiness

`wake_native_after`, `wake_native_at`, and `wake_native_file` register exact-self
wakes using trusted native metadata. All expose lifetime/startup properties.
Existing Grok registration tools expose the same policy properties while retaining
their host-bound actor requirements. `wake_owner_complete` reconciles an exact operator-approved owner event; absent
terminal evidence returns `owner_completion_evidence_required`. It cannot
override lifetime or startup choices.

Registration reports `requires_worker_schema=8`. `--require-monitor` requires a
currently compatible worker; otherwise the original intent is retained with an
actionable compatibility diagnostic. Disk persistence, trusted-clock eligibility,
monitor readiness and actual accepted delivery remain separate outcomes. Source
restart/epoch tests do not prove that a production service restarts after reboot.

## Record compatibility

Schema8 retains all existing scheduling/attempt fields and adds
`intent_schema_version` (6 for native, 7 for managed Grok) and a version1
`wake_policy`: lifetime, owner, owner-end action, startup, and the resolved default
configuration revision. Older readers hold schema8. New readers validate the
policy before routing through the existing intent core. Legacy schema6/7 records
are not rewritten, and policy-shaped data in a legacy version is held.

Schema8 keeps one atomic canonical record across statuses, preserving original
origin/clock anchors, expiry, prompt and uncertain attempt identity. Startup
failure does not consume an attempt. Owner retirement cannot retract a submitted
effect or turn missing evidence into non-submission.

## Future scheduling, lifetime and delivery windows

A time wake may be scheduled beyond 24 hours, independently of the creating
session's execution window. Positive relative durations use `s`, `m`, `h`, or
`d`; absolute due times use timezone-qualified ISO8601 dates. There is no24-hour
scheduling ceiling. Dates and their displayed expiry must fit the supported ISO
calendar; unrepresentable projections are explicitly unsupported, never armed.

For time wakes, `ttl` is the delivery window **after the due time**, not a limit
on how far in the future the wake may be scheduled. File-wake TTL starts at its
registration origin. Independently persistent lifetime removes owner-completion
retirement; it does not erase an explicit expiry or authorize new execution
resources. Task/conversation completion policy remains separately enforceable.

Registration receipts expose original `due_at`, `expires_at`, `armed`, monitor
ownership and `scheduling_status`. Qualified original UTC anchors provide dates
immediately; counter-only origins remain explicitly relative rather than
inventing UTC. A compatible persistent loop must be observed for `armed=true`.
A retained unmonitored intent is not an active schedule; its response names the
root and asks for monitor setup/reconciliation. Journal persistence and delivery
are separate outcomes.

`native reconcile ID` can refresh a pending native timer from its saved clock
origin without submitting a model turn or restarting the delay. An uncertain
submission still uses evidence reconciliation and is never replayed. Agent
inventory includes original due/expiry dates, and cancellation still requires
host root/action grants. Reusing an unchanged idempotency key returns the same
intent, including after monitor setup or a process restart.

Recurrence remains the existing HF-20 responsibility: one schedule authority
computes each occurrence, with declared missed-run/overlap behavior. A prompt
that asks a model to re-arm a wake is a continuation contract, not proof of a
native cron timer. This repair does not create a second recurrence authority or
change those existing decisions.

### Verified-session controls on a shared root

The host can opt into self-service inspection/cancellation without a new caller
entry for every conversation. Pass a private owned `--wake-control-config` to
the MCP process, with this version2 format:

```json
{"version":2,"callers":{},"native_self":{"roots":["/absolute/host/wake-root"],"actions":["list","cancel"]}}
```

Actual native caller metadata is required. Only integrity-qualified native wakes
whose frozen permission context identifies that same creator and recipient are
selected. Listing filters peers; cancellation (including `all`) rechecks ownership
under the existing effect lock. Spoofed caller IDs, peer wake IDs, all-root scope,
and root-wide pause/resume/interruption are refused. Configure the existing
common permission policy first so new native registrations freeze provenance.
Older records without that provenance still need explicit operator grants.

Version1 explicit caller/root/action grants retain their existing semantics.
An explicit caller entry takes precedence over the optional verified-self default;
that default cannot bypass a caller-specific restriction. Fresh connections use
the configured host file; editing config does not prove resident MCP connections
have reloaded. Existing supported refresh/idle boundaries still apply.

## Native compatibility registration

New native callers still select a session mode. Where an existing independent
policy is required, select `session_mode: explicit_policy` and supply all of
`wake_lifetime`, `recipient_startup`, and `routes` explicitly. This preserves the
legacy target and fingerprint on an identical-key retry; it does not migrate a
wake already bound to another mode. Lifetime, owners, exact-self identity, ordered
route permissions and idempotency remain enforced. This native-only selector does
not change recurring-schedule mode choices or grant deployment/dispatch authority.
