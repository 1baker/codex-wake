# LOCAL-P233 | Grok inference in the modded Codex harness

State: CLOSED
Workflow: DELIVERED_AND_RECONCILED
Work item: LOCAL-P233; related prior intake621 / draft622 is a separate CLI path
Owner: primary / ecochran76
Scope: provider and authentication design; no implementation before shared understanding
WIP limit: one coordinator; one completed read-only provider-auth fact discovery

## Current tracker reconciliation | P255

Issue #628 read back CLOSED after explicit acceptance disposition on2026-11-21.
[Reconciliation](../evidence/plan0255/reconciliation.md) records the accepted
boundary and remaining successor/runtime limits. Historical parent-open, early
authentication and pre-deployment statements below describe their original
milestones and are superseded for current tracker state. No original failures
or operational evidence were erased.

## Objective and settled terminology

The operator wants Grok models to run inside the modded Codex coding harness,
analogous to its OpenAI model use. Codex retains the agent loop, tools, sessions
and worker management; Wake supplies the surrounding runtime tooling. This is
distinct from the earlier separate native Grok CLI/ACP worker proposal.

Existing GLOSSARY.md terms Coding harness, Model identity and Inference provider
already express this distinction. No competing glossary or speculative ADR is
needed. Hard-to-reverse provider/auth decisions will be recorded when settled.

## Current evidence

- The installed modded source revision f986f6ed supports custom model providers,
  Responses wire API, provider-specific credentials and capability overrides in
  codex-rs/model-provider-info/src/lib.rs. Configuration support alone is not
  qualified Grok tool/streaming/resume compatibility.
- Official xAI Build documentation describes Grok in a custom agent loop using
  the public Responses API at api.x.ai/v1 with API-key authentication.
  Source: https://docs.x.ai/build/overview
- Official Build enterprise documentation distinguishes its session inference
  proxy from the public API-key endpoint. Native account/session authentication
  is not established as interchangeable with public Responses authentication.
  Source: https://docs.x.ai/build/enterprise
- Current Grok FAQ describes a shared subscription allowance across products,
  including API usage. Exact account entitlement, credentials, quota attribution
  and custom-client access remain to be verified; do not infer billing from the
  words subscription or API key alone. Source: https://docs.x.ai/grok/faq
- Published native authentication documentation describes session login and
  refresh. It does not by itself qualify credential interoperability with Codex.
  Source: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md

Read-only sidecar /root/grok_provider_facts supplied bounded official-source
evidence and unknowns; primary accepted the auth/endpoint distinction and the
entitlement correction. No credentials, login or inference were accessed.

## Settled decisions: round 1

Operator answered `yes all` to Q1-Q3:

1. Account sign-in and verified existing entitlement lead the first version.
   Public API-key access is an explicit alternative, with no silent auth/billing
   fallback. Exact account access and quota attribution still require verification.
2. Grok is selectable for both the main conversation and individual workers,
   including an OpenAI parent with Grok workers. Existing OpenAI defaults remain.
3. Initial acceptance includes streaming, multi-turn tool use, terminal commands,
   file editing, MCP, interruption and conversation resume. Provider-specific
   extras are advertised only after separate qualification.

## New source evidence after round 1

Official Grok shell documentation explicitly describes direct inference using the
native login session: CLI inference proxy `/v1/chat/completions`, bearer session
credentials, the native-client authentication header and model-routing header.
This supports a direct provider design without running Grok's agent loop. It does
not establish general Codex Responses compatibility or concurrency-safe shared
refresh. Source: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/README.md#using-authjson-for-api-access

The focused authentication guide describes external credential updates and
refresh behavior. Use actual expiry metadata; older README claims about fixed
lifetime/auth precedence conflict with the focused guide. Never assume multiple
writers can safely rotate the same session store without qualification.

Grok keyboard cancellation and its persisted session format describe its own
harness. They do not prove server-side cancellation, zero later billing, rollback
of tool effects or native Codex resume compatibility. Codex must own its durable
history and interrupted-tool state for the chosen provider integration.

## Settled decisions: round 2

Operator answered `yes all` to Q4-Q9:

4. Reuse official Grok sign-in with shared login/logout behavior, coordinated
   refresh and no per-worker credential copies.
5. A unified model/account picker selects provider/account automatically. Workers
   inherit their parent's selection unless explicitly overridden.
