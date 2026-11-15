# #674 bounded native reconciliation

Source candidate; installation and final issue closure remain separate.

The original whole-history path could lose its native connection while the
supported paged API remained usable. The transport-close cause (size versus
another failure) is not established. A protocol-boundary regression first failed
with the whole-history connection error, then recovered exact original
client/message/turn identities through two complete pages without input calls.

Reconciliation now reads exact thread metadata and full-item turn pages, at most
128 pages of16 turns, under the existing single10s monotonic observation deadline.
The remaining deadline is passed to each RPC and checked after response and before
return. Missing cursors, cursor cycles, repeated turns, unknown statuses, missing
items and summary-only responses remain held. Exact prompt/client/message/turn
matching and multiple-submission refusal remain in the existing classifier.
Only explicit first-page method-not-found permits legacy whole-history fallback,
under the same budget; malformed/partial pages do not authorize fallback.

The actual native0.169 generated schema describes summary as display-only and
full as every persisted ThreadItem available for that turn. Full pages preserve
exact input matching and the existing agentMessage-text output summary; no
display summary is treated as full output, usage or result acceptance. Finite
WebSocket/page/time bounds remain; this does not promise arbitrary-size history.

A read-only candidate composition against the actual current long native
conversation used five full pages, recovered the original synthetic round-trip's
exact client/message/turn identity and completed execution in7.649s, with zero
input calls. Raw conversation history was not retained; only receipt metadata,
output-summary coverage and method/timing observations are private. This does
not replay the original incident or alter its journal/queue custody. An earlier
probe of an archived synthetic recipient was refused at queue/list; that refusal
was not ignored and the recipient was not loaded to force a pass.

Local focused43checks PASS9.156s. Broader lifecycle61checks PASS66.721s after
updating one existing native protocol responder to advertise full turn pages.
Initial broader failures are preserved: an invalid selected module name and19
spawn checks whose old responder returned an empty object for the new method.
Native delivery modern-page responders now exercise real classifier paths;
the large-response transport test retains explicit older-server fallback.
Deadline overrun and unknown legacy state were each red before their guard fixes.
No fixture framework, provider prompt or runtime write was added for this repair.

Private commands/results/native schema and synthetic readback receipts live
under user-state history674. Final source/UID qualification and actual installed
adoption evidence will be appended after their gates. Hosted paid CI excluded.

## Independent review and bounded remediation

Review at6c1805b7 againsteb14ec93: Standards no consequential findings; Spec one
accepted P2. Exact-prompt user messages could retain absent/non-string identities.
The existing classifier predated this patch, but exact message/client identity
is required by this packet. A public reconcile regression failed on five malformed
identity cases, then passed after validation. Missing clientId still uses the
valid native message ID; invalid explicitly supplied client IDs are not promoted
into a fallback. Matching queue identities must also be valid nonempty strings.
Eight protocol/reconciliation tests PASS after this bounded remediation; no second
review loop or new native writes. Final combined/package gates remain separate.

## Exact package and final local gates

Product source 9829b1c00dd85d4b31be7c61b2ae3c8242ba4afe. Immutable
dev35 wheel SHA256 c92742ef52e89d35a6d34bbcb6a357462b75e1b300cb58cf4c7389a36297ddf7.
All349 package files match source and the separate UID1017 installation; CLI and
distribution metadata report0.22.0.dev35. Final source119tests PASS102.736s.
Undefined-name lint (F821,F822,F823), compileall, policy wiring and diff checks PASS.
Unrestricted Ruff style selection exposed existing compact-style violations;
the repository's required undefined-name selection passes.

Separate UID initial119test run had four test-package import errors; correcting
PYTHONPATH to include the copied tests' parent made all9 lifecycle tests pass.
The complete corrected installed-package rerun is recorded separately. No source
package path is in this qualification's PYTHONPATH. Linux UID isolation shares
the host kernel; test Python3.12.3 versus working3.12.13, with no3.11 matrix run.
Pinned dependencies are identical.

A fresh own native app-server under UID1017 was stopped after its owned probe.
It used a private empty CODEX_HOME and received zero native model/input calls.
Its first alias-socket probe was refused by custody checking; resolving the owned
physical socket reached the native service. A fresh unsaved empty thread then
refused turns/list, so that probe is recorded as FAIL, not native history proof;
the sole created thread was archived. It does not establish history upgrade or
launcher acceptance and no native daemon package is being installed. The existing
working daemon2082, browser379435 and unrelated test daemon3287769 remain alive.
Positive long-history adoption remains the post-deployment read-only gate.

Corrected full installed-package UID1017 run:119tests PASS82.075s, using
`PYTHONPATH=/tmp/cw674-qual:/tmp/cw674-qual/tests` and the installed venv Python.
All10 selected modules match the final source run. Initial failed receipts retained.

## Merged and installed adoption

PR682 merged as8009ce7cd7d4cc14f6e4ec7d13cb4a34ecb44775. The exact qualified
wheel's349 package files match merged main and the installed working prefix
`~/.local/share/codex-wake/releases/0.22.0.dev35-c92742e`. Both systemd unit pins
now select this prefix; only the connector restarted, PID1921906, active, with
KillMode=process and SendSIGKILL=no retained. Public protected-resource metadata
HTTP200 and anonymous MCP HTTP401. Native2082/startticks2000, browser379435 and
unrelated UID1017 daemon3287769 were preserved.

Actual installed read-only reconciliation of the original synthetic round-trip
in the current long native conversation: PASS3.027s,5 full pages, exact original
client/message/turn identity, execution turn_completed,20bytes/1 agentMessage
output-summary coverage,0 native input calls. Metadata read excluded turns;
no whole-history fallback. Private installed receipt retains methods/timing and
identities, never raw conversation bodies. This establishes the repaired read
path, not replay of the incident or downstream acceptance of its output.

#674 criteria satisfied; the original incident journal remains unmodified.
Container-loss/monitor-restart acceptance is #681, not a history-fix claim.
