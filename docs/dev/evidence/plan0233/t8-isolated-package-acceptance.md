# P233 T8 isolated package qualification — real-account gate pending

T8 #639 remains OPEN; this is partial joined acceptance. Native source is
`abc2ce28469ca57e584ef33cf71b4ad172f8bb26` (unchanged from accepted T7), complete
tree `16c26eb541990a1fb57edf7dc2b3346bff1e6dc0`. Wake runtime code/wheel is based
on `1f8fd14b33faad7e145919a6861daa5a36bc2b16`; T8 changes only the existing
qualification script and evidence. No Rust/public schema/runtime module change
requires another compile. Both existing worker branches are
`feat/p233-release-qualification`; no new worktree was created.

## Complete immutable package

The maintained `just assemble-codex-package` entrypoint selected variant `codex`,
explicit GNU Linux target and dev-small profile. A grouped offline/locked Cargo
build resolved all four first-party binaries from current source: standalone
`codex`, `codex-code-mode-host`, `codex-exec-server` and Linux `bwrap`. Retained
verified third-party `rg` completed the package. No old protocol companion binary
was substituted. The resulting directory has all five executables plus
`codex-package.json`; exact hashes/modes/sizes are in the tracked package manifest.

The existing implicit native-host cache was retained, with Rust1.95, jobs2,
incremental0, retained V8 inputs and the shared flock. Supported prebuilt flags
then staged those freshly resolved Cargo outputs through the maintained assembler,
with explicit GNU target/strip-none, avoiding a duplicate target-specific Cargo
cache. This is an exact artifact claim, not measured bit-reproducibility. Existing
vendor bubblewrap missing-field-initializer warnings were retained; compilation
and assembly succeeded. No cache cleaning or paid hosted CI occurred.

Private evidence root: `~/.local/state/codex-wake/p233-t8/`.
`build-input.json` and `build-package.sh` retain exact argv, source/lock/tool inputs.
CargoSignal `job-20261115T122851Z-04459228458e`, receipt
`20261115T122851Z-f7cd9b894a1a/receipt.json`, PASS1048.585s; Cargo17m26s.
The package entrypoint SHA is
`a54f0739611354fcdd535f5a6a391197c4c0fe92615ade9f4bfd6bb725713792`.
All six source files match the UID1017 copy. All five executable help/version
smokes passed, including standalone Codex and both companions.

## Installed isolated acceptance

The real Linux user was `codex-daemon-test` UID1017, sharing the WSL kernel.
A separate candidate Wake prefix used the supported installer with declared MCP
extras. Its wheel SHA is
`48675871d83010a29f6499a84f0a17a4d051e8470642116fef7b0ad7351d1ae0`.
Installed Python3.14.6 and declared dependencies differ from the earlier source
checks' Python3.12. All336 installed module/resource hashes match source; installed
CLI/API/MCP auth/catalog13 and usage16 checks passed in8.016s through the actual
candidate interpreter, without source PYTHONPATH. No credentials/history were
copied. Test provider configuration was explicit localhost with plugins disabled;
intended inference was scripted, not real entitlement proof.

- Existing resume-upgrade journey: `job-20261115T125020Z-c4235c9ef4d8`, PASS63.880s.
  Actual supported update `--from-cli --yes` replaced retained baseline4712 with
  candidatea54f, then rolled back to baseline4712. Active conversations, mirror,
  idle and fresh TUI clients reconnected. Public `thread/list` and `thread/read`
  preserved actual saved conversation visibility/path/original turn IDs before,
  after and after rollback. Durable handoffs, original goals/counters/limits and
  duplicate recovery reconciliation passed. All six files of both actually
  installed package releases match their immutable source inventories.
- Failed-start/repair/rollback journey:
  `job-20261115T130518Z-71e80025d8ef`, PASS64.439s. The existing fixture made only
  its owned daemon stderr log unwritable at the mandatory replacement startup
  open. The new process could not start, no work resumed before repair, the exact
  mode was restored, supported startup recovered, then rollback preserved
  histories/handoffs/counters/limits. Package and account configuration bytes
  stayed unchanged; both complete installed release inventories match source.
- Existing saved-session open/close/exact-resume probe:
  `job-20261115T125042Z-c77026d8c937`, PASS14.222s; two real synthetic saved
  conversations, distinct identities, peer history preserved and no duplicate UI.
- Public installed private-client ownership probe:
  `job-20261115T124843Z-5a177b1cdb18`, PASS7.793s. A real candidate client held the
  private lock. A second public launch identified the live owner PID/account,
  refused with close/fuser guidance and preserved the first client. After owned
  release, a fresh client opened normally; final owned processes were empty.

`runtime-qualification.json` binds full private receipts/hashes and both installed
package inventories. Final UID1017 census: zero owned processes, all13 pre-existing
persistent processes preserved, zero additional unattributed processes. No Cargo/
rustc writer remained. The rollback package is retained unchanged. Package copies,
synthetic histories and candidate prefix remain for primary reconciliation and the
required real-account gate; they are not working-profile installations.

## Retained failures and limits

An inaccessible source-path installer attempt failed126 before staging; exact
public installer/wheel copies in UID-owned paths passed. An initial history
assertion incorrectly expected a message-less idle thread in the default saved
conversation list; it failed on the baseline before candidate activation and was
corrected to list actual conversations and read the idle thread by ID.

The old failed-start fixture depended on a noncanonical marker file; canonical
package identity now suffices. Execute-bit mutation of an installed copy did not
prevent the updater starting, so it was not qualified as failed-start evidence.
A subsequent unreadable-config control also did not block startup: the app server
logged invalid config and used defaults. That discarded control had fresh empty
auth state/environment; no real provider response was observed, but whole-OS
network traffic was not captured. Possible unauthenticated warmup/metadata-attempt
uncertainty is retained. The earlier historical unpinned WebSocket attempt is
also not erased. Do not claim zero historical network attempts. The final actual
startup gate faults a mandatory no-fallback log open, with valid explicit local
provider configuration, and passes. Failed attempts and repairs remain private
receipts; they are not product REDs or passing acceptance.

Qualified StableTime close measurement was
2026-11-15T13:11:46.539960771Z, finite127.39115ms, evidence generation1053; raw
measurement is retained. Source, package, isolated runtime and real authority are
separate. Real sign-in/refresh/entitlement, coding inference, MCP/mixed-worker/
handoff/Stop/usage proof remains NOT RUN. Current sanitized Grok readiness is
unavailable/native_auth_missing; logout unconfirmed, entitlement/inference
unverified. No login retry or working-account revocation occurred.

Primary's concrete next gate is `t8-real-account-gate.md`. No working native
installation/restart/deployment, native push to OpenAI or hosted CI occurred.
T8 is not complete and #639 must not close from this packet. Broad review and
bounded remediation counters remain zero. Memory disposition is forbidden:
this delegated source/evidence slice does not write external program memory.

Primary verification: all six original package and UID1017 candidate-file hashes
match independently. Worker source six-file hashes and Git bundle verified;
full-index zero-context patch independently reconstructs the exact Wake tree.
All twelve job outcomes reconciled, including each required runtime success.
Fresh UID1017 OS readback still shows the thirteen pre-existing persistent
processes; no task-owned process was added. Local Grok auth is freshly observed
unavailable/native_auth_missing; the real-account gate remains unexecuted. The
installed official CLI has changed since historical T1; its current digest and
network-isolated device-login help inspection are retained privately. No login,
refresh, provider request or working-profile installation was initiated.
