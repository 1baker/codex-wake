# P233 T5 mixed-worker source acceptance

Native source `45169bbc996d8baf1da130f2f11ac9f09d05ba2f` builds on accepted T4
`1eee8143f7642561f5d5573613b1e3658e208e63`. Wake account pinning is published at
`ec2d7cda1095c1f4a7c626c8ddf08db088418d86`. The native delta, thirteen file hashes,
complete tree and validation identities are in
`runtime/grok-native-233/t5-source-manifest.json`. Applying its binary-capable,
zero-context patch to the exact base independently reconstructs tree
`4ffbad5fca1eb6c308847907cb3da8563ba245e9`; a verified Git bundle is also retained
privately. The native source has not been pushed to the upstream OpenAI repository.

Normal native worker controls now resolve an exact qualified selection ID or
`grok__ACCOUNT` with exactly one validated account default. Workers retain the
accepted snapshot unless explicitly overridden. An OpenAI model override from a
Grok parent uses the configured OpenAI provider and model catalog and clears the
Grok selection. Existing permissions, parent/root identity and shared allowance
paths remain in use. Private bearer commands require the accepted registration
revision on each fetch; ordinary native token rotation does not change it.

Completed-response accounting observations are now durable. They and numeric
usage records retain the accepted selection; old records deserialize without the
optional field. Durable observations exclude opaque provider usage metadata.
Unknown provider usage remains absent, never a fabricated zero. Existing OpenAI
attribution retains its session provider and turn-model records. No OpenAI account
identity is inferred from a label.

Focused local acceptance:

- `just test --locked --offline --cargo-profile dev-small -p codex-core --test all --retries 0 -E 'test(grok_parent_can_select_openai_worker) | test(spawn_agent_selects_grok_account_default_under_existing_parent) | test(spawn_agent_requested_model_and_reasoning_override_inherited_settings_without_role)'`: five pass, 3.245 seconds execution in final job `job-20261115T025927Z-b3d206c72a95`. Both child variants must finish without error and with an agent reply. Disposable loopback transports supply inference; no real provider is called.
- Actual native parent/child histories from that run were consumed unchanged by Wake's public `observe_usage(..., session_scope=True, token_accounting='cache_inclusive')`. Both Grok-to-OpenAI and inherited-Grok trees have two parent records and one child record, fifteen tokens each: qualified total45 across two threads. Removing the child's numeric usage record from a separate copy produces unknown, used_tokens null, response_usage_missing. This verifies the existing cumulative observer, without creating or resetting an allowance.
- Same native runner selecting `test(suite::rollout_budget::) | test(spawn_agent_role_overrides_requested_model_and_reasoning_settings)`: twelve pass, 9.891 seconds execution, job `job-20261115T032320Z-ee3a8976b09e`. This includes shared subagent spending, exhaustion, compaction and no-retry behavior.
- Stable and experimental schema generation, Python SDK generation and four schema/TypeScript/precomputed consistency checks pass in job `job-20261115T024233Z-a1ac921ebb78`. The internal RolloutLine schema changed; unchanged public SDK outputs are retained. Existing uint-format generator warnings are preserved. Proto/config wire inputs did not change in T5.
- Wake auth9, public catalog1 and existing usage13 checks pass. Changed Rust formatting and whitespace checks pass; stable rustfmt reports that nightly import-granularity configuration is ignored.

The source loop retained failing tests before account/default/selection/provenance
fixes. Earlier reverse-worker timeouts were later diagnosed as unsupported fixture
capabilities, not proven provider-resolution failures. A one-token/two-client
fixture and duplicate fixture usage reports were also corrected; failed attempts
remain retained. An invalid T4 test parameter discovered by the core integration
compile was removed. These corrections are not the reserved broad review or its
post-review remediation.

Environment: local GNU Linux, Rust1.95, dev-small, jobs2, locked/offline dependencies
and a serialized existing cache. Compilation dominated elapsed time; this is not
hosted or multi-platform validation. No paid CI was run. T5 accepts the source
worker/accounting slice. T6 continuation, T7 interruption/revocation, T8 real-account
and complete isolated-package qualification, and the one broad review/remediation
remain separate gates. No native install, restart, device-login retry, real-provider
request or deployment occurred. Parent #628 remains open.
