# P233 | Native Grok inference in modded Codex

Status: APPROVED; test seams, eight tickets and fixed review bases confirmed
Origin: confirmed shared understanding in the P233 design interview

## Problem Statement

The operator wants Grok models to run in the existing modded Codex coding
harness, including mixed OpenAI/Grok worker trees, with the same coding tools,
MCP, history and Wake controls. Delegating to a separate Grok CLI agent does not
provide that experience. Repeated sign-in, hidden billing changes, incompatible
history reuse or inaccurate accounting would make the integration unreliable.

## Solution

Add a native Grok provider to Codex's inference boundary. Wake coordinates the
existing Grok account session and runtime controls. A unified model/account
selection serves conversations and workers, preserving existing OpenAI defaults.
Provider/account handoffs create automatic linked continuations; failures and
unsupported capabilities remain explicit. Deliver the qualified implementation
to one existing modded profile after review, bounded remediation and acceptance.

## User Stories

1. As an operator, I want Grok inference inside Codex, so that my existing coding
   workflow remains under one harness.
2. As an operator, I want Wake to coordinate native Grok sign-in, so that I can
   authorize the intended account through the supported provider flow.
3. As an operator, I want an existing Grok login reused, so that starting workers
   does not require repeated authentication.
4. As an operator, I want refresh coordinated with the official session store,
   so that simultaneous clients do not race single-use refresh tokens.
5. As an operator, I want credentials kept out of worker configurations and
   visible output, so that delegation does not disclose account secrets.
6. As an operator, I want account entitlement and quota attribution verified,
   so that a signed-in state is not mistaken for usable inference access.
7. As an operator, I want API-key access only when explicitly selected, so that
   authentication and billing do not silently change.
8. As an operator, I want OpenAI and Grok in one model/account picker, so that
   selecting a model also resolves its provider and account.
9. As an operator, I want explicit account labels, so that multiple Grok accounts
   are distinguishable without exposing credentials.
10. As an operator, I want unavailable, stale and unverified choices identified,
    so that catalog visibility is not mistaken for readiness.
11. As an operator, I want optional unsupported features disabled individually,
    so that limitations are understandable without simulated success.
12. As an operator, I want a model missing required capabilities unavailable for
    that workflow, so that acceptance requirements remain meaningful.
13. As a parent agent, I want workers to inherit my exact inference selection,
    so that ordinary delegation needs no repeated account setup.
14. As a parent agent, I want explicit per-worker selection overrides, so that
    an OpenAI parent can use Grok workers and vice versa.
15. As a parent agent, I want an explicitly configured validated Grok default,
    so that a provider-only worker request resolves deterministically.
16. As an operator, I want the resolved selection pinned for accepted work,
    so that model/account choices do not silently change mid-task.
17. As an operator, I want current OpenAI defaults preserved, so that enabling
    Grok does not redirect existing work.
18. As an operator, I want a selection made during a turn staged for a safe
    boundary, so that changing selection does not itself interrupt work.
19. As an operator, I want provider/account changes to create automatic linked
    continuations, so that I can switch without extra confirmation.
20. As an operator, I want portable working context carried forward, so that
    the objective, constraints and completed work remain available.
21. As an operator, I want full source history retained, so that a handoff does
    not rewrite or erase the original conversation.
22. As an operator, I want opaque provider reasoning and auth-store secrets kept
    out of portable context, so that incompatible state is not misused.
23. As an operator, I want ordinary same-provider model changes preserved,
    so that the integration does not unnecessarily change existing behavior.
24. As an operator, I want streaming multi-turn Grok conversations, so that
    replies and ongoing coding progress remain visible.
25. As a Grok-backed Codex agent, I want native terminal and file-editing tools,
    so that I can perform real coding work through existing permissions.
26. As a Grok-backed Codex agent, I want MCP tools, so that existing integrations
    remain available under their current authority.
27. As a parent agent, I want clear held results for provider/auth/quota failure,
    so that I can explicitly reassign work under existing authority.
28. As an operator, I want uncertain requests retained rather than replayed,
    so that connection loss does not duplicate work or side effects.
29. As an operator, I want existing Wake allowances to cover the whole mixed
    tree, so that a provider change does not create a fresh allowance.
30. As an operator, I want qualified usage with provenance, so that missing data
    is not silently counted as zero.
31. As an operator, I want strict-budget work held when required accounting is
    unknown, so that unsupported metering is not advertised as enforcement.
32. As an operator, I want Stop to prevent further local tool scheduling,
    so that owned coding work follows Codex interruption semantics.
33. As an operator, I want provider completion/usage uncertainty shown separately,
    so that local Stop is not mistaken for confirmed provider-side cancellation.
34. As an operator, I want resume from durable known state without replaying
    uncertain actions, so that interrupted coding work can be reconciled.
35. As an operator, I want shared logout/revocation to block new Grok turns and
    interrupt this harness's owned Grok work, so that account control is effective.
36. As an operator, I want OpenAI and unrelated sessions preserved during Grok
    logout and rollout, so that the integration stays within its authority.
37. As an operator, I want selection and observed model identity distinguished,
    so that status reflects actual evidence rather than configuration alone.
