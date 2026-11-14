# External OAuth connector qualification

Source implementation:7edb7943, based on33cde3f4. Official installed MCP2.2 transport
and existing OAuthAuthority/ProtectedOperations are reused. No new token cryptography,
ambient stdio forwarding, executor, native daemon upgrade or provider invocation.

Focused source command (PYTHONPATH=src:tests, Python3.12.13, MCP2.2/httpx2):

`python -m unittest test_external_oauth_connector test_controller_auth test_unified_connectors test_unified_bulk test_unified_transports test_unified_contract test_controller_flow_surfaces -q`

33cases PASS30.319s under120s budget. Source legacy-reader test has its actual Git
baseline available. Seven external connector cases cover public metadata/challenge,
real official SDK initialize/list/read, explicit operator/subset consent, narrow
catalog/action denial, PKCE/code/consent replay, refresh/revocation, owner/CSRF/origin,
fixed redirect, private configuration, actual loopback IdP HTTP verification and
refusal to follow an IdP redirect, plus narrowed host-policy token refusal.
Synthetic identity/provider effects only; no production connector grant created.

Red/green receipts: discovery missing module ->PASS; /register404 ->full consentPASS;
SDK method-not-found ->authorized scoped readPASS; wrong-owner login redirect303
->explicit403PASS; broad old token incorrectly accepted200 after policy narrowing
->401PASS. Setup/import/API-spelling failures remain recorded independently.

Installed dev21 baseline: actual stdio initialize/list511tools and authorized
wake_environment_snapshot read PASS using temporary state; no mutations.
Ruff F821/F822/F823, compileall, policy wiring, generated command/contract freshness,
active planning and git diff whitespace PASS. Hosted paid CI skipped. No full-suite,
Python3.11 matrix, live provider, authenticated public owner/OpenAI-client claim.
Raw receipts: ~/.local/state/codex-wake/external-oauth-0235/ outside Git.

Current deployment gate: codex-wake HTTPS inventory exists only for exact POST
/github/webhook8820. Eight exact OAuth/MCP route candidates use8822 and preserve
that webhook. The existing Cooper Authelia rules have no matching codex-wake host;
consent needs one new exact-host sign-in rule. Applying the supported helper
recreates shared Cooper Authelia and requires existing local sessions to sign in
again. That shared-session impact must be explicitly approved before adoption.
Client-installation scope and actual owner consent remain pending separately.

Installed candidate wheel SHA256c03fbfb2840085e4baf230e4fae35063b7abb5f70f3227bfe42dc742e4f2d430;
separate Linux UID1017/Python3.12.3 installed seven connector tests PASS7.661s,
no skips. First setup attempt inherited an inaccessible cwd; corrected from/tmp
with uv configuration disabled, without changing product code or tests.
Ingress renderer nine cases PASS; inventory validates. Proposed backend port
revised from37186 to pinned8822 after the validator identified the ephemeral-range
risk. No Python/package change; current candidate artifact remains identical.

All348owned package members (346Python plus2data files) match source/wheel/UID1017
installation exactly; installed connectors serve --help PASS. Final backend8822
availability checked;8821 was occupied and never adopted. Actual live-renderer
baseline equals current live inventory, and all unrelated rendered entries remain
identical in the candidate. Shared-auth helper dry-run confirms a new rule would be
added. Current public metadata404; public publication has not happened.
