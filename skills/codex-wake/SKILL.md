---
name: codex-wake
description: Use Codex Wake for durable recurring clock/interval monitoring, one-shot follow-ups, exact saved-conversation tab recovery, tracked agent exchanges, session discovery, and optional resource supervision. Honor existing numeric ceilings, manual or supervised mode, host grants, exact identities and uncertain-effect reconciliation. Prefer scheduler-owned recurrence over worker self-rearming. Distinguish persistence, monitor readiness, restoration qualification and actual execution. Prefer configured MCP tools; use the supported CLI otherwise.
---

# Codex Wake

Use durable triggers when work must resume after a defined event. Load the
matching reference before acting; inspect the returned receipt before claiming
registration, delivery, enforcement or refresh.

| Request | Required reference |
| --- | --- |
| Grok inference or workers inside Codex | [Native Grok provider status](references/grok-native-provider.md) |
| Token/time allowance for the existing native `/goal`; enrollment or held enforcement | [Existing goal limits](references/existing-goal-limits.md) |
| Controller maintenance or real-agent acceptance | [Operator maintenance and acceptance](references/controller-maintenance.md) |
| Memory, swap, CPU or task controls in a dedicated executor | [Resource limits](references/resource-limits.md) |
| Update this client's skill/MCP, spawn a worker or hand off to fresh context | [Lifecycle](references/lifecycle.md) and [refresh workflow](references/workflows.md#refresh-this-agent-after-an-update) |
| List/cancel wakes or emergency pause/interrupt/resume | [Wake controls](references/wake-controls.md) |
| Durable peer request, claim, reply or suspended reply wake | [Tracked work](references/workflows.md#tracked-agent-to-agent-work) and [mailbox workflow](references/workflows.md#local-agent-mailbox-workflow) |
| Find a session/tab or address a human tab target | [Human targets](references/workflows.md#human-tab-targets-through-mcp) |
| Repeated clock/interval monitoring | [Durable recurring schedules](references/workflows.md#durable-recurring-schedules) |
| Scheduled follow-up, transport choice or host readiness | [Native workflow and preconditions](references/workflows.md#native-workflow-first) and [patterns](references/workflows.md#common-patterns) |

Use your actual native caller identity and existing objective allocation.
Successors retain cumulative spend, the original deadline and stop latches.
New enrollment defaults to fresh input plus output; re-enrollment preserves its
accounting basis. Verify a fresh independent controller and qualified accounting
before externally supervised campaign work. An explicit operator choice of manual
resource monitoring permits bounded development/repair under the same cumulative
limits; report the fallback and keep shared services and stopped campaigns unchanged. A held campaign still permits operator replies,
bounded setup diagnosis and checkpoint writing. Only explicit user renewal
recorded through host authority creates a new allowance.

Reading an operator-provided handoff in a new session continues the already
authorized objective with its remaining allowance and original deadline. It does
not require resource reset, repeated approval or optional governor enrollment.
Continue in the operator-selected manual mode when applicable; do not enable a
watcher or governor just because a handoff was read. A completed or blocked native
goal for another objective is not a global session lock. Genuine exhaustion of
the continuing objective remains explicit and does not replenish on handoff.
When already-enabled supervision is requested through the host adapter, a
qualified native successor automatically selects its source's existing allocation.
An ordinary Markdown read alone is not native lineage or accounting proof; keep
manual continuation separate from claims of verified automatic enforcement.

For refresh, inspect the profile's scope and preserve one fixed intent. A
thread_mcp_idle profile requires a successful read-only native scope probe and
refreshes only the selected thread's MCP connections after that thread is idle.
Older daemons remain unsupported. Shared MCP refresh requires all affected
conversations idle; queued admission is not verified refresh. Client replacement
alone does not prove MCP reconnection.

Detailed workflows and examples remain in [workflows](references/workflows.md).

## Managed harness additions (0.21 source)

Use `wake_agents_list/show/enroll/reconcile` for persistent managed identity and
verified self-enrollment. Operator unenrollment remains effective until explicitly
re-enabled; inventory membership grants no operations.

Use `wake_task_briefs_propose/approve/inspect/admit/pin` to freeze approved scope
for an instruction. A worker proposal cannot approve itself; controller approval
is delegated by private host policy. Carry the exact admitted pin in checkpoints.

Use `wake_native_after/at/file` for exact-self scheduled intent with explicit
lifetime and recipient startup. New registration defaults to configurable
create/load/run, but a missing runtime capability remains unsupported. Disk
persistence is not monitor or delivery proof. `wake_owner_complete` reconciles an
exact operator-approved completion event; identity alone cannot declare an owner
finished, and absent evidence holds. It never replays an uncertain submission. See
repository docs/managed-inventory.md, docs/task-briefs.md and docs/wake-policy.md
for the source contracts. This source update does not refresh installed skills.