6. Cross-provider changes create automatic linked continuations with portable
   messages/tool results. Preserve original history and opaque provider state;
   no extra confirmation. Ordinary same-provider model changes remain normal.
7. Quota/auth/provider failure returns a clear held state. The parent may
   explicitly reassign within existing authority. No hidden provider changes,
   indefinite retries or replay of uncertain work.
8. Existing Wake allowances cover the mixed-provider worker tree. Missing usage
   is never zero; strict accounting requirements hold until qualified.
9. Codex owns inference/tools; Wake coordinates accounts/auth/runtime. Put any
   necessary Grok-specific protocol adapter in Codex's provider boundary; a
   general translation gateway is outside the first release.

These trade-offs are recorded in ADR0006. Provider session and Provider handoff
are added to the existing glossary, preserving the concurrent unified-control
lane's unrelated Byobu environment terminology.

## Focused source evidence before round 3

- The official Build catalog has its own `x.ai/models/list` surface. Catalog
  visibility alone does not prove account entitlement or successful inference.
  Source: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/src/cli_models.rs#L74
- Official login code uses a persistent advisory auth lock, inode checks and
  atomic credential writes, accounting for single-use refresh tokens. Reuse the
  compatible contract rather than introducing an independent refresh writer or
  breaking a held lock. Source: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-login/src/manager/lock.rs
- Login-change generations distinguish login, logout and token rotation. File
  absence is not confirmed logout: official reload behavior can retain cached
  refresh state. Explicit revocation needs a qualified semantic event/readback.
  Source: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-login/src/manager.rs#L567
- Current upstream source mechanisms are not proof that the installed released
  binary shares the same contract. Pin and qualify the chosen revision/version.

## Settled decisions: round 3

Operator answered `yes all` to Q10-Q16:

10. Distinguish account-accessible, qualified model choices from unavailable,
    stale or unverified choices. No guessed model IDs or invisible substitution.
11. A selection change during a turn is staged for the next safe turn boundary.
    Changing selection does not interrupt work; Stop remains explicit.
12. Handoffs carry objective, constraints, active context, completed tool results
    and workspace/checkpoint references, compacting older history. Preserve full
    source history; exclude credentials and provider-private reasoning state.
13. Logout/revocation blocks new Grok turns and requests interruption of this
    harness's active Grok work. OpenAI work continues; interruption uncertainty
    remains explicit.
14. Stop uses Codex local interruption semantics, preventing further local tool
    scheduling. Provider completion/usage uncertainty is separate. Resume uses
    durable known state without replaying uncertain actions.
15. First rollout targets one existing modded profile after required package,
    isolated upgrade/rollback and bounded real-provider workflow qualification.
    Preserve OpenAI defaults/unrelated sessions; defer fleet rollout.
16. Label accounts explicitly and inherit the exact selected account. An account
    change uses the linked-handoff rule; no automatic account substitution.

Inference selection is now recorded as model plus provider account in the existing
GLOSSARY.md, distinct from observed model identity and verified readiness.

## Derived invariants, not additional user choices

- Handoff compaction is automatic, but failure to preserve the required objective,
  constraints, attribution or allowance holds the handoff and retains its source.
  It does not silently drop those already-required elements or reset allowances.
- Provider-private reasoning/opaque continuation data stays attributable to its
  source. No auth-store credentials are copied into conversation context.
- Shared refresh must honor the qualified native lock/rotation contract; unknown
  ownership or incompatible store versions hold rather than spawning another
  writer or breaking a lock.
- Usage reconciliation can release a strict-budget hold only from qualified
  evidence or a separately explicit operator mode/allowance decision. Missing
  usage never grants free work or a fresh allowance.
- Account/provider choices and actual observed identity remain distinguishable in
  records and UI; an unresolved identity/capability is not reported as ready.

## Settled decisions: round 4

Operator answered `yes all` to Q17-Q21:

17. Disable unsupported optional features individually with a clear reason. A
    model missing required baseline functionality is unavailable for that workflow.
    No simulated success or silent fallback.
18. A request for a Grok worker without a model uses an explicitly configured,
    validated account default. Record and pin the resolved model for accepted work.
19. Acceptance may run bounded coding, MCP, mixed-worker, handoff, interruption and
    resume checks in a disposable workspace. Forced logout/revocation tests remain
    isolated from everyday account sessions.
