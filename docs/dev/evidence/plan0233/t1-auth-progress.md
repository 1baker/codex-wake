# P233 T1 authentication progress

Ticket #629 remains OPEN. This is a partial implementation, not account or
inference acceptance.

The official credential file can be inspected through sanitized public status.
A private command-auth bearer path uses the configured StableTime service and
conservative expiry bound, takes the persistent native advisory lock without
breaking a holder, checks its inode/device, and rereads the credential file.
Expired, missing-expiry, ambiguous, insecure and missing sessions hold. API keys
are not adopted implicitly. No native credentials or live provider calls were
used for this progress check.

Focused local checks at this slice:

- `PYTHONPATH=src python -m unittest discover -s tests -p test_grok_provider_auth.py`
  initially RED: new public module absent. Then GREEN: two tests.
- `PYTHONPATH=src /home/ecochran76/workspace.local/codex-wake/.venv/bin/python -m unittest discover -s tests -p test_grok_provider_auth.py`
  GREEN, two tests.
- Same interpreter and PYTHONPATH, `-m codex_wake grok auth --help`: PASS.

The default shell interpreter lacks websockets; initial CLI invocation failed
before parser construction. The existing project virtual environment provides
the declared dependencies. `uv` is not on this shell's PATH. These failures were
not product passes and were not erased by the corrected environment check.

Remaining T1 acceptance: registered account binding, official login initiation,
qualified native refresh/rotation interoperability, public generated controls,
and operational readiness. Entitlement and inference remain unverified.

Second vertical slices (same focused unittest command): registration was RED
with `GrokAccounts` absent, then GREEN after account binding implementation.
Native rotation for the same identity is admitted; substituted user/principal
identity holds. Official-login bridge was RED with `login` absent, then GREEN;
native exit zero without a credential remains logged out, and raw provider
stderr never leaves the boundary. Four focused tests now pass.

The private CLI contract now selects a registered account:
`codex-wake --wake-root ROOT grok auth token ACCOUNT`. Registration pins the
native identity without copying credentials. Operator `grok auth login` runs an
explicit native executable with device authentication and emits only validated
human verification information. Default native-store observation was logged
out; no actual login was initiated. Native `login --help` and `models --help`
were inspected without account/provider activity. Refresh delegation through
`models` is still an investigation, not implemented or qualified.

Sanitized status is now wired into native MCP and protected HTTP from one tool
schema. Exact account-target grants are checked before credential I/O; a broad
host observation grant is insufficient. Private token and registration commands
are absent from public schemas. Focused public owner suite: five PASS. Existing
account observation regression: six PASS. Existing profile transport parity:
four PASS. A guessed `test_mcp_server.py` selection collected zero and is not
reported as validation. `ruff` is absent from the existing project environment;
`git diff --check` passes.

An official device login was initiated through the new sanitized CLI bridge.
The operator received the native verification link/code; account confirmation
and real provider readiness remain pending. No model inference was requested.
Device codes and links are intentionally excluded from this tracked receipt.

Refresh delegation is implemented through the registered, SHA-256 pinned
native `models` utility. Wake never writes auth.json or refresh tokens. The
utility owns AuthManager, native locking and rotation. A durable attempt marker
holds failed/interrupted attempts against the same credential generation;
changed native credentials can be reconciled without replaying the old attempt.
The broker obtains fresh StableTime again after the utility before emitting a
bearer. Exact account identity is rechecked under the native read lock.

Focused suite: seven PASS (0.227s last run). Refresh delegation red was the
missing `executable` registration argument, then green after pinned delegation.
A further public-boundary regression proves an uncertain helper is not invoked
again: the adversarial helper would return a usable credential on replay, but
two broker calls both hold for reconciliation. This is local seam evidence,
not real provider refresh acceptance.

Upstream source inspection was pinned to public main
`2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`. Relevant utility code:
https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/src/models.rs
It initializes the catalog through an in-process ACP shell and installs an
AgentShutdownGuard on every return path; no coding prompt is submitted.
Installed native version reports `1.0.70 (f50904eaee6c)`, stable. That revision
was not resolvable in the public source repository (422); source review alone
does not prove installed behavior. Live refresh interoperability remains an
explicit acceptance gate.

## T1 integrated implementation acceptance

The frozen spec explicitly assigns joined real-account proof to the qualification
stage. T1's independent source slice is accepted on the approved CLI/API/MCP and
private command-auth seam; it does not claim a qualified Grok account or coding
turn. The initiated device flow terminated without sign-in. It was not retried.

At implementation commit `6bbb4efad2535e901b7fd523692a1002afcd3f49`, the focused
suite was extended to invoke the real CLI parser/dispatch for register, public
status and private token emission. Only the external qualified-time adapter is
substituted; the real broker reads synthetic owner-only native credentials.
Public output omits the token and private command stdout equals the bare bearer.
The exact-grant scenario now invokes both protected HTTP operations and native
MCP CommandRunner and verifies their public result payloads agree. The initial
API assertion incorrectly compared transport attribution with an owner-only
result; the expectation was corrected to compare the public result payload.
No product change was needed for that assertion failure.

Command:
`PYTHONPATH=src /home/ecochran76/workspace.local/codex-wake/.venv/bin/python -m unittest discover -s tests -p test_grok_provider_auth.py`
Result: eight PASS, 0.828 seconds. No hosted CI runs. Shared local venv is used;
the hosted environment may install declared dependencies afresh.

Acceptance mapping:

- Official sign-in initiated through sanitized Wake CLI; native owns OAuth and
  persistence. A successful process exit alone is never interpreted as sign-in.
- Real CLI/private token boundary exercised; public CLI/API/MCP cannot request
  bearer output. Exact account grant admission precedes native credential I/O.
- Official pinned metadata utility owns shared refresh writes; Wake's private
  read takes compatible flock/inode checks and rereads. Identity substitution,
  unknown expiry, expiry, insecure state and uncertain refresh hold. Uncertain
  attempts are not replayed; rotation from the native writer is adopted.
- Public status separates authentication presence, unverified freshness,
  entitlement and inference. No implicit API-key selection is implemented.

Remaining joined T8 gates: real account sign-in, installed official refresh
interoperability, real model entitlement and coding inference, complete isolated
native package qualification. These remain OPEN, not implied by T1 acceptance.
