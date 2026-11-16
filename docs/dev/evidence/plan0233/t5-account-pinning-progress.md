# P233 T5 account pinning progress (ticket remains running)

Wake private token CLI accepts `--expected-account-revision`. Its public status
reports the canonical registration revision; both time-qualified bearer reads
hold if that registration changed. Native token rotation within the registered
identity remains supported. Generated native catalog commands carry that revision
and disable command-auth caching so later fetches revalidate the registration.
No credential value is added to the catalog, selection or worker configuration.

Focused local checks, using the existing Python3.12 environment and CLI harness:

- `PYTHONPATH=src <root>/.venv/bin/python -m unittest discover -s tests -p test_grok_provider_auth.py`: nine pass. The new registration-change/token-rotation behavior and public CLI pin each failed before implementation and passed after it.
- Same command with `-p test_grok_model_catalog.py`: one public CLI/API/MCP scenario passes. Its emitted private-command pin/cache assertions failed before the generator change and passed after it.
- Native public model/list and ordinary thread/start test
  `grok_catalog_selection_is_qualified_pinned_and_native` failed with the pinned
  command before the validator change, then passed in 2.415 seconds after it.
  Exact retained CargoSignal jobs: RED `job-20261114T231008Z-f81a8c2bf827`,
  GREEN `job-20261114T233435Z-632e8aee0aad`, under the private P233 T5 state root.
  RED compiled25m15 and retried the same expected failure once; GREEN compiled
  16m01 and disabled retries. These are focused source checks, not live proof.

Native source is based on accepted T4 commit
`1eee8143f7642561f5d5573613b1e3658e208e63`; the T5 delta is still in its owned
checkout pending complete ticket acceptance and exact source custody. Existing
serialized cache, Rust1.95/dev-small/jobs2/offline/locked settings were retained.
No hosted CI, native installation/restart, login retry or real inference occurred.

Normal mixed-worker selection/inheritance, canonical usage attribution and shared
allowance acceptance remain unfinished. T5 #634 stays open; T6 is blocked by T5.
Broad review and bounded post-review remediation remain at zero.
