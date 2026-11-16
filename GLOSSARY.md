# Codex Wake

Codex Wake records wake requests and agent messages whose deadlines must remain meaningful across outages and restarts.

## Language

**Wake deadline**:
The point in time when a registered wake becomes due, including time spent asleep.

**Message expiration**:
The deadline after which a message is no longer eligible for delivery, including time spent asleep.

**Trusted time**:
A bounded estimate of current time accepted under the configured source-selection rules.

**Time uncertainty**:
The condition in which available evidence cannot establish whether a deadline has passed.

**Scheduling intent**:
The durable original request to schedule one follow-up, retained even when a
clock cannot yet qualify its deadline. Reusing its key returns that request;
it does not authorize another submission.

**Relative clock continuity**:
Evidence that elapsed observations belong to the same qualified host-counter
epoch and rate policy. Losing continuity holds the original anchor rather than
starting the delay again. Elapsed evidence does not establish absolute UTC.

**Message receipt**:
An attributable record of retrieval, acceptance or another message outcome.
Reading records retrieval; it does not accept the work.

**Work claim**:
The exact recipient's explicit acceptance of processing a message. Only a newly
accepted claim permits that worker to begin; it grants no additional task rights.
Successful or failed processing requires this claim before terminal acknowledgment.

**Receipt publication**:
Making an existing receipt available to observers. Publication is durable journal
work and does not itself require the recipient's tab to remain open.

**Recovery disposition**:
The operator's attributable decision to retain snapshot-era work as unknown and
prohibit its processing or replay. It does not infer missing outcomes.

**Recovery hold release**:
A separate operator action after committed disposition. It leaves the bus paused
and requires fresh grants before new work; original history stays fenced.

**Agent spawn**:
Starting a separate agent conversation with an explicit assignment and scope.

**Compact dispatch packet**:
A bounded assignment containing objective, authority, scope, acceptance, evidence
locators, allowance, stop conditions and governance readback requirements. It
starts fresh context by default; full-history context requires a recorded
task-specific reason and a pinned source. A packet snapshot creates no authority.

**Agent refresh**:
Reloading selected runtime resources while preserving the conversation identity
and unfinished work. Legacy profiles reopen its client; approved shared MCP
refresh keeps clients and reconnects the shared server's MCP connections after
idle observations. Neither path renews counters or resource allocation.

**Agent handoff**:
Passing an unfinished objective and its checkpoint to a different conversation,
continuing its already-authorized scope, cumulative spending, remaining allowance
and original deadline. It does not renew resources, change identity or widen
permissions, and does not require optional governor enrollment in manual mode.

**Handoff checkpoint**:
The outgoing agent's durable account of completed work, remaining work, evidence,
authority, pending obligations and resource allowance for its successor to verify.

**Lifecycle controller**:
The external owner that observes and coordinates an agent's lifecycle transition.

**Continuation allowance**:
The explicitly authorized resources remaining for work on the same objective.
Fresh context does not replenish that allowance.

**Session budget**:
The user-authorized token and elapsed-time limits for one agent goal session.

**Objective budget**:
The user-authorized cumulative token and elapsed-time limits for an objective,
including successors, reviewers, delegated work, retries and failed attempts.
Changing conversation does not replenish this budget.

**Resource allocation**:
The resources a user authorizes for a named objective and its continuations.
Conversation identity does not determine or replenish that authority.

**Allocation renewal**:
An explicit user change to a named objective's resource allocation. It does not
change unrelated allocations or erase their usage history.

**Allocation continuity**:
The verified relationship that charges a successor's work to the same objective's
existing allocation, preserving cumulative usage and its original deadline.

**Caller provisioning**:
Binding a verified conversation to the resource authority it may exercise.
Provisioning alone is not proof of accounting or running enforcement.

**Goal supervision**:
Observing an existing goal's authorized resource usage, requesting a checkpoint
before its limits, and pausing continuation when its stopping condition is reached.

**External goal watcher**:
The independent process observing one goal/allocation and requesting native
checkpoint, pause and exact-turn interruption. Configuration alone does not prove
that the watcher is running or has accepted an enrollment.

