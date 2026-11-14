# External OAuth connector

State: DONE
Owner: ecochran76 / root
Work item: #646
Branch: feat/external-oauth-0235

## Current State

Operator approved merge/deploy and the shared Cooper Authelia restart on
2026-11-14. Server PR647 merged at b9f8d96e; ingress PR13 merged at a9e1ae2e.
The qualified dev22 wheel is installed in a separate immutable connector prefix;
new user service is active on loopback8822. Public OAuth metadata returns200,
anonymous MCP GET/POST/DELETE401 with resource discovery, consent redirects303 to
Cooper sign-in, unlisted callback/wrong-resource400, authenticated nonowner403.
No production grant was created. Owner consent and client installation remain
explicit follow-up choices, outside this server delivery. Existing webhook8820,
native/core sessions and unrelated ingress entries are preserved.
See [deployment evidence](../evidence/plan0235/deployment.md).

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
