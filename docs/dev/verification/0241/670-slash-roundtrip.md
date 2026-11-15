# #670 — Structured slash round trip

Validated against deployed external connector `0.22.0.dev28-1fb9180`, public
HTTPS OAuth/MCP resource `https://codex-wake.ecochran.dyndns.org/mcp`.
Frozen spec baseline: `882aae8007e71cc2641c66a742e340e6cf007310`.
Worker source starts at integration checkpoint `a67f445d`.

The opt-in script provisions one disposable native conversation and a separate
exact-conversation grant. A single native preparation turn makes transcript
observations available; it is separate from the structured slash action. Codes,
PKCE verifier and access token stay in process memory. Public token exchange,
MCP initialization and actual deployed tool calls exercise the connector.

| Criterion | Observed acceptance |
|---|---|
| Discover current supported actions | Actual MCP tools and qualified native slash catalog discovered; `/status` advertised as native `thread/read` |
| Execute a harmless action | `/status` completed through the structured slash run operation |
| Retrieve correlated result | Slash result tool returned the same durable operation ID, native target ID, completed execution and native method |
| No ordinary prompt fallback | Result explicitly reported `model_submission: false`; native user inputs were identical before/after |
| Unsupported action | `/model` returned `unsupported_slash_command`; no prompt fallback |
| No unrelated target changes | Own conversation stayed idle; queue remained empty; name and working directory unchanged |
| Cleanup | Own temporary grant revoked and rejected by public MCP with HTTP401; own native thread archived |

A first attempt passed discovery and structured `/status` execution, but its
refusal assertion expected a flat error value while the deployed slash error
used nested `error.code`. That failed attempt's receipt and cleanup were retained
privately. Correcting only acceptance-client envelope parsing allowed the second
fresh disposable scenario to pass every criterion. No product source change or
unknown write retry occurred.

## Reproduction

```sh
"$CONNECTOR_PREFIX/bin/python" scripts/connector_slash_roundtrip_acceptance.py \
  --config "$CONNECTOR_PRIVATE_CONFIG" --receipt "$PRIVATE_ACCEPTANCE_RECEIPT"
```

The live successful receipt is retained under the operator's private Codex Wake
state (`connector-slash-roundtrip/acceptance2.json`). It is not a public credential
or transcript artifact. The script is opt-in and is not added to hermetic CI.

Local focused checks:

- Installed Python with `PYTHONPATH=src:tests -m unittest test_local_slash_commands -q`: 5 passed in 75.041s; existing dependency deprecation warnings only.
- `python3 -m py_compile scripts/connector_slash_roundtrip_acceptance.py`: passed.
- `git diff --check`: passed.

Python3.12 on the installed host was exercised; the hosted 3.11/3.12 matrix was
not run under repository CI cost policy. No native daemon or connector restart,
operator grant/plugin change, operator conversation prompt, or operator tab
closure occurred. Memory disposition: `forbidden` — no explicit memory write
requested.
