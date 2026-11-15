# External connector session-control acceptance

Operator-approved spec, published as #663. Publication target: GitHub Issues, CochranResearchGroup/codex-wake. Category enhancement; state ready-for-agent. This work qualifies existing product behavior and fixes demonstrated defects; it does not assume the capabilities are missing.

## Problem Statement

The operator can use ChatGPT to send a prompt to an existing Codex conversation and retrieve its answer. The demonstration exposed and repaired stale cancellation reporting. That round trip does not establish duplicate protection, busy-input policy, tab-loss continuity, the three wake session modes, slash results, restricted permissions or connector restart continuity. External connectors need trustworthy evidence that they control the intended conversations exactly once and report actual outcomes.

## Solution

Qualify each behavior through the deployed OAuth-protected connector and its actual native effect owner, using disposable conversations and tabs for disruptive scenarios. Retain a compact acceptance receipt for each independently demoable behavior. Repair only observed defects and repeat the failed scenario. Preserve the existing personal ChatGPT plugin identity and operator conversation. Distinguish request admission, native acceptance, execution, delivery, final answer retrieval and cleanup.

## User Stories

1. As an operator, I want two submissions with the same intent key to return the same operation, so that retries cannot duplicate my instruction.
2. As an operator, I want an altered payload using an existing key to be refused, so that a retry cannot change its original meaning.
3. As a connector, I want durable operation handles, so that I can reconnect and read the original result.
4. As an operator, I want proof of one native input, so that matching operation IDs alone cannot conceal duplicate effects.
5. As an operator, I want reject policy to refuse input while a conversation is busy, so that it cannot interrupt or queue work silently.
6. As an operator, I want queue policy to preserve active work and execute afterward, so that the next instruction is delivered predictably.
7. As an operator, I want steer policy to address the exact active turn, so that unrelated work cannot receive the instruction.
8. As an operator, I want explicitly selected interrupt-then-submit behavior verified on disposable work, so that interruption is attributable and the replacement prompt runs once.
9. As an operator, I want a changed active-turn identity to be refused, so that stale control cannot affect a new turn.
10. As an operator, I want my saved conversation to remain identifiable after its tab closes, so that tab lifetime is not mistaken for conversation lifetime.
11. As an operator, I want an authorized background continuation to retain conversation identity, so that closing its terminal does not create unrelated work.
12. As an operator, I want background execution results readable through the connector, so that silent execution remains observable.
13. As an operator, I want wake session mode selected explicitly, so that the scheduling agent cannot silently choose persistence behavior.
14. As an operator, I want this-session-only wakes cancelled when the recipient session closes, so that abandoned tasks do not run later.
15. As an operator, I want detaching a terminal client distinguished from closing the recipient session, so that harmless detachment does not cancel valid wakes.
16. As an operator, I want re-open-session-live wakes to restore the same conversation visibly, so that I can inspect resumed work.
17. As an operator, I want visible restoration to use the most recently verified harness and working directory, so that work resumes in the expected environment.
18. As an operator, I want background wakes to use an existing live terminal when available, so that they respect my current workspace.
19. As an operator, I want background wakes to continue without a visible terminal when needed, so that recurring work can survive tab closure.
20. As an operator, I want cadence, end conditions, missed-wake handling, overlap policy and delivery behavior stated separately from session mode, so that persistence does not invent scheduling policy.
21. As a connector, I want to discover supported slash actions before execution, so that it does not send unsupported command text as a prompt.
22. As an operator, I want a harmless slash action and its correlated result demonstrated, so that structured harness control is proven separately from ordinary prompts.
23. As an operator, I want a restricted connector to read only its granted targets and content, so that account access does not imply unrestricted control.
24. As an operator, I want read-only grants to reject prompt submission, so that denied writes produce no native effect.
25. As an operator, I want cross-target and stale-generation requests refused, so that credentials cannot bypass conversation identity.
26. As an operator, I want connector restart to preserve original operation custody and idempotency, so that reconnection cannot replay work.
27. As an operator, I want a real client to read the completed answer after reconnect, so that service health alone is not treated as acceptance.
28. As an operator, I want cancelled, failed, pending and completed states to reflect native evidence, so that answer text is never used to invent success.
29. As an operator, I want each demonstration to clean up only its own tabs, sessions, grants, schedules and processes, so that acceptance does not disrupt my workspace.
30. As a maintainer, I want a proven defect captured at an existing stable seam before repair, so that future regressions are caught without building a separate test platform.

## Implementation Decisions

