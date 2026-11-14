# External OAuth MCP connector

Run the optional SDK transport with the selected immutable package's MCP extra
(the new server does not require restarting existing core services):

```sh
RELEASE_PREFIX/bin/codex-wake connectors serve --config /absolute/private/connector.json
```

The private file must be a regular file owned by the service user, mode0600.
The service binds127.0.0.1; the fixed port and matching ingress routes are deployment
configuration. Example (replace owner/host/root and confirm the client's callback):

```json
{
  "issuer": "https://codex-wake.ecochran.dyndns.org",
  "owner": "YOUR_AUTHELIA_USERNAME",
  "host": "YOUR_HOST",
  "environment": "posix",
  "wake_root": "/ABSOLUTE/PRIVATE/WAKE_ROOT",
  "port": 8822,
  "targets": [{"host": "YOUR_HOST", "environment": "posix"}],
  "scopes": ["observe"],
  "grant_seconds": 86400,
  "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
  "authelia_url": "http://127.0.0.1:19097/api/authz/forward-auth",
  "login_url": "https://cooper-auth.ecochran.dyndns.org/"
}
```

That callback was observed in the existing Previews deployment. Copy the exact
callback actually shown for the intended new client; never add wildcards. A local
Codex client is a separate installation, with its own exact callback and credentials.
`scopes` and `targets` bound what browser consent may grant; they grant nothing on
startup. Configure only the operator's intended maximum. A token broader than the
current host scope/target ceiling is refused after policy reload; existing effect
records are retained, and explicit revocation remains a separate operation. All eleven existing
controller scopes are supported; content observation and terminal input stay
separate. The UI requires an explicit operator/subset selection. Restricted mode
requires named canonical actions; grants expire at the displayed deadline.

The browser identity is independently checked against fixed loopback Authelia on
both consent GET and POST. Request identity headers are ignored. Wrong signed-in
users receive a denial. Unauthenticated browsers use the configured sign-in portal.
Consent uses a Secure/HttpOnly/SameSite cookie and a one-use, expiring stored flow;
POST requires the exact origin. No operator consent secret is copied into a browser.
Do not expose the old manual-consent controller as a substitute for this flow.

## Protocol and authority

Resource: `https://HOST/mcp`. OAuth issuer: `https://HOST`.
Discovery: `/.well-known/oauth-protected-resource/mcp` (also root alias),
`/.well-known/oauth-authorization-server`. Protocol endpoints: `/register`, `/token`,
`/revoke`, `/mcp`; browser consent: `/authorize`.

Official MCP2.2 handles Streamable HTTP lifecycle, content negotiation, notifications,
cancellation and shutdown. Stateless requests carry authenticated context per call;
no session ID grants authority. The catalog contains canonical protected tools only,
filtered by the current actor's scopes/actions/content rights. Calls reauthenticate
through existing ProtectedOperations and target owners. Local-only ambient-authority
stdio tools are not forwarded. Existing local stdio/CLI/API remain supported.

OAuthAuthority remains the sole grant/code/token owner: exact resource and redirect,
S256 PKCE, one-time codes, rotating refresh, expiry and inherited revocation. Browser
consent uses fenced delegated credentials even for explicit operator mode. Revocation
uses the existing durable operation cancellation/reconciliation owner. Disconnects
and cancellations do not silently repeat an original effect.

Anonymous MCP discovery/calls require OAuth401 with resource_metadata, rather than
an HTML guard. Public OAuth metadata and DCR reveal no session data. Wrong resource,
missing/expired/revoked token, wrong owner or insufficient rights fail before protected
dispatch. Public request sizes, registration/consent/token rates and connections are
bounded. Cookies/tokens/authorization queries are not written to application access logs.

## Ingress and client handoff

Preserve existing exact POST `/github/webhook` on8820. Add only the above exact paths
to the connector backend8822 in canonical Cooper Webservices inventory. Keep
paths-only publication; do not forward the hostname root or arbitrary local routes.
Protocol routes must reach OAuth/MCP, not an HTML Authelia redirect. Interactive
identity checks remain in the app against Cooper Authelia; never trust proxy identity
headers alone or change a shared IdP policy to make an account pass.

Example systemd unit: `docs/deployment/codex-wake-connector.service.example`.
Install only a locally qualified merged immutable package; keep its interpreter,
private policy, owner/root and pinned port explicit. Preserve existing grant/flow
SQLite state during restart. An intentional issuer/resource change requires a new
authority, not mutation of the existing authority binding.

For ChatGPT, create/connect the intended personal OAuth MCP connector using the
verified `/mcp` URL, then choose and approve rights in the browser. Creating a
workspace/public plugin or replacing an existing app is separate authority. Source
checks, installed server, external TLS/discovery, actual owner consent and actual
OpenAI tool dispatch are separate acceptance boundaries. The deployment readiness
record must name any unqualified boundary. Server publication alone never proves
that a ChatGPT/Codex account has installed or authenticated the connector.

References: [MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization),
[OpenAI authentication](https://developers.openai.com/plugins/build/auth).

## Explicit delegated setup

The operator-private policy may include `consent_delegations`, empty by default.
Each entry requires `id`, exact Authelia `principal`, exact `client_ids`, nonempty
`scopes`, host-owned `targets`, explicit allowed `modes` (`operator`/`subset`),
finite Unix `expires_at`, and an operator authorization `reason`. No wildcard
client or owner identity alias is accepted. The authenticated delegate consents
on behalf of the configured owner only within these ceilings. Consent still
requires an explicit mode and selected rights; setup authority selects no mode.
The page identifies both actual consenter and owner.

Delegations are private deployment authority, never a request field. Preserve
operator authorization provenance outside Git. Reload by restarting only the
connector service. GET/POST bind the same identity and unchanged policy; expiry,
identity switches, changed policy, wrong clients and privilege expansion fail.
Issued grants retain actual consenter/delegation/mode in `connector_consent_audit`.
Credentials expire no later than delegation expiry. Token issuance and every MCP
authentication recheck current delegation, including original consent ancestry;
removing or narrowing a delegation fences existing credentials and descendants.
Existing owner sign-in and external IdP rules remain unchanged. Old in-flight
consent forms require a fresh GET after this upgrade.

Before downgrading to a connector version without consent-delegation checks,
revoke every grant listed in `connector_consent_audit` through the existing
authority revocation path, including pending code grants. Confirm revocation
receipts before starting that older runtime. Older releases do not enforce this
new private policy; rollback is not a policy-withdrawal mechanism.
