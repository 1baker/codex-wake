# #672 — Connector restart continuity

PASS through the deployed HTTPS OAuth/MCP boundary on installed
`0.22.0.dev30-c7d7279`, using a separate exact-conversation authorization and
the opt-in `scripts/connector_restart_continuity_acceptance.py`.

The accepted run used script source commit
`9212b17b8316d37db93a3e29546e9b7f7a914c48` and the installed Python 3.12
environment. A persisted disposable conversation received a separate setup
turn, then a connector-submitted bounded `sleep 60` task. Before the restart
checkpoint, the client verified one native user input correlated by operation
ID, its in-progress native turn, and a nonterminal retained operation. The
client disconnected MCP while retaining its original token in memory. The
controller restarted only the connector and released the checkpoint after
public startup readiness; the script also observed protected-resource metadata
200 and anonymous MCP 401 before reconnecting.

The reconnect used the same caller grant and unchanged payload/idempotency key.
Its retry returned the original operation. The public result tool returned
`execution=completed`, the exact `RESTART_CONTINUITY_CONFIRMED` answer, and the
same original native turn. Native history contained exactly one input with the
original operation's client ID. The native daemon PID, process start ticks,
executable and endpoint were unchanged. All 62 previously loaded conversation
IDs remained loaded. The separate acceptance monitor also remained running;
neither native daemon nor monitor was restarted.

Cleanup archived the owned conversation, revoked only its test grant, verified
public MCP 401 using that revoked token, and found zero owned shell processes.
Private receipts retain the exact target, operation, grant, endpoint and process
bindings; secrets and unrelated histories are not published.

One earlier actual run is explicitly **INCOMPLETE**: the controller released its
restart checkpoint before public startup readiness, so immediate MCP initialize
failed and the cleanup HTTP probe received 502. The owned conversation was
archived and its grant revoked; a separate read-only authority lookup confirmed
that exact grant's revoked flag, and the owned shell census was zero. That run
is retained privately and is not counted as acceptance. The controller then
authorized one fresh owned case with a new key, plus one additional connector
restart. The script added bounded read-only metadata/anonymous-MCP readiness
before reconnecting. It did not replay or reauthorize the earlier operation.

Validation: `python -m py_compile scripts/connector_restart_continuity_acceptance.py`,
the script's `--help`, and `git diff --check` passed. The accepted live command
used installed dev30 `bin/python`, this script, `--approve-real-agent`, the
preserved native PID, and a fresh private `--output` directory; exit 0 with
`verdict=PASS`. This is an opt-in real-provider Linux/Python 3.12 acceptance,
not the complete hosted Python matrix. Hosted CI was skipped under cost policy.
No product source, deployment configuration, grant privileges or policy were
changed. Root retains integration, issue closure and shared-ledger ownership.
