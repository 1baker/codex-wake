# P238 | Browser consent Origin

State: OPEN
Owner: root / ecochran76
Work item: #654
Branch: fix/connector-consent-origin

Actual browser POST returned invalid_origin before any grant. Real Chrome fixture
proves no-referrer sends Origin:null; same-origin sends the actual first-party
origin. Change only the consent response referrer policy, retaining exact Origin,
identity, delegation and cookie/flow checks. Cross-site callbacks omit referrer.

Regression initially fails no-referrer != same-origin. Source/installed connector
suite and actual browser callback qualification follow. One isolated checkout
protects dirty root; retire after integration and remote custody. No shared IdP,
core/native, ingress or browser restart. Explicit operator mode already selected.

## Qualification

Actual browser POST failed invalid_origin; strict Origin checking rejects it
before grant creation. Independent real Chrome fixture: no-referrer sends literal
null; same-origin sends actual first-party origin. Initial fixture lacked HTML
Content-Type and could not find its button; corrected response media type and
retained that setup failure. HTTP regression red no-referrer != same-origin;
source10connector/delegation tests PASS11.067s, policy wiring/whitespace PASS.
No origin allowlist expansion or null-Origin exception.

Exactdev24wheel SHA25623111e24e5206cd3b288f65d62b03b769565173d9df3578427d975e54ccdfb9b
installed under Linux UID1017:10tests PASS7.810s;339package members match source,
wheel and installed package. Shared kernel; no full-suite/Python3.11 matrix or
hosted paid CI. No source change after qualification.

Live continuation: dev24 preserved POST Origin, so the selected operator consent
created an audited grant. Chrome then blocked its external303 under form-action
self. No token was exchanged; revoked that unused grant through existing authority
and retained receipt. Add only the already validated exact callback origin/path
to form-action, encoding directive punctuation. Exact Origin, CSRF, identity,
client redirect allowlist and delegation fences remain unchanged. CSP regression
first failed because registered callback was absent. No OAuth callback replay.

Callback continuation qualification: Chrome fixture blocks self-only external
redirect (0requests), permits exact callback (1request), and blocks a different
origin (0requests). Source10tests PASS9.031s. dev25wheel SHA256
5a801f993e12c5a624a95c2be36897687314c47ea3df05c2132e10f7b37ea0f3;339payload
members match source/wheel/UID1017. Installed test result retained privately.
