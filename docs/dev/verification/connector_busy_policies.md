# Connector busy-input policy acceptance — issue #665

Owner: primary operator / delegated busy-policy worker. Spec: #663.
Frozen source base: `882aae8007e71cc2641c66a742e340e6cf007310`.
Installed product: `0.22.0.dev28`, wheel SHA256
`1fb9180dd253f01e4073cd24f87b9119ef35e5cdf8958bb1acbc2fac841ed336`.
No product module, service, account configuration or operator grant was changed.

## Actual deployed acceptance

`connector_busy_policies.py --approve-real-agent --output <new-private-directory>`
ran against the existing public HTTPS OAuth MCP connector and a newly created,
disposable native conversation. A separate exact-conversation `cw665-busy` client
used public PKCE token exchange; credentials stayed in process memory. The script
kept the native creator attached and seeded its first real turn before input
admission. This is real provider work, not an injected native protocol fixture.

Observed through deployed MCP:

- Busy `reject` returned `session_busy`; the rejected marker was absent from native input.
- `queue` acknowledged the native queue while the original turn remained active,
  then completed with the exact requested `BUSY_QUEUE_DONE` reply.
- `steer` acknowledged the exact original active turn and completed with the exact
  revised `BUSY_STEER_DONE` reply.
- Idle `steer` returned `turn_unavailable`, with no prompt fallback.
- Explicit `interrupt_then_submit` interrupted only the second disposable turn;
  one native input with its derived continuation client message ID completed with
  `BUSY_INTERRUPT_REPLACEMENT_DONE`.
- Each accepted operation returned `completed` and `owner_observed` with its
  correlated native turn and answer.

The completed conversation was archived, its independent grant revoked, and a
fresh OS readback found zero remaining owned shell/sleep processes in its private
working directory. Credential-free detailed operation receipts remain user-local.

Two initial incomplete attempts are preserved separately: closing the creator of
an empty new thread made history/discovery unavailable before qualification. The
first still proved reject, then refused queue before admission; its thread/grant
were cleaned. The second created no provider turn or grant; its exact empty
thread was subsequently archived. Neither failure was retried as an uncertain
mutation. The attached-creator run used a fresh owned conversation and intent.

## Deterministic stale-turn fencing

The public input API does not accept a caller-selected expected turn ID. It
captures the active turn internally and revalidates that identity immediately
before native dispatch. A focused existing-boundary test supplies an original
active turn on admission and a replacement turn on revalidation. `submit` retains
`stale_target` and sends only the two read calls: no steer, start, interrupt or
queue effect. The journal's conservative execution label is `unknown` after
admission, not a fabricated failed/completed result.

This native-boundary injection proves the deterministic changed-turn race. It is
separate from the actual deployed transport evidence above and is not presented
as a live race measurement.

Validation:

- `python3 -m py_compile scripts/connector_busy_policies.py` — PASS.
- `PYTHONPATH=src:tests <installed-python> -m unittest test_connector_busy_policies test_unified_session_input -q` — 7 PASS in 2.132 seconds.
- `git diff --check` — PASS.
- Actual OAuth/MCP scenario — PASS, all five policy checks and cleanup verified.

Hosted CI was skipped under repository cost policy. Local checks used Linux
Python 3.12 on the working host; no Python 3.11 hosted matrix is claimed.
Memory disposition: forbidden; no explicit memory write request.
