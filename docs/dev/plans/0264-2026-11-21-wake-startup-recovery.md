# Plan 0264 | Wake startup recovery

State: CLOSED
Owner: primary / ecochran76
Work items: #723 and #742
Spec: #749

## Current State

The operator confirmed that the wake service owns recovery and reconciliation
at startup. The operator approved readiness and placement fallbacks, same-harness
restoration, Wake Codex account continuity, and heuristic tab reclamation. The
design decisions below are settled.

## Agreed behavior

- On startup, automatically re-arm eligible recurring schedules with no
  unresolved delivery. Reconcile interrupted occurrences from retained intent
  and delivery evidence.
- Continue a provably unsent occurrence only while it remains eligible.
  Preserve its original identity, deadline, and missed-run policy. Retain
  accepted delivery outcomes without replay.
- Hold only the unresolved occurrence when evidence cannot settle delivery.
  Report why and expose a supported reconciliation action. Independent wakes
  continue. Future occurrences follow the existing overlap and missed-run policies.
- Resolve delivery eligibility before restoring the exact saved conversation.

## Tab restoration

- Report restoration readiness separately. A blocked restoration does not prevent
  delivery to a verified live attachment of the exact saved conversation.
- Capture terminal session, tab name, and position. For example, a tab displayed
  as `13: wk-grok` in the main Byobu session makes slot 13 a strong candidate
  after reboot when the saved placement and current presentation agree.
- Resume the exact conversation with its previous harness and working directory.
  A Wake Codex session reuses its saved profile and the same account. If that
  binding is unavailable, report the gap and hold restoration.
- Reuse a verified live attachment of the exact conversation even if the tab
  moved or was renamed. For an idle candidate, rank it using the saved terminal
  session, title, position, and the pane's observed working directory. A matching
  working directory corroborates placement, especially when title or position
  drifted. Verify pane ownership and idle placeholder status before reclaiming
  the position. Preserve the original shell when reclaiming its slot.
- Leave tabs with other work or ambiguous ownership intact. Create a new tab
  using the saved placement and naming fallbacks.
- Recreate a missing terminal session from its saved definition. Append when an
  anchor is gone and report actual placement. Hold when the destination session
  cannot be recovered. For a name collision, choose a unique restored name and
  report it.

## Restored tab presentation

- Keep the tab title and any existing Codex Bots family accent and immediate-parent
  label. Render a small **↻** marker beside the title on a restored tab, including
  a new tab created when the original slot is occupied.
- Clear the marker on the first explicit focus. Preserve the **Restored by Wake**
  record and the actual placement in tab inspection after the marker clears.

## Acceptance

Restart an isolated supervisor with clean, provably unsent, accepted, and unknown
occurrences. Verify automatic re-arming and one eligible delivery without manual
reconciliation. Keep the unknown result scoped and show the operator why it is
held. Separately verify exact tab restoration after isolated terminal loss,
including exact placement, mild layout drift with matching working directory,
and an occupied slot where another pane uses the same working directory.
Verify preservation of harness and Wake Codex profile/account. Check that the
restoration marker clears on explicit focus while inspection retains provenance
and placement, and that the title and bot family accent survive.

## Definition of done

Pass the isolated restart and tab-restoration acceptance cases through the
public surfaces, with matching startup, placement, and delivery evidence.

## Out of scope

Changes to existing production wakes or terminal sessions during design.

## Execution ledger

Integration branch `feat/issue-749-wake-recovery`, base `a1dbceed656c4c906f87b280185b9d8cdb5c7904`.

| Ticket | Blockers | Owner | State |
| --- | --- | --- | --- |
| #750 Startup recovery | None | primary | Validated locally at `9beac576`, tracker closed |
| #751 Binding and readiness | None | readiness751 | Source `97f1db94`, integrated and validated at `22eb8b9e`, tracker closed |
| #752 Exact tab restoration | #750, #751 | restore752 | Source `1d9fdda9`, integrated and validated at `b2aeccef`, tracker closed |
| #753 First-focus marker | #752 | marker753 | Source `c0808ce1`, integrated and validated at `0bc3925f`, tracker closed |

