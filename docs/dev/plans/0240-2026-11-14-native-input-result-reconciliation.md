# 0240 — Reconcile native input completion

State: CLOSED

Local ticket CW-0240. Owner primary. Priority P1. State DONE. Dependencies none. WIP one.
Branch fix/native-input-result-reconciliation; isolated checkout until integration and runtime acceptance.

Symptom: ChatGPT reads the correct final answer but retained execution says cancelled. The exact native turn now says completed. A private replay through public SessionInputs.result reproduces cancelled with zero native observations. Changing only retained phase to waiting observes completed. Minimal synthetic queue/interrupted/completed regression fails in 0.468s.

Ranked hypotheses: (1) terminal early return freezes earlier interruption; (2) concurrent stale save overwrites completion; (3) projection/status mapping corrupts completion. Phase-only replay confirms (1); direct completed mapping is correct. Initial native read with 10s deadline timed out; bounded 60s read captured only selected turn fields. No mutation or resubmission used.

Scope: caller-authorized read-only reconciliation of cancelled input against the exact original correlated native turn. Require native completed status and exact original input identity; never infer success from answer text, redispatch, or downgrade terminal results. Preserve previous cancellation in a correction event. Stale/foreign peers remain refused.

Acceptance: failed regression turns green; genuine cancellation, unavailable observation and mismatched turn stay cancelled; original private replay passes; exact wheel qualifies under UID1017; connector live result and ChatGPT readback show completed for original operation. No native daemon restart, OAuth changes or extra prompt.

Definition of done: accepted source, isolated connector deployment, readback and own-checkout cleanup. Memory disposition forbidden: no explicit memory write requested.

Source PR661 merged bfb0a1d0. Exact version 0.22.0.dev28, wheel SHA256 1fb9180dd253f01e4073cd24f87b9119ef35e5cdf8958bb1acbc2fac841ed336. Source focused checks: 14 passed in 20.145s; exact installed UID1017 selection: 14 passed in 24.258s. All 339 payload members match source and both installs. Linux Python3.12/shared kernel; hosted 3.11 matrix untested, Actions skipped by cost policy. Policy wiring, compileall, diff checks pass; no debug logging added. Original private replay passes with exact native client input captured; earlier reduced capture omitted user identity, so it correctly could not authorize correction until that load-bearing evidence was retained. Public metadata 200, anonymous MCP 401. Only isolated connector restarted.

Live acceptance: same original operation and turn now return completed / owner_observed / exact reply through real ChatGPT read-only result call. Exactly one native_completion_reconciled journal event retains previous_execution=cancelled. No prompt resubmitted. Private evidence stays outside Git. The initial native interrupted observation was not captured contemporaneously; its origin is not established, while stale terminal retention is reproduced and fixed. Own checkout retires after merged closeout and verified remote custody.
