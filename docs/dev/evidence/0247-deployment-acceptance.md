# #690 | Deployed acceptance

PR692 merged as8542810979d961f9ac69f1e4706e70c3431a7a0e. Exact immutable dev38
wheel SHA256169ad1f16fc986a8cc529b91ef32e7ee41663e31b9cab894c2b0e935ba259522.
All349 package files match the separate UID1017 installation and staged working
prefix.144 source tests and144 installed-wheel tests pass. Dependencies retain
the31 pinned versions from the existing connector environment. Working Python
3.12.13 versus UID1017 Python3.12.3 shares the host kernel; no3.11/full-suite claim.

CLI and both canonical services now use dev38. A higher-priority deployment
override supersedes historical executable pins, preserving previous files,
resource limits and child-preservation controls for rollback. Nine owned
launchers were updated; the native codex launcher/client/daemon was not replaced.
The shared daemon's PID generation stayed unchanged.

Installed reconciliation of the original blocked peer completed3.34s and retained
native source-verified past-fact evidence. No native input or manual wake-state/
deadline reset was used for recovery. The exact lifecycle poll hold created by
graceful deployment stop was inspected and acknowledged with the supported
supervisor reconcile command; no other root's hold was cleared.

One15s/10m-window persistent time wake was registered through authenticated MCP.
The exec bridge's CLI self-identity check had refused registration before creating
a wake; no permission was weakened or duplicate test created. The new test first
waited for recipient_busy while the operator-response turn was active, then
delivered on existing_tab with exactly1attempt. The actual wake envelope's
trigger and native submission matched the retained test. This proves observed
delivery, not native terminal execution inferred from queue acceptance.

Private raw identifiers, service backups, traces and observed-delivery receipt
remain in the user-scoped incident directory. The curated JSON receipt hashes
native identifiers. Hosted CI was skipped under cost policy. No additional wake
is scheduled by closeout, and ScraPaper/other projects remain outside this packet.
