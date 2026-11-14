# Plan0234 single review and remediation

Base `1aa498674a4907f93b5216a4a98dd75a22c6ecec`; frozen reviewed head `bf4b5e00d1b925b3daf21e079a192a6295d00d15`. Command: `git diff 1aa498674a4907f93b5216a4a98dd75a22c6ecec...bf4b5e00`. Commit list and full diff retained in user-state `unified-0234/review-commits.txt` and `review.diff`. Exactly one broad two-axis round; independent reviewers unified_standards_review_final and unified_spec_review_final, primary adjudication below. No second broad review.

## Standards

- S1, P1, **blocking, resolved**: generated terminal-wait child receipt did not exist, so uncertain/disconnected waits failed reconciliation with operation_not_found. Confirmed at unified_bulk.py frozen166–172 and controller_flows.py604. Violates policies0003 status evidence and0004 result retrieval. Recovery now validates the current attempt and frozen run, derives the original owner handle from the durable completed call and observes that exact handle without resubmission.
- S2, P3, **accepted judgment call, resolved**: duplicated member-node prefix construction in definition/projection. Small shared member-prefix helper now owns naming, also used by recovery. This is Fowler Duplicated Code guidance rather than a hard standard violation.

## Spec

- P1, P1, **blocking, resolved**: spec125–127 separates metadata/content/input/admin rights. Stored program definitions were readable through flows.definition/programs.definitions.show without content.observe. Reproduced with an actual subset grant and published private literal. Delegated definition and run-state returns now require the content scope; compatibility aliases share the same fence. Discovery records additional delegated scopes. Existing nondelegated authority is unchanged.
- P2, P1, **blocking, resolved**, same defect as S1: spec132–134 requires restart/uncertainty reconciliation. Causal test covers both returned uncertainty and lost wait reply, reconnects with a new BulkControls instance, retrieves original terminal answer and proves exactly one submission.
- P3, P2, **blocking, resolved**: spec129–130 requires per-target uncertainty. A wait's uncertain phase was incorrectly projected as admitted. Public member projection now preserves uncertain/executing/dispatching and interrupted active-wait uncertainty.

## One bounded TDD pass

Existing public seams: ProtectedOperations plus actual OAuth subset grants catch content leakage through both canonical/legacy routes; BulkControls start/advance/reconcile/result with an external protected-owner boundary catches lost-handle recovery and projection, without native provider effects. No fixture project or second executor.

Exact commands (PYTHONPATH=src:tests, Python temporary source environment):

- `python -m unittest test_unified_connectors.ConnectorTests.test_metadata_only_delegation_cannot_read_stored_program_definition -q`: corrected red AuthError not raised; green1PASS0.865s. Initial setup error used wrong host/environment and is retained separately.
- `python -m unittest test_unified_bulk.BulkTests.test_terminal_wait_reconciles_original_handle_after_uncertainty_or_disconnect -q`: red2 operation_not_found errors; green1PASS2.237s. Next vertical assertion red admitted != uncertain; green1PASS2.088s retained in review-member-green.log.

Raw red/green receipts live in user-state `unified-0234/review-{content,wait,member}-*.log`. Focused post-fix regression33PASS38.160s and exact reviewed wheel qualification PASS at f38abc6d; no native/provider/live acceptance is inferred.

Accepted findings: Standards2 (highest P1), Spec3 (highest P1); three unique blocking defects plus one naming-duplication judgment resolved. No rejected, backlog or unresolved findings.
