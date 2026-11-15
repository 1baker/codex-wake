# #664 — Duplicate input protection

Validated against deployed 0.22.0.dev28 through public HTTPS OAuth/MCP with a separate exact-conversation grant. Command: installed connector Python running `scripts/connector_duplicate_acceptance.py`.

One disposable conversation received a separate native setup turn because an empty new native thread does not support history reads. The test then submitted its exact input twice with one key: both returned one operation ID, the native transcript contained exactly one corresponding user input, a changed payload was refused with idempotency_conflict, and original result returned completed with the exact marker reply. Owned thread archived; temporary grant revoked.

First preparation attempts exposed broad discovery timeout, empty-thread history refusal and an SDK structured-content attribute mismatch. Those runs are retained privately; they are not counted as passing acceptance. No unknown write was resubmitted. The final successful experiment used its own new disposable target/key and independently verified native input count. No product source change was required.

Private receipts retain target and operation binding; credentials and native histories are not published. Applicable local syntax/diff checks pass. Hosted CI skipped under cost policy. This opt-in check uses Python3.12 on the installed host and real native provider; it is not the complete hosted Python matrix.
