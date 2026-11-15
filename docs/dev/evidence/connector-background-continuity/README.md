# Connector background continuity — issue #666

## Result

PASS against the actual installed `0.22.0.dev28` connector and native `0.169.0` daemon, through public HTTPS OAuth/MCP. No product source changes were needed.

A previously created, exclusively owned synthetic conversation was unarchived and resumed using a persistent uniquely named native client. It already contained a completed harmless preparation turn. A real Codex TUI resumed that exact conversation in one owned tmux tab. Native discovery established `metadata_matched` attachment, including the exact TUI process generation. The owned tab was closed and the TUI process exited. Exact-thread history remained readable and the daemon independently reported the same thread loaded, while the terminal server/session was absent.

Only after closure, a separately scoped OAuth client submitted one explicit `reject` input through the deployed MCP connector. The original operation returned `completed` with the exact expected reply `BACKGROUND_CONTINUITY_CONFIRMED`; its conversation UUID matched the original saved conversation. No replacement visible tab was created. The native thread was archived and the temporary OAuth grant revoked during cleanup. A fresh OS readback found neither the owned TUI process nor its private tmux server.

This proves continuation after loss of the TUI while the existing app-server still holds the conversation. It does not prove automatic recovery after native daemon exit, machine restart, or an unloaded conversation; those are separate wake-mode/recovery cases. Presentation parking was not substituted for tab closure.

## Invocation and evidence

Run the opt-in script with the installed connector Python:

`python scripts/connector_background_continuity_acceptance.py --reuse-owned-thread <owned preparation UUID>`

The reuse parameter accepts only an ID already listed in the private task-owned preparation manifest. Without it, the script prepares a new disposable conversation. Public MCP authorization uses an independently named client and an exact-conversation grant; credentials remain in process memory and are revoked in `finally`. No browser tokens or operator grants are copied or changed.

The live successful invocation reused the exact owned preparation conversation from the fourth attempt. Private `result.json` records the target UUID, native TUI PID, original operation ID, result, absence of a recreated tab, and cleanup. Logs and receipts are kept in the user-scoped connector-background-continuity state directory rather than Git. No credentials, transcripts, or unrelated inventory are published here.

## Earlier attempts and limits

Earlier readiness attempts are retained as failures, not passing acceptance. They exposed remote-resume permission-override refusal, a trust prompt in an empty temporary directory, a broad saved-history observation timeout, and a later transient native initialization rejection. The three temporary-directory trust entries created by those owned UI confirmations were removed by exact path/block match, preserving unrelated configuration. Subsequent work used an already trusted repository directory and no permission overrides.

The proven launch is the installed native executable with `resume --remote <exact endpoint> --no-alt-screen -C <trusted cwd> <exact UUID>`, with inherited session IDs and pane identity removed. Permission policy was set at initial native conversation creation, not overridden during remote resume. Exact-thread saved history reads avoid broad CWD pagination. Transient read readiness failures are bounded on the same owned identity rather than creating replacement conversations.

Final source changes after live acceptance only adopt the already-used WebSocket context-manager entry/exit form and persist newly created ownership IDs before later reads. These prevent a deprecation warning and make interruption recovery explicit; syntax and whitespace checks passed without repeating live provider work.

## Validation and disposition

- Installed connector Python: real HTTPS/MCP acceptance, PASS.
- `python3 -m py_compile scripts/connector_background_continuity_acceptance.py`: PASS.
- `git diff --check`: PASS.
- Hosted GitHub CI skipped under repository cost policy. This live case used Linux/Python3.12, sharing the host kernel; it is not the complete hosted version matrix.
- No broad review or post-review TDD pass was run by this worker; the coordinator owns those single passes.
- Memory disposition: `forbidden`; no explicit memory write was requested.