20. Done means reviewed, merged, qualified and deployed to the selected modded
    profile: one broad review and one bounded TDD remediation pass. Source tests
    alone are insufficient; no repeated broad-review loops or fixture frameworks
    as deliverables.
21. Supersede separate CLI-worker draft622/intake621, preserve evidence and retire
    only its task-owned idle runtime after fresh active/uncertain-work checks.
    Browser Grok and unrelated sessions remain untouched.

## Complete shared understanding

- Grok inference runs inside the modded Codex harness. Codex retains tools, MCP,
  conversations and mixed-provider worker management; Wake coordinates accounts,
  native sign-in, refresh and runtime controls. No general translation gateway or
  second Grok agent loop is part of this release.
- Reuse official Grok provider sessions with qualified coordinated refresh and
  shared logout semantics; no worker credential copies. Verify actual entitlement
  and quota attribution. API-key access is explicit, never an automatic fallback.
- One model/account picker serves main conversations and workers. Preserve
  existing OpenAI defaults. Workers inherit exact inference selection unless
  explicitly overridden; configured Grok defaults are validated and resolved
  selections are pinned for accepted work.
- Provider/account changes occur at a safe turn boundary through an automatic
  linked continuation. Carry bounded portable working context and completed tool
  results; preserve source history and opaque provider state. No extra handoff
  confirmation, credential copying or silent loss of required task constraints.
- Provider/auth/quota failures are actionable holds. Parents may explicitly
  reassign under existing authority. No hidden provider/account switches,
  indefinite retries or replay of uncertain work.
- Existing Wake allowances cover the mixed tree. Missing usage is not zero;
  strict-budget work holds until its accounting is qualified. Stop prevents
  further local tool scheduling, retains provider uncertainty and preserves
  durable resume state. Logout interrupts only this harness's owned Grok work.
- Required acceptance covers streaming, multi-turn coding tools, terminal/file
  edits, MCP, mixed-provider workers, handoff, interruption and resume. Optional
  capabilities are individually gated; required-capability failures block ready
  status. Qualified package upgrade/rollback precedes a bounded live disposable
  workflow, then rollout to one existing modded profile without changing OpenAI
  defaults or unrelated sessions.
- Complete through PR/review/one bounded remediation, merge, qualification and
  deployment. Retire the superseded task-owned CLI setup only after safe readback;
  keep its evidence and leave browser Grok untouched.

The operator explicitly confirmed the complete shared understanding and invoked
to-spec, to-tickets and implement-spec, with ticket closure, one broad review and
one bounded TDD remediation. The design frontier is closed; engineering discovery
cannot silently weaken these requirements.

## Current State

All21 decisions and the complete shared understanding are confirmed. The frozen
spec draft, eight ticket drafts and execution ledger are prepared. The invoked
skills require one concrete check of proposed public test seams, ticket graph and
fixed review bases before publication/dispatch; this does not reopen product
requirements. Primary takes auth ticketT1; native providerT2 and retirementT3 are
initially independent delegated tickets. Preserve unified-control design0234 and
its unrelated glossary edits. No implementation or new provider login/inference
has started in this packet.

## T4 implementation contract | model and account selection

T4 reuses the native model picker, `model/list`, ordinary `thread/start` config
overrides and remote thread configuration. Wake supplies a sanitized account/model
catalog through an explicitly configured bounded command source. That public JSON
channel is separate from the existing private account-pinned bearer command.
The catalog command performs no sign-in, native refresh or inference.

Model metadata, registered account identity, authentication freshness and independent
entitlement/inference qualification remain separate evidence. A model listing or a
present credential cannot produce `qualified`. Missing required streaming, terminal,
file-edit and MCP capability holds the coding choice; unsupported optional features
remain individually identified. Freshness is evaluated by Wake using qualified time,
not a guest wall clock. Operator-imported qualification receipts retain exact source,
account binding, model, capability evidence and validity bounds for T8 reconciliation.
Public read/resolve operations require exact account grants; qualification admission
and default changes remain local operator operations.

Each resolved inference selection carries its provider configuration ID, exact
registered account ID/label/binding revision, model ID, catalog/qualification source
revisions and stable selection ID. An explicit per-account default must resolve to a
currently qualified coding choice. It does not replace the global OpenAI default.
Native thread creation resolves the exact selection against fresh catalog evidence,
uses its existing command-backed Grok provider and supported native model metadata,
and retains the immutable selection snapshot for dependent worker/continuation work.

