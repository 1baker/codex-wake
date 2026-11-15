# #690 | Selective native completion observation

Initial status probe (orientation, not sufficient alone to prove admission):

```sh
python ~/.local/state/codex-wake/figurelabs-delivery-diagnosis/repro-completion.py
```

Red:1.683s, execution=not_observed, assertion failed. Installed adapter queue read
succeeds0.199s; includeTurns=true exhausts the remaining9.8s. Pinned metadata-only
read succeeds0.105s. unix:// is intentional auto-discovery, not a broken socket.

Ranked hypotheses: expensive history hydration, endpoint discovery, daemon health,
missing identities. Native boundary probes establish hydration as causal. Existing
main91b80b09 contains PR682 but still times out in10.007s on full turn pages here.
Summary discovery finds the exact completed wake in0.071s; selected full items
take0.095s (9items/38480bytes). No private bodies or real IDs enter tests.

Source regression, PYTHONPATH=src:tests and existing installed Python3.12:

```sh
python -m unittest test_native_reconcile_discovery -v
```

Red:3 errors in0.030s. Real adapter with external protocol replacement reproduces
full-hydration timeout; real peer admission tests terminal receipt release and
summary/full identity mismatch. First compatibility run:40 tests, two failures
in old full-projection expectations. Retained first results; expectations now
allow summaries as discovery but still require no native evidence from them.

Repair: summary turn pages; complete matching-turn item pages; exact hydrated
user/client identity and turn ownership; unique item IDs; cursor/page/time limits.
Summaries never become terminal evidence directly. No source DEBUG logs added.

Actual original native replay: PASS1.09s, exact original turn/user/client IDs,
execution=turn_completed and full native agentMessage text summary. Only queue,
metadata, summaries and one selected turn were read. Zero native input, whole
history requests or production-record writes. Same transport/executable/prompt
and recipient as failing probes. No completion receipt fabricated or inserted.

Raw probes and identifiers remain private under
~/.local/state/codex-wake/figurelabs-delivery-diagnosis/. Named debug scripts stay
there for replay, not as product commands. Source repair does not establish
installation or a newly delivered notification. Working runtime and existing
wake records were preserved.

## Peer admission loop and compatibility

The authoritative red-capable loop uses the real native adapter and peer guard,
with only peer enumeration minimized to the blocking prior wake and receipt
storage redirected to a private temporary directory. It preserves the original
target, executable, prompt and native transport. Production writes and native
input are forbidden:

```sh
python ~/.local/state/codex-wake/figurelabs-delivery-diagnosis/repro-peer-admission.py baseline
python ~/.local/state/codex-wake/figurelabs-delivery-diagnosis/repro-peer-admission.py candidate
```

Baseline: pending=true,10.008s, no terminal receipt. Candidate: pending=false,
5.944s, one source-verified private receipt. An earlier concurrent candidate
observation also reached its10s deadline; preserve this unavailable sample.
The live result is pass-on-retry evidence, not a clean first-pass latency claim.
The existing absolute budget and unavailable behavior remain under load.

Final compatibility:144 tests PASS302.285s with absolute source/tests PYTHONPATH,
Python3.12, installed dependency environment. Selection: test_native_reconcile_discovery,
test_native_protocol_large_response, test_native_delivery, test_wake_mode_runtime,
test_native_intent_recovery, test_agent_spawn, test_agent_handoff_preflight.
The first broader run failed49 assertions and2 errors because an existing
handoff mock server closed its connection on the optional turns/list read.
It now explicitly returns method-not-found, faithfully exercising older-server
fallback while preserving every handoff assertion. Correcting PYTHONPATH alone
did not fix that failure; all first receipts are retained.

Hosted CI skipped under operator cost policy. This is focused compatibility,
not the whole repository suite or Python3.11 matrix. Automatic notification
delivery and working-prefix deployment are not established by these checks.
