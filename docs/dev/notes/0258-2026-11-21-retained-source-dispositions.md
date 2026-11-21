# Retained source research | LOCAL-P258

State: CLOSED (bounded research complete)
Owner: primary / ecochran76
Priority: close existing delivery and custody gaps before new features
Work item: existing PR454, #420 and retained source custody
Branch: docs/retained-source-research-258
Authority: current main4e2eea75d62d83181b66a9d9258ac0b5256cf83e; original PR454
head ef156ba466f83e7adb692be248379f857c1157fe. No deployment authority added.

## Research bound

Question: which retained outcomes already exist on main, which warrant a current
port, and which can release their checkout after reviewed exact history custody?
Primary sources only: exact Git objects, repository specifications and acceptance
receipts, current tracker readbacks. Inspect PR454, the24 residual Wake histories,
18 upgrade-worker histories and8 clean native history holds. Stop when each has
a disposition or an explicit missing proof. No builds, provider calls, production
effects, source publication or cleanup of held content in this research packet.
The temporary documentation checkout protects the dirty primary; retire it after
merged custody. This note is the single report, not a new competing specification.

## PR454: port required; do not close as already delivered on main

The old branch implements a durable opt-in upgrade owner, release discovery,
semantic repair, qualification, future-launch selection and outcome reconciliation.
Its public CLI/API/MCP verbs include enable/disable/start/advance/reconcile, which
are distinct from the current recipe-based release driver's prepare/build/resume/
qualify/cleanup/run interface. Thus the later release driver does not establish
that the autonomous upgrade owner is integrated. Sources:
[old command contract](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/src/codex_wake/upgrade_commands.py),
[current release driver](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/release_driver.py).

The branch's final ledger records validated_closed_delivery and all444/447–453/
455–457 closed. Its final review records one Standards/Spec pass, two corrected
findings and93 affected tests on each Python version; the2026-test full profile
belongs to the preceding source. These are historical0.166 acceptance claims,
not current0.171 validation. The stale draft PR text saying453/457 remain blocked
must not override later identified receipts. Sources:
[final ledger](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/docs/dev/plans/0193-upgrade-bot-ledger.json),
[final review](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/docs/dev/evidence/issue0444/final-review.md),
[native acceptance](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/docs/dev/evidence/issue0444/native453-acceptance.md).

