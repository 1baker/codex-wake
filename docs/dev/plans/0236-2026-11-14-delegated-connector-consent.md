# P236 | Delegated connector consent

State: OPEN
Work item: #650
Owner: root / ecochran76
Branch: fix/connector-consent-delegation

## Current State

Operator explicitly authorized completing setup through the Cooper agent account.
The owner-only consent check incorrectly rejects that delegated workflow. Add an
operator-private, exact-principal/exact-client, expiring consent delegation with
scope/target/mode ceilings and actual-consenter audit. No implicit mode, arbitrary
identity aliases, new IdP account, broader host rule or credential copying.

Acceptance: browser OAuth regression red/green; owner behavior preserved;
unlisted/expired/wrong-client/identity-switch/policy-change denied; credential and
MCP dispatch recheck current delegated policy. Qualify installed package under
UID1017, deploy only connector service, resume existing browser connection.
Client consent remains an explicit mode choice; do not infer from setup request.

Lane checkout exists to isolate multi-file authorization repair from dirty root;
retire after verified remote custody and integration. One primary lane, no agents.
