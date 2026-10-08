# Exact-owner wake repair checkpoint

Date: 2026-10-05. Status: **PARTIAL — installed tests verified; real-owner validation scheduled, not yet observed.**

## What changed

The stdio dispatcher now stays alive until the matching terminal turn, enforces real deadlines, refuses a live writer, and preserves uncertain outcomes without replaying them. Optional managed-owner delivery uses the existing foreground Codex client, bounded inline instructions, bracketed paste, exact rollout receipts, and a separate response-visibility check. A pane-locked in-flight guard prevents two wakes for one owner from overlapping. Legacy transports and per-task/phase review limits were not increased.

No proposal text, Word files, Zotero fields, drawing canvases, browser sessions, shared host, or shared monitor was changed by this engineering repair. No source release or GitHub push is claimed.

## Verification

- Full suite: 182 tests passed in 1.047 seconds.
- `git diff --check`: exit 0, no output.
- Installed disposable stdio canary: created → firing/sending → submitted/accepted → completed, one attempt. The private receipt records the exact terminal turn; the reply contains the unique synthetic marker and derived wake token.
- Installed synthetic managed-TUI canary: created → firing/sending → pasted → submitted/accepted → completed, one attempt. The private receipt records the exact turn; full saved envelope text and blank lines match the rollout. The 4 KB payload arrived as one user turn, used no tools, and produced `visible_response_observed` in the target pane.
- Synthetic service stopped and disabled, both diagnostic wakes archived, only the new diagnostic window closed. Saved rollouts and evidence retained.
- Claude Code accepted both canaries and the footer fix at repair revision 10, then approved the serialized guard and final arming spec at revision 12. This is source/plan approval, not proposal approval or real-owner success.

## Installed candidate identity

This is a local repair candidate, not a published `v0.5.0` release. Its version string remains 0.5.0; the content hashes identify it.

- Wheel SHA-256: `ea00a9302f2faed294bc303f1aa09fc70456940cd005d295abddf8f8f8ad6c80`.
- Owner-delivery module SHA-256, identical in source and isolated installation: `6fe3a774057c4d9d849ca8bf0a6bc72c1779fdf14341e96307f15bbecabce8b0`.
- An isolated candidate runtime, dedicated service and fresh private monitor root were verified at the historical checkpoint. The interval was 2 seconds, and persistent monitor health reported `monitor_ready=true` for that exact root. The default-name service card did not represent the custom-named service; its own systemd readback proved its identity.
- Exact runtime paths, service bindings and process identities remain in private evidence. These notes do not assert that the historical service is still active.

## Deferred real-owner validation

Schedule-time readback verified the exact thread, native process lifetime, pane and loopback remote endpoint. The dispatch checks ownership and both idle gates again before any paste. Changed identity fails closed. Exact values are retained privately and omitted from this public source note.

| Wake | Due UTC | Allowed action | Current evidence |
| --- | --- | --- | --- |
| Owner canary (private identifier) | 2026-10-05 05:07:39 | No-tools reply-only canary | Historical: firing / waiting for owner idle; zero attempts; no prompt sent |
| Report wake (private identifier) | 2026-10-05 05:22:39 | Verify first wake, recover checkpoint read-only, report and stop | Historical: pending; no delivery claimed |

The second wake must require completed delivery, the exact owner and matching terminal turn, the derived response marker, and `visible_response_observed`. If any check fails, it reports the gap and stops without resend. If verified, it reads the proposal's CURRENT, RUNBOOK, issue ledger and original capped peer task state only. No peer review, task reset, document edit, provider action, further wake, approval or finalization claim is part of this validation.

Historical readback at 05:12 UTC confirmed the first record was deliberately waiting for the active turn to finish, with no delivery metadata and zero attempts. The second was pending with zero attempts. The private tracker milestone was written and read back; the proposal issue remained open and in progress. The tracker and exact original notes are private.

The proposal remains unfinished: its four-party final-file gate is separate. The latest Word/PDF candidate hashes are unchanged. Current candidate registration and approval counts must be checked afresh by the report wake.

## Remaining completion evidence

Do not mark real-owner delivery complete until the first wake has a matching terminal event and visible reply. The second wake must also reach the user with its verification report. Its own terminal delivery cannot be proved from inside its still-running turn. Keep the workflow outcome open until that later readback exists.
