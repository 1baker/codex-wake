# Codex Wake Roadmap

## P231 | Specialist bot families

Delivered source: Wake607/Bots77 plus corrective Bots78; five implementation
tickets closed; one review and one bounded remediation complete. Spec #601 stays
open. Durable specialist/account/task
hierarchy and inherited guidance in codex-bots; Wake supplies exact tab bindings,
background family placement, reversible accents/navigation and accepted temporary
worker cleanup. Execution: [Plan0231](docs/dev/plans/0231-2026-11-13-bot-tab-hierarchy.md)
and its ticket ledger. Subsequent authorized installation deployed Wakedev19 and
Bots c7fe3a1; see [deployment evidence](docs/dev/evidence/plan0231/deployment.md)
for actual acceptance and preserved holds. No provider/account grant expansion.

## P229 | Reconnect failures

Issue #596 delivered: PR597 merged6150e5a5; dev14 monitor deployed and actual
tab16 reconnect error detected, preserving pane identities and settings. See
[Plan0229](docs/dev/plans/0229-2026-11-13-reconnect-error-detection.md).

## Evidence reconciliation | 2026-11-12

This bounded documentation reconciliation uses delivery base `1a276d0f` and
canonical issue/receipt evidence; it is not a fresh installed-runtime readback.
P197/P198 are integrated and have recorded package deployment. P209's bounded
implementation/qualification is complete. P213/P214 retain OPEN plan labels for
explicit disposition, but P216's later monitor qualification is already delivered.
The local OBS draft chain was superseded; canonical #541–#547 remain CLOSED and
parent #540 remains OPEN. Current automation history belongs to later P223, which
records disabled automation; older enabled/stopped statements below describe
their own milestone dates.

See [canonical P216 findings](docs/dev/notes/0216-2026-11-12-canonical-acceptance-reconciliation.md),
[P198 deployment](docs/dev/evidence/plan0198/deployment.json),
and [documentation work item](docs/dev/plans/0227-2026-11-12-roadmap-evidence-reconciliation.md).
No historical receipt establishes current installation or grants runtime effects.

## P225 | Actionable CLI outcomes

State: CLOSED

Current State: LOCAL-P225 corrects workspace format enable and outcome-first tab
CLI presentation, retained-result exit codes and bounded formatting status at
`f4167c0e`.67focused checks pass on each Python3.11/3.12 and10private installed
checks pass. Expanded tab validation retains one installed-baseline cadence
failure; existing P220/P224 planning-header findings are separate. Source fix is
integrated by PR590 at55a2ee5d and exact0.22.0.dev12 is installed. Final67focused
and10exact installed checks pass.9launchers,10resident services and27native
identities verified; global formatting/startup hold preserved. Formatting
reactivation remains separate. [Deployment](docs/dev/evidence/plan0225/deployment.json).

Plan: [Actionable CLI outcomes](docs/dev/plans/0225-2026-11-12-actionable-cli-output.md)

## P01 | Wake Spooler Architecture

State: CLOSED

Current State: Closed by `docs/dev/0001-wake-spooler-design.md`. The accepted architecture direction is a wake spooler: agents request wakes through `codex-wake`, deterministic runtime code owns trigger persistence and firing, and the MVP targets a live Codex TUI through tmux plus a `UserPromptSubmit` hook ack.

Plan: [Initial Wake Timer Design](docs/dev/plans/0001-2026-05-18-initial-wake-timer-design.md)

Deliverables:

- Source-backed design brief for the MVP and preferred future mode.
- Wake-record JSON contract.
- Trigger/status vocabulary.
- Runtime state layout under a user-scoped wake root.
- Explicit split between model-requested wake intent and daemon-owned execution.

## P02 | Agent-Facing CLI

State: CLOSED

Current State: Closed by the first Python package and CLI implementation. `codex-wake` can create `after`, `at`, and `file` wake records, list records, show a record, and cancel pending or firing records.

Plan: [Agent-Facing CLI](docs/dev/plans/0002-2026-05-18-agent-facing-cli.md)

Planned surface:

- `codex-wake after <duration> -- <prompt>`
- `codex-wake at <timestamp> -- <prompt>`
- `codex-wake file <path> -- <prompt>`
- `codex-wake list`
- `codex-wake show <wake-id>`
- `codex-wake cancel <wake-id>`

Acceptance target:

- The CLI captures cwd, `TMUX_PANE`, tmux socket, trigger predicate, prompt text, and creation metadata.
- Relative file predicates are stored with the creating cwd and validated before write.
- Time triggers store absolute UTC timestamps, not only relative expressions.
- Trigger JSON never contains shell commands to execute.

## P03 | Wake Daemon And Trigger Engine

State: CLOSED

Current State: Closed by the first `codex-waked` implementation. The daemon can poll pending records, evaluate `not_before` and `file_exists`, move ready records into `firing`, and fail records with invalid predicates.

Plan: [Wake Daemon And Trigger Engine](docs/dev/plans/0003-2026-05-18-wake-daemon-trigger-engine.md)

Planned behavior:

- Poll pending wake records.
- Support `not_before` and `file_exists` first.
- Add `file_changed` and `process_done` only after the base state machine is stable.
- Mark triggers `firing` before injection.
- Use per-pane locks so concurrent wakes cannot paste into the same TUI.
- Require ack before marking a trigger `submitted`.
- Requeue with bounded backoff when ack is missing.

## P04 | Tmux Injection MVP

State: CLOSED

Current State: Closed by the first tmux injector implementation. Firing records can be dispatched through a testable injector path, canonical prompts are generated from wake id only, unsafe panes are rejected, per-pane locks are enforced, and missing ack requeues with backoff.

Plan: [Tmux Injection MVP](docs/dev/plans/0004-2026-05-18-tmux-injection-mvp.md)

Planned behavior:

- Capture target pane from `TMUX_PANE` at trigger creation time.
- Resolve tmux socket from the environment or tmux introspection.
- Before injection, use tmux capture heuristics to reject obvious unsafe states such as approval prompts, active tool output, or non-Codex shell prompts.
- Inject only:

```text
WAKE_TRIGGER_ID=<wake-id>
Resume the scheduled wake task.
```

- Keep full wake context in the trigger record and hook-added context, not in the pasted prompt.

## P05 | Codex Hook Ack And Context Loader

State: CLOSED

Current State: Closed by the repo-local `UserPromptSubmit` hook. The hook self-filters for `WAKE_TRIGGER_ID=...`, writes ack files, and returns wake context through `hookSpecificOutput.additionalContext`.

Plan: [Codex Hook Ack And Context Loader](docs/dev/plans/0005-2026-05-18-codex-hook-ack-context-loader.md)

Planned behavior:

- Self-filter for `WAKE_TRIGGER_ID=...` because Codex ignores `matcher` for `UserPromptSubmit`.
- Write an ack file when the wake prompt is submitted.
- Load the trigger JSON and add the full wake context as developer context.
- If the trigger file is missing, add context that instructs the agent to inspect wake state before continuing.
- Keep the hook short and bounded by a small timeout.

## P06 | Runtime State, Retention, And Safety

State: CLOSED

Current State: Closed by runtime-state documentation and the terminal-record archive command. Operators can inspect active and archived wakes, and terminal wake records can be archived without touching active `pending` or `firing` records.

Plan: [Runtime State, Retention, And Safety](docs/dev/plans/0006-2026-05-18-runtime-state-retention-safety.md)

Planned state layout:

- `.codex/wake/pending/`
- `.codex/wake/firing/` or status-bearing records
- `.codex/wake/acks/`
- `.codex/wake/logs/`
- `.codex/wake/archive/`
- `.codex/wake/locks/`

Safety requirements:

- Never store secrets or raw private transcripts in trigger JSON.
- Require idempotent prompts: every wake should first verify whether the task is already complete.
- Define cleanup and archival semantics before broad use.
- Treat missed, failed, expired, cancelled, and submitted wakes as distinct inspectable outcomes.

## P07 | App-Server Controlled Mode

State: CLOSED

Current State: Closed by the stdio app-server controlled dispatch path. Wake records can target app-server threads, dispatch uses `initialize`, `thread/resume`, and `turn/start`, and WebSocket mode remains explicitly deferred behind the documented experimental/auth boundary.

Plan: [App-Server Controlled Mode](docs/dev/plans/0007-2026-05-18-app-server-controlled-mode.md)

Planned behavior:

- Support Codex app-server as a target transport.
- Store app-server thread id and target cwd when available.
- Use `thread/resume` followed by `turn/start` for controlled wake dispatch.
- Treat WebSocket mode as localhost or SSH-forwarding first; require auth/TLS before non-local exposure.
- Keep `codex exec resume <session-id> ...` as a fallback when a live TUI pane is not required.

## P08 | Installed Runtime Verification

State: CLOSED

Current State: Closed by `docs/dev/verification/0001-2026-05-18-installed-runtime-verification.md`. Installed console scripts, CLI lifecycle, daemon predicate movement, hook ack behavior, and app-server target creation were verified from a temporary virtualenv.

Plan: [Installed Runtime Verification](docs/dev/plans/0008-2026-05-18-installed-runtime-verification.md)

Acceptance target:

- A wake request can be created from a tmux-hosted Codex TUI.
- The daemon observes the predicate and moves the wake through expected states.
- The injector sends only the canonical wake prompt.
- The `UserPromptSubmit` hook records ack and supplies context.
- The resumed agent can inspect the trigger and referenced log/event files.
- Failed ack, unsafe pane, cancellation, timeout, and duplicate wake attempts are observable.

## P09 | User-Scope Install And Operator Smoke

State: CLOSED

Current State: Closed by `docs/dev/verification/0002-2026-05-18-user-scope-install-operator-smoke.md`. `codex-wake` and `codex-waked` are installed as uv user tools and verified through PATH-resolved operator smokes.

Plan: [User-Scope Install And Operator Smoke](docs/dev/plans/0009-2026-05-18-user-scope-install-operator-smoke.md)

## P10 | Disposable Live Tmux Wake Smoke

State: CLOSED

Current State: Closed by `docs/dev/verification/0003-2026-05-18-disposable-live-tmux-wake-smoke.md`. A disposable tmux-hosted Codex TUI wake was verified with repo-local hook trust, delayed multiline submit, daemon-observed ack, and a submitted wake record.

Plan: [Disposable Live Tmux Wake Smoke](docs/dev/plans/0010-2026-05-18-disposable-live-tmux-wake-smoke.md)

## P11 | Release Packaging And Install Docs

State: CLOSED

Current State: Closed by `docs/dev/verification/0004-2026-05-18-release-packaging-install-docs.md`. README install docs, v0.1.0 release notes, installed `codex-wake-hook`, clean package build, and refreshed user-scope install evidence are complete.

Plan: [Release Packaging And Install Docs](docs/dev/plans/0011-2026-05-18-release-packaging-install-docs.md)

## P12 | User Daemon Service And Dogfood Wake

State: CLOSED

Current State: Closed by `docs/dev/verification/0005-2026-05-18-user-daemon-service-dogfood-wake.md`. A user-scoped systemd path is documented, the daemon logs non-empty poll results, and a real dogfood wake resolved through the running service.

Plan: [User Daemon Service And Dogfood Wake](docs/dev/plans/0012-2026-05-18-user-daemon-service-dogfood-wake.md)

## P13 | Service Installer CLI

State: CLOSED

Current State: Closed by `docs/dev/verification/0006-2026-05-18-service-installer-cli.md`. Operators can now manage a repo-local user systemd service with `codex-wake service install/status/logs/stop/uninstall`.

