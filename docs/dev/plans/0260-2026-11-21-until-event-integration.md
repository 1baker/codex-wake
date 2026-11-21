# P260 | Reconcile accepted until-event source with current main

State: CLOSED (source integration acceptance; deployment separate)
Work item: https://github.com/CochranResearchGroup/codex-wake/issues/733
Original accepted source: #697;2b9f7a9cf3f2e1831f3e3ab1bda79c067d56d821
Owner: primary / ecochran76; implementation merge_core
Priority: P1
Branch: fix/native-until-event-port
Base:85c280d9763c6c2bac3c613476b3df2f3c3e0961
Target: origin/main; source integration only
WIP: one implementation lane plus disjoint bounded custody review

## Scope and acceptance

Integrate the existing opted-in native-file observation policy until_event_or_cancel.
Observation survives registration age; a single durable observed match anchors a
bounded delivery window. Finite defaults remain compatible. Preserve exact caller,
event, recipient, idempotency and current stop/cancel/pause/authority/uncertainty
barriers. Advertise schema/core/capability support honestly so old finite readers
cannot claim this contract. No new protocol or clock architecture.

Use the retained existing public CLI/MCP/native-intent regressions and external
ports. Observe actual current-main red before production edits. Run affected
focused checks and one frozen Standards/Spec review. Done when the accepted
current-main source, qualification and exact merge custody close #733, while #697
remains closed at its original source boundary. Working installation and actual
Auth406/414/415 continuation remain separate.

## Custody and independent reconciliation

Reuse the original clean checkout on a fresh main-based port branch; original
branch and local archive preserve2b9f7a9 without exposing unknown old blobs. Root
owns docs/tracker/merge; worker owns source/tests. Retire checkout after verified
public port custody and artifact/reference gates. Original dirty main preserved.

A separate worker reviews only private-native-launch and release-startup-fix
historical blobs for safe exact archive and normal retirement; their patches are
already equivalent on main. No old source merge is needed. PR454 draft summary
was refreshed from its final public ledger/review to remove stale claims that
453/457 or its completed final review remain unfinished; current-main port remains
open. Existing source/custody/deployment boundaries stay distinct.

## Non-goals and current state

No model/provider calls, real native input/wake, credentials/history copies,
production monitor/service restart or deployment, old allowance replay, paidCI,
forced cleanup or unreviewed historical source publication. No unrelated test
framework or clock-client work. Original regression is being reproduced against
current product code; final evidence will record exact red/green and limits.

## Reproduction and port progress

Unchanged current product code rejects the retained public CLI regression with
SystemExit2: unrecognized --observation-policy. The five retained event tests
pass after the narrow port and adaptation of external test ports to the existing
utc_bounds and bounded-submit/reconciliation interfaces. Old monitor-freshness
fixture and removed unbounded adapter API failures are retained separately from
product RED. Core9 waiting cancellation is exercised under a held real delivery
gate and then settled on monitor poll, without matching or external input.
Final affected-suite results and review remain pending.

## Original-history inventory correction

The two exact-public-blob checks found a prior metadata error: exclusion-walk
output can include blob objects already reachable from public commits. P258's
Wake unknown-blob figures are now explicitly labeled candidates, not publication
absence proof. A read-only explicit object-set subtraction recount is underway.
Five separately reviewed histories were safely archived and retired; dispatch
qualification logs were preserved privately. Their exact remote archive and
reference/artifact gates remain valid independently of the incorrect counts.

## Final focused source qualification

Source6d0e52c605ae887b6d5175c255e5e1a4fdd16849 passes the same seven-module
71-test selection on Python3.11 and3.12, zero skips/exclusions. The first full
selection had70PASS/1 importERROR because tests was absent from PYTHONPATH;
correcting only the runner path resolves it. Original failures are retained.
Selected native-event/recovery/session-mode/explicit-policy and cancellation/MCP/
bounded-delivery seams cover finite compatibility, original match anchor,
capability gating and no-replay, including wrapped core9 cancellation.
No broad full-suite or installed-monitor acceptance is claimed. Public exact
commands and qualification: [acceptance](../evidence/plan0260/acceptance.json).
One frozen review: Standards zero accepted findings; primary Spec zero confirmed
defects. No second review or speculative remediation framework.