**Allowance extension**:
An explicitly authorized increase to an allocation's ceiling or deadline that
retains the resources already consumed. This is a form of allocation renewal.

**Budget window reset**:
An explicitly authorized new allocation generation/window with a qualified usage
anchor. Prior charges, stop history and native counters remain intact; a zero
current-window counter does not mean zero lifetime usage of that objective.

**Enforcement notice**:
A durable explanation of watcher engagement, checkpoint, stop or supervision loss
for model context and operator presentation. Recording, control acknowledgement,
presentation and operator response are separate proof boundaries. The visible
notice/renewal workflow is planned under #343, not established by this definition.

**Handoff preflight**:
The successor's verification of runtime readiness and assessment of whether the
outgoing work advanced the approved objective with adequate evidence and scope
discipline. Runtime readiness alone does not establish work acceptance.


**Emergency pause**:
An operator-controlled hold preventing new wake deliveries in its selected scope
until explicitly resumed. It preserves scheduled work and original deadlines.

**Wake cancellation**:
Retiring an eligible wake so it no longer delivers, while preserving its history.
It cannot retract work already submitted to a recipient.

**Owned-turn interruption**:
Stopping a running turn only when durable assignment evidence identifies it as
Wake-owned. It is separate from pausing future deliveries and cancelling wakes.

**Recipient binding**:
The verified relationship between one conversation and the live client that
currently owns its input. A tab label or working directory alone is not a binding.
Attachment observation must retain the selected runtime and executable context.
Failed executable discovery is unavailable evidence, not proof that a recipient
has no attachment.

**Observed delivery**:
Inspection evidence that a wake prompt was accepted in the bound recipient's
interface. It does not establish a receiver acknowledgment or a work claim.

**Native completion observation**:
Evidence from the exact native turn and complete matching user/client items
that execution reached a terminal state. Compact summaries can locate a turn,
but cannot alone establish this evidence. Unrelated tool output need not be
hydrated to reconcile the selected submission.

**Receiver acknowledgment**:
An attributable receipt from the exact recipient confirming a specified delivery
outcome. Its meaning is limited to that outcome; it does not imply completed work.

**Busy delivery policy**:
The selected behavior when an exact recipient is already working: wait, verified
queueing or explicitly authorized interruption, within the original deadline.


**Host-bound runtime actor context**:
An operator-issued mailbox actor capability paired with a private frozen runtime
binding. Grok invocation checks the managed process generation, inherited session
claim, caller ancestry and enrolled root. This is host delegation, not native Grok
caller attestation; terminal text and claimed IDs alone grant no work authority.

**Native mailbox host delegation**:
An explicitly configured MCP host's operator authority to issue and reuse distinct
mailbox actors for verified native callers within previously enrolled roots.
Native identity selects an actor; it does not itself grant project enrollment.
The host keeps credentials outside tool arguments and uses caller-local launch
context rather than a mutable shared actor credential.

**Definitive pre-I/O non-submission**:
Positive adapter evidence that a selected method was unavailable before any
submission bytes. An absent response, missing marker or timeout is insufficient.
Only a host-approved fallback profile may switch methods on this evidence.


**Terminal attachment**:
A particular terminal view associated with a conversation. Its label and position
are separate from the conversation's identity.

**Managed agent**:
An agent whose one exact conversation, execution context and permitted operations
are explicitly tracked by a controller. Its identity survives verified process
and terminal changes; a successor conversation is a separate managed agent.

**Agent instruction**:
One bounded agent turn admitted as a declared instruction in a workflow.

**Step attempt**:
One attempt to execute a declared workflow operation. Its reported completion
and acceptance are separate outcomes.

**Work acceptance**:
An evidence-backed decision that a result meets its declared acceptance
conditions. A worker's completion report alone is not that decision.

**Recurring schedule**:
An agreement defining when repeated checks become due, which conversation receives
them, their session mode, and the conditions under which scheduling ends.

**Scheduled occurrence**:
One planned execution arising from a recurring schedule, distinct from attempts
to deliver or execute that occurrence.

