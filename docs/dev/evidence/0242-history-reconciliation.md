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
