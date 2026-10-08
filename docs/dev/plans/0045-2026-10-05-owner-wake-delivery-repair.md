# Exact-owner wake delivery repair

## Desired result

Resume the existing proposal owner after an idle trigger, deliver its saved instructions, and distinguish accepted, completed, interrupted and uncertain delivery. Preserve the live owner and the proposal's four-party final-file approval gate.

## Scope and decision

Use the verified existing Codex TUI for managed-owner delivery. An external ModelLabs ingress connection cannot mutate another connection's thread. The native client, its ancestry, foreground terminal, resume UUID and captured remote endpoint provide the target proof, not the pane's top-level command or saved label.

Fix short unowned stdio wakes separately: enforce real deadlines, keep the client alive until the exact completion event, and refuse a held writer lock. The live kernel fdinfo for the installed Codex writer descriptor reports `FLOCK ADVISORY WRITE`, confirming the local lock primitive. Never create, delete or unlock another process's lock.

Add optional owner-mode metadata without changing legacy tmux dispatch or schema-v1 status meanings. Inline payloads are bounded, digest-bound and acknowledged through the exact rollout; no global hook installation is needed. Persist a sending boundary before any submission. Uncertain submissions must not replay.

## Non-goals

No ModelLabs changes, shared-service restart, second writer, proposal text or Word edits, browser review, approval-limit increase, source push, or declaration that the proposal is finished.

## Plan

1. Add tests for deadlines, held ownership, payloads, no replay, exact foreground owner and incremental completion evidence.
2. Implement bounded stdio completion and optional exact-owner tmux delivery. Keep completion and pane visibility separate.
3. Run the full suite and obtain a peer drift check before installation.
4. Build an isolated runtime, verify a monitored disposable canary, then schedule one safe owner canary after this turn stops. Do not inject into an active turn.
5. Verify exact-owner completion and visible response before arming real proposal continuation. Publish a sanitized checkpoint and update the existing private status tracker.

## Completion checks

- Short stdio wake completes with the actual saved instruction and matching turn ID.
- Live-owned stdio targets are refused before resume.
- Sending/uncertain records cannot be re-dispatched after crash, EOF or timeout.
- Owner delivery validates PID lifetime, ancestry, foreground terminal, resume UUID and remote endpoint immediately before paste.
- Accepted and terminal rollout evidence matches the wake ID and payload digest, preserving inode and offset boundaries.
- The same owner interface displays the completed canary's unique response.
- The shared host, unrelated monitors, Office files and proposal review caps remain unchanged.

## Agreement and current position

Codex accepts v2 and Claude Code accepted its architecture at repair-task revision 4, with explicit no-replay, foreground-owner and payload checks. This is engineering-plan acceptance, not final proposal approval. The first drift review at revision 6 required a non-echoed response token, owner-only bracketed paste, live-monitor custody, idle expiry and short-stdio deadline recovery. The adjacent supervisor wrapper forwards the same one-shot owner-dispatch guard as the daemon. No ModelLabs changes were needed.

Both installed synthetic canaries passed. The current interface's known shortcuts footer is supported without relaxing the runtime terminal gate. A revision-10 peer review caught overlapping due records; a same-owner in-flight guard now runs inside the pane lock. All 182 tests pass and the diff check is clean. At revision 12 Claude explicitly approved the source and the bounded two-wake validation spec, not actual-owner success. Codex accepts that same spec.

Historical checkpoint (2026-10-05): exactly two records were scheduled on an isolated, private owner-monitor root: a no-tools owner canary, then a read-only checkpoint/report wake 15 minutes later. The latter had to verify the former's exact terminal and visible response before proceeding. It could not edit documents, call a peer review, reset tasks, create further wakes, or assert approval. At the recorded checkpoint the canary was waiting for owner idle with zero attempts and no delivery, and the report wake remained pending. This is historical evidence, not current service or delivery status. Keep the engineering outcome partial until actual-owner evidence and the report are observed. See [installed validation evidence](../verification/0070-2026-10-05-exact-owner-wake-repair.md). Exact owner bindings and original local notes are retained privately.
