# Native wake explicit-policy renewal regression

Work item: native-explicit-policy-renewal. Owner: primary agent. Priority: P1.
State: reconciled source and UID1017 installed registration qualified; production renewal open.
Request: operator invoked diagnosing-bugs after persistent monitor renewal failed.
Scope: native registration compatibility only. No permission edits, trigger writes,
existing record migration, daemon replacement, service restart or live dispatch.
Baseline origin/main5fa63408; installed MCP/CLI0.22.0.dev38-169ad1f.

## Feedback loop and cause

Actual installed decorate_policy with synthetic root/principal and mocked allowed
permission responses rejects all three advertised modes for ordered routes
existing_tab/background/new_tab: session_mode_routes_conflict. Loop0.12s, no wakes
written. Original retained key also refuses adding a target session_mode that was
absent originally. CLI fallback refused policy/identity checks; that is a separate
correct authority boundary, not permission to impersonate an operator.

Ranked predictions: mandatory-mode API cannot express independent legacy policy;
legacy record decode defect; mislabeled permissions. Constructor rejects fresh
requests before route checks even when grant response is allowed. Legacy CLI
registration with full independent fields succeeds. Public MCP regression first
failed invalid_argument for explicit_policy, then passed after adding the explicit
compatibility selector. This confirms API representability/compatibility gap.

## Fix and invariants

Add native-only session_mode selector explicit_policy. It requires wake_lifetime,
recipient_startup and routes, then uses the existing independent policy contract.
No persisted target lifecycle field is added and legacy fingerprints stay equal.
All existing permission, exact-self, owner and retry validation remains active.
A key already bound to any lifecycle mode cannot use this selector to drop it.
Missing mode remains rejected by MCP; missing explicit fields remain rejected.
Recurring schedules keep their existing three-mode schema; no new mode semantics
or reader capability is silently advertised for persisted records.

Four hermetic public-caller tests exercise exact legacy-key retry, a successor,
incomplete contract rejection, denied route and bound-lifecycle preservation.
Existing explicit-mode and route/uncertain-delivery tests continue passing.
No debug instrumentation added to tracked implementation. Private tagged repro
remains in a clearly marked diagnostic directory, outside this repository.

## Current-main qualification and limits

Reconciled against canonical7b9e9d96, retaining the original branch history and
current busy-policy, detached-directory and transport behavior. The original
positive test first failed on that main product code with invalid_argument.
All four original explicit-policy tests pass after the narrow native-only fix.

The seven focused modules discover52 tests. Selected48 pass on both Python3.11
and3.12 using isolated HOME/XDG directories and an empty StableTime configuration.
Four unchanged-baseline failures were reproduced against immutable7b9e9d96:
three task-brief caller tests require qualified UTC, and the owner-completion
policy fixture expects armed state without a qualified reader observation.
Their precise IDs and raw3FAIL/1ERROR baseline result are retained privately.
No fixture, clock or production readiness changes were made to hide those defects.
Ruff undefined-name checks, policy wiring and scoped diff checks pass locally.
Hosted CI was not run under the repository cost policy.

Exact wheel0.22.0.dev44 SHA256
4cdb753370ce656ebbc7d2711b2461b298cfebaf3a08f8de98203a38d6f04c08
was installed only into a task-owned UID1017 target. Public CLI registration used
an owned native0.171 server's actual metadata and synthetic actor capability.
Actual stdio MCP then preserved the legacy ID, target, fingerprint and ordered
routes, admitted a successor, and rejected missing explicit fields, removal of a
bound lifecycle and a denied route. All353 installed Python files equal the wheel.
Three synthetic records retained zero attempts; no monitor, dispatch, provider
request or qualified-time gate was invoked. Awaiting qualified clock is retained
registration state, not an armed or delivered receipt. The owned server exited0.
Private evidence: reconcile-status-20261121/pr699, installed case p699-reg-r5.
Earlier setup failures and their cleanup remain retained alongside the pass.

This proves installed registration compatibility only. Production monitor renewal,
working-account installation, schema reload and armed-receipt acceptance remain
outside this change. Preserve original monitor keys and exact prompt/cadence/TTL/
startup/routes when separately authorized; do not invent replacement keys for an
uncertain send. No extension of spam enforcement is implied.
