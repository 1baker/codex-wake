# LOCAL-P231 | Specialist bot hierarchy and worker-tab organization

State: CLOSED
Workflow: DONE; source integrated, tickets closed, one review/remediation complete
Work item: https://github.com/CochranResearchGroup/codex-wake/issues/601
Owner: primary / ecochran76
Branch: feat/bot-family-hierarchy
Base: e8c79a79
Scope: accepted specification, dependency-ordered implementation and ticket closure
WIP limit: one coordinator; up to three bounded workers, one ready ticket each; no live changes

## Current tracker reconciliation | P255

Issue #601 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Objective

Make bot relationships and specializations visible through their terminal tabs.
Operator example: a ChatGPT specialist bot manages account-specialist sub-bots;
each may further specialize in a task and its ticket graph. Every bot has its own
tab; codex-wake provides organization and identifiable presentation.

## Settled placement decisions

- Default placement is a workers session; adjacent-to-parent is an override.
- One shared workers session per terminal server, grouping workers by root.
- Nested workers retain the original root family/color, with immediate-parent labels.
- Muted family accents remain distinct from error/attention indicators.
- Manual moves persist; automation respects operator placement.
- A temporary worker tab may close after its parent accepts its result, preserving
  conversation history. Failed, unfinished and manually adopted tabs remain.
- Remove the workers session when empty.
- If a root tab closes, workers remain with family association and root-tab-unavailable
  indication; the persistent root bot may still be available. Closing a tab does not terminate descendant work.

## Settled bot hierarchy and inheritance

- Every node is its own durable bot identity, including task/ticket-graph bots;
  retirement and tab cleanup preserve identity/history.
- Root ChatGPT specialist -> account-specialist sub-bots -> task/ticket-graph
  specialist descendants; each bot has its own tab presentation.
- Parent bots supervise children: assign work, inspect progress, accept results
  and request pause/stop within their granted authority. Codex-bots owns that
  relationship; Wake presents organization, identity and navigation.
- Long-lived account sub-bots also use the shared workers session when spawned.
  Only tabs explicitly designated temporary are automatically cleaned up.
- Inheritance is automatic and low friction: specialist guidance, account context
  and authority the parent can already delegate carry through at creation, without
  repeated setup/approval. A new account or expanded permission still requires
  authorization. Do not reinterpret inheritance as fresh rights or budget renewal.
- Tab labels and positions are presentation, never proof of bot/account identity.
- Parent tab closure does not imply bot termination or loss of all contact.

## Settled attachment, guidance and focus behavior

- Reopening a bot reuses its primary tab within the same client/environment;
  another client can maintain its own attachment to the same durable bot.
- Descendants pick up updated inherited specialist guidance on their next turn,
  retaining account/task-specific additions. Do not change an active turn midway
  or treat a guidance update as expanded authorization.
- Spawned tabs open in the background and preserve the current selection.
  Intervention is signaled with attention indicators, never automatic focus theft.
- Reuse existing named-session, routing and reversible-decoration facilities;
  record parent/root identity independently of titles, tab indices or placement.

## Interview frontier

All presented design choices are settled. Await the operator's final confirmation
of the consolidated shared understanding. This document is a design record, not
implementation, integration or deployment authority. The next proposed phase is
specification and dependency-ordered tickets across codex-bots and codex-wake.

## Documentation and acceptance

GLOSSARY.md is the single terminology authority. Codex-bots owns its bot model;
verify existing definitions before adding competing hierarchy terms. Record only
settled definitions, with implementation decisions in this plan. No speculative
ADR. Definition of done for this packet: agreed model, domain terms reconciled,
open decisions enumerated, operator confirms shared understanding. Build and
live-effect scope require their own subsequent packet.

## Custody and discovery

Primary owns this design checkout until interview/spec handoff; next review is the
next operator reply. Registered checkouts119before/120after. Reuse it across rounds;
cleanup once documentation has durable custody and no active editing need.
/root/bot_hierarchy_discovery is a read-only, bounded facts lane over at most two
repos, no edits/live effects/memory writes. Primary reconciles its source locators.
Repo-native sources and the supplied use case suffice for the current design;
Graphiti discovery skipped. No memory capture is authorized by this interview.

## Existing model reconciliation

