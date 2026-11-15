# 0239 — Pinned native input lookup

Local ticket: CW-0239. Owner: primary agent. Priority: P1. State: IN_PROGRESS.
Dependencies: none. WIP limit: one. Branch: fix/pinned-native-input.

The authorized ChatGPT greeting was refused before creating an operation because discovery of an unrelated registered daemon failed. Resolve a complete expected target through the host-selected shared endpoint first, retaining peer ownership and complete generation checks. Unpinned discovery and explicit endpoints retain existing behavior. No account, permission, native daemon or OAuth grant changes.

Acceptance: regression fails before the fix and passes after; changed target remains refused; real read-only lookup matches this chat; exact wheel qualifies under UID1017 before isolated connector deployment; ChatGPT retries the same idempotent queue request and reports native acceptance.

Done means deployed acceptance, source custody and task checkout cleanup. Queue acceptance does not prove consumption while this turn remains active.

Validation: initial focused regression failed with daemon_unavailable; source live lookup with complete identity now succeeds. Full commands and installation evidence are retained in private external-oauth-0235 artifacts. Memory disposition: forbidden; no memory write requested.
