# 0239 — Pinned native input lookup

Local ticket: CW-0239. Owner: primary agent. Priority: P1. State: IN_PROGRESS (runtime deployed; ChatGPT acceptance pending).
Dependencies: none. WIP limit: one. Branch: fix/pinned-native-input.

The authorized ChatGPT greeting was refused before creating an operation because discovery of an unrelated registered daemon failed. Resolve a complete expected target through the host-selected shared endpoint first, retaining peer ownership and complete generation checks. Unpinned discovery and explicit endpoints retain existing behavior. No account, permission, native daemon or OAuth grant changes.

Acceptance: regression fails before the fix and passes after; changed target remains refused; real read-only lookup matches this chat; exact wheel qualifies under UID1017 before isolated connector deployment; ChatGPT retries the same idempotent queue request and reports native acceptance.

Done means deployed acceptance, source custody and task checkout cleanup. Queue acceptance does not prove consumption while this turn remains active.

Validation: initial focused regression failed with daemon_unavailable; source live lookup with complete identity now succeeds. Full commands and installation evidence are retained in private external-oauth-0235 artifacts. Memory disposition: forbidden; no memory write requested.

Integration: PR658 merged as 494bde00. Version 0.22.0.dev26, wheel SHA256 e46b1acf444bd06f1a6a46e9717a5ba30ff62f4d2f9baf8f1b3d0ed06de05e98. Focused source selection: 17 passed in 48.124s; installed same selection under UID1017: 17 passed in 20.212s. All 339 package members match source and both installed prefixes. Initial UID staging import failure was directory permissions, corrected before executing checks. Linux Python3.12 shares kernel; hosted 3.11 matrix not run. Connector restarted alone; public metadata 200 and anonymous MCP 401. No native daemon restart.

Follow-up: real ChatGPT retry refused before operation creation. Full enumeration reads roughly 60 threads against one 10-second observation budget; selective loaded membership plus exact-thread metadata avoids unrelated reads, reducing live pinned lookup to 3.695 seconds. Explicit pinned revalidation uses the same selection. Complete loaded membership enumeration and generation checks remain mandatory.
