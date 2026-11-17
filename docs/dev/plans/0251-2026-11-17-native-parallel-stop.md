# Maintain opt-in parallel local-tool Stop acceptance
State: CLOSED
Work item: LOCAL-P251
Tracker state: DONE
Owner: primary
Branch: test/native-parallel-stop
Target: main

## Outcome and scope
Preserve the demonstrated two-active-tools Stop probe as an opt-in acceptance script. Run only in a separate UID1017 test account with a pinned complete native package, fresh synthetic home and loopback provider. Positive case must observe two active local processes, interrupt their exact turn, require both dead, reject late markers/follow-up provider requests and reap its native process. Omitted-Stop control must demonstrate the marker assertion can fail. Keep original failed setup receipts and qualified native identity outside Git. No production source fix, new provider calls, installation, native rebuild or exhaustive scheduler-race claim.

## Acceptance / execution
- CLI accepts explicit native path, expected executable hash, and fresh output path; rejects the working UID and existing output paths before native launch.
- Socket readiness resolves native pathname aliases and verifies actual owner/type.
- Existing public native_request RPC seam; existing loopback Responses fixture pattern; no fixture framework.
- Positive local execution PASS; omitted-Stop expected RED with late markers. Exact commands/results recorded below. Failures retain machine-readable receipt and log.
- Cleanup checks record exact owned child identities and final status, not only daemon service status.
- Document direct reproduction and explicit coverage limits in script help/docstring and acceptance reference.

## Current State
Implemented and validated opt-in script plus reproduction reference. Positive2.730s PASS, negative3.452s expected RED tool_continued_after_stop; both native servers reaped and all four tool processes absent. Wrong UID/hash/existing-output guards verified. Ruff0.14.2 undefined-name checks, compileall and policy wiring PASS. Evidence docs/dev/evidence/0251/parallel-stop.json. Published review branch is the remaining integration gate; no merge/deploy claimed.

## Review and authorized release
User requested review/merge/deploy. Fixed base22381945, initial candidate33a72939. Primary Standards review accepted a real check/read /proc observation race; process exits are now read atomically with missing-process handling, and unconfirmed cleanup cannot pass. Spec review confirms the declared two-active-tools scope and intentional negative control. Focused reruns: positive4.372s PASS; negative4.181s expected tool_continued_after_stop; four known tools absent, native processes reaped. Ruff/compileall/policy checks pass. Implementation acceptance complete; PR710 is the integration path. Deploy only the exact merged canonical script to the isolated acceptance location, then record digest and runtime smoke separately; no application/native installation is needed.
