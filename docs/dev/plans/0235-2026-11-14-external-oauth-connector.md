# External OAuth connector

State: OPEN
Owner: ecochran76 / root
Work item: #646
Branch: feat/external-oauth-0235

## Current State

Server PR647 and ingress PR13 are open and mergeable. Source33tests PASS30.319s;
installed immutable wheel c03fbfb2 under UID1017 passes7tests7.661s and all348owned
package members match source/wheel/install. Ingress9renderer tests and inventory
validation PASS. Final backend8822 confirmed available; webhook8820 unchanged.
Readiness/runtime/ingress candidates retained in user-scoped external-oauth-0235 state.

Required next action: await explicit operator approval to merge/deploy and add the
exact codex-wake host rule through the supported Cooper Authelia helper. Dry-run
confirms the rule is absent; applying it recreates the shared realm and signs out
existing Cooper browser sessions. Do not adopt live routes or auth changes without
that approval. Current public metadata404; no publication or production grant.
Client installation scope/owner OAuth consent remains separate and unselected.
Existing services, root dirty work, stdio and client configuration are unchanged.

## Scope and architecture

Use official installed MCP2.2 Streamable HTTP session manager and bearer middleware,
with stateless per-request authenticated context and existing ProtectedOperations.
Reuse OAuthAuthority for DCR, exact redirects, PKCE, expiring codes, rotating tokens,
revocation and cross-version credential fences. Add browser flow custody/CSRF and
Cooper Authelia owner verification; never trust incoming identity headers. Owner
and subset mode/scopes/targets/actions are explicit consent inputs bounded by private
host policy. No code passes a bearer token to a local ambient-authority subprocess.
Expose a canonical filtered tool catalog, preserving existing local stdio/API.

## Acceptance and test seams

Existing HTTP/public authority seams: OAuth discovery, registered exact redirect,
owner GET+POST consent and real SDK initialize/list/read, wrong identity/audience,
PKCE/replay, CSRF, denied mode/target/action/content, refresh/revocation. Synthetic
fixture root and external identity callback only; no fixture project/provider turn.
Focused checks120seconds; local CI only. Qualify source, installed transport,
external ingress and account installation separately. Preserve first failures.

## Delivery and non-goals

One implementation branch/PR with local checks, installer/service/ingress packet
and nonsecret readiness handoff. New HTTPS OAuth routes must remain protocol routes;
protect consent without changing webhook/auth policy. Proposed fixed loopback8822;
exact public host already owned: codex-wake.ecochran.dyndns.org. Deployment follows
merged-main/qualification policy and applicable operator authorization. No native
upgrade, session input, production wake/grant creation or account-wide publishing.
Client linking requires exact app/account/callback and explicit human consent.
