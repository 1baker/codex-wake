# Historical native receipt reconciliation

State: CLOSED

Work item WAKE-HISTORICAL-HARNESS. State DONE (source repair only); priority P1; owner current
Codex repair agent; WIP one. User requested repair after an approved Auth event
was retained but no native delivery attempted. Branch
fix/historical-receipt-reconciliation, base e4eda2bd. Existing cancellation repair
is a separate checkpoint; unrelated dirty primary work remains preserved.

Outcome: reconcile exact old submissions through a qualified current read-only
native transport when their historical CLI has been removed, without rewriting
original bindings or replaying effects. Preserve genuine uncertain/nonterminal
holds, expose unavailable reconciliation separately, and report registration
harness readiness independently of monitor health. Readiness is rechecked at
execution and never grants credential or provider authority.

Acceptance: regression reproduces removed historical CLI at actual peer admission;
current transport returns exact terminal evidence, original target stays unchanged;
wrong evidence/unavailable source stays held with precise reason. Public native
registration cannot report armed when harness preflight fails or peer history is
unreconciled. No daemon bootstrap, resume, input or submit in preflight.

New isolated checkout needed because primary has another actor's dirty work and
existing lanes have other purposes. Complete registered inventory saved privately;
none removed or repurposed. Retain checkout through package qualification or an
explicit durable handoff; review at source closeout. No production state repair,
record overwrite, lock removal, service restart, wake replay or authentication
input in this source packet. Installed adoption requires policy0006 qualification.
Memory disposition forbidden: no authorized memory write.

## Validation and custody

Two original regressions failed before production changes: removed historical
CLI returned a peer hold, and unavailable native preflight still reported armed.
First combined pass exposed a test setup qualification error: the selected
runtime Python executable is group writable and correctly fails the replacement
transport guard. The test now creates an owned0700 inert CLI fixture rather than
weakening that guard. All original failure logs remain private.

Final source command with selected Python3.12 and PYTHONPATH=src:tests:
`python -m unittest test_wake_mode_runtime test_wake_session_modes
 test_native_intent_recovery test_native_delivery test_wake_policy
 test_wake_control_mcp`:71tests,36.940seconds,0failed/errors, no skips.
The six new regression/boundary cases include exact terminal readback with
unchanged original target, unsafe replacement refusal, unavailable versus
in-progress, exact identity, and registration peer hold/no input.
Pinned `ruff==0.14.2 check --select F821,F822,F823 src scripts tests .codex/hooks`
passed; `python3 scripts/check_policy_wiring.py` PASS; `git diff --check` passed.
Local checks replace hosted CI; no paid hosted runs requested. Tests use isolated
synthetic native ports; actual daemon/provider acceptance is not asserted.

No new runtime dependency or persisted wake schema. Registration adds `harness`
and may return `held_harness`/armedfalse where older builds overstated readiness.
One original historical peer is still reconciled per monitor admission; this
bounded progression does not bypass remaining history. Upgraded source must be
packaged and qualified under policy0006 before working-host adoption. No original
runtime request, grant, old wake or terminal receipt was rewritten by this task.
Remaining live gate: installed old monitor continues to hold the approved wake.
Checkout retained for exact-candidate test-user qualification, review at that
packet's start; publication alone is not installation or acceptance.
