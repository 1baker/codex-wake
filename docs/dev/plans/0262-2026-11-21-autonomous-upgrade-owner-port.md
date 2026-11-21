# Plan 0262 | Autonomous upgrade owner port

State: CLOSED
Owner: primary / ecochran76
Work item: #737
Integration branch: feat/issue-737-upgrade-owner. Base: ec412b151f82b76a70bd993e488eacc7c1b602f3.
Historical accepted source: PR #454 at ef156ba466f83e7adb692be248379f857c1157fe.

## Current State

Port the accepted durable upgrade owner to current controller authorization, release and package contracts. Preserve existing build operations and StableTime authority. The GitHub spec and ticket acceptance criteria govern scope. Working-host deployment and historical job replay are out of scope.

| Ticket | Blocked by | Owner | State |
| --- | --- | --- | --- |
| #738 Durable upgrade lifecycle | None | primary | validated, tracker closed |
| #739 Repair and qualification | #738 | repair739 + primary | validated, tracker closed |
| #740 Future-launch selection and rollback | #739 | promotion740 | validated, tracker closed |

The primary owns lifecycle, discovery, public adapters and shared job schema. Repair owns source preparation, repair and qualification. Promotion owns selection, rollback and outcome reconciliation. Integrate serially. The integration worktree protects the existing primary edits and can retire after validated custody.

Acceptance requires public controller regressions, CLI and MCP parity, local checks on Python 3.11 and 3.12, and exact-package launcher acceptance in the dedicated test environment. Run one Standards and Spec review with one focused remediation pass. Tracker closure requires the corresponding accepted evidence.

## Lifecycle validation

The integration commit containing this section passed 30 tests per runtime on Python 3.11.15 and 3.12.13 with `PYTHONPATH=src:tests python -m unittest test_upgrade_jobs test_upgrade_discovery test_upgrade_storage test_upgrade_private_permissions test_controller_builds -q`. Ruff 0.14.2 passed `python -m ruff check --select F821,F822,F823 src tests`. Checks ran in isolated local environments with declared dev and MCP dependencies, without hosted Actions. These are source and public interface checks. Exact-package deployment acceptance belongs to the dependent slices.

Ticket #738 source and remote custody: `f660a4224141abe2f1c1269f0e4831bd4498b5cd`. The tracker readback confirmed CLOSED. Additional checks on that source passed 40 tests on each runtime with `PYTHONPATH=src:tests python -m unittest test_controller_build_authorization test_controller_portable_client test_release_driver test_release_build test_release_qualification test_upgrade_qualification test_measurements -q`.

Ticket #739 worker `/root/repair739` started from the validated #738 SHA. Its result and installed acceptance remain pending.

## Repair and qualification checkpoint

Worker base `f660a4224141abe2f1c1269f0e4831bd4498b5cd`, worker result `58ba21fdc133714d5b8402d80daf9778e911ce2d`, integration `b6f312a9dfa1d7efc71e853c0c99bde24fe19d69`. The worker checkout was removed after an exact remote readback and disposable cache cleanup. The current integration source passed 84 tests on each runtime with `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_upgrade_*.py' -q`. Pinned Ruff passed with `python -m ruff check --select F821,F822,F823 src scripts tests .codex/hooks`. An earlier integration checkpoint built the sdist and wheel successfully using `python scripts/validation_build.py --outdir <private-output>`.

The presubmit planning audit reports the same three state metadata errors on the base and branch (plans 0259, 0260 and 0261). The 237-test controller selection had two failures. The controller-default test reproduces on the base. The Native MCP execution-state test passed unchanged in focused runs on both base and branch and remains an intermittent broader-suite failure. The full presubmit is unqualified.

Earlier installed acceptance attempt was blocked. The dedicated UID1017 test user has a StableTime configuration and prior package assets but no existing upgrade policy binding a fresh sealed staged job to designated A/B identities. Disposable wsl-test has the historical package, policy and old stage receipt, with no dedicated StableTime client found. It returned to its original stopped state. The historical job was not replayed. Resume at #739 when a dedicated client and approved test identities are available. #740 and the single broad review and remediation pass remain pending.

## Installed qualification

Wsl-test UID1000 consumed the existing Windows StableTime service. Retained 0.166 package inventory matched the original sealed stage, package SHA256 `fe4266c33a9c2e71b08bb09df0aa5359d59d16b1307cea0bc536e2fd5a852003`, executable `48ed489ceed144d277c44a505ef5cbcb63250fa361fe132bed1fdab3f7cfb7d5`. Installed current Wake wheel SHA256 `f67e00e5f9db3b1612e184782d6f0d2830b411d55d431c79a164b125b147f89f` supplied the launcher. The history harness correction is `9ffdc06cee3dc2bcf798d076198f996e44b1ddfe`.

