# 0239 — Pinned native input lookup

Local ticket: CW-0239. Owner: primary agent. Priority: P1. State: DONE.
Dependencies: none. WIP limit: one. Branch: fix/pinned-native-input.

The authorized ChatGPT greeting was refused before creating an operation because discovery of an unrelated registered daemon failed. Resolve a complete expected target through the host-selected shared endpoint first, retaining peer ownership and complete generation checks. Unpinned discovery and explicit endpoints retain existing behavior. No account, permission, native daemon or OAuth grant changes.

Acceptance: regression fails before the fix and passes after; changed target remains refused; real read-only lookup matches this chat; exact wheel qualifies under UID1017 before isolated connector deployment; ChatGPT retries the same idempotent queue request and reports native acceptance.

Done means deployed acceptance, source custody and task checkout cleanup. Queue acceptance does not prove consumption while this turn remains active.

Validation: initial focused regression failed with daemon_unavailable; source live lookup with complete identity now succeeds. Full commands and installation evidence are retained in private external-oauth-0235 artifacts. Memory disposition: forbidden; no memory write requested.

Integration: PR658 merged as 494bde00. Version 0.22.0.dev26, wheel SHA256 e46b1acf444bd06f1a6a46e9717a5ba30ff62f4d2f9baf8f1b3d0ed06de05e98. Focused source selection: 17 passed in 48.124s; installed same selection under UID1017: 17 passed in 20.212s. All 339 package members match source and both installed prefixes. Initial UID staging import failure was directory permissions, corrected before executing checks. Linux Python3.12 shares kernel; hosted 3.11 matrix not run. Connector restarted alone; public metadata 200 and anonymous MCP 401. No native daemon restart.

Follow-up: real ChatGPT retry refused before operation creation. Full enumeration reads roughly 60 threads against one 10-second observation budget; selective loaded membership plus exact-thread metadata avoids unrelated reads, reducing live pinned lookup to 3.695 seconds. Explicit pinned revalidation uses the same selection. Complete loaded membership enumeration and generation checks remain mandatory.

Final package: PR659 merged as 67787e55. Version 0.22.0.dev27, SHA256 5a96379fed0a98a63e58ecf287fb23d8e3aa5e33d614607c77e8663cc9681781. Focused source checks: 18 passed in 49.953s; UID1017 installed checks: 18 passed in 23.781s. All 339 payload members match source and installs. `python3 scripts/check_policy_wiring.py` and `git diff --check` pass. Hosted Actions skipped under cost policy; Python3.11 not exercised.

Live acceptance: ChatGPT OAuth connector submitted the exact authorized greeting with the original idempotency key. Native operation admitted, execution queued, delivery submitted. Consumption not observed while this same turn is active. Private operation/target receipts remain outside Git. Initial failures were pre-effect; no alternate conversation or input policy was used. Checkout retires after this closeout is merged and remote custody verified.
