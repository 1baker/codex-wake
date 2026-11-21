# CW-0235: Native registration from a detached MCP working directory

State: CLOSED
Owner: Codex. Priority: high. WIP limit: one.
Outcome boundary: completed source/focused-validation packet; later integration and operational rearm remain separately evidenced.
Source request: operator invoked diagnosing-bugs, then tdd after the SoyLei monitor failed to rearm.

## Scope and acceptance

Native MCP registration must remain usable when its long-lived process has lost its working directory. Recover the workspace only from verified same-thread native metadata; do not accept caller-selected roots or weaken principal checks. Preserve existing healthy-cwd fingerprints, persistent lifetime, delivery policy and exact-key deduplication. If native workspace cannot be qualified, fail closed without retaining a wake. No daemon deployment, credential/policy changes, ad changes or new monitoring scope.

Stable seam: CommandRunner.call for native scheduling. Filesystem getcwd and external native thread metadata are boundary fixtures. Use temporary wake roots and explicit unavailable-clock fixtures; never production timers or credentials.

Red/green receipt: recorded below. Source base: 1aa498674a4907f93b5216a4a98dd75a22c6ecec.
Installed release is separately 0.22.0.dev41-8966396; source validation is not installed recovery.

Definition of done: regression red before fix, focused scheduling/authority tests green, local validation recorded, source changes reviewable. Live monitor remains open until installed acceptance and one monitored successor are verified.

## Validation receipt

Tier: focused; local Linux/WSL, Python3.12.13 from installed Wake release, source imported with PYTHONPATH=src (or src:tests). No hosted CI or live provider effects. Source base above; exact change is retained on fix/detached-mcp-cwd.

Red and green command (same selection, before/after implementation):

```
PYTHONPATH=src /home/ecochran76/.local/share/codex-wake/releases/0.22.0.dev41-8966396/bin/python -m unittest discover -s tests -p test_harness_callers.py -k detached -v
```

Red: one failure, harness_operation_held / errno19 No such device,0.597s. Green: one pass,0.468s. Only filesystem getcwd, external native thread metadata, clock and runtime observation boundaries are fixtures. The public registration and its deduplication/principal policy execute normally.

Additional focused commands, same interpreter:

- `PYTHONPATH=src python -m unittest discover -s tests -p test_harness_callers.py -v`:10passed,2.981s.
- `PYTHONPATH=src:tests python -m unittest test_native_delivery test_wake_session_modes test_handoff_permissions test_session_permissions test_network_wakes`:43passed,10.536s.
- `PYTHONPATH=src:tests python -m unittest test_native_intent_recovery`:19passed,11.692s.
- `git diff --check`:passed.

No full presubmit, comprehensive, live or soak claim. No retries of failed checks. No debug instrumentation added to production code. Existing caller metadata validation and public schema remain unchanged. Healthy cwd retains previous fingerprint behavior; fallback is private and only accepts workspace from the verified native caller. The source fix does not reconnect an already-running old MCP process. Installation qualification, deployment and exact live monitored rearm remain separate outstanding operational work.