**Wake durability**:
The interruptions or owner lifecycles a retained wake is required to survive.
Durability is separate from its deadline and delivery outcome.

**Parking a tab**:
Moving a live terminal attachment into a holding workspace while preserving its
agent. Parking alone does not pause work or renew resource allowance.



**Session permission profile**:
A named set of action permissions a session may use under operator authority.
Selecting a profile does not establish session identity or provide more resource allowance.

**Mandatory permission prohibition**:
An operator restriction that a more permissive profile or session-specific rule cannot override.
**Agent succession**:
The relationship between a predecessor and successor managed agent continuing
the same task, with outstanding obligations and resource continuity preserved.

**Task brief**:
The approved objective, phase, boundaries, acceptance conditions and context for
an assignment. An admitted instruction refers to a particular revision.

**Recipient-startup policy**:
The selected conditions under which a wake may use an existing recipient, load
a saved conversation or start its declared task. It is separate from wake lifetime.

**Wake session mode**:
An explicitly selected policy for whether a wake ends with its recipient session,
restores that conversation visibly, or continues it through an available live or
background recipient. Selecting a mode does not define recurrence or cadence.

**This session only**:
A wake session mode that cancels future wakes when the recipient agent exits or
its pane or tab is destroyed. Detaching a terminal client is not session closure.

**Re-open session live**:
A wake session mode that restores the same conversation in a visible terminal
when needed, using its most recently verified harness and working directory.

**Background**:
A wake session mode that uses the same conversation in its live terminal when
available and otherwise continues that conversation without a visible terminal.

**Semantic agent state**:
A fresh evidence-backed account of what an exact managed conversation is doing.
It is distinct from binding readiness, work acceptance and permission to act.

**Mutation resource claim**:
Exclusive cooperative custody of a declared resource while work may mutate it.
Losing contact with its owner does not release custody or authorize a new writer.

**Acceptance contract**:
An approved immutable set of checks bound to one exact task-brief assignment pin.
An evaluation records independent evidence; missing or stale evidence is unknown.

**Input owner generation**:
The current cooperative custody token for automated or human terminal input.
A takeover changes the generation and fences old automated operations.

**Attention response**:
An attributable operator answer to a specific current request. Recording an answer
alone grants no permission, executes no effect and authorizes no uncertain replay.

**Background job result wake**:
An existing exact-owner wake observing the durable result of one approved bounded
local job. Awaiting the result does not relaunch the job or renew its task allowance.

**Governor**:
The operator-visible controller that applies authorized resource limits to a selected objective and explains its interventions to the operator and model.

**Governor deactivation**:
The operator's durable choice to stop governor interventions in a selected scope. It preserves accounting and work, does not renew resources or resume stopped work, and remains in effect until explicitly changed.

**Host compatibility preflight**:
A bounded read-only check before opted-in dispatch, separating reusable static
host observations from fresh accounting, controller and operator-control state.
It reports the actual enforcement mode without granting work or resource authority.

**Protected completion resources**:
The unused acceptance, review and bounded remediation estimates retained inside
an existing objective allowance. Host-bound completion work may use them;
implementation must leave them available. Deferral keeps mandatory work pending,
and verified completion releases unused protection without renewing the grant.


**Logical agent**:
A durable controller identity linking an agent's work across explicitly related
conversations and runtime instances. Keeping this identity does not transfer
credentials, permissions or resource allowance.

**Conversation**:
A provider or coding runtime's durable record of an exchange. A successor
conversation has its own identity and retains a relationship to its predecessor.

**Coding harness**:
The application that owns a coding agent's interaction and workflow. Its identity
is distinct from the model and inference provider used by a conversation.

**Model identity**:
The model name or revision reported for a conversation or turn. A configured
model selection is distinct from an observed model identity.

**Inference provider**:
The hosted service or local serving runtime through which a model is accessed.
It is distinct from the coding harness, account profile and execution host.

**Provider session**:
An authenticated relationship with an inference-provider account. It is distinct
from an agent conversation and may be shared by related conversations.

**Inference selection**:
The chosen model and provider account for a conversation or worker. It is distinct
from the provider-reported model identity and verified execution readiness.