Plan: [Service Installer CLI](docs/dev/plans/0013-2026-05-18-service-installer-cli.md)

## P14 | Hook Setup And Doctor CLI

State: CLOSED

Current State: Closed by `docs/dev/verification/0007-2026-05-18-hook-setup-doctor-cli.md`. Operators can run `codex-wake hook install/check` and `codex-wake doctor` to set up and inspect wake readiness without bypassing Codex hook trust review.

Live note: `docs/dev/verification/0009-2026-05-18-current-tui-dogfood.md` confirmed that tmux injection can resume the active TUI pane, but an already-running TUI session still needs `/hooks` review before the installed `codex-wake-hook` ack path should be expected to fire.

Plan: [Hook Setup And Doctor CLI](docs/dev/plans/0014-2026-05-18-hook-setup-doctor-cli.md)

## P15 | Clean Fresh Install Smoke

State: CLOSED

Current State: Closed by `docs/dev/verification/0008-2026-05-18-clean-fresh-install-smoke.md`. The public `v0.3.0` tag installs into an isolated `uv tool` path and passes command, hook, doctor, and temporary service lifecycle smokes without relying on the local checkout.

Plan: [Clean Fresh Install Smoke](docs/dev/plans/0015-2026-05-18-clean-fresh-install-smoke.md)

## P16 | CI Release Gates

State: CLOSED

Current State: Closed by `docs/dev/verification/0010-2026-05-19-ci-release-gates.md`. GitHub Actions now runs compile checks, unit tests, package build, and installed-wheel CLI smoke checks for Python 3.11 and 3.12 on push and pull request.

Plan: [CI Release Gates](docs/dev/plans/0016-2026-05-18-ci-release-gates.md)

## P17 | Event Predicates

State: CLOSED

Current State: Closed by `docs/dev/verification/0012-2026-05-19-event-predicates.md`. `codex-wake changed <path>` and `codex-wake pid <pid>` now create declarative predicates, and the daemon can move ready `file_changed` and `process_done` records to `firing`.

Plan: [Event Predicates](docs/dev/plans/0017-2026-05-19-event-predicates.md)

## P18 | App-Server Hardening

State: CLOSED

Current State: Closed by `docs/dev/verification/0014-2026-05-19-app-server-hardening.md`. `codex-wake app after` and `codex-wake app at` now create explicit app-server wakes, and accepted app-server dispatch stores available `thread_id` and `turn_id` metadata.

Plan: [App-Server Hardening](docs/dev/plans/0018-2026-05-19-app-server-hardening.md)

## P19 | PID Reuse Safety

State: CLOSED

Current State: Closed by `docs/dev/verification/0016-2026-05-19-pid-reuse-safety.md`. `codex-wake pid` now records best-effort process identity on Linux, and the daemon fires when a live PID no longer matches the registered process.

Plan: [PID Reuse Safety](docs/dev/plans/0019-2026-05-19-pid-reuse-safety.md)

## P20 | Runtime Retention Cleanup

State: CLOSED

Current State: Closed by `docs/dev/verification/0018-2026-05-19-runtime-retention-cleanup.md`. `codex-wake cleanup` now previews old archived records by default, deletes them only with `--delete`, and can archive terminal records first with `--archive-terminal`.

Plan: [Runtime Retention Cleanup](docs/dev/plans/0020-2026-05-19-runtime-retention-cleanup.md)

## P21 | Hook Session Visibility

State: CLOSED

Current State: Closed by `docs/dev/verification/0020-2026-05-19-hook-session-visibility.md`. `hook check` and `doctor` now report hook ack evidence and explicitly mark active-session hook state as unknown until an ack is observed.

Plan: [Hook Session Visibility](docs/dev/plans/0021-2026-05-19-hook-session-visibility.md)

## P22 | Wake Record Schema Versioning

State: CLOSED

Current State: Closed by `docs/dev/verification/0022-2026-05-19-wake-record-schema-versioning.md`. Schema version `1` is now documented as an additive optional-field contract, and `codex-wake schema` exposes the compatibility policy.

Plan: [Wake Record Schema Versioning](docs/dev/plans/0022-2026-05-19-wake-record-schema-versioning.md)

## P23 | Doctor JSON Inspection Surface

State: CLOSED

Current State: Closed by `docs/dev/verification/0024-2026-05-20-doctor-json.md`. `codex-wake doctor --json` now emits structured command, tmux, hook config, hook runtime evidence, service, and trust fields while preserving text doctor output.

Plan: [Doctor JSON Inspection Surface](docs/dev/plans/0023-2026-05-20-doctor-json.md)

## P24 | Status JSON Summary Surface

State: CLOSED

Current State: Closed by `docs/dev/verification/0026-2026-05-20-status-json.md`. `codex-wake status` and `codex-wake status --json` now summarize wake counts by status, predicate type, and target transport.

Plan: [Status JSON Summary Surface](docs/dev/plans/0024-2026-05-20-status-json.md)

## P25 | Status Summary Dogfood

State: CLOSED

Current State: Closed by `docs/dev/verification/0028-2026-05-20-status-dogfood.md`. Bounded dogfood confirmed `status --json` exposes pending, firing, and archived summary movement for a short repo-local wake without live pane injection.

Plan: [Status Summary Dogfood](docs/dev/plans/0025-2026-05-20-status-dogfood.md)

## P26 | Cleanup JSON Surface

State: CLOSED

Current State: Closed by `docs/dev/verification/0029-2026-05-20-cleanup-json.md`. `codex-wake cleanup --json` now reports cleanup mode, terminal archives, matched archived records, deletion state, and counts without changing dry-run defaults.

Plan: [Cleanup JSON Surface](docs/dev/plans/0026-2026-05-20-cleanup-json.md)

## P27 | Controlled Live Dispatch Dogfood

State: CLOSED

Current State: Closed by `docs/dev/verification/0031-2026-05-20-live-dispatch-dogfood.md`. The installed daemon fired one live tmux dispatch, observed the `UserPromptSubmit` hook ack, moved the wake to `submitted`, and the dogfood wake was archived with `active_total=0`.

Plan: [Controlled Live Dispatch Dogfood](docs/dev/plans/0027-2026-05-20-live-dispatch-dogfood.md)

## P28 | Installed Runtime State Tidy Dogfood

State: CLOSED

Current State: Closed by `docs/dev/verification/0032-2026-05-20-installed-runtime-state-tidy-dogfood.md`. The repo-local wake root is tidy after archiving four terminal records with installed `cleanup --archive-terminal --json`; no archived evidence was deleted.

Plan: [Installed Runtime State Tidy Dogfood](docs/dev/plans/0028-2026-05-20-installed-runtime-state-tidy-dogfood.md)

## P29 | App-Server Contract Refresh

State: CLOSED

Current State: Closed by `docs/dev/verification/0033-2026-05-20-app-server-contract-refresh.md`. Codex CLI `0.131.0` still exposes the stdio app-server primitives used by codex-wake, and the source-tree stdio initialize smoke passed. No code change is required before a live disposable-thread dogfood or thread-status preflight lane.

Plan: [App-Server Contract Refresh](docs/dev/plans/0029-2026-05-20-app-server-contract-refresh.md)

## P30 | App-Server Thread Status Preflight

State: CLOSED

Current State: Closed by `docs/dev/verification/0034-2026-05-21-app-server-thread-status-preflight.md`. `codex-wake app status` reads app-server thread status without starting a turn, and app-server dispatch now starts `turn/start` only after an idle resumed-thread preflight.

Plan: [App-Server Thread Status Preflight](docs/dev/plans/0030-2026-05-21-app-server-thread-status-preflight.md)

## P31 | Disposable App-Server Dogfood

State: CLOSED

Current State: Closed by `docs/dev/verification/0036-2026-05-21-disposable-app-server-dogfood.md`. Released `v0.4.9` app-server dispatch succeeded against a disposable thread with a persisted rollout; `thread/start`-only targets are not resumable and should not be treated as valid wake targets.

Plan: [Disposable App-Server Dogfood](docs/dev/plans/0031-2026-05-21-disposable-app-server-dogfood.md)

## P32 | App Status Resume Mode

State: CLOSED

Current State: Closed by `docs/dev/verification/0037-2026-05-21-app-status-resume-mode.md`. `codex-wake app status --resume` now mirrors the dispatch preflight path with `thread/resume` while default `app status` stays on `thread/read`.

Plan: [App Status Resume Mode](docs/dev/plans/0032-2026-05-21-app-status-resume-mode.md)

## P33 | App-Server Target Discovery

State: CLOSED

Current State: Closed by `docs/dev/verification/0039-2026-05-21-app-server-target-discovery.md`. `codex-wake app candidates` now lists recent local rollout-backed thread ids from Codex session metadata and points operators to `app status --resume` before wake registration.

Plan: [App-Server Target Discovery](docs/dev/plans/0033-2026-05-21-app-server-target-discovery.md)

## P34 | App Candidate Validation

State: CLOSED

Current State: Closed by `docs/dev/verification/0041-2026-05-21-app-candidate-validation.md`. `app candidates --validate` checks local rollout-backed thread ids with resume-backed status, and `--only-idle` filters to candidates whose resumed status is idle.

Plan: [App Candidate Validation](docs/dev/plans/0034-2026-05-21-app-candidate-validation.md)

## P35 | v0.4.12 Installed App Dogfood

State: CLOSED

Current State: Closed by `docs/dev/verification/0044-2026-05-21-v0412-installed-app-dogfood.md`. The installed public `v0.4.12` runtime created, fired, app-server-dispatched, submitted, and archived one dogfood wake.

Plan: [v0.4.12 Installed App Dogfood](docs/dev/plans/0035-2026-05-21-v0412-installed-app-dogfood.md)

## P36 | Tmux Visibility Accounting

State: CLOSED

Current State: Closed by `docs/dev/verification/0051-2026-05-23-tmux-visibility-accounting.md`. Tmux dispatch records sanitized visibility evidence so hook ack is no longer conflated with operator-visible prompt proof.

Plan: [Tmux Visibility Accounting](docs/dev/plans/0036-2026-05-23-tmux-visibility-accounting.md)

## P37 | App-Server Service Environment Skill Hardening

State: CLOSED

Current State: Closed by `docs/dev/verification/0053-2026-05-23-app-server-service-env-skill-hardening.md`. The agent skill now warns that app-server service dispatch depends on the daemon environment, not the interactive shell, and points agents to service logs and `doctor --json`.

Plan: [App-Server Service Environment Skill Hardening](docs/dev/plans/0037-2026-05-23-app-server-service-env-skill-hardening.md)

## P38 | App-Server Service Environment Product Hardening

State: CLOSED

Current State: Closed by `docs/dev/verification/0054-2026-05-23-app-server-service-env-product-hardening.md`. Service-installed app-server dispatch can persist an explicit Codex CLI command, and `doctor --json` exposes service-side Codex readiness.

Plan: [App-Server Service Environment Product Hardening](docs/dev/plans/0038-2026-05-23-app-server-service-env-product-hardening.md)

## P39 | v0.4.13 Release

State: CLOSED

Current State: Closed by `docs/dev/verification/0055-2026-05-23-v0.4.13-release.md`. Public tag `v0.4.13`, release notes, GitHub release, public tag install smoke, and refreshed user-scoped install verification are complete.

Plan: [v0.4.13 Release](docs/dev/plans/0039-2026-05-23-v0413-release.md)

## P40 | OpenClaw Gateway Wake Transport

State: CLOSED