38. As an operator, I want isolated package upgrade/rollback qualification and
    bounded real-provider coding acceptance, so that deployment proves the surface
    I will actually use.
39. As an operator, I want one broad review and one bounded remediation pass,
    so that accepted findings are resolved without repeated review loops.
40. As an operator, I want the qualified package deployed to one modded profile,
    so that the outcome is usable rather than merely source-complete.
41. As an operator, I want the superseded separate CLI-worker setup retired
    safely with its evidence retained, so that the previous approach does not
    misroute future delegation.

## Implementation Decisions

- Codex owns inference, stream interpretation, tool execution, conversations and
  worker management. Wake owns the surrounding account/auth/runtime coordination.
- Add Grok-specific native protocol compatibility without a general gateway or
  second Grok agent loop. Existing OpenAI transport/defaults remain intact.
- Keep the existing command-backed provider-auth boundary as the shared contract:
  an admitted native provider receives credentials only over its private process
  channel; public CLI/API/MCP surfaces return sanitized account/login status.
- Reuse the compatible official credential/session contract, including persistent
  locking, atomic rotation, expiry metadata and explicit revocation semantics.
  Do not break locks, create per-worker stores or infer logout from file absence.
- Model discovery, account availability and capability qualification are distinct.
  Resolve an inference selection before dispatch and retain observed identity.
- Worker selection inherits exact provider/account/model unless explicitly
  overridden. Preserve the existing tree's admission, permissions and allowances.
- A cross-provider/account handoff creates an attributable successor at a safe
  turn boundary. Carry bounded portable context and known completed tool results;
  retain source history and provider-specific opaque state.
- Compaction may not silently discard the objective, constraints, attribution or
  allowance. Hold the handoff if those required elements cannot be preserved.
- Provider/auth/quota failure is an actionable held state. Parent reassignment
  remains explicit; no hidden account/provider/billing fallback or uncertain replay.
- Stop and shared revocation use exact owned native targets. Preserve uncertainty
  about provider-side completion, billing and in-flight tool effects.
- Usage is attributable to the original tree/selection. Missing usage is unknown,
  not zero, and required strict accounting stays held until qualified.
- Preserve generated/remote protocol compatibility so managed native TUI clients
  can actually select and use the new provider through their daemon.
- Retain exact source/build/rollback custody. Qualify the complete package in the
  approved isolated native environment before working-profile installation.
- Supersede only the earlier task-owned CLI-worker approach, with fresh effect
  reconciliation and reversible retirement; do not disturb unrelated Grok work.

## Testing Decisions

- Test external behavior, not private helper shape or implementation-mirroring
  assertions. Each check protects a named acceptance requirement or regression.
- Proposed primary seam: existing Codex public app-server conversation/worker
  operations, with existing native TUI checks where selection presentation matters.
  This proves native tool turns, model/account selection, mixed workers, handoff,
  interruption, resume and accounting behavior; it does not alone prove provider
  entitlement or installed package effects.
- Proposed second seam: existing Wake CLI/API/MCP account/auth controls and the
  native provider's existing private command-auth boundary. This proves safe
  sign-in/status, session reuse/rotation/revocation and sanitized errors; it does
  not by itself prove a model completed coding work.
- Reuse existing provider HTTP/SSE and core/app-server tests for independently
  specified fragmented text/function calls, native tool execution/continuation,
  malformed/incomplete streams, uncertainty and backward compatibility. Do not
  build another fixture framework or a generic protocol simulator.
- Initial independent auth/transport slices share the existing auth-command
  contract; their final integrated real-account proof belongs to the joined
  qualification stage, not to a mocked claim of provider readiness.
- Use existing native package/history/multiclient/rollback acceptance machinery.
  Live checks use a bounded disposable coding workspace. Adverse auth/logout tests
  stay isolated from everyday account sessions; do not force a production logout.
- Run local checks under the repository CI cost policy. Record exact commands,
  selections, environments, failures and remaining gates. No full-suite claims
  from focused checks, and no paid hosted CI.
- Once implementation tickets close from integrated acceptance, run exactly one
  broad two-axis review against pinned bases and one bounded TDD remediation for
  accepted findings, with focused verification. Requalify causally affected package
  evidence after remediation before the authorized merge/deployment stage.

## Out of Scope

- Separate Grok CLI agents as the inference/worker engine for this feature.
- Browser Grok control or clearing its existing desktop-input hold.
- A general model translation gateway, unrelated provider integrations, fleet
  rollout, or changing current OpenAI defaults.
- Silent API-key/billing/account fallback, copied credentials, weakened grants,
  invented resource allowances, fabricated usage or provider-stop guarantees.
- Rewriting source history, transferring opaque provider state as portable
  context, replaying uncertain actions or claiming unsupported capabilities work.
- Test/fixture frameworks, benchmarks without a named criterion, repeated broad
  review cycles, paid CI or unrelated cleanup/refactoring.

## Further Notes

All21 interview decisions and the complete shared understanding were explicitly
confirmed. The operator approved the public test seams, eight-ticket breakdown and fixed
review baselines; implementation proceeds without reopening product decisions.
Source publication, integration, qualification, tracker closure and working-profile
deployment retain distinct evidence. Keep the parent specification open under the
ticket skill; close implementation children only from their stated acceptance.