**Provider handoff**:
A logical agent's transition to another inference provider through a linked
successor conversation, carrying portable context while preserving source history.
_Avoid_: Model change when the inference provider also changes.

**Runtime instance**:
A particular running instance of a coding agent or app server. It is distinct
from the durable conversations it can serve.

**Presentation attachment**:
A terminal pane, TUI connection or structured client connection through which a
runtime can be presented or accessed. Replacing an attachment does not by itself
replace the conversation or logical agent.

**Byobu environment**:
The operator's collection of Byobu terminal sessions, including their tabs,
panes and associated parent-child agent relationships.
_Avoid_: "My tabs" when a precise resource identity is required.

**Terminal session**:
A named collection of terminal tabs whose saved definition can remain when it
has no tabs. It is distinct from an agent conversation and a code repository.
_Avoid_: Workspace when referring to the user-facing terminal session.

**Empty terminal session**:
A saved terminal session with no tabs. Its existence does not imply a running
terminal container or agent process.

**Tab routing rule**:
A saved criterion and destination terminal session for relocating matching tabs.
Continuous application is an explicitly enabled behavior of the rule.

**Routing hold**:
A per-tab suspension of automatic relocation following a manual move. It remains
until routing is explicitly resumed for that tab.

**Tab pin**:
An explicit instruction to retain a tab's placement against automatic routing.

**Terminal tab**:
A terminal window within a terminal session, containing one or more panes.
Moving a tab between terminal sessions does not itself replace its conversations.

**Tab trait**:
An observed property of a terminal attachment or its associated session, such as
harness, build, account, reported model, inference provider, remote host, turn
activity, responsiveness or visible error. Each observation retains its freshness and uncertainty; one trait does
not establish another.

**Tab activity**:
The observed work state of a conversation associated with a tab, such as running,
idle or waiting for input. It does not establish that the terminal interface is responsive.

**Monitor observation freshness**:
Whether a retained monitor frame remains within its allowed elapsed age. The
default reader uses authenticated Stable Time counter evidence from the same
epoch and frequency, including conservative rate and counter-resolution bounds.
Missing evidence or lost continuity is stale; guest wall timestamps are display
metadata and cannot qualify freshness. An authenticated counter can qualify
elapsed age even when UTC is unavailable.

**Tab responsiveness**:
The observed ability of the exact terminal interface associated with a tab to
answer a health check. Conversation activity or an available metadata source
alone does not establish responsiveness.

**Visible tab error**:
An error freshly observed as displayed on a terminal attachment. It is distinct
from an internal runtime error and from an unavailable observation source.

**Observation availability**:
Whether the source supplying a tab trait is currently usable. Losing that source
makes affected evidence uncertain without changing the tab's identity or appearance preferences.

**Tab group**:
A named or criteria-based collection of terminal attachments. Group membership
alone does not move attachments or change their conversations.

**Worker tab**:
A terminal tab presenting an agent carrying out work delegated by another agent.
Its placement is separate from the identity and lifetime of that work.

**Bot**:
A persistent specialist identity shared across its clients. Its identity survives
individual conversations, runtimes and terminal attachments.
_Avoid_: Tab, conversation or client as synonyms for bot.

**Sub-bot**:
A bot supervised by a parent bot, with a specialization inherited and further
focused from that parent.

**Bot family**:
A root bot and all its descendant sub-bots. A sub-bot's immediate parent and
its family root can be different bots.

**Workers session**:
A terminal session collecting worker tabs from one or more bot families.

**Tab view**:
A filtered and ordered presentation of terminal attachments and their traits.
Updating a view is separate from physically rearranging the attachments.

**Resource binding**:
The explicit relationship between a stable controller resource identity and its
scoped native representations. A binding identifies context; it grants no action
or resource authority.

**Resolved operation target**:
The particular resource identity and instance selected for one operation.
Subsequent label reuse or instance replacement does not redirect that operation.

**Searchable agent inventory**:
A view relating agents and conversations to their accounts, execution contexts,
runtimes, presentation attachments and control relationships. Names and stable
identifiers can locate observations, whose freshness and uncertainty remain visible.

