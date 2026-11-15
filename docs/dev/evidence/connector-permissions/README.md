# Connector permissions acceptance — #671

Source baseline: `882aae8007e71cc2641c66a742e340e6cf007310`.
Live installed connector: `0.22.0.dev28-1fb9180` (wheel SHA256
`1fb9180dd253f01e4073cd24f87b9119ef35e5cdf8958bb1acbc2fac841ed336`).
Public resource: `https://codex-wake.ecochran.dyndns.org/mcp`.

The opt-in acceptance script exercises the real deployed HTTPS OAuth token and
MCP endpoints. Local operator authorization creates three independent, bounded
permission grants for a disposable empty native conversation. Codes, verifier,
access and refresh tokens stay inside the test process. Existing operator grants
and deployment policy are read before/after and remain unchanged.

| Criterion | Live observation |
|---|---|
| Explicitly scoped read succeeds | Protected environment snapshot completed under an observe-only conversation-scoped grant |
| Read-only prompt denied | `insufficient_scope` |
| Out-of-scope prompt denied | A separate control grant for another conversation returned `insufficient_scope` |
| Stale generation fails closed | Changed socket generation returned `daemon_unavailable`; no input admitted |
| Denied input has no native queue effect | Queue empty and conversation idle before/after; initial thread start contained no turns |
| Own credentials cleaned up | Three grants revoked; public MCP rejected each old access token with HTTP401 |
| Own conversation cleaned up | Disposable conversation archived |

The stale-generation diagnostic is less specific than desired: a mismatching
pinned target falls through full registry discovery, where an unrelated daemon's
ownership cannot be verified. This establishes fail-closed refusal but **does not
prove a generation-specific `stale_target` error**. No product change is hidden
inside this acceptance ticket.

A first run stopped before credential issuance because an empty native
`thread/read(includeTurns=true)` returned JSON-RPC -32601, `list_turns is not
supported yet`. The same error reproduced while retaining the creator websocket;
retaining that connection is therefore not a remedy. This script instead uses
the applicable native empty-thread metadata and queue observations. It sends no
setup/model prompt and never addresses the operator's conversation. The bounded raw-error probe was separately archived. Archiving an earlier
preliminary target was refused; a complete native loaded-thread listing then
verified it was absent. That refusal is retained in private diagnostics rather
than hidden or retried destructively.

## Reproduction

Use the exact installed connector Python, with its already configured private
policy and a private receipt destination:

```sh
"$CONNECTOR_PREFIX/bin/python" scripts/connector_permissions_acceptance.py \
  --config "$CONNECTOR_PRIVATE_CONFIG" --receipt "$PRIVATE_ACCEPTANCE_RECEIPT"
```

Actual run used the version above, the operator-owned external connector config,
and a receipt under the operator's private Codex Wake state. Output reported
`status: passed`; credential-free summary and full private receipt remain outside
Git. The script is opt-in; it does not join the hermetic unit suite.

Focused checks: `python3 -m compileall -q scripts/connector_permissions_acceptance.py`
and `git diff --check` passed. Hosted CI was not run under repository cost policy.
No connector restart, native daemon restart, plugin change or account alteration
occurred. Memory disposition: `forbidden` — no explicit memory write requested.

Existing generation-guard regressions also passed (2 tests, 36.055s):

```sh
PYTHONPATH=src:tests "$CONNECTOR_PREFIX/bin/python" -m unittest \
  test_pinned_native_lookup.PinnedNativeLookupTests.test_changed_target_cannot_use_fast_path \
  test_local_sessions -q
```

The first refuses a changed pinned target; the second exercises real CLI/Unix
peer discovery and rejects stale generation. These establish the intended
identity guard separately from the less precise live registry refusal above.

## Final read-isolation remediation — 2026-11-14

Source baseline: `fe449f35c1b812a0d674c7ed3a13dc832a0434e6` plus the
script changes in this commit. The deployed boundary was
`/home/ecochran76/.local/share/codex-wake/releases/0.22.0.dev34-c3cf1d1`;
this acceptance-only change required no installation or service restart.

The earlier snapshot-success assertion did not prove read isolation. The
expanded public HTTPS MCP check inspects the returned projection: host and
environment match the grant, and `sessions`, `unplaced_tabs`, `agents`,
`bindings`, and `unavailable` are empty. This projection describes terminal
placement, so a conversation-only grant exposes no terminal resources; it does
not enumerate the granted native conversation. Two actual content-read calls
through `wake_environment_conversations_observe` now establish the independent
fences: the owned conversation with only `observe` returns `insufficient_scope`,
and the same conversation under a different-conversation grant containing
`content.observe` also returns `insufficient_scope`. The disposable thread has
no turns, so these denied calls use a bounded turn selector and never create a
model turn or admitted observation.

The live run passed all checks, including `stale_target` for the changed
socket generation (superseding the older less precise live diagnostic above),
zero native queued inputs, idle state before/after, unchanged existing operator
grants/config, four temporary grants revoked with HTTP401 readback, and owned
thread archival. The receipt is private and preserved at
`~/.local/state/codex-wake/acceptance/671-read-isolation-final-20261114.json`.
Receipt destinations are now reserved exclusively before live effects; an
existing receipt fails instead of being overwritten.

Commands and results:

```sh
/home/ecochran76/.local/share/codex-wake/releases/0.22.0.dev34-c3cf1d1/bin/python \
  scripts/connector_permissions_acceptance.py \
  --config /home/ecochran76/.config/codex-wake/external-connector.json \
  --receipt /home/ecochran76/.local/state/codex-wake/acceptance/671-read-isolation-final-20261114.json
python3 -m compileall -q scripts/connector_permissions_acceptance.py
git diff --check
```

The opt-in `live_or_soak` selection passed once with no retry; focused syntax
and whitespace checks passed. No hosted CI was used under the cost policy;
the material environment difference is that this opt-in check uses the actual
installed connector and public OAuth/MCP service rather than hermetic source
fixtures. No product behavior changed, so no additional test framework or
unit fixture was added. Memory disposition: `forbidden` by this task's explicit
no-memory-write boundary.