Read-only discovery /root/bot_hierarchy_discovery completed; primary accepted its
source-grounded distinctions. codex-bots-standalone@ee4c1d4 GLOSSARY.md:8 defines
Bot as a persistent specialist shared across clients; bot clients separately own
sessions/desktops/authentication. README.md:13 roster fields do not establish
parent/account/task specialization inheritance. src/tenant-tasks.mjs:113 records
bot assignment/executor/ownership revision, not a descendant bot hierarchy or
ticket graph. src/specialist-account-setup.mjs:15 qualifies account capability;
it does not make an account a child bot. src/wake.mjs:9 uses exact targetThreadId
wakes, not bot hierarchy. Wake managed-agent and terminal-attachment definitions
already keep durable identity separate from presentation.

The proposed hierarchy extends that persistent Bot model. Operator confirmed
distinct durable descendants, low-friction delegated inheritance, workers-session
placement for persistent descendants, and actual parent supervision.
No claims that parentage/inheritance/supervision are already implemented.
Memory disposition forbidden: developer requires an explicit memory-update request;
this design/documentation interview authorizes no durable-memory capture.

## Current State

Operator confirmed shared understanding and explicitly invoked to-spec, to-tickets,
implement-spec, one broad code-review and one bounded TDD finding-remediation pass.
Canonical frozen requirements: 0231-bot-family-spec.md. GitHub spec601 stays open;
implementation ticket readiness and worker custody live in0231-execution.json.
Primary owns Wake registry T2. Bots hierarchy T1 is the other initially unblocked
lane; placement T3 and display T4 unlock after T2; joined bridge T5 after T1/T2/T3.
One integration branch per repo is necessary for the cross-repository delivery;
there is one coordinator and joined acceptance ledger. Current repo roots remain
main. Existing design checkout is reused, with explicit ownership through final
closure; all task-owned worker checkouts retire after merged published custody.

## Integration reconciliation

Concurrent mailbox initiative occupied plan0230 and main advanced to17e2c3fe with
dev18. This program is nowP231, same spec601/tickets/worker custody/review limits.
Merged both histories by intent; only package version conflicted, resolved asdev19.
Other mailbox/composer/StabeTime behavior and its P230 evidence remain intact.
Review fixed point for our Wake delta is17e2c3fe, excluding unrelated initiative.

## Final source acceptance

Wake PR607 merged88aca4fc; Bots PR77 merged78501a84. Wake602/603/604 and
Bots75/76 read back CLOSED. Parent spec601 remains open under to-tickets contract.
One broad review (Standards /root/p231_standards_review; Spec /root/p231_spec_review)
accepted STD-1(P1),SPEC-1(P1),SPEC-2(P2), all Bots; no Wake blocker. One bounded
TDD pass by /root/bot_family_model observed each regression red then green;
coordinator focused5PASS0SKIP1.176s and source/syntax checks verified correction.
Bots corrective PR78 mergeda9e868fd. No second broad review or accepted blocker.

Local affected Wake287PASS127.423s, post-merge family/mailbox76PASS23.883s;
CLI replay5PASS2.111s; installed disposable earlier wheel16PASS14.344s.
Bots source46PASS4optionalbrowserSKIP; actual source WakeCLI/tmux/native binding
join1PASS7.53s. Exact commands/failures remain in per-ticket records. These are
selected source/package checks, not full unrelated/3.11/provider/live acceptance.
Existing provider-qualified child auth enrollment remains required; source does
not synthesize grants. Unknown moved-TUI recovery holds rather than replacing a
conversation. Live installation, account enrollment and provider journeys excluded.

Source delivery and requested ticket closure are complete. Final docs-only receipt
records results; both task integration checkouts retire after its verified merged
custody. Root checkouts stay main; unrelated worktrees remain untouched.
Memory disposition forbidden: no explicit memory-update request; zero graph writes.


## Operator-authorized installed follow-up

The subsequent instruction `pr review merge deploy` authorized live package
deployment separately from the source-only packet above. Wakedev19 installed from
282dcf02; Bots compatibility PR80 mergedc7fe3a1 qualifies the exact already-running
0.169.0 daemon and Wakedev19 versions. The feature's broad review/remediation
counts remain1/1; only the bounded compatibility delta received a focused check.
See [installed evidence](../evidence/plan0231/deployment.md) for package identities,
local checks, actual service/ingress/attachment readbacks, preserved holds and
rollback custody. Account grants and model/provider journeys remain excluded.