Fresh independent package reads and probes are retained under the disposable `upgrade739-current-main` lab as `metadata-02.json` and `native-probe-02.json`. The designated A-B-A metadata journey observed distinct accounts and the original account after reconnect. All 11 installed native checks passed, including three-home visibility, reconnect, failed start, ownership and compatible rollback. Zero external provider or model requests, zero surviving owned processes. The earlier failed history receipt is retained. The harness now uses native turn completion and a metadata-only thread read for the older baseline.

This qualification reused the exact previously built package and ran fresh installed checks against the current port. The old durable job and selected build were left alone. Public selection and outcome-only reconciliation belong to #740.

The tracker readback confirmed #739 CLOSED. Worker `/root/promotion740` owns #740 from `97e030557968d51488b48d1048ba1759dad318bd`. Its disposable lane uses a new catalog and retained exact packages. Public owner reconciliation, installed selection, and tracker closure have separate evidence.

## Installed selection and rollback

Worker result `6adc123a4fc31912ed6920d1415ca82ae8f39b46`, integrated as `81c1134f`. Against the integration source, 84 upgrade tests passed on each Python version. Public lost-result regression verifies the original StableTime budget after a guest-wall jump and observes a committed selection without replay. The worker recorded RED before the fix and GREEN after it.

Dedicated UID1017 ran wheel `d9e27a94e768e07afbf906c70c55bd9a9af0a059bd9f3e09bd90ede2964daf14` with verified sealed 0.165 and 0.166 packages in a fresh catalog. WSL command startup timed out, so the sealed package artifacts were transferred and checked against their inventories. The installed future selection kept an active 0.165 client pinned and launched the next client with exact 0.166. Public `upgrades.rollback` restored 0.165 and the following launch used that exact executable. Duplicate operations left registry bytes stable. No model or external provider requests and zero surviving owned processes. The scoped client used the Windows StableTime service. Private receipt: UID1017 lab `upgrade740-current-main/receipt.json`.

The installed run exercised selection and the public rollback, and source regressions exercised the public lost-result path. No historical upgrade job was rerun. The final Standards and Spec review is recorded below.

## Final review and bounded remediation

One review compared `git diff ec412b151f82b76a70bd993e488eacc7c1b602f3...7d6cae5c12db2edfdece2934cb8e9cc4f3ed0fe6`, after all three ticket closures.

- Standards, one accepted P1. Stage launch and polling bypassed the durable owner guard. Launch and worker registration now share the owner lock and guard. Polling rechecks the same authorization, policy, generation and allowance. Teardown preserves recorded terminal cancellation.
- Spec, two accepted findings. The staging authorization defect is the same P1. A P2 allowed a cancelled phase to overlap a newly admitted candidate on the shared compiler cache. Start and readmission now use the same occupancy condition as cache cleanup.
- Spec, rejected. Independent review prior to promotion is explicitly required by the originating Plan 0193. A clean deterministic replay can avoid a coding worker while retaining the review gate.
- Spec, evidence gap retained. Installed checks covered exact-package qualification and selection/public rollback in fresh test state. Public lost-result observation and the durable lifecycle were verified locally. One fresh installed job traversing all phases was outside the executed receipt.

One TDD pass used `PYTHONPATH=src:tests python -m unittest test_upgrade_jobs.UpgradeJobsTests.test_disable_during_work_rejects_late_success test_upgrade_jobs.UpgradeJobsTests.test_public_advance_holds_before_starting_a_worker_after_policy_change -v`. Both tests failed on the frozen source and passed after remediation. Final integrated source passed 85 upgrade tests per runtime with `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_upgrade_*.py' -q` on Python 3.11.15 and 3.12.13. Pinned Ruff, command reference, compileall, and sdist/wheel build passed. Final wheel SHA256 `048928f94d11be7b1400cd22b545a58aa430148e5b6cddbb67a5f96361b1a394`. Current installed acceptance used the identified pre-remediation wheels. The staging guard correction is covered by the public source regressions. Existing broad presubmit gaps remain recorded above.

Tracker #738, #739 and #740 all CLOSED. The validated port is on the integration branch. The spec and old draft PR remain as integration locators.