Fresh merge-tree inspection against current main still reports six conflicts:
GLOSSARY, ROADMAP, RUNBOOK, runtime-proof, active-lanes and controller_http.
The controller conflict overlaps modern authorization and tool registration;
accepting an entire old side would risk removing later operations. The old branch
also modifies build_channels/upgrades and introduces its own qualification and
promotion pipeline. Current capability/package acceptance must be reconciled,
not inferred from old controller tests. The branch itself adds official_source_url;
its absence on main alone is not a postmerge import defect. Sources:
[controller changes](https://github.com/CochranResearchGroup/codex-wake/pull/454/files),
[qualification owner](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/src/codex_wake/upgrade_qualification.py),
[promotion owner](https://github.com/CochranResearchGroup/codex-wake/blob/ef156ba466f83e7adb692be248379f857c1157fe/src/codex_wake/upgrade_promotion.py).

Recommended delivery slice: port the existing public upgrade job owner onto
current controller/recipe/package contracts. Preserve current protected operations,
original cumulative allowance and disable behavior, deterministic-first repair,
exact package identity and outcome-only reconciliation. Use existing public job
regressions and disposable package acceptance; do not restart expired campaigns
or construct another orchestrator. Close PR454 only after that port is integrated;
keep working deployment separate. This recommendation is not implementation or a
new acceptance result.

## Decision rule for retained histories

Behavioral integration and exact historical custody are separate questions.
An equivalent fix on main permits closing an implementation gap only to its
original accepted boundary. It does not make all old commits public or authorize
discarding unpublished historical blobs. Conversely, an unpublished old blob is
not evidence that its behavior is missing from main. Keep branch history and
checkout retention decisions explicit; review source before publishing an archive.
No retained history is merged simply to satisfy a cleanup count.

## Residual Wake history inventory

Counts describe historical blob custody, not missing functions. SHA links identify
the exact preserved source; payload privacy review remains a separate gate.

| History | Exact head | Unreviewed historical blobs |
|---|---|---:|
| auth697-until-event | `2b9f7a9cf3f2e1831f3e3ab1bda79c067d56d821` | 15 |
| cancel-contention | `575554403be6115d5b20367283c54d727e246036` | 9 |
| codex-wake-413 | `fb3f6f7725449bd7902dd5f6726b65c9f1c13fa6` | 34 |
| codex-wake-dispatch350 | `11c702e54a0c856a15fca283dfabaf7b4ca11b38` | 1 |
| codex-wake-guard-admission | `b808a121ed303d26a59e377d541f4cd0c7331e6c` | 2 |
| codex-wake-guard-handoff | `73102f8443f04d002a48b1d8ac5bb5f06b7eb514` | 2 |
| codex-wake-host-execution | `9c6dd1673e93c1b643424c5c2ef92068733388c9` | 3 |
| codex-wake-live380-version | `0577f932270f5937980a2db90a54f2e7a6dafa38` | 4 |
| codex-wake-local-health | `bcb365cc305885a9fc126fae1a1cc088d71e5b61` | 5 |
| codex-wake-modern-managed-acceptance | `112e97e46829fd6ac0080747c4ba9a936ec004ee` | 18 |
| codex-wake-native-managed-qualification | `e5251703e41ee0c9e498aca80fee084dc7834bec` | 2 |
| codex-wake-output-modes | `d96101c23b5eb041a95addde2974b20d3f992175` | 11 |
| codex-wake-reconcile419 | `9ff60357011788a9edabedfd768bca0a6c23030c` | 73 |
| codex-wake-refresh-qualification | `46ca4432d84df395bfd52f415228545ea7d1f54e` | 3 |
| codex-wake-review-fixes-flow393 | `c8083a9d63fb8dd31a3be3ac4aab6f4eadf0748f` | 12 |
| codex-wake-review-fixes-scheduler393 | `9819853974e1b46903745f0d6bab0b66c8ccfa3f` | 2 |
| codex-wake-runtime-bootstrap | `8c40601db5cf57f41c03a6fa93e8f01259383cd4` | 9 |
| codex-wake-self-limits | `7481475cde76d0b8065e214f90e03017af052eba` | 7 |
| codex-wake-self-limits-reopened | `481a4aebb877d68913fcc81b877f7090cff8126a` | 7 |
| codex-wake-session-resilience | `8a3df935e95644fdf92ef565a9863d2731c5186c` | 3 |
| codex-wake-slash-commands | `277d34ac32fe9fd0d6097b8fbebc349a049e9b4b` | 3 |
| codex-wake-validation350 | `81c461097b846526aa6f9f6395cc521a2880e9e6` | 3 |
| private-native-launch | `aad1b0b3c4e3349d3d91eb63871eb887200516f5` | 4 |
| release-startup-fix | `bc390fcca676fd9abfc61c4a9fa75eb599a6ef51` | 2 |

Inventory provenance: exact retained Git heads reconciled in P257; private
per-path/object receipts remain outside Git. These counts can overlap between
histories and must not be summed as distinct objects. No blob payload was
published merely to make the inventory complete.

## Eighteen autonomous-upgrade worker histories

Their delivered outcomes are represented by the accepted PR454 packet, not by
current main. Do not reimplement them independently from worker names. Original
history custody remains unresolved: the existing inventory found96 distinct
historical blob revisions,1,517,002 bytes, across45 already-public paths. All41
unique commit messages were reviewed; this is not a finding of secrets. The
ancestry search covered438 available public heads and55 unavailable refs, so
failure to find custody is bounded evidence, not universal absence proof.
Source: the exact PR454 specification/ledger/final-review links above; P257's
private object and ancestry receipts retain the complete per-history inventory.

Next gate: review those96 historical revisions or locate exact public custody,
then verify archive refs and fresh checkout/reference/ignored-artifact gates.
This is a custody task independent of porting PR454. Keep all18 checkouts until
that bounded decision; the paused parent alone is not a permanent checkout need.

## Eight clean native history holds

| History | Unknown tip blobs | Unknown history blobs | Public tip reconstruction |
|---|---:|---:|---|
| codex-318 | 0 | 23 | exact scoped-MCP patch tree |
| codex-native-413 | 40 | 96 | not established |
| codex-native-415 | 37 | 66 | not established |
| codex-native-416 | 34 | 61 | not established |
| codex-native-417 | 35 | 63 | not established |
| codex-native-reconcile419 | 41 | 119 | not established |
| codex-wake-native-0164-notices | 5 | 5 | not established |
| codex-wake-native-health405 | 0 | 18 | exact TUI-health patch tree |

The two tip matches do not preserve intermediate history. The separate public
modern-notices patch does not match the retained notices tip. Existing proof
used published patches, without a new build or native push. Source patches:
[scoped MCP](https://github.com/CochranResearchGroup/codex-wake/blob/ae58668788d39e34bbf13228699216af4be9878a/patches/codex/318-thread-scoped-mcp.patch),
[TUI health](https://github.com/CochranResearchGroup/codex-wake/blob/ae58668788d39e34bbf13228699216af4be9878a/patches/codex/modern-0.164-tui-health.patch).
Exact apply/tree receipts remain in user-scoped P257 evidence. All eight retain
history-custody and checkout-dependency gates; no automatic source rewrite or
native publication is warranted.

## Behavioral dispositions for all24 residual histories

| Retained history / tip | Evidence and decision | Next bounded step |
|---|---|---|
| `auth697-until-event` / `2b9f7a9c` | **Publication/integration gap.** Retained Plan0248-until-event says source-qualified, Auth406/ticket410_mail owns integration; coordinator publication and installed acceptance were separate. Main has none of `until_event_or_cancel`, `native_file_until_event_v1`, event-match anchoring or its five public regressions in CLI/MCP/intents. This is distinct from main's unrelated Plan0248 queue-expiry packet. Parent freshly verified issue697 CLOSED; do not reopen an accepted source ticket automatically. retained local Git `2b9f7a9cf3f2e1831f3e3ab1bda79c067d56d821:docs/dev/plans/0248-2026-11-15-native-until-event.md`, [main intents](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/native_intents.py) | Reconcile Auth406/415 coordinator ownership and source custody, then propose a narrow current-main feature port with existing five tests. Adapt to current service observations; do not revive obsolete clock architecture or assume closed697 equals integrated main. |
| `cancel-contention` / `57555440` | **Narrow port candidate.** Source-only DONE contract retains exact authorized cancellation while the delivery lock is held, with per-wake reconciliation and uncertain-send holds. Main lacks `wake_cancellation.py`, pending-cancellation integration and the two retained identity/peer-scope regressions. retained local Git `575554403be6115d5b20367283c54d727e246036:docs/dev/plans/0236-2026-11-14-durable-cancellation-contention.md`, [main wake control](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/wake_control.py) | First port candidate: reproduce original cross-process contention failure on main, then port only durable exact-scope request/reconciliation and original public tests. Preserve current lifecycle/authority and unknown-input barriers. |
| `codex-wake-413` / `fb3f6f77` | **Qualification outcome retained.** Canonical Plan0191 names this exact recovery evidence tip, closes isolated integration and records the30-case matrix; the retained changes are acceptance/evidence, not a missing current production feature. Current maintained resume qualifier retains the important rejection/rollback/deletion cases. [Plan0191](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0191-2026-10-30-recovery-controller-reconciliation.md#L4-L27), [qualifier](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/scripts/native_daemon_upgrade_resume_acceptance.py) | Preserve custody/evidence; no old-source merge. Separate unknown historical blob publication review from the completed isolated packet. |
| `codex-wake-dispatch350` / `11c702e5` | **Source outcome retained.** Compact dispatch packet, task-brief snapshots, spawn/handoff integration and original regression names remain in main. Plan0175 explicitly includes355 and compact immutable dispatch in its delivered child graph. [Plan0175](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0175-2026-10-25-transparent-governor-delivery.md#L40), [packet](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/dispatch_packet.py) | No port; reconcile historical custody only. |
| `codex-wake-guard-admission` / `b808a121` | **Source outcome retained.** Main Guard keeps `actor_admissions`, later-actor first-snapshot grace, expiry for unbound admitted actors and both original public tests. [Guard](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/strict_executor.py#L215-L218), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_strict_executor.py#L493) | No port; preserve later timing changes. |
| `codex-wake-guard-handoff` / `73102f84` | **Source outcome retained.** Current Guard attributes successor/source goal actors separately, carries immutable usage-observation leases and retains original tests. [bindings](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/strict_executor.py#L243-L250), [observation lease](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/strict_executor.py#L340-L355) | No port; no new admission or elapsed-time architecture. |
| `codex-wake-host-execution` / `9c6dd167` | **Source outcome retained.** Dedicated `SystemdExecution`, InvocationID/cgroup binding, limits, scoped stop and original host tests remain. Canonical Plan0166 closes this integrated adapter and names later PR280 delivery. [adapter](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/host_execution.py), [Plan0166](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0166-2026-10-16-objective-enforcement.md#L23) | No port or service action; historical custody review only. |
| `codex-wake-live380-version` / `0577f932` | **Source outcome retained with modern formatting.** Current Profiles has neutral temporary-home pinned version inspection, exact-version fast path and account-state-preservation test; no reason to reintroduce old snapshot. [inspection](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_profiles/build_channels.py#L331), [test](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_controller_builds.py#L115) | No port; version readback is not live380 activation proof. |
| `codex-wake-local-health` / `bcb365cc` | **Source outcome retained.** Same-user exact controlling-TUI health and its five original tests remain; Plan0200 records469 closed within installed Codex scope. [health](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/local_health.py), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_local_health.py) | No port; retain exact-native capability limits. |
| `codex-wake-modern-managed-acceptance` / `112e97e4` | **Qualified historical packet retained.** Main retains the completed-display managed-roundtrip receipt and canonical display-history reader/tests, including failed predecessors. [receipt](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/evidence/plan0173/modern-managed-update-qualification.md), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_native_modern_display_history.py) | No rerun or port; preserve as historical package proof, not today's cutover claim. |
| `codex-wake-native-managed-qualification` / `e5251703` | **Qualified historical packet superseded/retained.** Its private managed lifecycle receipt and maintained qualifier remain on main; modern-managed qualifier subsequently adapts official0.164 history/protocol. [original receipt](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/evidence/plan0173/native-managed-lifecycle-qualification.md), [maintained qualifier](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/scripts/scoped_refresh_native_qualification.py) | No wholesale old qualifier port; differences are expected modernization, not independently a defect. |
| `codex-wake-output-modes` / `d96101c2` | **Source outcome retained.** Main retains loaded-thread attach, durable bounded output telemetry, response modes/status and original output tests; Plan0200 closes471. [events](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/local_session_events.py), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_local_output_modes.py) | No port; preserve modern response/custody behavior. |
| `codex-wake-reconcile419` / `9ff60357` | **Completed isolated outcome retained; no blanket historical merge.** Canonical Plan0191 contains final package/health/recovery acceptance and recorded launcher fixes. Current source preserves managed backend selection/options forwarding. [Plan0191](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0191-2026-10-30-recovery-controller-reconciliation.md), [Profiles](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_profiles/build_channels.py) | Custody/evidence review only. Isolated COMPLETE is not historical production activation or equivalence of all original bytes. |
| `codex-wake-refresh-qualification` / `46ca4432` | **Qualification seam retained.** Current `shared_refresh_acceptance.py` retains nearly all original fixture additions/test contracts; canonical HF06 ledger records isolated two-thread shared refresh PASS and keeps current-session-only gap separate. [qualifier](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/scripts/shared_refresh_acceptance.py), [ledger](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0173-agent-harness/hf-06-execution-ledger.md#L149) | No port or provider replay; keep scoped/shared capability boundaries. |
| `codex-wake-review-fixes-flow393` / `c8083a9d` | **Source outcomes retained, with deliberate test evolution.** Immutable predicate registry, iteration reservations/limits, original-item cancellation, retry accounting and elapsed high-water handoff are present with corresponding tests. Old wall-rollback-holds test is replaced by explicit qualified-elapsed continuity/rollback tests; absence of the old method is not evidence to revert. [current regression set](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_controller_flow_review.py), [owner](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/controller_flows.py) | No old snapshot port. A full timing-policy audit is outside this24-history disposition. |
| `codex-wake-review-fixes-scheduler393` / `98198539` | **Source outcome retained exactly at relevant seam.** Current `maintain` catches `sqlite3.Error` and projects held/scheduler_owner_unavailable; original public test is retained. [handler](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/controller_schedule.py#L51-L52), [test](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_controller_schedule_auth.py#L62) | No port. |
| `codex-wake-runtime-bootstrap` / `8c40601d` | **Needs split owner review; do not port whole commit.** Old source adds local PowerShell/QPC producer readiness and WSL_INTEROP discovery plus changes native executable default. Main lacks those exact producer changes and its cold-start/host-executable tests. But current Plan0250 explicitly forbids requiring an application-specific counter bridge and makes the service the authority; native clock now uses that service. [current contract](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0250-2026-11-17-stable-time-everywhere.md#L9-L27), [native clock](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/native_clock.py), [current parser](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/native_delivery.py#L34) | Classify old bridge work as superseded under current service contract. Separately inspect only whether host-registered executable selection still has a real current service-environment bug before proposing a tiny path-resolution port. No clock repair project. |
| `codex-wake-self-limits` / `7481475c` | **Source outcome retained.** Own-session limit enforcement and configured watcher startup remain with original tests. Plan0200 closes468 implementation/qualification. [self limits](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/self_limits.py), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_self_limits.py) | No port; voluntary allowance is not external governor activation. |
| `codex-wake-self-limits-reopened` / `481a4aeb` | **Admission correction retained with later timing evolution.** Main self_limits explicitly observes existing goals without creating/activating them; original self-limit regression names remain. Plan0200 records the no-effect admission correction; later Plan0250 owns timing contract. [no-goal path](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/self_limits.py#L103), [Plan0200 correction](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0200-2026-11-03-wsl-session-control.md#L69) | No historical counter/UTC behavior port. |
| `codex-wake-session-resilience` / `8a3df935` | **Source outcome retained.** Original local-turn custody/reconciliation behavior and all added regression methods remain; Plan0200 closes474. [operations](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/local_session_operations.py), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_local_session_resilience.py) | No port; no uncertain model-input replay. |
| `codex-wake-slash-commands` / `277d34ac` | **Source outcome retained.** Durable native slash interactions, serialized receipt projections and every original slash regression remain; Plan0200 closes472. [owner](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/local_slash_commands.py), [tests](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_local_slash_commands.py) | No port. |
| `codex-wake-validation350` / `81c46109` | **Source outcome retained.** Source/runtime-bound fail-fast validator and every original public subprocess test remain. Plan0175 names exact worker81c4610 integrated at6515311. [delivery ledger](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0175-2026-10-25-transparent-governor-delivery.md#L34), [validator](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/scripts/validate_candidate.py) | No port or new validation framework. |
| `private-native-launch` / `aad1b0b3` | **Exact patch-equivalent on main.** Git cherry marks original commit `-`; restrictive child umask paths and original tests remain. [launcher](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_profiles/build_channels.py), [daemon owner](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/controller_daemons.py) | No port. Root may continue custody/ignored-artifact gates independently. |
| `release-startup-fix` / `bc390fcc` | **Exact patch-equivalent on main.** Git cherry marks original commit `-`; startup transport requalification and original regression remain. [observer](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/src/codex_wake/tab_observer.py), [test](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/tests/test_tab_format_autostart.py) | No port. Root may continue custody/ignored-artifact gates independently. |

The common source authority for469/471/472/474/468 is [Plan0200's CLOSED state and explicit installed-scope limits](https://github.com/CochranResearchGroup/codex-wake/blob/4e2eea75d62d83181b66a9d9258ac0b5256cf83e/docs/dev/plans/0200-2026-11-03-wsl-session-control.md#L3-L35). This report does not claim arbitrary TUI ownership, exact Grok cancellation/metering, today's installed identity or production activation from those historical receipts.

Stop criterion reached: all24 histories have a supported disposition or an explicit remaining ownership question. The narrow next slices are cancellation contention, coordinator-led697 publication/integration reconciliation, and executable-selection-only diagnosis if a current symptom exists. Unknown blob and ignored-artifact inventories remain authoritative in the frozen residual receipts; none was admitted for public release by this research.

## Recommended order and validation

1. Reproduce and port cancellation contention through its existing public seam.
2. Reconcile697 source publication with its original coordinator, then port the
   accepted until-event behavior. Keep source acceptance and installation separate.
3. Port PR454's existing owner onto current controller/package contracts.
4. Review original historical blobs for exact custody; retire obsolete checkouts
   only after that independent gate. Do not merge the21 already-represented
   snapshots or restore the superseded application-specific clock bridge.

Primary adjudication accepted both bounded worker reports; complete raw comparison
and object receipts stay user-scoped. Local validation checks exact cited Git
objects, note whitespace and policy wiring; no runtime/test/deployment success is
newly claimed. Source main remains the pinned ref above. Dirty root preserved.
