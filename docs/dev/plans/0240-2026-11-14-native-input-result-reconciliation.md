# 0240 — Reconcile native input completion

Local ticket CW-0240. Owner primary. Priority P1. State IN_PROGRESS. Dependencies none. WIP one.
Branch fix/native-input-result-reconciliation; isolated checkout until integration and runtime acceptance.

Symptom: ChatGPT reads the correct final answer but retained execution says cancelled. The exact native turn now says completed. A private replay through public SessionInputs.result reproduces cancelled with zero native observations. Changing only retained phase to waiting observes completed. Minimal synthetic queue/interrupted/completed regression fails in 0.468s.

Ranked hypotheses: (1) terminal early return freezes earlier interruption; (2) concurrent stale save overwrites completion; (3) projection/status mapping corrupts completion. Phase-only replay confirms (1); direct completed mapping is correct. Initial native read with 10s deadline timed out; bounded 60s read captured only selected turn fields. No mutation or resubmission used.

Scope: caller-authorized read-only reconciliation of cancelled input against the exact original correlated native turn. Require native completed status and exact original input identity; never infer success from answer text, redispatch, or downgrade terminal results. Preserve previous cancellation in a correction event. Stale/foreign peers remain refused.

Acceptance: failed regression turns green; genuine cancellation, unavailable observation and mismatched turn stay cancelled; original private replay passes; exact wheel qualifies under UID1017; connector live result and ChatGPT readback show completed for original operation. No native daemon restart, OAuth changes or extra prompt.

Definition of done: accepted source, isolated connector deployment, readback and own-checkout cleanup. Memory disposition forbidden: no explicit memory write requested.
