# Opt-in parallel local-tool Stop acceptance

Use `scripts/native_parallel_stop_acceptance.py` after a native upgrade when the
required behavior is cancellation of two local tools that are already active in
the same turn. This is an isolated runtime acceptance check, excluded from the
normal Python suite. It uses the public `turn/interrupt` RPC, a synthetic loopback
Responses provider and a fresh home; no credentials, production histories or
working daemons are needed. No native rebuild is required.

Run as the separate `codex-daemon-test` Linux account (UID1017), using its installed
Wake Python with native-protocol dependencies. Stage the script there and select
the exact qualified complete-package executable. The script requires its SHA256
and refuses another UID, a hash mismatch or an existing output directory before
starting native work. Use an absolute fresh output directory for every attempt.

```sh
python native_parallel_stop_acceptance.py \
  --native /path/to/qualified/package/bin/codex \
  --expected-native-sha256 FULL_SHA256 \
  --output /path/to/fresh/positive-case
```

The positive case must exit0 and produce `result.json` with `state: passed`, exact
turn status `interrupted`, both tool processes dead, no post-Stop marker and no
follow-up provider request. It records native executable hash, observed tool PIDs,
elapsed time and post-cleanup process states. Full native output remains in the
private case directory. A failure or timeout is never passing evidence.

Run a second fresh case with `--omit-stop` as the negative control. It intentionally
exits1; require `error: tool_continued_after_stop` in its receipt. An arbitrary
setup error does not qualify the negative control. The tool commands then reach
their markers, proving the assertion can detect continuing work. Retain both
receipts; do not convert this deliberate RED into a product bug report.

Both tools announce startup and wait on an explicit file barrier before the
interrupt. Polling is bounded (15-second startup/tool barrier, 5-second turn and
process completion, 10-second individual RPC bound). Cleanup releases any blocked
owned tools, terminates/reaps only the native process group created by this case,
and reports remaining known tool states. Do a fresh OS process readback after
failures; service status alone is not a resource census.

Coverage limit: this proves only the two-already-active-tools cancellation case.
It does not force every native scheduler interleaving, prove cancellation of
queued tools, test a TUI key binding, or qualify remote/external provider behavior.
Do not change production cancellation code without a reproduced product failure.
