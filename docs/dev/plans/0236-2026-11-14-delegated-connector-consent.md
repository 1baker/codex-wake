# P236 | Delegated connector consent

State: CLOSED
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

## Deployment and closeout

PR651 merged fa9ae165b40f5971c7f0dc8df86bb13571b9ac17. Exact qualified dev23
wheel installed in release0.22.0.dev23-a22e27d and connector-only service restarted.
Existing historical649 service override was selecting the older prefix; updated
only its executable path after comparing package payloads. All prior historical
modules match; differences are version and connector files plus the new helper.
Keep existing KillMode and SendSIGKILL settings. No IdP/ingress/core/native restart.

Private deployment delegation binds the existing ChatGPT client to the Cooper
agent, host/environment ceilings, allowed modes and24-hour expiry. It selects no
mode and creates no grant. Actual browser sign-in now reaches the consent form:
ChatGPT identity/callback correct, actual agent plus delegating owner shown,
operator/subset radios both unchecked. Public metadata200 and anonymousMCP401.
This closes the bug; final OAuth linking awaits the operator's explicit mode.
36source checks/10UID1017installed checks and339package-member parity recorded
in validation.md. Separate-account shared-kernel limitation remains.
Task checkout retires after documentation integration; root dirty work preserved.
Memoryforbidden: no explicit user request to write memory.