Current State: Closed by `docs/dev/verification/0059-2026-05-25-openclaw-plugin-registration-smoke.md`. `codex-wake` can create structured `openclaw_gateway` wake records, reject placeholder session keys, dispatch through OpenClaw Gateway method `agent`, and the external OpenClaw plugin at `plugins/openclaw-codex-wake/` can register a durable wake from live OpenClaw session context. Real smokes produced Slack-visible responses for `wake_20260525_203934_201f` and plugin-created wake `wake_20260525_211551_b1f4`.

Plan: [OpenClaw Gateway Wake Transport](docs/dev/plans/0040-2026-05-25-openclaw-gateway-wake-transport.md)

Acceptance target:

- `codex-wake` can store and dispatch an `openclaw_gateway` wake target with real `agent_id`, `session_key`, and channel/thread evidence.
- The daemon rejects placeholder targets and no-dispatch false positives for OpenClaw smokes.
- A real OpenClaw wake is verified through Gateway response plus Slack Mirror or transcript evidence.
- The OpenClaw plugin path can create wake records from live session context, or a precise missing SDK/core seam is documented.

## P41 | v0.4.14 Release

State: CLOSED

Current State: Closed by `docs/dev/verification/0061-2026-05-25-v0.4.14-release.md`. Public tag `v0.4.14`, GitHub release, CI, public tag install smoke, OpenClaw CLI target smoke, plugin visibility checks, installed-skill checks, and user-scoped `uv tool` refresh are complete.

Plan: [v0.4.14 Release](docs/dev/plans/0041-2026-05-25-v0414-release.md)

Acceptance target:

- `pyproject.toml`, README install docs, and release notes name `v0.4.14`.
- Source, package, plugin, installed-wheel, and installed-skill validation pass.
- Public tag, GitHub release, public tag install smoke, and user-scoped install
  refresh are recorded under `docs/dev/verification/`.

## P42 | Wake Monitor Readiness And User Supervisor

State: CLOSED

Current State: Closed by
`docs/dev/verification/0062-2026-05-26-wake-monitor-readiness-user-supervisor.md`.
The skill, CLI, and OpenClaw plugin now gate unattended wakes on monitor
readiness; `codex-wake-supervisor.service` monitors explicitly enrolled roots;
the repo-scoped service remains supported; and live Codex app-server plus
OpenClaw Gateway wakes fired from the supervisor with recorded evidence.

Plan: [Wake Monitor Readiness And User Supervisor](docs/dev/plans/0042-2026-05-25-wake-monitor-readiness-user-supervisor.md)

Acceptance target:

- The `codex-wake` skill requires monitor readiness before unattended wake
  scheduling.
- The CLI exposes monitor readiness for the selected wake root and can fail
  scheduling when a caller requires an active monitor.
- A user-scoped `codex-wake-supervisor.service` can monitor explicitly
  registered wake roots across Codex and OpenClaw transports.
- The OpenClaw plugin schedules into monitored roots by default, or returns a
  clear failure instead of implying unattended delivery.
- Real Codex app-server and OpenClaw Gateway wakes fire from monitored roots
  with recorded validation evidence.

## P43 | Productization Completion

State: CLOSED

Current State: Closed by
`docs/dev/verification/0069-2026-05-26-v050-release.md`. `v0.5.0` is tagged,
published, CI-passed, public-install-smoked, installed user-scoped from the
public tag, and live-validated through Codex app-server plus OpenClaw Gateway
wakes. Slices 1 through 5 are implemented.
`codex-wake openclaw-plugin
install|update` can materialize a public tag, install through OpenClaw's
non-linked plugin installer, prune stale linked plugin paths with a config
backup, refresh the generated registry, and survive Gateway restart from
`~/.openclaw/extensions/codex-wake`. `codex-wake product-readiness --json`
reports normalized installed readiness across CLI, hooks, skills, repo service,
supervisor roots, monitor health, app-server, OpenClaw Gateway, OpenClaw plugin,
and tmux. Runtime state classes and cleanup/archive/supervisor-unenroll effects
are documented, and stale supervisor roots now include health status plus
remediation. `scripts/product_smoke.py` and `docs/product-smoke-matrix.md`
codify safe installed/public-tag smokes, optional live Codex/OpenClaw smokes,
and the manual tmux visibility boundary. README, daemon-service docs, the
OpenClaw plugin README, the `codex-wake` skill, and
`docs/support-boundary.md` now document the public install path, monitor
selection, readiness checks, cleanup boundaries, and unsupported false
positives. Fresh Codex app-server and OpenClaw Gateway smokes through the
harness are recorded in
`docs/dev/verification/0068-2026-05-26-live-product-smokes.md`. Remaining
product risk is closed for the scoped `v0.5.0` productization DOD.

Plan: [Productization Completion](docs/dev/plans/0043-2026-05-26-productization-completion.md)

Acceptance target:

- OpenClaw plugin install/update works from a durable public tag or package
  artifact, not only from a repo-linked path.
- Installed readiness reports CLI, supervisor, monitor, hook, app-server,
  OpenClaw Gateway, plugin, and tmux status without leaking secrets.
- Runtime state cleanup and supervisor root lifecycle are documented and
  validated.
- A repeatable smoke matrix covers installed CLI, supervisor, Codex app-server,
  OpenClaw Gateway, and manual/operator-visible tmux boundaries.
- A productization release is tagged, published, public-install-smoked, and
  recorded with live wake evidence.

## P44 | App-Server Active Writer Policy

State: CLOSED

Current State: Closed on 2026-08-25. App-server preflight never calls
`turn/start` while the target is active. Active-writer contention fails by
default, including for older records without the additive target option, and
`--retry-active-writer` opts a wake into the existing bounded three-attempt
backoff policy.

Plan: [App-Server Active Writer Policy](docs/dev/plans/0044-2026-08-25-app-server-active-writer-policy.md)

Acceptance target:

- Active-writer contention never calls `turn/start`.
- Default and legacy records fail visibly when the target is active.
- Explicitly opted-in records retry with the existing bounded attempt and
  backoff policy.
- CLI, persisted schema, tests, operator docs, and agent guidance agree.

## P45 | Cross-Root Wake Hook Routing

State: CLOSED

Current State: Closed on 2026-09-04. Canonical prompts carry the absolute wake
root, the hook resolves records and retained archives against that owner, and
terminal archived wakes fail closed without resuming stale work. The redundant
project hook was removed while the user-scoped hook remains installed.

Plan: [Cross-Root Wake Hook Routing](docs/dev/plans/0045-2026-09-03-cross-root-wake-hook-routing.md)

Acceptance target:

- Every transport includes the owning absolute wake root in its canonical prompt.
- Cross-repository and archived wake submissions resolve against the owner.
- Terminal records return explicit do-not-resume context.
- Legacy id-only prompts retain the cwd fallback.
- Exactly one user-scoped hook remains installed on this workstation.

## P46 | v0.5.1 Maintenance Release

State: CLOSED

Current State: Closed by
`docs/dev/verification/0070-2026-09-04-v051-release.md`. The patch release
contains P44 and P45 plus the unpublished stable-command and removed-repository
service maintenance already present on `main`. `v0.5.1` is tagged, published,
CI-passed, public-install-smoked, and installed user-scoped; hook, skill,
supervisor, and OpenClaw plugin readbacks are complete.

Plan: [v0.5.1 Maintenance Release](docs/dev/plans/0046-2026-09-04-v051-maintenance-release.md)

Acceptance target:

- Source, package, plugin, and planning validation pass.
- The release commit and `v0.5.1` tag are pushed without rewriting history.
- GitHub CI and the GitHub release complete successfully.
- Public-tag smoke, user-scoped CLI refresh, hook/skill synchronization,
  supervisor restart, and OpenClaw plugin refresh are verified.

## P47 | Readiness Alternative Monitor Status

State: CLOSED

Current State: Closed by
`docs/dev/verification/0071-2026-09-04-v052-readiness-release.md`. Installed
`v0.5.2` reports the inactive repo service as `not_needed`, with
`required=false` and `covered_by=supervisor`, when the active enrolled
supervisor and ready monitor prove alternative coverage. Missing or unhealthy
coverage still warns.

Plan: [Readiness Alternative Monitor Status](docs/dev/plans/0047-2026-09-04-readiness-alternative-monitor-status.md)

Acceptance target:

- Healthy supervisor coverage reports the repo service as `not_needed`.
- Missing or unhealthy alternative coverage preserves the warning.
- Overall readiness treats `not_needed` as neutral.
- Source, CI, public-tag, and installed-runtime evidence agree.

## P48 | Event-Driven Wakes Product Lane

State: CLOSED

Current State: Closed at checkpoint `P48-G1-C05`. Issues #4 through #10 are
accepted on `origin/main` through `0f917719f8a50f55f76d33262c3ca639c7f515c4`.
The provider-neutral signal module, v1 compatibility, filesystem wakes, GitHub
polling, signed webhook convergence, lifecycle productization, disposable
package proof, and bounded routing calibration are integrated. The calibration
was honestly inconclusive and retained `balanced` defaults. Provider access,
public ingress, live dispatch, installed-runtime mutation, deployment, tag,
and release were not performed.

Plan: [Event-Driven Wakes Product Lane](docs/dev/plans/0048-2026-09-14-event-driven-wakes-product-lane.md)

Goal campaign: [Event-driven wakes goal campaign](docs/dev/plans/0049-2026-09-14-event-driven-wakes-goal-campaign.md)

Vision: [Event-driven wakes](docs/event-driven-wakes.md)

Acceptance target:

- A provider-neutral signal module arms, ingests, evaluates, and explains
  filesystem and GitHub events without provider logic leaking into dispatch.
- Durable receipts, deduplication, checkpoints, reservations, and recovery
  prevent missed or duplicate wake transitions across restarts.
- Existing wake predicates and target transports retain their documented
  behavior through a versioned compatibility path.
- GitHub Issues, short-lived branches, pull requests, CI, and the active-lane
  catalog provide shared coordination and custody evidence.
- Bounded subagent use and measured model routing reduce accepted-slice cost
  without weakening correctness, safety, or delivery evidence.

## P49 | Installed Filesystem Wake Canary

State: CLOSED

Current State: Issue #30 is ready for one isolated installed-candidate service
and one live tmux dispatch. The global `0.5.2` uv-tool installation and normal
repo wake root are observation-only. The candidate service, wake root, marker,
and venv use exact P49-only identities and must be removed after evidence
capture. Provider access, public ingress, deployment, tag, and release remain
excluded. A pre-effect review found that schema-v2 filesystem registration
must first gain a supported one-attempt bound; the same lane will implement and
validate that prerequisite before any installed mutation.

Closure: Candidate `86291bf` completed the isolated live canary with one
verified filesystem match, one dispatch, hook acknowledgement, and
`visible_prompt_observed`. The canary found and repaired stale pending
republication after terminal submission. Verification 0073 records the test,
receipt, archive, complete rollback, and unchanged global/normal runtime state.

Plan: [Installed Filesystem Wake Canary](docs/dev/plans/0057-2026-09-14-installed-filesystem-canary.md)

Acceptance target:

- Bind the candidate source and wheel to one isolated active user service.
- Persist and enforce `max_attempts: 1` through the supported CLI and
  journal-authoritative record path.
- Arm `file.created` while absent and dispatch exactly once after the initiating
  turn becomes idle.
- Recover the same pending wake across a controlled service restart before the
  marker is created.
- Prove submitted status, hook acknowledgement, and visible prompt evidence.
- Archive and roll back the canary without global install, normal wake-root,
  supervisor, or unrelated service drift.

## P50 | GitHub CI Wake Productization And Installed Canary

State: CLOSED

