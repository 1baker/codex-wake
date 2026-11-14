# Plan0234 source acceptance

Source delivery only; no production installation, provider turn, merge or deployment.

- At `dfcfb7c61e1c134fcd86bcc9b8ff342fef112033`, selected presubmit: 75 existing modules, 471 cases PASS in471.078s (472.671s wall /600s budget). Selection/command/log: user-state `unified-0234/presubmit-{selection,result}.json` and log. This is not a full-suite claim.
- At `a7d6a8f14f16ef380fe119f79ef06a0713aa5463`, causal authentication regression: `python -m unittest test_controller_auth test_controller_recovery test_controller_runtime test_controller_hosts test_controller_flow_sessions test_controller_flow_surfaces test_unified_connectors test_unified_bulk test_unified_transports -q` with PYTHONPATH=src:tests: 45 cases PASS51.286s (52.068s wall/120s budget).
- Exact baseline OAuth reader compatibility test first failed accepting an attenuated authorization code. Separate delegated codes and versioned credential kinds now make old readers refuse code/access/refresh credentials; current readers retain action restrictions and inherited revocation. The historical object was available and the compatibility test ran.
- Wheel0.22.0.dev21 SHA256 `9c33105c23f2674be6c076d264a2aba363daa4769f4d1ac3e54fc3affdf15ee3` built from a7d6a8f1:344 package Python members match source/wheel/temporary installation exactly; seven canonical roots,511 native schemas, installed CLI/help/protected bulk discovery PASS. Temporary prefix is not production.
- `python -m ruff check --select F821,F822,F823 src scripts tests .codex/hooks`, `python scripts/generate_unified_contract.py --check`, `python scripts/generate_command_reference.py --check`, `python scripts/check_policy_wiring.py`, and `git diff --check`: PASS.

## Public acceptance map

The ledger records ticket-specific red/green and integration evidence. Existing `test_unified_transports` crosses private HTTP/MCP/CLI: enumerate dev/bot children, register a schedule, publish/run a program, then reconnect from a fresh CLI process to the same completed run and original schedule. Observation, prompt/slash, presentation, raw terminal and bulk boundaries have separate causal public tests in the same existing harness. Terminal literal LF/no implicit Enter and park/restore exercise real private tmux; native binding is injected and explicitly qualified as such. No fixture project or second executor was added.

Observation is snapshot-derived with explicit gaps, not a live native notification stream. Presentation preserves the native TUI process with park_live/restore_live; headless detach and unsupported native slash pickers are rejected. Remote mutation uses an injected SSH receiver and explicit opt-in, not live SSH acceptance. Windows client bridge tests do not qualify native Windows ownership. Semantic provider execution/metering remains unqualified and requires existing explicit admission.

## Validation limits and custody

Local Python3.12.13/Linux replaces hosted GitHub CI under repository cost policy. Python3.11 matrix, full historical suite, production provider/runtime and complete hosted installed-smoke matrix were not run. OpenClaw is parked and no plugin work was performed. First failures and corrected runs remain outside Git at `~/.local/state/codex-wake/unified-0234/`; setup failures are not product failures. The baseline direct-file controller_client invocation also fails its relative import; supported module invocation passes existing tests.

Local CI-scope classifier test:1 case PASS4.687s; compileall PASS. No hosted CI requested.

## Final reviewed candidate

At `f38abc6dc4dd06be0b49192edca05e4fe66d8dd6`:

- `PYTHONPATH=src:tests python -m unittest test_unified_bulk test_unified_connectors test_unified_contract test_unified_transports test_controller_flows test_controller_flow_surfaces -q`:33 cases PASS38.160s; focused tier, under120s budget. Two earlier affected runs exposed an obsolete remote grant lacking content scope and then an incorrect test expectation (`not_started` is the correct denial outcome). Both failures are preserved; the corrected real remote-owner test verifies refusal without content and success with content.
- Rebuilt wheel SHA256 `4130b2bf2ed15135e519f34b76b68b56b4148083a2f1f98c3f6c101064902a43`; installed-reviewed.json proves344 Python members exact source/wheel/install match,511 native schemas, canonical CLI discovery/help and protected bulk discovery. Candidate only; production remains untouched.
- Final Ruff undefined names, compileall, generated contract/reference freshness, policy wiring and diff whitespace checks PASS. Active-only planning audit PASS. CodeGraph initialization encountered a database lock; current source was available, but caller-graph completeness is unqualified. No graph-derived runtime claim.

Review count1, bounded TDD remediation count1. No unresolved accepted findings. The final evidence-only commit does not alter qualified Python/package behavior.
