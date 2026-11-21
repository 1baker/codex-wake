# #369: Concurrent accounts and identifiable, maintainable Codex builds

State: APPROVED_FOR_IMPLEMENTATION. Owner: ecochran76 / primary coordinator. Coordinating issue: https://github.com/CochranResearchGroup/codex-wake/issues/369. Related workspace recovery: #368. This draft consolidates the approved interview; test boundaries and ticket breakdown approved by the explicit implement-spec invocation. Implementation is not complete.

## Current tracker reconciliation | P255

Issue #371 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Problem Statement

Operating-mode correction: [Plan0205](../0205-2026-11-06-stock-home-and-independent-profiles.md) records the later requirement to retain stock's shared home across logout/login switches and seed independent Wake profiles with explicit transfer. For this mode it supersedes the assumptions below about replacing plain codex or sharing managed-profile configuration. The corrected mode is not yet implemented or activated.

Switching previously authenticated Codex profiles now repeatedly requests login. The cause and first affected release remain unknown. The current launcher can use an official client against a modified shared backend while both show the same upstream version. The operator wants concurrent accounts, common skills/settings/MCP connections, unified history discovery, genuine stock side-by-side operation, and straightforward upgrades without disrupting work or silently dropping modifications.

## Solution

Extend codex-profiles as the account launcher and shared-configuration owner. Keep account authentication and writable runtime state isolated. Add explicit stock/modded build selection, visible actual client/backend/account identity, and supported cross-profile discovery. Normal resume returns to the owning account. Explicit continuation under another account creates a linked successor. Provide automatic update discovery, reproducible staging and explicit activation/rollback, backed by real installed-path tests in a disposable WSL environment.

## User Stories

1. As an operator, I want to log in once per account so ordinary profile switching retains authentication.
2. As an operator, I want A → B → A to select the correct saved account every time.
3. As an operator, I want accounts A and B running simultaneously without either changing the other's credentials.
4. As an operator, I want existing profile names and aliases preserved.
5. As an operator, I want shell and executable launchers to resolve the same configuration.
6. As an operator, I want plain codex to launch the modified build under my selected account.
7. As an operator, I want an explicit stock command that actually uses an official backend.
8. As an operator, I want a persistent account and STOCK/MODDED indicator reflecting the connected backend.
9. As an operator, I want exact upstream/build/patch identities and supported capabilities inspectable.
10. As an operator, I want one shared skills/settings/MCP configuration to maintain.
11. As an operator, I want supported operator-level MCP logins reused regardless of Codex account.
12. As an operator, I want necessary connector/account/channel overrides explicit and inspectable.
13. As an operator, I want to browse conversations from all selected tenant homes without shared writable databases.
14. As an operator, I want ordinary resume to select the conversation's owning account.
15. As an operator, I want compatible stock and modified builds to access the same tenant's conversations.
16. As an operator, I want duplicate activation of the same conversation prevented across channels.
17. As an operator, I want incompatible versions to preserve my history and explain what is unsupported.
18. As an operator, I want explicit continuation with another account to create a linked successor with available history.
19. As an operator, I want original conversation provenance, goals and cumulative accounting preserved across continuation.
20. As an operator, I want automatic notification of upstream releases and visible custom-build lag.
21. As an operator, I want one command to build, qualify and stage a modified upgrade.
22. As an operator, I want an explicit switch and known-good rollback that preserve running work until cutover.
23. As an operator, I want failed builds/tests to leave my active package intact.
24. As an operator, I want realistic isolated upgrade tests without importing production credentials.
25. As an operator, I want disposable caches and inactive payload archives so testing does not consume primary storage indefinitely.
26. As an operator, I want exact account/channel/conversation identity available to later workspace recovery.
27. As an operator, I want genuine authentication expiry distinguished from an account-routing regression.
28. As an operator, I want explicit partial results and uncertain-operation reconciliation rather than silent fallbacks.

## Implementation Decisions

