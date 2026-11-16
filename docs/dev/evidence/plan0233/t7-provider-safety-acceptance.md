# P233 T7 provider safety: worker source acceptance

Issue #637 remains open for primary custody, integration and closure. Native source
is `abc2ce28469ca57e584ef33cf71b4ad172f8bb26`, based on accepted T6
`977af9d6c5bf2c5d59de1a46009ffa9a34f00b22`. Wake worker base is
`592c97d13b98b784a8067a26fc5c71f85e5caeac`; both worker branches are
`feat/p233-provider-safety`. Broad review and final remediation counters remain zero.

## Behavior and contracts

- Existing native `Op::Interrupt` fences further owned local tool dispatch before
  existing cancellation. It explicitly leaves provider completion, final usage
  and already in-flight external effects unconfirmed. Delayed provider tool
  output is not dispatched, and uncertain requests are not replayed.
- Existing account-auth CLI adds `grok auth revoke ACCOUNT --expected-target JSON`.
  Protected API `grok_auth.revoke` and MCP `wake_grok_auth_revoke` require exact
  `account.revoke` authority and target. The private owned atomic registration
  fence changes the accepted account revision and denies bearer issuance without
  writing/removing the official credential store or invoking provider logout.
  Other account labels/bindings remain intact. Public output contains no bearer.
- An active native turn consumes semantic revocation for its pinned account via
  the existing public catalog command, at one-second intervals. It aborts only
  the matching owned turn. A global catalog revision change does not cancel
  another Grok account or OpenAI. Missing credential files report unavailable,
  not confirmed logout. Provider logout/completion remains unconfirmed.
- A private version1 `CODEX_HOME/provider_safety/THREAD.json` intent precedes Grok
  request I/O, including local compaction. It retains exact root/thread/turn and
  selection identity, observation/uncertainty and a no-replay rule. Original-root
  unknown-accounting markers fence enforced cumulative allowances. No credential,
  opaque provider history or second numeric spending ledger is introduced.
- Strict Grok tool scheduling waits for both response usage and the existing
  shared controller's budget decision. Auth, quota, provider, incomplete and
  missing-accounting failures produce actionable held states, without automatic
  provider/account fallback. Reassignment remains explicit and cannot override
  unknown actions/accounting.
- Completed strict cold history can be inspected, but new spending holds without
  its original live `LocalAgentRuntime` authority. A new launch limit cannot
  turn a fresh controller's zero spending into authority over old work. This is
  a conservative held recovery contract, not automatic budget reconstruction.
- Existing canonical usage remains the sole numeric source. Interrupted/failed
  registered Grok requests yield unknown/null aggregate usage; prior charges stay
  retained. Fully observed budget exhaustion retains its known charge subject
  to existing response/usage attribution checks. T5 worker lineage and T6 fences,
  leases, original permissions/allowance and portable context remain unchanged.

No native public protocol/SDK schema changed. Existing remote configuration and
private account-pinned bare-bearer command contracts remain intact. Wake account
registration changes are additive (`revoked` and `revocation_target`); old records
remain readable. New private intents are versioned and malformed/unowned records
hold. No release/install migration or real-provider readiness is claimed.

## Bounded local validation

Private receipts, logs, input hashes and canonical captures are retained under
`~/.local/state/codex-wake/p233-t7/`. Exact drivers retain the existing Rust1.95,
GNU target, dev-small/jobs2/incremental0, offline/locked shared cache, serialized
flock and retained V8 inputs. The standard just stack was 8MiB. Hosted CI was not
run; these are focused Linux source/mock checks, not complete package acceptance.

- `native-safety-green.sh`: CargoSignal `job-20261115T120703Z-2cd94dcfa3fb`, receipt
  `20261115T120704Z-47353e2a7327/receipt.json`, PASS, 551.766s including compilation;
  13 existing integration cases passed in 8.421s. They exercise actual accepted
  loopback requests, local Stop, exact account revocation/peer survival, 401/429/
  503, incomplete response, missing usage/no tool effect, local compaction,
  cold known/unknown recovery, actual T6 terminal/patch/MCP and budget/lease
  behavior, OpenAI stream recovery and ordinary local-compaction usage.
- `canonical-safety-usage.json`: unmodified actual native captures qualify known
  history at8 tokens and the actual two-thread mixed tree at90. Seven adverse
  Stop/failure captures remain unknown/null. Source JSONL hashes were unchanged
  before/after observation. Actual late/unknown tool sentinel effects were absent;
  each failed/uncertain request count remained one.
- Existing qualified Python environment with `PYTHONPATH=src`, unittest discovery:
  `test_grok_provider_auth.py`12PASS (`wake-auth-green.log`), selected existing
  catalog revocation case1PASS (`wake-catalog-revocation-green.log`), and
  `test_goal_usage.py`16PASS (`wake-failed-usage-green.log`, 1.470s). CLI/API/MCP,
  private broker revision pinning, peer isolation, unknown accounting and known
  budget charges are exercised through existing seams.
- `rustfmt --edition2024 --config skip_children=true --check` changed Rust13PASS.
  `public-schema-causal-diff.txt` is empty for protocol/app-server-protocol/SDK
  against the exact accepted native base; no unchanged schema generation or
  TUI/app-server rebuild was added.

## Retained RED and failure classification

Actual RED evidence includes absent CLI revoke, protected unsupported operation,
missing-store falsely reported logout, native next-turn admission after Stop,
Wake actual stopped native history qualified as zero, failed Grok request
qualified as zero, missing selected-account interruption, compaction completing
without an uncertainty hold, and cold known history admitting a fresh900 limit.
Each was followed by a bounded causal correction and the acceptance above.

Compile failures, missing system-Python websockets, owned writer-lock fixture
shutdown omission, a peer SSE missing mandatory observed model identity, and an
Error-before-terminal steering assertion are retained separately as compile/
environment/harness failures. They are not counted as independent product REDs.
The corrected exact-account test passed while both unrelated peers completed.

## Custody and remaining gates

`t7-source-manifest.json` identifies all13 native changed-file hashes, complete
native tree, verified zero-context patch and private bundle digest. Reapplying
`t7-provider-safety.patch` in an isolated Git index reproduces exact tree
`16c26eb541990a1fb57edf7dc2b3346bff1e6dc0`. Private bundle verification passed.
The native checkout and Wake checkout are retained for primary integration and
required T8 qualification; final source IDs, status and writer-lease return are
in the worker completion receipt. No native push to OpenAI occurred.

T8 still owns real-account sign-in/entitlement/inference, installed identity and
complete isolated UID1017 package/history/multiclient/upgrade/rollback acceptance.
No working-profile install/restart/login/logout/refresh or live provider calls
were made for this ticket. The previously documented historical unpinned
WebSocket warmup attempt remains a historical limitation; no zero-historical-
connection or real-account-qualified claim is made. Memory disposition is
`forbidden`: this delegated source/evidence slice does not write external program
memory; primary retains program closeout authority.

Primary acceptance: independently verified all13 native/15 Wake commit-file hashes,
tracked-clean tips, exact patch reconstruction and bundle digest/verification,
terminal native13 receipt and unchanged protocol/schema/SDK inputs. Fast-forwarded
worker source6e6de81c into the integration branch. Repeated Wake auth12/catalog1/
usage16 checks successfully. Independently reconsumed all unchanged canonical
captures: known8 and90 remain qualified; seven adverse Stop/failure captures are
unknown/null. No duplicate native build or real-provider effect was initiated.