Current State: Checkpoint `P50-G1-C12` accepts issues #34 through #37 and #45.
The production source is fixed-origin, bounded, read-only, positive-only, and
explicitly reports `GITHUB_COVERAGE_UNPROVEN`; it never promotes list exhaustion
or mutable `updated_at` into complete-history or completion-time evidence. The
supported CLI, daemon recovery, readiness, support, and installed-wheel paths
are canonical. Installed retry 3 observed successful run `34984194234`, matched
once, dispatched once with `visible_prompt_observed`, archived, and rolled back
without global-runtime drift. PR #56 merged its verified receipt at
`30c6f2d721d48cedcb12d0e55374369ece7645a4`; no P50 live effect remains.

Plan: [GitHub CI wake productization goal campaign](docs/dev/plans/0058-2026-09-14-github-ci-wake-productization.md)

Acceptance target:

- An explicit enabled-source registry and fixed-origin read-only client enforce
  repository, workflow, ref, conclusion, credential, and resource limits.
- Positive run-attempt evidence and history coverage are independently truthful;
  missing or delayed provider evidence never advances a false checkpoint.
- A supported `github-ci` recipe and daemon runner persist and recover the same
  wake, anchor, checkpoint, retry state, and source health across restart.
- Operator readiness and support surfaces remain bounded, sanitized, and
  explicit about recovery strength and degradation.
- One isolated installed candidate observes one exact post-anchor workflow
  completion, dispatches once with visibility evidence, archives, and rolls
  back without global or normal-runtime drift.
- Issues #34 through #37 integrate through pull requests and required CI; no
  webhook ingress, provider mutation, global refresh, deployment, tag, or
  release occurs.

## P51 | Local Runtime Event Wakes

State: CLOSED

Current State: Checkpoint `P51-G1-C11` accepts the runtime contract, exact
same-user process-exit wake, read-only user-systemd transition wake, shared
product lifecycle, and installed canary through issues #59 through #63 and PRs
#67, #71, #73, #77, and #79. The final installed receipt proves one exact
restart-recovered systemd transition, one acknowledged and visibly observed
tmux wake, archive, and complete isolated rollback without global or normal
runtime drift. The active-lane projection is empty and parent issue #58 closes
with the final coordination merge.

Plan: [Local runtime event wakes goal campaign](docs/dev/plans/0059-2026-09-15-local-runtime-event-wakes.md)

Acceptance target:

- Exact process and user-unit identities are authorization-bound and cannot be
  widened through a wake request.
- Runtime observations are read-only, bounded, restart-correct, deduplicated,
  and fail closed on ambiguity or backend loss.
- Process wakes never attach to PID reuse or claim unavailable exit code/time;
  systemd wakes never claim unseen transitions or acquire unit-control power.
- Supported CLI, daemon, readiness, status, support, packaging, and legacy
  compatibility surfaces remain truthful and tested.
- One isolated installed candidate produces one bounded visible wake, archives,
  and rolls back without global or unrelated runtime drift.

Completion evidence:

- Process wake canonical commit:
  `54311f35f9e3b6dd0c21be3d0beaa2eb443616a3`.
- User-systemd wake canonical commit:
  `f41ef0ba6d5b37ab85bea7a1cebbc9bd6b0ad748`.
- Productization canonical commit:
  `08447afdfe0384b23d73079e4579ca050dffe2c0`.
- Installed canary canonical commit:
  `00af8fa2142ce5adb102f48ba651c6a09c02df1b` and verification receipt
  [0077](docs/dev/verification/0077-2026-09-15-installed-runtime-wake-canary.md).

## P52 | Event Source Extension Framework

State: CLOSED

Current State: PR #89 accepted issue #82 at canonical `f8059cd`, freezing the
closed built-in source-family registry plus provider-free conformance fixture.
PR #93 accepted local-source migration #83 at canonical `3c30947`; PR #95
accepted GitHub migration #84 at canonical `e0d8862`. PR #99 accepted
productization #85 at canonical `2929d93`. Its shared catalogue inventory,
additive readiness/support projection, maintainer docs, and provider-free
installed-wheel conformance pass both Python 3.11/3.12 release gates. All four
child issues and implementation lanes are closed. No new source, provider
effect, live dispatch, arbitrary plugin loading, release, deployment, or global
installation refresh occurred.

Plan: [Event source extension framework goal campaign](docs/dev/plans/0065-2026-09-15-event-source-extension-framework.md)

Acceptance target:

- One immutable built-in source-family catalogue replaces source-specific
  daemon reconstruction branches without changing source semantics.
- A provider-free fixture proves extension, collision rejection, ordering,
  batching, failure isolation, recovery, and side-effect-free introspection.
- Filesystem, process, user-systemd, and GitHub CI sources preserve their exact
  configuration, authorization, anchors, retry, health, and recovery behavior.
- Readiness/support, documentation, and an isolated dispatch-disabled installed
  wheel agree with runtime registration.
- GitHub issues, short-lived branches, pull requests, CI, and canonical-main
  readback provide custody and acceptance evidence.

## P53 | Signed GitHub Webhook Ingress

State: CLOSED

Current State: Issues #104 through #109 are accepted. The bounded listener,
durable signed-ingest join, supported lifecycle, installed qualification, and
exact Cooper/bastion route are canonical. The separately gated live successor
created one exact `workflow_run` hook, squash-merged docs-only PR #133 as
`5f21ed1`, and accepted provider delivery
`80e50480-b201-11f1-9387-9a306ef1c969` for successful run `35138287516/1`.
The durable occurrence converged `0 -> 1 -> 1`; the wake moved pending to local
firing with dispatch disabled. The hook was deleted, the successor secret
retired, and the isolated service and root removed. Fresh readback shows no
hook, unit, process, or port-8820 listener. Retained failed predecessor evidence
remains owner-only and secret-free. Verification 0081 binds the accepted
receipt. No release, global install, ingress mutation, redelivery, or live
target dispatch occurred.

Plan: [Signed GitHub webhook ingress goal campaign](docs/dev/plans/0070-2026-09-16-signed-github-webhook-ingress.md)

Acceptance target:

- A dedicated loopback-first listener rejects ambiguous HTTP framing and
  untrusted proxy claims within fixed connection, byte, time, and shutdown
  budgets.
- Signed GitHub deliveries retain authoritative attempt reads, commit-before-
  ack, durable deduplication, restart correctness, and polling convergence.
- CLI, service, readiness, status, support, packaging, and owner-only secret
  references form one supported product lifecycle.
- One installed service, one exact Cooper/bastion HTTPS route, and one exact
  live GitHub delivery are independently proven and cleaned up or retained by
  explicit receipt.
- Public ingress exposes only the HMAC-authenticated webhook path; provider
  mutation and target dispatch remain separate authorities.

Acceptance state: P53 is closed and accepted at canonical `8171220`. Movement
is `outcome_progress`. The retained ingress route and predecessor evidence
remain unchanged; no P53 hook, secret, listener service, or isolated successor
root remains.

## P54 | Managed GitHub Webhook Wakes

State: OPEN

Current State: Reconciled 2026-10-10: parent issue135 and C5 issue142 remain OPEN;
C4 issue141 is CLOSED. The previous CLOSED roadmap label was premature.
This remains a separate campaign; historical packet narratives below do not
assert current installed/provider state. Issue #135 and Plan 0083 own the managed-production successor to
P53. The accepted P53 route, listener, journal join, authoritative GitHub
verification, and polling convergence are reusable foundations, but the live
hook, secret, service, and isolated root were intentionally removed. P54 must
add durable exact ownership, provider reconciliation, restart-correct secret
rotation, independent health/fallback, safe rollback, one retained activation,
and one separately gated visible dispatch. The approved child graph is #138
through #142. Issue #138 and Plan 0084 own the active provider-free ownership
and reconciliation slice. Final remediation checkpoint `d2de93e` implements its provider-free
binding store, ambiguity-safe reconciler, bounded GitHub.com administration
adapter, and dry-run-first CLI. Local focused, comprehensive, plugin,
compilation, and diff gates pass after addressing all eight initial independent
review findings and the final mismatched-UPDATE variant. Independent review
accepts checkpoint `93ba14a`. PR #143 passed both hosted gates and squash-merged
as canonical `a3b2c98`; GitHub closed #138. No provider, service, secret,
ingress, installation, release, or dispatch effect occurred in C1.

Plan: [Managed GitHub webhook wakes goal campaign](docs/dev/plans/0083-2026-09-16-managed-github-webhook-wakes.md)

Acceptance target:

- One owner-scoped, nonsecret binding and operation journal prove the exact
  repository, hook, callback, service, source, executable, desired generation,
  last observed state, and sanitized receipt history.
- Reconciliation is idempotent and crash-recoverable, classifies drift and
  collisions, and never repeats an ambiguous provider write.
- Secret rotation preserves source/journal/checkpoint identity, restarts into
  bounded dual-key acceptance, proves a new-key delivery, and safely retires or
  rolls back the prior generation.
- Local listener, provider delivery, polling coverage, and dispatch health are
  projected independently; polling remains the correctness fallback without
  duplicate occurrence or dispatch.
- One installed managed activation is intentionally retained and reversible;
  one later exact visible webhook-origin wake reaches one named target once,
  with canonical GitHub and verification custody.