Startup recovery hands versioned poll evidence to the existing durable
record-level dispatcher. Unversioned poll holds still require exact-token
reconciliation when their delivery effect cannot be proved. An empty firing
directory alone cannot clear one. A native delivery with durable uncertainty
retains its original occurrence and follows the schedule's overlap policy.

Local Python 3.12 supervisor scheduling tests passed (7 tests). A public
recurring schedule regression verified that an uncertain delivery retains its
identity and reason across scheduler generations while an independent
schedule materializes exactly once.

The supervisor, recurring schedule, native intent and native delivery selection
passed 66 tests on Python 3.12, including the disposable supervisor process
qualification. The comparable Python 3.11 source selection passed 65 tests
with the project dependencies installed in a disposable environment. A raw
Python 3.11 attempt lacked websockets and was superseded by that run.

The integrated binding, runtime mode and recurring schedule selection passed
34 tests on Python 3.12. The #751 worker also passed 24 CLI, API, MCP and
contract tests. Binding verifies the pinned account home and reports provider
login identity as unverified. Real restored delivery is part of #752.

The restoration worker passed 32 focused tests per Python 3.11 and 3.12.
The integration selection passed 51 tests on Python 3.12. It includes real
isolated tmux placement checks for the exact slot, title drift with matching
cwd, and a same-directory occupied slot. The placeholder shell kept its
original window and pane identity when moved to the spare slot.

A separate end-to-end run at `b2aeccef` used the exact previously qualified
Native `d907a42df3` binary, its matching StableTime wire v2, a disposable
native home and tmux server, the public supervisor, and loopback model
responses. It saved the conversation, restarted the private native daemon and
supervisor, verified the exact conversation and pinned home, and observed one
additional native turn complete after the original occurrence was admitted.
The restored window reclaimed slot 1 with a unique title, and the displaced
shell survived. No owned processes remained. The retained passing receipt
SHA-256 is `9c5800125d9f5cf80f50218b935ed9cc35ab6fb9582af20db2c0d54744d026c4`.
Earlier attempts are retained. The older wire-v1 Native binary left an input
queued when used with the wire-v2 time reader. That result was not counted as
delivery. The matching-native run used a disposable provider and did not
exercise a provider login.

The marker worker and integration both passed the 15 focused restoration and
formatter-startup checks. A second integration selection passed 32 tests.
The private tmux check verified explicit select, next, previous, and last
window actions. Startup rendering shows the marker on the initial implicit
selection. Focus clears the marker and preserves placement in inspection.

## Final review and remediation

The one Standards and Spec review compared `a1dbceed...0bc3925f` after all
four implementation tickets closed.

- Standards accepted two findings. Temporary startup lock contention stranded
  a recoverable root. Schedule readback on the monitor hot path also reread
  the wake archive for each schedule. The supervisor retries only contended
  startup candidates on the registry cadence, and polling reuses its existing
  wake snapshot.
- Spec accepted three findings, including the same startup contention defect.
  A changed account inside the same registered profile home could pass the
  existing check. Affected OpenAI profiles now pin the local cached ChatGPT
  account claim as a digest and hold restoration if it changes or becomes
  unavailable. This is cached identity evidence. Verified live attachment reuse
  remains available. Schedule readback now includes the original unresolved
  reason when retained and the exact native reconciliation command.

The single focused TDD pass at `2b7939fa` reproduced all three public
behavior failures and passed 12 selected regression tests after the fix.

The final affected source selections passed 140 tests on Python 3.11 and
141 on Python 3.12, including the disposable supervisor qualification on
3.12. Sixteen additional account and controller tests passed. Pinned Ruff
and Git whitespace checks passed. Hosted CI was skipped.

The final private native run repeated restoration and confirmed the
first-focus marker and retained placement on the fixed source. Its
receipt SHA-256 is
`e1e4f811bc70591bc5221887fd4a5b96c708510ec43c5558c7807cda3d51fb3d`.
The acceptance exercised the pinned profile home with loopback responses.
Cached account drift is covered through the public API regression. The
implementation tickets are closed and the integration branch is published.
The parent spec remains open for integration and deployment tracking.
