# P253 one final review and bounded remediation

Frozen comparison: `git diff 42bbcb95ba1b9ee5bc0616b7126b0c4942c59d8c...0c9df4f15536093275df34ed1f32eed9d3659729`.
Commits:6a125077,9b4e6b1e,aa77b65b,0c9df4f1. Spec snapshot is the published #716 body captured alongside this receipt. Standards sources: AGENTS, relevant planning/runtime/Git/validation/architecture/testing/collaboration policies, glossary, saved terminal-session ADR and runtime-proof contract. No CONTRIBUTING or CODING_STANDARDS found. Review count1; remediation count1. Primary adjudicates candidate findings; no second broad review.

## Standards

Reviewer `/root/review_standards`: no actionable findings or consequential baseline smells. Primary accepts this result. Separately, deterministic generated-reference check detected stale destination-help text; regenerated from the contract and checked during remediation.

## Spec

Reviewer `/root/review_spec`: S1(P1), pinned sibling can be displaced by ordinary same-session insertion without checking its protection. Public native reproducer moved pinned sibling index1to2 while companion2to1. Criterion: preserve existing focus, pin and input protections.

Primary disposition: blocking, high confidence, accepted. Reopened #720 while correcting; #721 earlier unprotected-layout samples retained, final package gate refreshed after source change. Minimal correction checks displaced siblings through existing protection owner and includes their protections/affected-work in preview. Linked siblings remain hard-held; established explicit force semantics are preserved. No-op has no displaced siblings or movement.

## Remediation verification

One public lifecycle regression with verified idle fixture processes first failed because preview reported requires_force=false for a pinned crossed sibling. After correction, preview reports the protected sibling, unforced application refuses without changing layout, and explicitly forced placement works under the existing control contract. Command: `PYTHONPATH=src <python> -m unittest tests.test_tab_lifecycle.TabLifecycleTests.test_same_session_insertion_reports_and_preserves_protected_siblings -v`. Red exit1; green exit0. No implementation-coupled helper assertions.

Final integrated selection and refreshed installed native CLI/MCP package evidence are recorded in0253-execution.json and installed-acceptance-final.json. The installed journey now uses a third idle native conversation as the crossed sibling; no protection is bypassed for an unqualified shell. All original successful samples and setup failures remain retained. No extra model requests or provider fixture framework.

Accepted findings: Standards0; Spec1(P1), verified resolved by20checks each3.11/3.12,generated-reference check,and corrected exact-wheel installed native CLI/MCP acceptance.