T4 selects new conversations only. It does not replace an active conversation,
carry history, implement safe-boundary staging or create a linked handoff; those
remain T6. T5 owns inheritance/admission and cumulative allowances. Native model/account
selection and local seam evidence do not claim real-account or installed readiness.

T4 selection wire contract (version 1):

- Operator metadata admission: `grok models import ACCOUNT --metadata FILE` binds model identifiers, display labels, context windows, boolean capabilities, sanitized source attribution and validity interval to the existing exact account registration revision. It does not qualify access. `grok models qualify ACCOUNT --receipt FILE` admits separately attributable account/catalog/model-bound entitlement, inference and required coding capability evidence; evidence is retained by content digest. This is an operator admission operation, not a provider test. T8 still owes real evidence. `grok models default ACCOUNT MODEL` succeeds only for a currently qualified model. No sole-model implicit default exists.
- Public reads: `grok models list ACCOUNT`; `grok models resolve ACCOUNT [--model MODEL | --selection-id ID]`. HTTP operations `grok_models.list` and `grok_models.resolve`, MCP `wake_grok_models_list` and `wake_grok_models_resolve`, use the existing `account.observe` scope and the complete exact `expected_target` from the account registration. Public operations cannot register accounts, qualify models, set defaults, request bearer values, refresh, log in or run inference.
- Native config: `inference_catalog_command = { command = ABSOLUTE_EXECUTABLE, args = [...], cwd = ABSOLUTE_DIRECTORY, timeoutMs = 1000 }`. The operator chooses the Wake executable and arguments `--wake-root ROOT grok models native-catalog --wake-executable ABSOLUTE_WAKE_EXECUTABLE`. Its bounded public JSON contains `schemaVersion`, `sourceRevision`, `selections` and account-keyed `providers`. This is distinct from the existing bare-bearer auth command. The generated provider uses only the official Grok session proxy and the account-pinned private Wake auth command.
- Existing native `model/list` returns OpenAI entries and account-qualified Grok entries; each Grok entry has `inferenceSelection`. That snapshot contains `selection`, `providerRevision`, `sourceRevision` and `revision`. `selection` preserves `providerId`, `accountId`, `accountRevision`, `modelId`, `catalogRevision`, `evidenceRevision`, `selectionId`, exact `accountLabel`, `displayName`, `contextWindow`, `readiness`, `reasons`, `capabilities`, `disabledFeatures`, `defaultForAccount` and sanitized `source`. Revisions hash canonical public source/provider data; no bearer value participates. Per-account defaults do not replace OpenAI's default marker.
- Existing `thread/start` accepts the snapshot through ordinary `config.inference_selection`. Native configuration admission reruns the explicitly configured source, requires an exact current snapshot and independently qualified required capabilities, then binds that provider and model. Managed provider requirements and conflicting explicit model/provider overrides hold. Client-supplied `qualified` bits cannot establish readiness. No provider inference is run by resolution.
- The TUI carries that same snapshot from the existing model response through the existing new-conversation path. Held rows are disabled; qualified rows explicitly start a new conversation. Accountless `/model MODEL` arguments cannot choose a Grok account. Existing conversation history is not transferred or staged by T4.
- Remote `SessionThreadConfig` retains optional `inference_catalog_command_json` (protobuf field 4) and `inference_selection_json` (field 5), decoded to the same typed structures and ordinary attributed session config layer. Native `Config.inference_selection` retains the admitted immutable snapshot. This is the inheritance input contract for T5 and continuation identity input for T6; neither worker allowance behavior nor staged/linked handoff is implemented here.
- Qualification requires qualified time, current metadata, current bound native auth without refresh, and independent unexpired entitlement/inference/coding evidence. Missing text/streaming/terminal/file editing/MCP support blocks readiness. Image generation, web search and reasoning summaries are individually disabled by this native adapter regardless of advertised provider metadata. Source readiness does not establish installed package or real-account acceptance.

The native snapshot is constructed by `model/list`, not by the Python resolver: its source revision additionally binds the configured catalog command, arguments, working directory and timeout, and its provider revision binds the accepted provider definition. A Wake `resolve` result is an authority readback; callers select the corresponding native entry by its exact selection ID and submit that native snapshot. A changed source command, provider, account binding, metadata, evidence or readiness holds a stale native snapshot. This pins configuration/source identity, not an installed executable hash; exact installed runtime/package proof remains T8. Client-settings native embedded and remote transports use the existing thread-start override. Hosted transports whose settings owner is the server hold this selection explicitly, rather than silently starting that server's default model.