**Upgrade recovery**:
Continuing work paused by a specific daemon upgrade from its durable checkpoint,
under the same authority, remaining allowance, deadline and conversation identity.
It does not resume work that was already paused or grant new resources.

**Recovery acceptance**:
Durable evidence that one recovery continuation was admitted for an exact upgrade
and conversation. An absent reply does not prove that continuation was rejected.

**Unknown recovery delivery**:
A recorded recovery attempt whose acceptance cannot be established. It remains
held for reconciliation rather than authorizing another attempt.

**Upgrade resource authority**:
Host-owned evidence binding a recovery to the original goal, tenant/account, policy, cumulative accounting and limits. The trusted TUI user action establishes original native policy when creating a native goal, and may carry already verified native policy through later controls without changing its grant. A later status action cannot convert an existing unknown or externally controlled goal into native-only authority. Model handoffs cannot establish this declaration; absent or unverifiable authority keeps recovery held.

**Conversation import**:
A source-preserving copy into a distinct destination conversation in a selected home, with
source identity and revision provenance. It transfers no credentials, goals,
grants or resource allowance and does not change exact-owner resume.

**Account daemon**:
A native daemon bound to one private account home, identified by its socket,
process birth/boot and executable build. It is separate from both the Wake
scheduler daemon and an attached native client.

**Stock shared home**:
The operator's stock Codex home whose history and configuration remain available
when the operator switches authenticated Codex accounts.

**Wake profile**:
An independently managed Codex environment with its own home, history and
configuration. It can be seeded or explicitly updated from another home without
sharing that home's writable state.

**User controller root**:
The persistent named-account registry and host control state selected by an
explicit root, optional host override or saved default. First use defaults to
`XDG_STATE_HOME/codex-wake/controller`; project-local wake records keep their
separate project root.

**Task governor**:
The control that observes and bounds one task's cumulative resource use across
its qualified delegated work, retries and continuations. Unrelated work remains
outside that task's scope.

**Advisory limit**:
A declared allowance whose observance is not externally enforced. Selecting it
is explicit; loss of enforcement does not silently make a limit advisory.

**Budget window**:
The resource allowance measured from a qualified activation or authorized reset
boundary. Starting a new window preserves previous charges and lifetime history.

**Formatting namespace baseline**:
The original managed terminal settings captured before decoration for one
terminal server/session identity. Explicit enable on a replacement namespace
retains the earlier baseline and captures new originals; returning namespaces
reuse their originals. Automatic refresh crosses this boundary only with an
explicit recover_namespace preference; rollback never crosses it.

**Tab startup service**:
An explicitly enabled, root-specific systemd user unit running the existing tab
monitor at login. It follows saved formatting policy and holds; it neither creates
terminal sessions nor grants authority to submit prompts.

**Codex launcher pathname**:
The absolute operator-selected executable path retained by a durable native wake.
If that path is a stable symlink, subsequent operator-selected builds may replace
its target without changing the registered launcher. An explicit release path
remains a release pin; missing historical pins do not authorize account fallback
or rewriting existing scheduling intent.

**Mailbox first contact**:
A host-delegated sender's initial message to a verified native recipient in an
already enrolled root. The recipient need not poll first; provisioning preserves
existing root grants, revocation and cross-root restrictions.

**Pending-recipient discovery**:
An operator opt-in that reconciles a pending authorized notification's exact
recipient with its current live tmux client. It refreshes delivery binding only,
without enrollment, actor reauthorization, client launch or notification replay.

**StableTime-required mailbox**:
A mailbox whose persisted time policy requires the configured StableTime service's
finite authenticated UTC evidence, without guest-clock or plain-NTP fallback.
Existing mailbox instances observe activation at their next transaction.

**Harness readiness**:
A read-only observation of the selected native runtime and exact recipient at
registration. It is separate from durable retention and monitor health, and is
rechecked at dispatch. Unreconciled prior submissions hold admission.

**Historical read transport**:
The current intent's qualified CLI used only to observe an exact old native
submission when its saved executable is gone. It never replaces the original
binding, grants authority, or authorizes submission replay.
