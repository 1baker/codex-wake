# Plan0250 bounded creation and wait batch review

Fixed point: `5d2919175664ae1e0ceab0843162b276d6ba6260`.
Frozen review tip: `f0556ea0`. Command: `git diff 5d291917...f0556ea0`.
Commit list: `git log 5d291917..f0556ea0 --oneline`: dc8ebc2c creation,
ee9f7f7f controller waits, f35b2e8e local waits, 781772f0 local actor,
f0556ea0 validation ledger. This is one review of this new batch; the previous
branch review remains historical and was not repeated.

Spec authority: Plan0250 and the four `current_batch` ticket acceptances in
0250-execution.json. Standards: AGENTS.md; policies0003,0005,0006,0014,0016;
docs/agents/runtime-proof.md; the supplied code-review smell baseline.
No CONTRIBUTING or CODING_STANDARDS files were found.

## Standards

Independent `/root/st04_batch_standards_review`: no blocking candidates and no
material smell candidates. Primary adjudication: no accepted Standards findings.
Qualified time, explicit fixture clocks, runtime custody, focused checks and
creation compatibility match the documented rules.

## Spec

Independent `/root/st04_batch_spec_review`: one candidate authorization bypass
on a wait timeout. Primary adjudication: **blocking, P1, accepted and resolved**.
The new counter read could cross actor expiry or revocation before the early
return. `operations.wait` now performs final `_owned` validation before publishing
its envelope, without another owner observation, deadline renewal or cancellation.

The public regression exercises expiry and revocation during both pre-refresh
and post-refresh clock observations. Exact review source failed all four
subcases (`st04-review-authority-red.log`). Minimal final authorization fix then
passed the regression plus four critical retained-result, counter-loss, stream
and revocation controls on Python3.11 and3.12 (five selected tests each).
This was the single bounded TDD remediation pass. No second broad review ran.

## Validation and boundaries

- Creation/records/network selection:34 PASS on each Python3.11/3.12.
- Combined controller/local wait, actor and daemon selection:23 PASS on each.
  Initial311 selection had21 passing and2 fixture errors after strict actor
  issuance; the corrected UTC fixture separates authority from counter loss.
  Original failure log retained, not relabeled green.
- Adjacent unified terminal/presentation checks:7 PASS on Python3.11.
- Final remediation selection:5 PASS on each Python3.11/3.12.
- Ruff undefined names, policy wiring and diff checks PASS.

Logs, exact selections and worker receipts are in the private #695 checkpoint
root, with qualified UTC metadata. These are focused source/private protocol
checks on WSL, not hosted GitHub CI, a comprehensive suite or installed Native
acceptance. No provider requests, credential changes, working daemon adoption,
Native build, merge or deployment occurred in this batch. The expired Grok
allowance and uncertain live sample are unchanged.

Four repo-local tickets are closed after validated integration. Global ST04,
parent #695/#628, full Python and runtime/activation gates remain open.

Summary: Standards0 accepted; Spec1 P1 accepted, resolved by the bounded pass.