## T6 worker source contract (primary custody pending)

The public continuation pathway is native `thread/fork`, using the existing
provider/model overrides and exact `config.inference_selection` snapshot. A
provider or account change uses portable context automatically. An additive,
default-false `providerContinuation` intent distinguishes the native picker's
same-account selection from an ordinary independent `/fork`; analytics labels
must not carry authorization semantics.

Native Codex stages a continuation without interrupting the current task. A
native-owned durable handoff record fences future source admission while the
current task finishes and while successor creation is unresolved. Recovery of
an unresolved record holds instead of replaying actions or reopening the source
with a new allowance. The record contains public identity/revision/status only,
not credentials, provider-private state, or a second spending ledger.

The successor retains canonical `parent_thread_id` and `forked_from_id` pointing
to the source, plus its original `session_id` and shared agent controller. Live
permissions, instructions, environment bindings, original cumulative allowance
and governor guards are inherited from the source. Only the admitted inference
selection changes. Source response/completion/usage records are retained there;
copying them into the successor would double-charge the shared task.

Portable context contains objective/constraints and bounded public working
context plus inert records of completed tools and source/checkpoint references.
It contains no executable tool-call history, encrypted reasoning, auth config,
or provider metadata. Missing required context, unmatched/unknown actions,
stale account binding or unpreservable authority holds the transition. Existing
ordinary OpenAI model updates retain their normal in-thread behavior.

These are implementation obligations for #636, not completed acceptance. T8
still owns real-account and installed-package proof.

The T6 intent supersedes T4's temporary new-conversation picker behavior. The
existing public `thread/fork` accepts `providerContinuation: true`, `model`,
`modelProvider` and the admitted `config.inference_selection`. Grok provider or
account transitions imply the intent even when the flag is omitted. Ordinary
known Responses-provider forks retain their existing independent-fork semantics.
A cold registered/configured Grok transition holds because the original live
controller cannot be established; reopening history never grants a new allowance.
The response retains `thread.sessionId` from the original task and sets both
`thread.parentThreadId` and `thread.forkedFromId` to the source. The TUI verifies
those fields against a source read, plus the exact requested provider/model,
before adopting the successor. An older server's independent fork is not adopted.

The native version-1 record is
`CODEX_HOME/provider_continuations/SOURCE_THREAD_ID.json`, private and owned,
with `source`, `successor`, `session_id`, source/target provider and selection,
`state`, `authority_revision`, `context_revision` and optional `held_reason`.
States are `staged`, `preparing`, `ready` and `held`. The original live runtime's
actual shared budget/admission/registry objects are required; matching display
IDs do not qualify a new controller. An unresolved or cold record holds future
work. This is a lifecycle fence, not a second spending ledger or a recovery grant.
The Rust host completes its existing goal transfer through
`ThreadManager::complete_provider_continuation(source, successor)` before the
successor admits work. Goal identity, objective, original budget, spent tokens,
active time and status must match the source; an intentionally deferred goal
stays deferred. Otherwise an inherited active goal continues without another
user turn. T7 owns explicit recovery/revocation behavior; this record does not
authorize reconstructing lost allowance or replaying actions.

The bounded model-visible checkpoint contains `sourceThreadId`,
`objectiveAndConstraints`, `recentPublicContext` and `completedToolResults`.
Completed records retain original `sourceThreadId`, `callId`, tool name, result,
full-result revision and truncation marker. Subsequent handoffs restore this
strictly typed native checkpoint and flatten its inert results, preserving
attribution across provider/account roundtrips. They do not reinterpret arbitrary
developer messages as completion proof. Objectives/constraints are bounded to
32 KiB, recent public commentary to eight 2-KiB entries, results to 128 2-KiB
entries and the complete checkpoint to 64 KiB; required context that cannot fit
holds instead of disappearing. Executable calls, encrypted reasoning and opaque
provider metadata remain in the source. Unmatched/ambiguous actions, unfinished
descendants, background terminal actions or uncertain source completion hold.
No current task is implicitly interrupted by selecting another account/model.

