# P261 | Tame retained Wake and native worktrees

State: CLOSED (preservation/retirement acceptance; final own checkout closure after merge)
Work item: LOCAL-P261-WORKTREE-TAMING; related #420
Owner: primary / ecochran76
Priority: P1
Branch: docs/worktree-taming-261
Base:7e9fe130b720d0785c6087d6f67749b558ff14d0
WIP: one custody/closeout lane with three disjoint bounded workers

## Scope and acceptance

Operator asks to tame remaining checkout chaos. Start12 Wake/16 native registered
checkouts. Preserve exact original source and dirty work, including old private
source. Reconcile all linked checkouts into an active retained need, a recoverable
private checkpoint/archive with released checkout, or a precise technical blocker.
Do not merge historical code merely to enable cleanup. Definition of done: exact
before/after inventories, preserved original refs and reviewed dirty bytes,
independent archive readback/integrity, normal retirement of unneeded checkouts,
and one concise retained-needs/custody map. Root primary dirty state stays exact.

## Preservation decision

Historical private/local native source is not newly published. Use independent
owner-only bare repositories as intended private Git custody remotes under user
state, with matching local/archive refs, exact remote readback, no alternates and
standalone integrity verification. This is same-host recoverable custody, not an
off-host backup. Source preservation duplicates Git objects for a concrete recovery
need; Cargo caches/dependencies are not copied as backups. Private archival is not
main integration, implementation acceptance or deployment.

For inactive dirty linked checkouts, review source/docs/synthetic evidence first.
Preserve original branches/HEADs; record exact reviewed current state on a new
private WIP/checkpoint branch, retaining qualification limits. No reset, stash,
discard or forced removal. Do not commit credentials/raw private histories or copy
such data; retain a precise blocker if present. Preserve unique ignored evidence
separately; generated disposable cache need not retain its checkout.

## Ownership and current state

merge_ui reviewed/classified three clean Wake histories, archived privately,
retired413/reconcile419 and handed the archived bootstrap checkout to primary.
Primary reuses that checkout for this documentation lane; retire after merged
custody. Original bootstrap branch and8c406 commit stay intact; old bridge candidate
is paused/superseded by current service architecture, no clock implementation.
merge_core owns eight clean native histories and native dependency/artifact gates.
upgrade_inventory owns eight dirty Wake linked histories; dirty-native followup
remains bounded separately. All ownership is temporary custody work, no operational
control authority. Private workstation paths and raw receipts remain out of Git.

## Non-goals

No provider/model replay, runtime/service/tab changes, build/test campaigns,
credential/history copies, public private-source disclosure, OpenAI pushes,
branch deletion, global prune, force, reset/stash/discard or paidCI. Preserve
installed immutable releases and unrelated sessions. Local Git integrity and
source/readback checks validate archive effects; they do not qualify old code.

## Accepted result and validation

All26 obsolete linked checkouts are accounted for: three clean Wake histories,
eight dirty Wake states, eight clean native histories and seven dirty native
states. The old bootstrap checkout is reused for this closeout, then retires after
exact merged custody. Primary roots remain; no original primary files are edited.
Original branches/HEADs remain exact. Fifteen dirty linked states are preserved as
private WIP/unqualified checkpoints; primary independently read back all56 changed
files from the intended archive and matched their original captured SHA256 values.
No source implementation or original feature ticket is closed by archival.

Both archives are independent owner-only bare stores with no alternates. Matching
archive refs, standalone strict Git integrity and independent fetch/readback passed.
Fresh process/FD/service/installed-prefix and ignored-artifact gates were recorded;
unreadable protected-process scope is disclosed rather than claimed absent. All
ignored outputs were reviewed as disposable generated data, or unique evidence
was preserved by the per-checkout receipts. No builds/runtime qualification ran.

One private recovery index replaces the scattered checkout reminders. It records
original/checkpoint refs, byte verification, artifact disposition and source-only
restore instructions. Private source stays private; original operational scratch
is never executed. Public compact [acceptance](../evidence/plan0261/acceptance.json)
keeps workstation paths and raw historical content out of Git. Final private
closeout records actual inventory after this documentation checkout retires.

Retained needs: Wake primary preserves original dirty work for #420 reconciliation;
native primary remains its main anchor. PR454 source integration and #716 deployment
remain separate programs, not reasons to retain old checkouts. Memory writes are
forbidden absent explicit request; this packet retains canonical evidence instead.