Acceptance state: P54 planning and its five-child issue graph are canonical;
#138-#140 are closed and accepted on canonical main. C2 integrated at
`143b1d3`; C3 integrated at `b0d4a85`. C4's provider-free correction passed
680 Python tests, 12 plugin tests, provider-free qualification, independent
review, and both hosted gates before PR #152 squash-merged it as canonical
`f90b6c8`. The first live attempt froze that candidate and prepared an isolated
runtime plus owner-scoped local configuration, then stopped before the distinct
read credential gate with zero provider writes, service starts, ingress
mutations, or dispatches. Plan 0090's later rehearsal created one hook and
started one dispatch-disabled service pair, but the listener had captured the
pre-create binding generation; provider deliveries failed closed with HTTP 503.
The sole workflow rerun failed one timing-sensitive Python 3.11 test. Exact
disable/delete and local cleanup restored zero hooks, no port 8820 listener,
no C4 units, and zero dispatch. Receipt 0085 preserves the evidence. Plan 0091
owns a fresh-identity second successor that reconciles each provider hook before
starting its listener and preserves the durable repository-scoped read
credential. Plan 0091's corrected ordering then proved signed completed
delivery and passing hosted gates, but positive-only polling exhausted its
fixed 200-request ceiling while walking 334 retained workflow runs. Exact
rollback again restored zero hooks, services, listeners, and dispatch; receipt
0086 preserves the evidence and the durable read credential remains owner-only.
Plan 0092 landed the polling correction at canonical `f2a4c3c`; its v5
rehearsal proved signed delivery and one successful poll, then rolled back when
no pending wake remained to drive the required second cycle. Receipt 0087
preserves the clean rollback. Plan 0093 owns a fresh v6 successor with a
pre-armed nonmatching sentinel for recurring-poll proof. Its rehearsal passed
signed delivery, two polling cycles, sentinel continuity, and exact cleanup.
Retained hook `685366419` and its dispatch-disabled listener and poller remain
active after signed delivery, two fresh polling timestamps, one bounded
listener restart, and five HTTP-401 ingress readbacks. Receipt 0089 closes the
C4 execution lane through the final closeout PR; issue #141 remains open until
the merge-generated normal `main` occurrence supplies three current health
samples and the retained sentinel is cancelled. Dispatch remains excluded
until separately gated C5 (#142).

## P55 | App-Server Dispatch Readiness Correction

State: CLOSED

Current State: Complete on canonical `main` at
`781e4e7cff304d3189537b27c519fe60fcc01a6e` through PR #154. Supervisor
dispatch and owner-specific readiness, changed-unit repo-service restart, and
regression coverage passed local and hosted gates; issue #153 is closed as
completed. No live or installed-runtime effect occurred, and any rollout
remains separate.

Plan: [App-server dispatch readiness correction](docs/dev/plans/0088-2026-09-21-app-server-dispatch-readiness.md)

Acceptance target:

- Supervisor-owned app-server wakes consume the exact enrolled stable Codex
  command when the durable target omits one.
- Repo-service installation restarts an already-active daemon when its rendered
  unit changes, so the process environment cannot remain older than readiness.
- Monitor and doctor command readiness are derived from the actual dispatch
  owner and fail closed for missing or stale supervisor commands.
- Provider-free focused, comprehensive, plugin, compilation, planning, and
  hosted checks pass before canonical integration; no live dispatch, service,
  installation, provider, release, or deployment effect occurs.

## P56 | App-Server Readiness Installed Rollout

State: CLOSED

Current State: Accepted on the installed user runtime from canonical
`5aad4e0c4a44da0fd647d861cd2fd7bd73a55c9c`. The candidate wheel is installed,
the exact installed regression passes, the supervisor restarted from PID 1073
to PID 3278, and all four roots have fresh ready health. Doctor now attributes
the enrolled command to `supervisor_registry`; active/firing counts remain
zero. Verification receipt 0084 records the bounded effect and absent
dispatch, OpenClaw, provider, release, other-service, and other-host effects.

Plan: [App-server readiness installed rollout](docs/dev/plans/0089-2026-09-22-app-server-readiness-installed-rollout.md)

Acceptance target:

- Candidate and rollback wheels are built from exact Git refs and bound by
  SHA-256 before the installed tool changes.
- The installed candidate passes the exact supervisor regression, replaces the
  active supervisor process, and reports all enrolled roots ready.
- Doctor attributes the codex-wake root's app-server command to
  `supervisor_registry` while the repo-scoped service remains inactive.
- No live wake, OpenClaw, provider, release, other-service, or other-host effect
  occurs; failure performs one bounded rollback and records that outcome.

## P57 | GitHub CLI Credential Backend

State: CLOSED

Current State: PR #167 merged the same-user `gh` backend as canonical
`8ae3a024`. The canonical wheel is installed in user scope; its changed module
hashes and CLI default match the artifact. One supervisor restart left all
four enrolled roots ready. The retained #141 owner remains on its isolated
runtime and explicit limited token. Receipt 0090 records the qualification
and rollout; live multi-repository proof remains separately gated.

Plan: [GitHub CLI credential backend](docs/dev/plans/0094-2026-09-25-gh-auth-credential-backend.md)

Acceptance target:

- New GitHub CI sources and managed webhook bindings default to `GH_CLI`.
- Polling, signed delivery verification, and explicit provider operations
  resolve that backend without persisting token values.
- Explicit limited token references continue to work for headless or isolated
  service use.
- The canonical wheel is installed in user scope, and the installed CLI and
  credential resolver pass readback without changing the retained #141 owner.

## P58 | Generic HTTP/JSON Completion Wakes

State: CLOSED

Current State: Issue #169 and Plan 0096 are complete. PR #170 passed hosted
Python 3.11 and 3.12 gates and squash-merged as canonical `0cae470`; its main
CI run `36356569300` also passed both gates. AuraCall's existing HTTP status
envelope remains one compatibility fixture rather than a bespoke producer
contract. No live dispatch, service, installation, provider, release, or
deployment effect occurred.

Plan: [Generic HTTP/JSON completion wakes](docs/dev/plans/0096-2026-09-27-generic-http-json-completion-wakes.md)

Acceptance target:

- A fixed-origin HTTP/JSON job-status resource can produce one wake when a
  selected field reaches an allowed terminal value.
- The source is reusable across products; AuraCall works through its existing
  generic run-status API without a Codex-Wake-specific producer contract.
- Polling is bounded, restart-correct, deduplicated, credential-safe, and
  resistant to redirect, origin, response-size, and parsing failures.
- CLI setup/readback, signal journaling, readiness, and tmux/app-server routing
  reuse existing governed seams and retain only bounded selected metadata.

## P59 | Session-Aware Tmux Wake Routing

State: CLOSED

Current State: Issue #172 and Plan 0097 are complete. PR #173 passed hosted
Python 3.11 and 3.12 gates and squash-merged as canonical `f18ca5e`; canonical
main run `36364547676` passed both gates. Session-aware creation resolves the exact
Codex thread to its current tmux pane and stores the TUI client PID plus process
start-time ticks. Dispatch validates that process identity, finds a unique
relocated pane within the captured session, or falls back to the same exact
app-server thread; ambiguous and unavailable targets fail closed. All 713
Python tests, compilation, diff hygiene, and active/goal planning audits pass.
Issue #172 is closed. No live dispatch, installation, service change, release,
or deployment occurred.

Plan: [Session-aware tmux wake routing](docs/dev/plans/0097-2026-09-27-session-aware-tmux-routing.md)

Acceptance target:

- Tmux wake creation records durable thread and TUI client-process identity.
- A stale or reused pane never inherits delivery authority; one uniquely moved
  client is found within the captured tmux session.
- Zero pane matches uses exact-thread app-server fallback with existing writer
  and retry safety; ambiguity and unavailable fallback fail closed.
- Routing, acknowledgement, and visibility remain separate evidence axes.
- Provider-free focused and comprehensive tests, compilation, planning, and
  hosted checks pass before canonical integration.

## P60 | v0.6.0 Release And Deployment

State: CLOSED

Current State: Complete. PR #176 merged release preparation as canonical
`d0a277b`; main run `36365595386` passed Python 3.11/3.12 gates. Public latest
release `v0.6.0`, public-tag smoke, user tool install, all three skill copies,
and the OpenClaw plugin resolve to the release identity. The supervisor
restarted from PID `14250` to `68539` with all four roots ready. The repo
service remains inactive/disabled; active/firing wakes remain zero. Receipt
0092 records the result and the intentionally stopped OpenClaw Gateway.

Plan: [v0.6.0 release and deployment](docs/dev/plans/0098-2026-09-27-v060-release-and-deployment.md)

Acceptance target:

- Publish `v0.6.0` from an exact pull-request-integrated canonical commit after
  local and hosted release gates pass.
- Prove public-tag installation and refresh the user-scoped installed product,
  skills, and plugin source to exact release identity.
- Restart only the already-active user supervisor, keep the repo service
  inactive/disabled, and retain all four existing roots as ready.
- Record a durable deployment receipt with no live wake dispatch, provider
  mutation, OpenClaw Gateway start, or unrelated service change.

## P61 | Tmux Active-UI Safety

State: CLOSED

Current State: PR #179 is integrated as canonical `5abbc098`. Local validation
passes 24 focused and 716 comprehensive Python tests, 12 plugin tests,
compilation, diff hygiene, and planning audits; hosted Python 3.11 and 3.12
checks pass. Verification 0093 records a genuine AuraCall terminal receipt
delivered to and acknowledged by a disposable tmux Codex target with
`visible_prompt_observed` on the sole delivery attempt.

Plan: [Tmux active-UI safety and dispatch accounting](docs/dev/plans/0099-2026-09-29-tmux-active-ui-safety.md)

Acceptance target:

- Recognize active approval/confirmation UI without treating inert transcript
  words as interactive state.
- Preserve privacy-safe explainability and bounded fail-closed behavior.
- Do not consume an actual delivery attempt before any prompt paste.
- Pass focused, comprehensive, hosted, and separately authorized live checks.

## P62 | Session Discovery And Byobu Selectors

State: CLOSED

Current State: Historical discovery design was completed under Plan0100.
Released v0.9.0 adds qualified native session addressing and visible tab lifecycle
under P65; see Plan0127 completion audit. That acceptance supersedes the former
product-implementation-pending statement without reopening the historical plan.

Plan: [Session Discovery Verbs](docs/dev/plans/0100-2026-10-03-session-discovery-verbs.md)

Deliverables:

- Read-only `sessions list`, `show`, `resolve`, `current`, and `watch`.
- Exact Byobu tab/pane selectors with explicit ambiguity and binding evidence.
- Stable JSON observations and exact-thread resolution for future messaging.

## P63 | Local Agent-to-Agent Communication

State: CLOSED

Current State: Plan0119's requested remaining-gate packet is accepted in
verification0122: released v0.7.1 automatic exchanges, cancellation,
restart/reconnect, cross-root flow, rollback and a full thirty-minute soak passed.
Server-unloaded recipient and broader held-recovery obligations remain open.
P64 subsequently qualified/released v0.8.0 network time; P65 qualified/released
v0.9.0 native lifecycle. Those releases do not close the remaining P63 obligations.
The older readiness reconciliation note0010 is historical.
2026-10-10: Plan0138/0139 shipped explicit saved reopening, claim instructions
and ordinary tab cleanup; active0.11.1. Plan0140 diagnosis is complete, original
notification uncertainty preserved. Plan0141 now owns eight ordered completion
tickets, beginning with native live submission; recovery obligations remain OPEN.

Execution Plan: [Finish usable A2A — Plan0141](docs/dev/plans/0141-2026-10-10-a2a-completion-stream.md)
Usable-feature requirements: [Plan0119](docs/dev/plans/0119-2026-10-04-usable-live-a2a-successor.md)
Original requirements: [Agent-to-Agent System](docs/dev/plans/0101-2026-10-03-agent-to-agent-system.md)
Live baseline: [wakeA/wakeB round trip](docs/dev/verification/0111-2026-10-04-wakeA-wakeB-live-round-trip.md)

Accepted packet deliverables (verification0122):

- Unassisted live request, recipient notification/reply and sender resumption.
- Busy/draft/offline/exact-thread/cancel guards demonstrated in real sessions.
- Same-thread worker restart and durable reply suspension.
- Normal installed CLI/service, enrolled cross-root flow and release/rollback.

Remaining scope: server-unloaded-recipient and broader held-recovery obligations.
Current target bus/guard/bindings/worker must be read back before claiming present
readiness; network-time activation is tracked under P64.

Final2026-10-10: all Plan0141 tickets and original Plan0101/0119 requirements
accepted. Released/active0.12.0/10c8a58; see plan0149/closeout.md for exact evidence,
limits, rollback and cleanup. Older remaining-scope statements above are history.

## P64 | Network-first Time for Wake and Mailbox Deadlines

State: DONE

Current State: Plan0122 revision2 COMPLETE. PR225 integrated edf2aea, published/installed v0.8.0,963 comprehensive tests and both hosted release gates pass. Three admitted plain-NTP operators retain quorum under each controlled single loss; installed native A→B→A proof verifies exact correlation/digest, submitted arm and bounded worker finish. Owned demo is paused/backed up and clients stopped; no old checkpoint reset. Authentication/additional-profile limits remain explicit follow-up, not hidden activation claims. Evidence: docs/dev/evidence/plan0122/activation/requirement-audit.md.

Parent design: [Plan0122](docs/dev/plans/0122-2026-10-08-network-first-time-provider.md).

1. [Plan0123: Network inspection](docs/dev/plans/0123-2026-10-08-network-time-inspection.md) — DONE; isolated inspection evidence recorded.
2. [Plan0124: Healthy Windows fallback](docs/dev/plans/0124-2026-10-08-healthy-windows-time-fallback.md) — DONE; health-qualified inspection fallback.
3. [Plan0125: Mailbox uncertainty recovery](docs/dev/plans/0125-2026-10-08-mailbox-time-uncertainty-recovery.md) — DONE; versioned migration and disposable outage/fault acceptance.
4. [Plan0126: Wake acceptance](docs/dev/plans/0126-2026-10-08-time-provider-wake-acceptance.md) — DONE; isolated installed workflow, review and release/rollback evidence.

After 0123, fallback and mailbox tracks are technically independent; the single-owner lane executes them serially. Acceptance is serialized after both. No source ticket implies live activation or historical clock root-cause proof.

## P65 | Native Codex Delivery and Wake Lifecycle

State: CLOSED

Current State: All five tickets and normal installed lifecycle pass. PR228 integrates final source/evidence as a686c7b; hosted PR/main Python3.11/3.12 gates pass. Publicv0.9.0 tag and downloaded artifacts are verified.983 frozen installed tests pass; audit repairs, migration/rollback, guarded close and owned-fixture cleanup pass. Final requirement audit is docs/dev/evidence/plan0127/completion-audit.md. Other project legacy readers and unrelated local work remain preserved.

Execution authority: [Plan0127](docs/dev/plans/0127-2026-10-09-native-codex-wake-product-boundary.md). Tickets0128–0132 are DONE. Source/release qualification is complete; docs/plan127-completion carries the final closure projection. P63's separate retained recovery obligations are unchanged.

## P66 | Native Network-time Parity

State: PLANNED

Current State: Approved governing Plan0133 and tickets0134–0136. No successor
implementation or installed acceptance has run. Reuse P64 time policy throughout
P65 native deadline handling; P63 retained obligations remain separate.

Execution Plan: [Plan0133](docs/dev/plans/0133-2026-10-10-native-network-time-parity.md).
Order:0134 arming →0135 evaluation/recovery →0136 installed acceptance.
The ready frontier contains0134 only. Rejected uncertain-time arms create no wake;
armed wakes retain deadlines during time holds.

## P150 — Policy routing and gov_policy pilot

CLOSED Plan0150 / issue237: reconcile policy pointers and admit one read-only scoped
policy-maintenance profile with canonical fallback and deterministic CI guard.
Tool qualification complete; total host-token efficiency remains unmeasured.

## P75 — Discoverable agent-to-agent MCP

State: CLOSED

Plan0151 / issue240: v0.13.0 published, verified and installed; 14 MCP tools
registered and qualified, human guides and installed agent skills advertise
tracked exchanges. Existing A2A acceptance remains CLOSED. New sessions must
discover the tools; messaging still requires operator-issued actor context.
Evidence: docs/dev/evidence/plan0151/closeout.md. Gov_policy evaluation deferred.

## P153 | Wake intent and time recovery

State: CLOSED

Issue243 / [Plan0153](docs/dev/plans/0153-2026-10-11-wake-intent-time-recovery.md):
DONE. PR244/241d7a4 integrated; v0.13.1 published/download parity/activated.
Matt setup/default labels applied and current StableTime adapter preserved.
Contract2.0 finite bounds supported, original expiry never rebased.1072 full
source OK/two skips;45 affected checks, two optional MCP tests and installed MCP
smoke PASS. Seven live daemon roots support schemas1–6; supervisor upgraded;
all70 records accounted for; independent webhook and root alternative preserved.
Acceptance: docs/dev/evidence/plan0153/final-acceptance.md. No incident replay.

## P154 | A2A response standards

State: CLOSED

[Plan0154](docs/dev/plans/0154-2026-10-11-a2a-response-standards.md): documented
TUI/local output versus sender replies, inbox-only returns, no-reply notices and
explicitly authorized third-party handoffs. Bundled and two installed skills
include the [response standard](skills/codex-wake/references/a2a-responses.md).
Existing MCP/CLI/worker contracts unchanged. Eight-scenario review and installed
parity: docs/dev/evidence/plan0154/review.md. No live model-compliance claim.

## P156 — Governed agent lifecycle

CLOSED Plan0156 and children0157–0159; issues248–251 and254–257 completed.
PR253 merged3bde6d5; v0.14.0 released/installed from exact main. Owned spawn,
configured same-thread refresh, both-mode native handoff/continuation/rollback,
selected full instructions and substantive review, nested budgets and bounded
correction are qualified. Original failures/deadlines/accounting retained.
Installed public fixtures cover non-GitHub selection and replacement/restart
bounds; released CLI/MCP/skills and cleanup pass. No shared daemon restart or
implicit grant/claim transfer. Final matrix: docs/dev/evidence/plan0156/final-acceptance.md.

## P160 | Explicit A2A return obligations

State: CLOSED

[Plan0160](docs/dev/plans/0160-2026-10-14-a2a-return-obligations.md) completes a
local standards follow-up to P154: mandatory return/wait owners, verified reply
arm before yielding, bounded observation and timeout checkpoints, recipient
reply-admission and requester result-read gates. Bundled and installed skills
aligned; PR259 merged as b4e2eb7 and deployed to both installed skill roots
with four-file parity. Both hosted CI gates pass; source worktree closed. No
runtime enforcement or live model-compliance proof. Review: docs/dev/evidence/plan0160/review.md.

## P161 | Repository custody reconciliation

State: CLOSED

[Plan0161](docs/dev/plans/0161-2026-10-14-repository-reconciliation.md) / issue260:
reconciles current worktrees and published checkpoints, registers P156/P160,
repairs duplicate P72 policy-pilot identity as P150, and retires archived Plan127
checkout after fresh zero-CWD-owner readback. Lifecycle PR253 remains draft with
shared ROADMAP/RUNBOOK conflicts and open acceptance; active owner retains it.
Receipt: docs/dev/evidence/plan0161/reconciliation.md.

## P162 | MCP informal tab targeting

State: CLOSED

Issue262 / [Plan0162](docs/dev/plans/0162-2026-10-14-mcp-tab-targets.md):
PR263/88f008d and corrective PR265/1ee7229 integrated. Released/activated0.15.1;
99 Python files, both skill roots,19-tool MCP and owned tab-only/fresh/exact resume
qualified. Hosted3.11/3.12 gates passed (1,231 unit tests). First0.15.0 startup
race/rollback retained; superseded prerelease preserved. Shared services and
unrelated sessions unchanged. Current clients need resource refresh for schemas.
Receipt: docs/dev/evidence/plan0162/final-acceptance.md.


## P163 | Lifecycle discovery and onboarding

State: CLOSED. Owner: primary / ecochran76. Workflow: DONE.
Issue267 / [Plan0163](docs/dev/plans/0163-2026-10-14-lifecycle-onboarding.md) polishes existing
README, lifecycle quickstart and agent skill for released spawn/refresh/handoff.
Depends on integrated P156/P162; no runtime changes or blockers. Acceptance:
CLI/MCP templates, accurate release claims, links and installed skill parity.

P163 delivery: PR268 merged72b1e5e after both required gates; issue267 closed.
Both installed skill roots synchronized to all five merged files with backups;
runtime stays0.15.1, no client/service restart. Exact receipts in Plan0163 evidence.


## P164 | Wake emergency controls

State: CLOSED. Owner: primary / ecochran76. Workflow: DONE.
Issue271 / [Plan0164](docs/dev/plans/0164-2026-10-15-wake-emergency-controls.md):
scoped inventory/cancellation, persistent pause/resume and separate owned-turn
interrupt, with CLI/MCP parity. Depends on integrated P156/P162/P163.

P164 delivery: PR272 merged d3ea192, v0.16.0 published/installed; final hosted
1268 tests and all release gates pass. Global inventory now13 service-owned roots,
9 upgraded existing readers, no duplicate supervisor monitoring. Exact source,
release/install/census and preservation receipts in Plan0164 final acceptance.

## P166 | Strict objective execution enforcement

State: CLOSED. Owner: primary / ecochran76. Workflow: DONE (released v0.17.0).
Spec #274, tickets #275–278 / [Plan0166](docs/dev/plans/0166-2026-10-16-objective-enforcement.md).
Final source `4ce6ae5` on `feat/objective-enforcement`; all four tickets are validated.
One whole-branch review and bounded remediation are complete. Native containment,
deadline, accounting, concurrency, refresh, renewal and successor evidence is retained.
The final full suite passed 1,326 tests with one optional host skip; installed-package
and live-host selection passed all 69 checks. Sampled token limits, unknown overshoot
and the failed local provider-turn count axis remain explicit. PR280 merged3cdc037; v0.17.0 released and installed. Strict first bootstrap
remains operator-provisioned.

## P167 | Resource enforcement discoverability and existing-session supervision

State: CLOSED. Owner: primary / ecochran76. Workflow: DONE.
[Plan0167](docs/dev/plans/0167-2026-10-17-resource-enforcement-discoverability.md),
work item #279; PR280 merged3cdc037 and released/installed v0.17.0. Existing dev
sessions use MCP enrollment, independent checkpoint then native goal pause and
exact-turn interrupt. Limits persist until explicit user reset. Native/control
and accounting acceptance passed; final CI1,351tests on both Python versions.
Host history-index blocker F2 resolved. Production controller heartbeat is fresh,
no goal enrolled/reset; existing clients need MCP refresh. Native stop scope is
the registered session only. Strict bootstrap remains separately operator-owned.

### P167 follow-up | Visible and actionable supervision

State: READY. Owner: primary / ecochran76. Work item #343; children #344–#346.
[Operator UX contract](docs/dev/plans/0173-agent-harness/goal-limit-operator-ux.md)
covers self-service watcher engagement and visible startup confirmation, interrupting
model/operator notices, and explicit allowance extension/window reset. This is new
follow-up scope; the shipped P167 enforcement history above remains unchanged.
Source/presentation implementation and installed acceptance are still pending.

## P168 | Operational self-refresh

State: OPEN. Owner: primary / ecochran76. Work item #282,
[Plan0168](docs/dev/plans/0168-2026-10-18-self-refresh-operational.md).
Repair the gap between shipped refresh discovery and actual host/client readiness.
Native resource reload, idle self-call deferral and exact caller scope are
qualification gates. No counter reset or shared-server restart.
v0.17.2 timeout repair released/installed from cdb499e; production intent remains
terminal without reload. A new attempt needs explicit new-expiry authority and
an idle window; actual native resource proof remains OPEN.
v0.17.3 additionally repairs fractional reserve input and clarifies exact newcaller
grants; no automatic grant inheritance or resource renewal is implemented.


## P169 | Verified resource allocation provisioning

State: COMPLETE. Owner: primary / ecochran76. Issue #289 CLOSED after PR298
75e7d9f and both required CI gates. Installed0.18.6, real-agent checkpoint/pause
and independent historical accounting acceptance passed. Historical timeout RPC
is unrecoverable; existing-connection refresh remains P168/#282.
[Current checkpoint](docs/dev/plans/0169-2026-10-18-objective-allocation-provisioning.md).

## P170 | Retrospective runtime and workflow safeguards

State: CLOSED. Owner: primary / ecochran76. Issue #299.
[Plan0170](docs/dev/plans/0170-2026-10-20-retrospective-safeguards.md).
Bounded controller maintenance, immutable first-stop evidence, reusable real-agent
acceptance preflight, static undefined-name gate, conservative evidence-only CI
and a short skill router. PR300 merged56cf6eb;0.19.0 installed,17installed checks
and fresh MCP identity passed. Existing allowances/latches and shared daemon preserved.


## P171 | Stable-time native counter handoff

State: CLOSED

Current State: PR303 merged, v0.19.1 released and installed; required CI/local
regression and original installed idle/busy native exchanges pass.
Plan: [Plan0171](docs/dev/plans/0171-2026-10-20-native-counter-handoff.md).

## P172 | Multi-runtime wakes and agent exchanges

State: OPEN

Recorded delivery boundary: the historical milestones below record MR-01–MR-06
candidate acceptance, PR306 integration and PR309 release preparation. Their
earlier intermediate "integration pending" statements are historical. This edit
adds no new release, production or wider native-control acceptance.

### Historical milestone evidence

Owner: ecochran76. Local intake CW-MR-172; no GitHub issue posted.
Plan: [Plan0172](docs/dev/plans/0172-2026-10-22-multi-runtime-wake.md).
The user-approved direction adds exact open-Grok TUI wakes and bidirectional
Codex/Grok A2A through a shared runtime delivery seam. Default wait, explicit
queue/interrupt modes and separately qualified terminal fallback preserve exact
recipient identity, deadlines and evidence strength. Same-host first release;
broader lifecycle/resource support and other runtimes follow.
Current packet is a specification and six dependency-aware local ticket drafts.
MR-01 qualifies Grok's exact live-session route before adapter implementation.
The first MR-01 wave used two disposable TUI launches, zero conversation
submissions and no subagents (all other tickets blocked). Both required Grok
sign-in. Native protocol availability is observed; no live delivery route is
qualified by that first run.
Authenticated rerun now qualifies one managed-launch terminal-observed route
with same-session response and fresh cleanup. MR-01 DONE. MR-02 now DONE for
the version1 Codex runtime seam, with full-suite and isolated-wheel controls.
MR-03 DONE for source/isolated artifact: isolated-wheel118 controls, live exact
Grok wake/reply with one attempt/no replay/clean teardown, and final frozen1438
suite PASS/one expected skip in462.612s. Test-only repair9fd40a0 preserves guards;
all119 production modules match the frozen live-qualified wheel. Earlier failures
remain retained. MR-04/MR-05 subsequently DONE for source/isolated artifact after parallel
implementation and primary reconciliation. Frozen1451 PASS341.346s/one expected
skip, unchanged source/tests; final installed changed-axis15 PASS. MR-06 DONE for installed candidate: real bidirectional TUI acceptance PASS;
full1455/one expected skip and installed61 PASS. PR306 integrated at dbc2dff;
Python3.11/3.12 release gates PASS. Release/production remain separate.
for real TUI/bidirectional live acceptance. Native Grok caller attestation, Codex
terminal fallback and strict queue/interruption remain unqualified/refused.
[MR-03 evidence](docs/dev/verification/0172-2026-10-22-mr03-grok-wake.md).
Main integration/release/production
installation remain separate; native Grok control/A2A receipts stay unqualified.
[MR-02 verification](docs/dev/verification/0172-2026-10-22-mr02-runtime-seam.md).
Preserve P168/#282 and existing controllers.

Plan0172 release preparation: issue308 tracks candidate0.20.0. REL-01 packaging
and independent REL-02 notes accepted; source/wheel/installed121 modules match,
provider-free MCP/wake-control/product smokes pass. REL-03 candidate preparation
DONE: PR309 sourcehead0f890c7 passed Python3.11/3.12 CI40048872250; final closure
commit remains subject to normal PR integration checks.
No public release or production rollout.


Agent harness planning backlog: [Plan0173](docs/dev/plans/0173-2026-10-23-agent-harness-backlog.md)
consolidates the post0.20.0 feature discussion into32 local TRIAGE drafts. Shared
ownership, coverage, hard dependencies and write-collision constraints are
separate. HF-01 is the next shared-contract grill; after it, HF-02 inventory,
HF-07 task/context and HF-13 wake durability form the first parallel frontier.
No implementation or new GitHub issue publication is authorized by these drafts.

2026-10-24 HF-01 design resolved: seven scenario decisions recorded in Plan0173.
Next interview frontier: HF-02 inventory, HF-07 task briefs and HF-13 wake durability.
No feature implementation authorized by interview completion alone.

2026-10-24 frontier interview: HF-02 configurable self-enrollment/operator
unenrollment and HF-07 brief revision rules resolved. HF-13 lifetime accepted;
recipient startup is an independent configurable axis; two policy defaults remain
pending. HF-06 must consume the other agent's host-policy repair, not duplicate it.

2026-10-24 HF-13 follow-up resolved: configurable owner-end retirement default
and configurable create/load/run startup default for new wakes. HF-02/HF-07/HF-13
product interviews are resolved; next work is bounded technical design/handoffs.

2026-10-24 first-frontier specifications drafted: HF-02 inventory, HF-07 task
briefs, HF-13 wake policy. Review public seams and existing three-ticket boundaries
before canonical GitHub publication. #310 owns the parallel self-access repair.

2026-10-24 approved first frontier published: HF-02 #315, HF-07 #316, HF-13 #317.
All three are ready-for-agent with no mutual blockers. Implementation not started;
primary retains shared hub integration and #310 overlap coordination.

2026-10-24 first frontier source complete: #315/#316/#317 closed after acceptance.
One two-axis review and one TDD remediation pass complete; PR326 final CI/integration
pending. Remaining28 feature tickets retain their own interview gates.

2026-10-24 HF-06 common permissions source complete: #320–#325 closed,
stacked PR327 on PR326. One broad Standards/Spec review and one bounded TDD
pass repaired assignment revocation checks and contextual approval inspection.
Installed acceptance #310 and runtime gaps #318/#319 remain open; no production
policy changes, deployment or resource renewal.

2026-11-02 product correction #380: [Plan0195](docs/dev/plans/0195-2026-11-02-product-acceptance.md)
owns Wake public account/daemon/import implementation and UID1017 demonstration.
Plan0190 source acceptance remains historical; Plan0194 live acceptance stays
open. Working-account activation is withdrawn; no working runtime effects.

2026-11-02 Plan0195 isolated-product acceptance complete at3f4052b: actual native
UID1017 accounts/daemons/TUIs/import/peer-preserving lifecycle and explicit rollback
pass, with local3.12 full and3.11 presubmit qualification. Source remains local and
unmerged; Plan0194/#380 authenticated live acceptance and any working-host effects
retain their separate gates. No memory write or old-job/goal resume.

2026-11-02 account-onboarding follow-up: Plan0196 adds local `accounts login/status`
after the operator rejected manual native-home/executable steps. Existing #380
live gates and Plan0195 frozen acceptance remain separate.

2026-11-02 Plan0196 complete: named local account login/status wraps native sign-in
and persists account credential-store provenance. Source2a82619;42focused checks
per supported Python plus installed UID1017 status/synthetic login pass. Human
OpenAI confirmation and working-account activation retain their own gates.

Command discoverability and CLI/API/MCP consistency: operator-confirmed design in
[Plan0197](docs/dev/plans/0197-2026-11-02-command-contract.md), LOCAL-0197.
Historical design state: PLANNED; accounts/daemons/history first, with generated help/reference,
automatically installed Bash/Zsh completion and explicit transport exceptions.

Plan0197 complete on local integration branch feat/command-contract-0197: five
local tickets DONE, review1/TDD1 complete, exact final installed fixture passed.
Accounts/configuration/builds/daemons/history are the first22operation contract;
remaining command families are explicitly deferred. Subsequent delivery: PR461
integrated this contract; PR462 package deployment is recorded below.

[Plan0198](docs/dev/plans/0198-2026-11-02-account-shortcuts.md) / LOCAL-0198 owns
open/resume, recent-history viewing and source-preserving recent batch copying.
Stacked on validated Plan0197; no working launcher or plain codex replacement.

Plan0198 / LOCAL-0198 DONE locally: open/resume shortcuts and recent copies
qualified with actual native UID1017 clients/daemons; sourcebdb2114. Plain codex
stays stock. Subsequent PR462 integrated `76ac7d9`; the exact238-member package,
completion/default root and real-account read-only recents were deployed.
[Deployment receipt](docs/dev/evidence/plan0198/deployment.json). No live copy/model
turn or blanket account/native acceptance is implied.

## P200 | WSL Session Control For codex-bots

State: CLOSED

Current State: Children #467–#476 are validated and closed. Installed Codex and
owned headless Grok workflows passed. One broad review and one TDD remediation
pass are complete; final local Python matrices, installed compatibility checks
and cached four-entrypoint presentation checks passed. One original intermittent
PowerShell bootstrap failure remains unattributed and is retained. Source
integration is tracked by Wake PR477 and Bots PR74; working deployments remain
unchanged. Qualification and review artifacts carry exact evidence and limits.

Plan: [WSL session control](docs/dev/plans/0200-2026-11-03-wsl-session-control.md)
Execution custody: [dependency ledger](docs/dev/plans/0200-execution-ledger.json)

Grok execution slice: [owned ACP session control](docs/dev/plans/0201-2026-11-03-grok-local-session-control.md).

Native release driver (closed local integration): [Plan0204](docs/dev/plans/0204-2026-11-06-native-release-driver.md) records six closed tickets, Cargo Signal execution, real-client/native acceptance and one reviewed remediation pass. Merge/deployment and comprehensive-suite qualification remain separate.

Plan0204 deployment: PR486 merged at5fd4aeb; Wake release-driver commands installed with automatic completion. [Deployment and rollback receipt](docs/dev/evidence/plan0204/deployment.json). Native Codex processes preserved.

## P205 | Stock shared home and independent profiles

CLOSED implementation/qualification: [spec #488](https://github.com/CochranResearchGroup/codex-wake/issues/488), tickets #489–#495. [Plan0205](docs/dev/plans/0205-2026-11-06-stock-home-and-independent-profiles.md): private seeding/adoption, explicit sync/snapshots, installed transport parity and two real accounts qualified. One review/one TDD pass resolved four blockers. PR496 merged and exact main prefix deployed; compatibility launchers repaired, completed worktrees/build copies reconciled. Plain stock/native sessions preserved. No comprehensive-suite claim.

## P206 | Stable user controller defaults

CLOSED: [#498](https://github.com/CochranResearchGroup/codex-wake/issues/498), [Plan0206](docs/dev/plans/0206-2026-11-07-default-controller-location.md). PR499 merged/deployed; canonical user controller, remembered account defaults and repaired shell launchers require no root exports. Native history/auth/journals and stock preserved; no-root CLI and Windows checks passed.

## P208 | Controller specification and hardening review

Review complete: [LOCAL-P208](docs/dev/plans/0208-2026-11-07-controller-hardening-review.md).
Reconciles existing harness/controller/session/profile tickets, two installed tab
failures and missing observer wiring. Proposed HARD-01–10 remain local TRIAGE;
first outcome is useful no-root workspace listing and installed grouping/undo.
No new runtime changes or provider acceptance were performed.

## P209 | Trait-based tab and session hardening

State: CLOSED implementation/qualification — all13 scoped tickets validated,
one broad review and one bounded TDD remediation pass complete. [Spec503](https://github.com/CochranResearchGroup/codex-wake/issues/503),
[plan](docs/dev/plans/0209-2026-11-07-trait-based-tab-hardening.md),
[execution ledger](docs/dev/plans/0209-execution-ledger.json).

Tickets504–515 and reused368 are validated and closed on
`feat/tab-hardening-503`;514 records exact installed WSL/actualPowerShell/public
CLI/API/MCP and real Byobu/nativepsmux acceptance. Three accepted behavior
findings are resolved; two P3 design notes remain nonblocking backlog. Traits, saved views/groups,
bounded monitoring, manual lifecycle, opt-in sorting, exact reattachment and
workspace recovery reuse the existing operation/native ownership. Stock and
production Wake remain unchanged. Existing broad governor/activation/handoff
parents retain their own unresolved acceptance.

Exact source/package/installed/native evidence and retained failed fixtures live
under [Plan0209 evidence](docs/dev/evidence/plan0209/). No new provider prompts,
working native restart, merge or deployment is included in this packet.

## P210 | Wake-owned tab formatting

Implemented and locally qualified on `feat/tab-formatting-517`:
[LOCAL-P210](docs/dev/plans/0210-2026-11-08-wake-owned-tab-formatting.md).
All seven implementation tickets closed; one review and one TDD pass resolved
four findings. Byobu/tmux and psmux share one WSL owner, with type/state styling,
manual holds and exact one-command rollback/re-enable. Installed native PowerShell,
CLI/API/MCP controls qualified. PR #525 merged as cb7cf62 and its exact qualified wheel is deployed.
Native Windows service hosting remains a later milestone using the same contracts,
providing Windows-startup availability independently of WSL.

P210 extensibility direction: plan Claude Code and custom/open harness adapters,
custom model identities and Ollama/local inference providers as distinct traits.
Common display policy should support new identifiers/capabilities without
hard-coded harness/model combinations. Runtime support and control capabilities
require separate adapter qualification; they are future milestones.


## P211 | Terminal session CRUD and criteria-based relocation

CLOSED implementation: [LOCAL-P211](docs/dev/plans/0211-2026-11-09-terminal-session-management.md).
All eight tickets #527–#534 closed; one review and one TDD remediation pass resolved
four findings. Named session CRUD, discovery, durable empty definitions, bot reuse,
criteria-based relocation and opt-in routing are implemented with CLI/API/MCP
parity. Installed Linux/native PowerShell and native psmux lifecycle/cwd qualify.
Native psmux custom argv/profile defaults and cross-server moves remain unsupported.
PR535 merged as bae92f9; the exact qualified package is deployed with completion
and local controller cutover verified. Windows-native service remains separate.
See the plan's final report and deployment receipt.


## P212 | Native mailbox host bootstrap

Source implementation complete: [LOCAL-P212](docs/dev/plans/0212-2026-11-09-native-mailbox-bootstrap.md).
Opt-in host delegation provisions separate actors for verified native callers in
already enrolled roots; shared MCP no longer needs a fixed per-thread capability.
Public question/claim/reply and installed package fixture qualify. PR536 merged
as74d6ea7 and the exact wheel is deployed. Shared MCP host delegation is configured
and actual native mailbox self-registration/inbox pass; real FigureLabs T06
question/claim/reply remains separate.

## P213 | Formatting throughput and STALE hardening

[LOCAL-P213](docs/dev/plans/0213-2026-11-09-tab-formatting-throughput.md) OPEN.
Native process churn and per-tab durable saves reproduced/fixed at source; private
42tab refresh1.143s. Original production rollback/monitor stop preceded PR537 deployment and the
later P214/P215 display evidence. P216 subsequently records monitor qualification;
P223 later records disabled automation. The plan remains OPEN pending explicit
remaining-scope disposition, not a new duplicate implementation chain.


## P215 | Named muted tab palettes

[LOCAL-P215](docs/dev/plans/0215-2026-11-10-tab-color-presets.md) CLOSED.
Slate/Dusk/Graphite presets shipped via PR539/7010cbe. Slate active fordefault,
44nativewindowreadbacks verified compact/noSTALE and subduedselection. Named
presets persist through shared configure and originalrollbackcustody. Automatic
monitor remains stopped pending separate loaded-host cycle qualification.

## P216 | Efficient tab observation and stable formatting

State: CLOSED

Plan: [Efficient tab observation](docs/dev/plans/0216-2026-11-10-efficient-tab-observation.md).
Specification [#540](https://github.com/CochranResearchGroup/codex-wake/issues/540) remains open.
All541–547 closed. PR551 merged/deployed; operational title-pin fix552/PR553
merged/deployed; compactcue tweak555/PR556 now0.22.0.dev5 18f1e73. Slate and1stick sharedmonitor enabled46tabs,
freshsnapshot,noformattingfailures. RealCLI rollback/restoration andreenable pass;
originalcurrentnamespacebaseline preserved, historicalbaseline archived privately.
315installedmembers/ninelaunchers/completion/accounts/nativeagents verified.
100tab resourcequalifications and dev4 performancecarry boundaries remain explicit.
Evidence: docs/dev/evidence/plan0216/deployment.json. No harness/provider effects.

Canonical reconciliation: #541–#547 were re-read CLOSED and parent #540 OPEN.
The later local OBS aliases are superseded; they do not reopen canonical child
acceptance. The original46-tab receipt remains valid historical evidence; a
supplemental43-tab run with3natural native transitions neither replaces it nor
proves stock/modded parity or current100-tab performance. See
[canonical mapping](docs/dev/notes/0216-2026-11-12-canonical-acceptance-reconciliation.md).
The enabled46-tab narrative above describes the dev5 milestone; later P223
records automation disabled and is not reversed by this patch.


## P217 | Human-friendly CLI output

[LOCAL-P217](docs/dev/plans/0217-2026-11-10-human-cli-output.md) CLOSED.
PR549 merged1a651e0; exact0.22.0.dev3 Python package deployed, readable accounts
and explicit JSON verified, fresh Zsh completion registered. Nine launchers,
305package members,22native processes and10protected files verified. Six inactive
checkouts archived with refs retained;50stale registrations pruned. Native owners,
stock and existing monitor/server state preserved; initial full-run setup error
and passing installed correction remain explicit in qualification evidence.


Stable tab management repair #563 / Plan0218: CLOSED. PR565 merged c9f220d8;0.22.0.dev6 deployed with freshSlate monitor. Ordering/physical grouping,transfer/undo/reconciliation and populated deletion now ignore display-metadata churn while retaining meaningful guards. Exact qualification and deployment: docs/dev/evidence/issue0563/. Native Windows qualification and saved-group cross-session policy remain separate.


## P220 | Usable governor and native /wake
CLOSED:#570 and tickets571–574. Plan0220 exact nativev4/Wake accepted in UID1017; one review and one bounded TDD pass complete. No merge/deployment.

### Plan0220 retrospective follow-ups

READY backlog: #576–581. [Findings and action index](docs/dev/evidence/plan0220/retrospective.md).
Plan0220 implementation is complete; these remain separate follow-up hardening.
Reuse existing preflight/summary tooling and preserve the no-paid-CI boundary.

## Native active-tab service-context repair

CLOSED (local source diagnosis): [Plan0220](docs/dev/plans/0220-2026-11-11-native-active-tab-executable.md).
Current state: deterministic missing-PATH reproduction and source regression/fix
qualified;233 related tests and staged-wheel service-context probe pass. Operator-approved installation and one actual automatic continuation now pass;
separate protocol acknowledgment fields remain unobserved.

Plan0220 publication: source reviewed and locally qualified through broad tests
plus focused retention-fixture remediation (see note0220); PR575 integrates the
exact installed product code. No remaining scoped source/installation/delivery
gate; independent protocol acknowledgment fields remain unobserved.

## P221 | Formatting after terminal server replacement

CLOSED (PR582 merged; 0.22.0.dev8 installed): [LOCAL-P221](docs/dev/plans/0221-2026-11-11-tab-format-reboot.md).
Explicit enable establishes namespace-specific originals while retaining earlier
baselines; automatic refresh and rollback remain fenced. UID1017 qualification
and working45-tab acceptance PASS; native services unchanged.

## P222 | Automatic tab formatting startup recovery

CLOSED (PR584 merged; dev9 installed and startup enabled): [LOCAL-P222](docs/dev/plans/0222-2026-11-11-tab-startup-recovery.md).
Owned user-service startup plus explicit opt-in namespace recovery; preserve
originals and disabled/paused custody. No host reboot or agent launch.

## P223 | Native tmux subscription crash containment

CLOSED (PR587 merged; dev10 installed; automation remains off): [LOCAL-P223](docs/dev/plans/0223-2026-11-11-tmux-subscription-crash.md).
Formatting/startup disabled and originals restored; remove the monitor's native
wildcard subscriptions after reproducing whole-server loss on tmux3.4.

## P224 | Governor release and working deployment

CLOSED: PR586 merged32eb90fb; dev11 installed and exact native4712 selected for
six configured future modded launches. Two idle package selections updated;
controller/supervisor refreshed,13 fresh roots and existing hold preserved.
All14 temporary pauses restored; existing stock clients and disabled automation
preserved. Plan0224 and docs/dev/evidence/plan0224/deployment.json own evidence.

## Native launcher continuity — P0226

State: CLOSED

[Plan0226](docs/dev/plans/0226-2026-11-12-native-launcher-continuity.md) closes the
bounded launcher repair, approved dev13 CLI installation and overdue recovery
verification. PR592 merged;97installed checks and3installed launcher regressions
pass. Current caller MCP reportsdev13. Reviews8/9 completion artifacts match
exact successor/submission IDs within original windows; transport acknowledgment
remains independently unobserved. No new reload or replay was performed.

[Acceptance and residual LP-01](docs/dev/evidence/plan0226/closeout.md): existing
successors retain literal release pins; recipient MCP identity was unavailable
while notLoaded. These remain explicit limits, not claims of universal durability
or completion of future reviews. Future release retirement/recovery needs its
own exact-record reconciliation and applicable authority.


## Persistent wakes | Explicit session modes and recurring schedules

Status: CLOSED (merged and deployed; PR #618)
Work item: #610; children #611–#616 CLOSED
Plan: [Persistent wake specification](docs/dev/plans/0173-agent-harness/persistent-wake-spec.md)
Current State: Explicit three-mode scheduling and durable recurrence implemented.
One review and one bounded remediation resolved seven findings; local validation
recorded. Merged a16b4de4 and deployed dev20; compatible monitor heartbeats verified.
Live provider/closed-Byobu execution remains unexercised; no schedules created.

## P230 | Native mailbox first contact and bindings

CLOSED (merged/deployed; native first-contact and reconnect accepted): [LOCAL-P230](docs/dev/plans/0230-2026-11-13-mailbox-first-contact-bindings.md).
One source lane; remove first-poll prerequisite and qualify opt-in client rebinding.

## P234 | Unified hierarchical connector control

Status: CLOSED; PR644 merged, dev21 deployed
Work item: #623; eleven child tickets
Plan: [Unified control spec](docs/dev/plans/0234-2026-11-14-unified-control-spec.md)
Current State: All eleven child tickets CLOSED; one two-axis review and one TDD
pass resolved accepted findings. Source/installed-candidate evidence and limits:
[validation](docs/dev/evidence/plan0234/validation.md), [review](docs/dev/evidence/plan0234/review.md).
Operator subsequently authorized review/merge/deploy. [Deployment evidence](docs/dev/evidence/plan0234/deployment.md); live provider acceptance excluded.

## P235 | External OAuth connector

Status: DONE. Work item: #646. Owner: root / ecochran76.
Plan: [External OAuth connector](docs/dev/plans/0235-2026-11-14-external-oauth-connector.md).
Current State: Source/installed package qualified and deployed after explicit operator
approval. Public metadata200, MCP401, owner isolation403. Human consent/client linking
remain separate. [Deployment evidence](docs/dev/evidence/plan0235/deployment.md).

## P236 | Delegated connector consent

Status: DONE. Work item: #650. Owner: root / ecochran76.
Plan: [Delegated consent](docs/dev/plans/0236-2026-11-14-delegated-connector-consent.md).
Explicit, scoped operator-authorized agent setup with separate actor attribution.

## P238 | Browser consent Origin

Status: OPEN. Plan: [Browser consent Origin](docs/dev/plans/0238-2026-11-14-browser-consent-origin.md).
Preserve first-party form Origin without sending cross-site referrers.
