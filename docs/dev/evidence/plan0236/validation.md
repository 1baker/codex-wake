# Delegated connector consent qualification

Issue650 / Plan0236; source based on a227bc06. Regression through actual HTTP OAuth
initially returned403 instead of200 for an explicitly delegated agent. Repair:
operator-private exact principal/client/expiry/scopes/targets/modes, browser
identity/policy fingerprint, actual-consenter audit, token and MCP ancestry checks.
Owner subject and independent IdP identity remain separate. No implicit mode.

Local command (PYTHONPATH=src:tests, qualified dev22 Python3.12/MCP2.2 environment):
`python -m unittest test_external_consent_delegation test_external_oauth_connector test_controller_auth test_unified_connectors test_unified_bulk test_unified_transports test_unified_contract test_controller_flow_surfaces -q`
36PASS50.220s. Covers expiry, other client/principal, spoofed headers, identity
switch, scope/target/mode expansion, policy changes, withdrawal of issued grant,
audit attribution, owner compatibility, actual SDK transport and original scopes.

Built0.22.0.dev23 wheel SHA256
`a22e27d203f8c8067e8df3a9ca2a2ce9c094270fc9fee623ad85206429e9a82c`.
Exact wheel with31pinned dependencies installed under separate Linux UID1017;
installed10connector/delegation tests PASS11.035s. Source/installed proof are separate;
shared kernel remains a limitation. No Python3.11/full suite/hosted paid CI claim.
Initial UID staging inherited private umask: corrected public test/wheel staging
permissions and reran from/tmp. Failed setup remains in session receipts.
Policy wiring and whitespace checks PASS. No new IdP/ingress/native/core changes.
Production token mode, grant and actual client call remain unselected/unqualified.
Private qualification and browser receipts remain outside Git under user state.
Memory disposition forbidden: no explicit request to write memory.
