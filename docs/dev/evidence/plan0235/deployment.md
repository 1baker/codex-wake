# External OAuth connector deployment

2026-11-14: operator explicitly approved both PR merges, deployment and the shared
Cooper Authelia restart. Server PR647 merged b9f8d96e576b61715469f089c5ab97234b30d994;
ingress PR13 merged a9e1ae2ead3a3e2b0f60d36329acf6a832b30c28.

Installed version0.22.0.dev22 in the content-addressed user release prefix
0.22.0.dev22-c03fbfb; wheel SHA256
c03fbfb2840085e4baf230e4fae35063b7abb5f70f3227bfe42dc742e4f2d430.
All338 codex_wake package payload members match merged source and working install.
Earlier348-member qualification additionally counted installed scripts outside the
package directory; retain the original receipts. Dependency31pins retained.
The codex-wake-connector user service is enabled/active, bound127.0.0.1:8822.
Core dev21 launchers/services and native sessions were not upgraded or restarted.

Supported Cooper helper validated/adopted one exact-host one-factor rule and
recreated Cooper Authelia; existing browser sessions must sign in again. Container
healthy afterward. Live ingress adopted only reviewed codex-wake inventory and
rendered namespace; all unrelated routers/services/middlewares compare identical.
Exact POST/github/webhook8820 preserved. Bastion snippet published with --no-restart;
no shared Traefik restart or bastion Authelia change. Bastion CODEX_LOG appended.
Touched bastion paths: CODEX_LOG.md and
traefik-portainer/conf.d/codex-wake-cooper.yml, both modified.

Public TLS at https://codex-wake.ecochran.dyndns.org verified:
- authorization-server and both protected-resource metadata paths200;
- anonymous MCP GET/POST/DELETE401 with resource_metadata challenge;
- unlisted callback registration400 and wrong-resource authorization400;
- anonymous valid consent303 to correct Cooper sign-in portal;
- independent Cooper agent sign-in succeeds; authenticated nonowner denied403.

No production grant, owner-authorized public tool call, or account installation
claimed. Browser operator/subset selection and client linking remain explicit.
No paid hosted CI. Prior33source/7UID1017installed/9ingress tests remain the local
validation basis; no runtime code changed during deployment. Public verification,
preimages, private policy, service and readiness receipts remain outside Git under
user state external-oauth-0235. Setup failure: default Python lacked PyYAML;
reran comparison/adoption with system Python, preserving live state.

Memory disposition: forbidden; explicit-user-request-only memory boundary.