A live empty chat first materializes its canonical source metadata before the
handoff reads history; it does not invent user input or replace the controller.
Input admission keeps managed provider requirements in force and revalidates an
exact qualified Grok snapshot against its bound catalog. A selected Grok thread
can therefore accept input while OpenAI remains the default. The reverse OpenAI
route is admitted only from a ready native record with the original live runtime
and allowance; an account label or copied ID is insufficient. Other retained
routes keep the existing current-profile mismatch checks. The proof is derived
from existing native lineage/journal state, so no client-supplied authorization
flag or new remote schema field is introduced.

Source settings-owned next-turn guards and captured task leases occupy their
existing separate extension-data scopes. Normal governed/goal admission combines
them, preserving pending constraints instead of overwriting one with the other;
unrelated new operator turns retain the original task-family semantics. This
preserves existing cancellation/allowance authority and does not implement T7
Stop, logout or recovery operations.

Before spawning, a handoff validates active and pending task leases together.
Different lease IDs for the same scope hold with conflicting ownership; neither
lease is cancelled or silently replaced. Distinct ancestor and successor scopes
retain their original identities through normal governed admission.

## T7 implementation contract (in progress)

The existing account-auth owner accepts `grok auth revoke ACCOUNT
--expected-target JSON`, protected `grok_auth.revoke`, and
`wake_grok_auth_revoke`. API/MCP requires `account.revoke` and the exact current
registered account target; observation grants and host-only scope do not grant
revocation. The durable registration fence invalidates accepted account revisions
and denies private bearer issuance. It retains the official credential store and
reports provider completion/logout unconfirmed, with owned native interruption
pending observation. It does not invoke provider logout, clear unrelated accounts
or treat credential-file absence as an explicit logout event. Native owned-work
interruption consumes the registered account revision and explicit revocation
reason; source acceptance is recorded separately from installed qualification.

Native request intent is a private version1 scheduling fence under
`CODEX_HOME/provider_safety/THREAD.json`, written before Grok provider I/O. It
retains original session/thread/turn and selection attribution, request/known-tool/
completed/held state, provider-completion observation and usage uncertainty. It
contains no credential or numeric spending ledger. A pending intent without its
original live turn holds on recovery; local Stop preserves that intent rather
than authorizing replay. Required unknown accounting additionally fences the
original shared root, retaining its existing allowance instead of constructing
a fresh budget. Known completed response charges stay in canonical usage records.
Strict Grok tool admission waits for the response's accounting observation and
the original shared controller's budget decision;
Stop/cancellation still uses the existing native task and tool cancellation path.
Normal successful completion flushes canonical history before retiring its
intent. Local compaction uses the same pre-I/O intent and post-budget observation
fence; Grok remote compaction remains unsupported. No public native protocol or
SDK type changes are introduced by T7.

Each active catalog-bound Grok turn observes public account metadata once per
second. Only the selected account's registration generation or explicit
`authentication_revoked` reason interrupts its exact owned turn. A change in
global catalog revision does not cancel peers. An unreadable source or missing
credential file is not proof of provider logout. The monitor does not fetch a
bearer, copy credentials or kill unrelated processes/sessions. New requests and
local tool dispatch retain their admission checks in addition to monitoring.

A completed strict Grok history may be read after unload/restart, but further
spending requires the same original live `LocalAgentRuntime` allowance authority.
If that authority is absent or different, recovery holds; changing a launch limit
does not establish a new zero-spend authority. T7 retains the original controller
identity rather than reconstructing a second numeric ledger from UI counters.
Unknown request/action history is never replayed. A failed request yields an
actionable held error and explicit reconciliation/reassignment requirement; no
automatic provider/account fallback is authorized.

The existing Wake usage observer reports interrupted or failed registered Grok
requests as unknown with null aggregate usage, retaining any prior observed
charges in canonical history. A fully observed `session_budget_exceeded` outcome
can retain its known charge subject to the existing response/usage-record checks.
Source mock acceptance does not confirm provider-side cancellation/logout, real
entitlement, package installation or live-account recovery; those remain T8 gates.

T8 wire-profile correction: a separately approved one-request native diagnostic
returned HTTP426. Official sampler revision `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`
uses `x-grok-client-version` for proxy version gating. The native adapter now
constructs this header from its explicit reviewed `1.0.77` wire-compatibility
profile and identifies itself as `codex-wake-native`; its Codex product version
and User-Agent remain unchanged. Ambient OpenAI/provider headers remain excluded.
The profile is a reviewed protocol dependency, not readiness evidence or a claim
to execute the official CLI. Header regression passes locally; exact package and
real-account qualification remain required before claiming live interoperability.
