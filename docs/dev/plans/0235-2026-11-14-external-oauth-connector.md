# External OAuth connector

State: OPEN
Owner: ecochran76 / root
Work item: #646
Branch: feat/external-oauth-0235

## Current State

External OAuth exposure and connector-install skills loaded. Current deployed dev21
already owns scoped grants, target/action fencing and canonical operations. Previews
uses explicit owner browser consent; LitScout uses SDK token verification. Existing
codex-wake HTTPS host publishes only POST /github/webhook to8820: preserve it.
SDK transport, canonical filtered catalog and explicit owner/subset browser consent
implemented. Public HTTP/SDK tests pass; current stdio initialize/list/read remains
qualified. Existing Previews callback recovered from current private configuration.
Installation client scope is pending an operator response; no account change or
broad permission selection inferred. Packaging and exact ingress publication follow.

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
protect consent without changing webhook/auth policy. Proposed fixed loopback37186;
exact public host already owned: codex-wake.ecochran.dyndns.org. Deployment follows
merged-main/qualification policy and applicable operator authorization. No native
upgrade, session input, production wake/grant creation or account-wide publishing.
Client linking requires exact app/account/callback and explicit human consent.
