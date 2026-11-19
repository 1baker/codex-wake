# Retrospective: Grok objective, #695 completion and dev43 release

Reviewed scope: the visible Codex conversation, #695/Plan0248/Plan0250 acceptance artifacts, the current review of PR #712, and local validation/deployment receipts. Earlier remote sessions were not reconstructed. Historical intermittent failures with no causal reproduction remain unknown. No raw private session logs or credentials are included.

## Outcome and the goal we lost

The broader product outcome was native Grok coding in the modded Codex harness (#628). #695 delivered a bounded native queue/expiry prerequisite. The clock work had a real cause—WSL clock discontinuities and real freshness/deadline failures—but grew into a universal timing migration and a long validation campaign. Completing that campaign did not complete Grok's remaining live sample/coding acceptance.

I should have kept the Grok outcome visible and bounded the clock dependency before expanding it. The later operator policy correctly replaced “remove every raw clock” with owner-specific requirements: supported StableTime service observations for reliable decisions, ordinary protective waits for transport, and no private counter bridge.

The current release review also found a more direct integration gap: expiry-qualified Native e728 and the deployed a5806e Grok carry share upstream d320 but retain different features. Selecting the expiry candidate would lose current Grok/worker changes. PR #712 deploys the Wake frontend; Native carry integration/cutover is tracked separately in #713.

## Recommended environment changes

| Priority | Finding supported by this session | Improvement | Status and maintenance cost |
|---|---|---|---|
| P1 | The native binary qualified as e728, but the committed patch/manifest still reconstructed 9af and wirev1. Source acceptance and public delivery drifted. | Check accepted source pin, patch digest and wire contract in the existing validation workflow. Before release, reconstruct the patch into a temporary Git index and compare the entire tree to the qualified commit. | **Implemented in PR #712:** `scripts/check_native_expiry_artifact.py`. It failed against the stale packet and now proves exact tree equality. Low ongoing cost: one source of acceptance pins, no new fixture framework or Native rebuild. |
| P1 | Native package qualification did not establish that it retained the selected Grok/worker carry. This review prevented a regressive cutover. | Make the selected product build/carry inventory an explicit release input alongside the feature candidate. Require the combined package before changing selection. | **Tracked in #713; Native selection preserved.** Medium cost: carry acceptance must evolve with the selected build, rather than becoming another independent benchmark suite. |
| P1 | The user had to ask why clock work had displaced Grok. Plan0250's raw-call inventory became an implicit target. | Add a small “user outcome / current dependency / sufficient evidence / stop condition” packet to the existing execution ledger. At a dependency scope change, reconcile it against the product outcome. Reviewer checks whether a prerequisite is being mistaken for the feature. | Recommendation; no global AGENTS edit. Low maintenance if kept in the active plan rather than copied into many instructions. |
| P2 | The private Python runner omitted the maintained Rust PATH, re-entered under multiprocessing without a main guard, and needed per-test/subtest result reconciliation. These caused misleading failures and duplicate work. | Use one maintained, import-safe local validation entrypoint with environment/tool preflight and durable per-case results. Preserve failure history and invalidate results by changed owner; do not hide failures with global fake clocks. | Recommendation for the existing validation owner, not a new framework in this release. Medium maintenance; it should replace private launchers rather than coexist with them. |
| P2 | An obsolete “never read a guest clock” test kept a protective RPC timer coupled to StableTime. A clock-client outage blocked queue inspection/cancellation. | Put the ordinary-wait/reliable-decision distinction beside the owning interface and test the actual clock-outage behavior. Keep expiry enforcement at Native admission. | **Repaired in PR #712:** public Unix read/delete/capability controls went red, then the 20 affected controls passed on both Python versions. No timeout/assertion relaxation or new bridge. |
| P2 | Messages to a completed worker did not restart it; useful repair work waited until `followup_task` was used. | Coordinator should inspect worker state and use the task-start operation for completed/idle workers. A scheduling acknowledgement must identify an active task, not merely queued mail. | Recommendation for orchestration tooling/skill owner. Low cost; do not add this implementation detail to every repository AGENTS file. |
| P3 | Broad tool reads repeatedly returned truncated skill bodies, Git stats and an entire large planning-audit object. Important details then needed rereading. | Prefer bounded fields (`ok`, `problems`, source IDs and relevant failure excerpts). Read known skill sections separately; graph queries should name the exact owner. | Recommendation. Existing tools/checks mostly exist; the problem was how they were called, not absence of another search system. Low maintenance. |
| P3 | Long progress updates emphasized rising test counts more than usable Grok capability or the remaining decision. | Report outcome, exact remaining gate and next action. Test counts belong in validation receipts; periodic updates should explain what the evidence changes. | Recommendation; no new policy file. |

## Existing guardrails versus missing wiring

This is not an unlinted repository. The CI workflow already runs Ruff undefined-name checks, compileall, unit tests, policy wiring, packaging and installed smokes. Operator policy substitutes documented local checks for paid hosted runs. The newly missing guard was **release artifact provenance**, now wired into that existing workflow. The all-history planning audit also reports older header/filename problems; the active-plan audit passes. Those legacy findings are separate from this release and were not silently “fixed” to make the report green.

AGENTS.md already contains extensive routing and the revised timing boundary. Adding another long global rule would increase context pressure without fixing the mechanical artifact mismatch. Keep detailed judgement guidance in the existing plan/reviewer references; use executable checks for mechanical invariants.

## Validation evidence and limits

- Prior source collections cover 2,806 unique cases on each Python version: 2,805 pass and one opt-in systemd skip. These are resumable, service-backed per-case results, not an uninterrupted hermetic green run. The Python3.12 collection reported 2,280.160 seconds; its three Windows cases passed unchanged focused reruns. Their full-run causes remain unproven.
- PR #712's merged-source affected selection passes 51 cases on Python3.11 and Python3.12. Standards accepted one P1; Spec accepted the same P1 plus one P2. Both unique blockers were repaired in one bounded findings pass.
- Exact Native e728 package/runtime proof remains distinct from current working Native adoption. Three Rust libtests were never executed after bounded compile attempts; the gap is explicitly deferred, not counted as a pass.
- The new working frontend preserves 31 runtime dependency versions. Its source-file parity and separate-UID installed checks are recorded in the deployment receipt.
- UID1017's previously configured time client reports transport failure in both old and new prefixes; the working-account reader is authenticated. This is not evidence of a StableTime service outage, and no credentials were copied or reset.

Runner-reported durations are historical diagnostics, not stable performance benchmarks or billing totals. No complete token/cost ledger is available for this session.

## Next product step

Return to the Grok path: reconcile #713's combined Native carry and #628's remaining selected-build live/coding acceptance. Preserve the expired uncertain request and require its separately approved live window before any new provider attempt. Do not turn that step into another general clock migration.