- Retain the existing coherent CLI/API/MCP operation hierarchy and durable operation ownership; this spec qualifies those interfaces rather than introducing another control layer.
- Prefer one acceptance boundary: real client calls through the deployed protected connector, correlated with native acknowledgments and retained results. Use existing focused operation-owner tests for deterministic regression coverage.
- Keep the installed source/build identity, selected target generation, caller grant scope and stable client app identity in private receipts. Publish only synthetic summaries and non-secret evidence.
- Give each demonstration its own intent keys and disposable target where appropriate. Repeated keys are deliberate only within the duplicate-protection and restart cases.
- Explicitly select busy-input policy and wake session mode. They are independent controls; neither authorizes a different conversation, account, harness or schedule.
- Background continuation must exercise a supported continuation mode and preserve the saved conversation. Closing a tab alone is not a request to restart its agent.
- Set bounded wake cadence, horizon, missed/overlap/delivery behavior for each experiment before activation. A short deterministic due event can qualify delivery; a twice-daily schedule does not require days of waiting or a new recurring production schedule.
- Use existing slash capability discovery. Run a declared non-destructive action only; unsupported actions produce explicit refusal, not prompt fallback.
- Derive restricted test grants from a separate bounded client authorization. Do not shrink, revoke, replace or broaden the operator's existing connector grant.
- Restart only the connector transport for restart acceptance. Preserve native daemon identity and unrelated sessions.
- Repairs may improve implementation behind existing contracts. Interface changes require an explicit revised decision and must not be smuggled into acceptance scaffolding.

## Testing Decisions

- Judge observable product behavior: exact native input count, original operation identity, correlated final reply, target generation, denied-effect absence, actual wake delivery or cancellation, and resource cleanup.
- Prefer the deployed OAuth/MCP boundary for each completed slice. Use the existing ChatGPT connection for final client readback; deterministic cases may use a supported separately scoped connector client where that makes evidence clearer.
- Reuse the native input owner, OAuth protected dispatch, recurring scheduler, native session discovery, slash operation owner and retained operation journal seams. Existing queue/input, cancellation reconciliation, schedule authorization and slash tests provide prior art.
- Do not create a fixture framework, generalized acceptance runner, fake production histories or test-only product deliverables. Minimal synthetic targets support one named scenario each.
- Busy-input tests cover all four explicit policies on disposable work, including exact-turn refusal and absence of fallback.
- Permissions tests prove both permitted reads and refused writes, with native-state evidence that no write occurred. Include target restrictions and stale generation refusals.
- Restart tests require an in-flight original operation, service restart, same-key retry and final result retrieval, with one native effect in total.
- A ticket closes only after its own live acceptance and cleanup, or after an explicitly documented supported refusal when refusal is the expected behavior. Unsupported required behavior remains open with an observed gap.
- Run applicable checks locally, record commands/results/source commit and environment differences, and do not use paid hosted CI. Any connector package changes follow separate-user qualification before working-account installation.

## Out of Scope

- Broad new API families, new harnesses or providers, UI redesign, generalized orchestration or a new test framework.
- Closing or interrupting the operator's working conversation, tab, or unrelated sessions.
- Altering account-wide authentication, public ingress, billing, plugin identity, grant privileges or native daemon installation.
- Activating an unbounded or production twice-daily schedule merely to demonstrate persistence.
- Treating ticket publication as authority to execute destructive scenarios or arbitrary live effects. Each scenario remains bounded to its approved disposable target and declared controls.

## Further Notes

The existing same-session round trip and stale-status repair are baseline evidence, not proof of this matrix. Preserve cancellation-to-completion correction provenance. The original early interrupted native snapshot was not captured contemporaneously; its origin remains unknown and must not be represented as established.

Proposed tickets: duplicate protection; busy-input policies; background continuation; this-session-only wake lifecycle; visible wake restoration; background wake routing; slash action round trip; restricted connector permissions; connector restart continuity. Each is independently demonstrable and has no genuine blocking edge on another acceptance ticket. Shared environment scheduling may serialize live scenarios without becoming a code dependency.

## Approved prerequisite extension (2026-11-14)

After reviewing the root-wide impact, the operator explicitly approved adopting the existing common permission resolver to qualify visible restoration. Inventory existing consumers and unfinished effects first; preserve named existing action decisions, refuse unknown actions by default, and scope any additional recovery permission to the owned disposable recipient and host-approved named profile. Use the supported migration/CAS policy owner, retain adoption history, and remove temporary recovery authority through a later revision. Do not delete adoption files as a rollback. This extension does not broaden the existing OAuth grant or authorize effects on unrelated recipients.
