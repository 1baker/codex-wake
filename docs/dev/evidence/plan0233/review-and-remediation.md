# P233 single broad review and bounded remediation

All eight implementation children were CLOSED before review began; parent #628 remains OPEN. Review count1, remediation count1. No working-profile installation or deployment is claimed.

Frozen comparisons:

- Wake: `git diff 1aa498674a4907f93b5216a4a98dd75a22c6ecec...487ba576`.
- Native: `git diff f986f6ed53d6b324aedbd7e32991e0185eacae14...1a2fb1df4cefdef9782cd82d8cceef8c70e1c05c`.

Both refs resolved and both diffs were nonempty. Exact commit lists and independent read-only reviewer reports are retained in private execution artifacts. The axes were reviewed independently and adjudicated by primary; no second broad review ran.

## Standards

Accepted `nonblocking_backlog`, addressed in this bounded remediation: `docs/grok-provider.md:12-23` showed relative command/no account-revision pin/auth cache60000, whereas qualified catalog admission in `core/src/inference_selection.rs:175-196` requires an absolute command, exact account-revision tail and refresh interval0. This was documentation drift against the user-facing configuration contract and Wake validation policy0006; it did not demonstrate an additional runtime defect.

The documentation now uses an absolute placeholder path, `--expected-account-revision`, zero auth-cache interval and the account-qualified provider identifier, and explains that placeholders must match the accepted catalog selection. No cosmetic refactor or new test framework was introduced.

## Spec

No confirmed blocking or backlog finding accepted. The candidate that same-account Grok picker selections create linked successors was `rejected`: the approved design public-contract supplement explicitly requires the picker's continuation intent, separately from ordinary independent forks. The ordinary OpenAI model-selection path remains unchanged. Qualification evidence keeps local Stop distinct from confirmed provider cancellation, and unknown usage distinct from zero. Working deployment remains a later stage.

## Bounded TDD remediation

The public seam was the documented TOML configuration consumed by an operator, checked against the independently established qualified catalog contract. One private, disposable TOML check ran RED before editing (absolute-command assertion failed), then GREEN after the minimal documentation edit. Exact command: `python /home/ecochran76/.local/state/codex-wake/p233/remediation-doc-contract-check.py`; logs `remediation-red.log` and `remediation-green.log` are private. No persistent test for a reversible documentation change was added.

Native documentation-only commit `7cdb5404a247bec03a4a8bb244eb4da84e9c1917`, tree `6c1fc5e2c2fb9e7fe29c9c9f31d601326c980256`, is held through an exact additive patch that reconstructs the tree and a verified private Git bundle. Manifest: `runtime/grok-native-233/review-auth-docs-source-manifest.json`. The only changed native path since qualified1a2fb1 is `docs/grok-provider.md`; no executable or schema changed. Native package and installed Wake runtime qualification therefore remain causally valid without rebuilding or issuing provider calls. `git diff --check` passes.

Summary: Standards1 accepted, highest severity nonblocking documentation drift, corrected; Spec0 accepted. Broad review1/1 and bounded remediation1/1 complete.
