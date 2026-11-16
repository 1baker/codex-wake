# P233 native source custody

This directory preserves native Codex changes as source patches. It is not an
assembled or qualified package and does not activate a working profile.

`t2-source-manifest.json` pins the T2 base, commit, complete source tree, changed
file hashes, patch hash and focused local acceptance. The base is the governor
source identified by `../governor-native-572/manifest.json`; that directory
retains its complete native patch and upstream anchor. Apply the T2 delta only
to that exact retained base. The primary independently applied this delta to an
isolated Git index at the base and verified the resulting complete tree equals
the manifest source tree. No native checkout or installed package was changed.
A verified Git bundle is additionally retained in workstation-local custody.

T2 adds the Grok-specific wire/configuration and SSE conversion into the existing
native tool loop. It preserves command-based private bearer authentication and
holds unqualified features and incomplete/uncertain streams. It does not enable
a generic chat gateway or silently route through API keys.

Local checks distinguish the 274 API/provider tests, three native behavior and
OpenAI regression tests, one remote configuration test, generated-protocol
comparison and focused API library lint. The native checks preceded a private
transparent type alias; affected API tests/lint followed it. Full workspace lint,
full platform coverage, account entitlement, live coding, complete packaging,
isolated upgrade/rollback and installed behavior are not established here.

Future ticket deltas must preserve this acceptance boundary. The program retains
one broad review and one bounded remediation after its implementation tickets,
then exact package qualification and authorized merge/deployment.

Source deltas omit unchanged context; apply them with `git apply --unidiff-zero`
against their exact manifest base. This avoids meaningless trailing-space
context records inside tracked patch data. Each delta was independently applied
in an isolated Git index and verified against its complete expected source tree.

T5 adds normal mixed-provider worker selection and durable attributed accounting.
After the exact T2 and T4 deltas, apply `t5-mixed-workers.patch` at its manifest's
T4 base with `git apply --unidiff-zero`. Its thirteen changed-file hashes and
complete reconstructed tree are independently verified. Wake private command
support at ec2d7cda or later is required for accepted-account revision pinning.
See docs/dev/evidence/plan0233/t5-mixed-workers-acceptance.md for focused local
acceptance and the remaining continuation, revocation, live and package gates.

T6 adds safe-boundary native provider/account continuations. After T5, apply
`t6-provider-continuations.patch` at its exact manifest base with
`git apply --unidiff-zero`. All 39 changed-file hashes and the reconstructed
complete tree match native 977af9d6c5bf2c5d59de1a46009ffa9a34f00b22.
The existing thread/fork pathway accepts optional boolean `providerContinuation`;
Grok provider/account transitions imply it. Linked successors retain original
identity, permissions, goal and cumulative allowance; cold or uncertain authority
holds. See docs/dev/evidence/plan0233/t6-provider-continuations-acceptance.md.
Worker source checks passed; primary custody/integration and issue closure remain
pending. This does not qualify live accounts, installation, Stop or recovery.

T7 adds owned Stop, exact-account registration revocation and durable request/
accounting fences. Apply `t7-provider-safety.patch` at its exact T6 manifest base
with `git apply --unidiff-zero`. All13 file hashes and reconstructed complete tree
match native abc2ce28469ca57e584ef33cf71b4ad172f8bb26. Public protocol/SDK bytes
are unchanged. Source mock checks passed; primary custody/closure and T8 complete
package/live-account qualification remain separate. See
`docs/dev/evidence/plan0233/t7-provider-safety-acceptance.md`, including the
conservative cold strict-allowance hold and provider completion/logout uncertainty.

T8's complete GNU/dev-small native package is identified by
`t8-package-manifest.json` (five executables and package metadata). The exact
package passed UID1017 upgrade/rollback, public history/multiclient/reconnect,
failed-start repair and private-client ownership checks. Real-account acceptance
remains a separate primary gate; #639 is not closed by package qualification.
See `docs/dev/evidence/plan0233/t8-isolated-package-acceptance.md` and
`t8-real-account-gate.md`. No T8 Rust/public schema change or working installation
is included, and broad review/remediation counters remain zero.

T8 incremental source corrections apply after the T7 native source in this order:
`t8-http-diagnostic.patch`, `t8-version-header.patch`, then `t8-usage-routing.patch`.
Each adjacent source manifest pins the exact prerequisite commit, resulting tree
and file hashes. Apply the full-index zero-context patches with
`git apply --unidiff-zero`. Source correction acceptance does not establish a
qualified installed package or real-provider readiness; consult the exact T8
package manifest and live evidence separately.