- codex-profiles owns existing profile aliases, selected account home, effective shared configuration and launch management. Native Codex owns actual client/backend identity, capabilities and complete-package runtime behavior. Wake consumes those identities for lifecycle/continuation; it must not introduce a competing account selector.
- Account selection and stock/modded selection are separate dimensions. Plain codex defaults to modified; the explicit stock command selects an official backend. Distinct runtime endpoint/package selection prevents accidental cross-channel connections.
- Preserve one tenant's conversation identity across compatible channels. Resolve writable database concurrency through the native supported ownership boundary; separate sockets alone do not make two database writers safe. Before removing current profile concurrency restrictions, prove account/channel endpoint isolation and safe native store access. If unsupported, report the limitation rather than silently duplicate or migrate sessions.
- Use versioned, inspectable build manifests for upstream base, patch revision, executable identity and capability results. Show actual account/backend identity at connection, reconnect and resume. Launcher labels alone are insufficient; unsupported stock identity features must be stated rather than represented as verified.
- Keep Codex login credentials account-local using existing native credential-store behavior. Do not rotate, copy or overwrite live credentials to simulate successful switching. Retain existing profile configuration edits during migration.
- Share common settings, skills, rules and MCP server definitions through the existing profile configuration owner. Share operator-level MCP authentication only through the connector's supported scope. Per-account exceptions are explicit. Effective configuration is inspectable; unsupported configuration is surfaced. Shared edits reach new launches; live refresh is explicit and does not silently restart peers.
- Cross-tenant session discovery is read-only and version-aware, retaining owning tenant/native namespace provenance. Ordinary resume routes to that owner. Equal directory names, tab names and latest activity do not establish identity.
- Compatible channel switching retains the tenant's conversation and enforces a durable active-conversation fence. Uncertain prior launch or stale ownership is reconciled from native evidence before another launch. Unknown incompatible schemas hold without destructive conversion.
- Explicit continue-with-account creates a separate linked successor using all available supported history; retain source provenance and disclose unsupported/truncated history. Original records remain intact. Resource/goal continuity must use the existing cumulative allocation owner; absent or exhausted authority does not become a fresh allowance. Preparing/resuming context does not imply replay of uncertain pending actions.
- Automatic update discovery does not activate upgrades. Staging verifies official provenance, applies the minimal versioned patches, produces a complete identifiable package, and runs capability acceptance. Patch conflicts, missing capabilities and failing checks preserve the active version.
- Activate a staged build explicitly, handling affected sessions and durable state compatibility. Rollback is qualified against supported database/history schemas; never promise an executable rollback reverses an irreversible data migration. Keep a compatible snapshot/rollback route or hold activation.
- Use an existing disposable WSL fixture, preserving unrelated contents and placing this lab in a dedicated run directory. Isolate test homes, daemon endpoints, temporary credential stores and provider fixtures; production accounts/secrets are not needed for initial tests. A separate user namespace or isolated keyring must prevent the fixture from reading the host's production credential store.
- Stage active payloads on primary storage, separate rebuildable caches from retained packages and evidence, and archive selected inactive loads to a verified HDD target. Record checksums/provenance and verify restoration before deleting staged copies. Logical VHD space is not physical drive capacity. Never move a live VHD or reset unrelated fixtures.
- Expose tenant, namespace, build/channel, logical binding and supported resume capability for HF-19. Implementing complete Byobu restoration remains #368, not an implicit deliverable here.

## Testing Decisions

Proposed highest public boundary: invoke actual account/channel launchers as subprocesses against isolated real native backends and durable tenant homes; inspect connected account identity, package identity, history, effective configuration and effects. Existing profile CLI tests and native scoped-reload/notice/history-recovery tests supply prior art. Prefer those seams over tests mirroring internal helper logic.

For authentication, first obtain a red-capable deterministic A → B → A regression at the actual launch/auth-storage boundary. Compare pinned known-working and affected builds when evidence identifies them. Test credential reload/refresh rotation with synthetic responses and an isolated test keyring. Shell/executable configuration differences are hypotheses, not established root cause. If supported native auth cannot be simulated faithfully, record the missing boundary and preserve the failure; a fabricated successful login is not acceptance.

The WSL product matrix covers two tenants × stock/modded, sequential switching, parallel distinct conversations, duplicate-conversation rejection, restart, reconnect, shared config/MCP resolution, schema compatibility refusal, staged upgrade failure, activation and compatible rollback. Test foreign explicit endpoints and mismatched client/backend identity. Start with owned local fixtures and no external provider calls.

Native capability qualification covers scoped MCP reload without peer disturbance, durable notices without model work, genuine caller/accounting provenance and orphan-output recovery. Unsupported stock capabilities are expected explicit differences. Identify source, package, installed runtime and operator-path acceptance independently. Local synthetic authentication proves local persistence/routing; a later real-account canary is a separate authority and evidence gate, not silently replaced with fake-auth success.

The acceptance packet retains build hashes, commands, red/green output, fixture identity, cumulative-accounting invariants, owned-process cleanup and remaining gaps. No full-scope pass is claimed from a version string, nonempty auth file or unit test count.

## Out of Scope

Complete Byobu restore (#368); business/provider experiments; production account login/logout; automatic account substitution; credential copying; governor activation; resource renewal/reset; global WSL shutdown; deleting prior fixture contents; silent live daemon restarts; unrestricted cross-host tenant discovery. These may not be inferred from test setup authorization.

## Further Notes

Approved choices: shared history within a tenant across compatible builds; owner-routed resume; explicit linked successor across accounts; modified default launch; shared supported MCP operator identity; automatic update checks with explicit activation; full available successor history with preserved accounting; existing disposable WSL setup and staged/HDD payload handling.

Current evidence: the original profile authentication regression has not been reproduced. Separate account auth files exist, but validity and account routing are unproven. The fixture is prepared, not acceptance-tested. Existing profile documentation still restricts cross-account concurrency. The running modified native package has independent tests but broader installed acceptance remains incomplete. #369 is coordination; children close only on their own named delivery target.

Definition of done: approved child outcomes delivered through installed paths in the disposable environment, one integrated compatibility/upgrade receipt with explicit remaining live gates, truthful documentation and no automatic production cutover.
