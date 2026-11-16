# P233 T8 live qualification progress — incomplete

The operator approved one bounded live packet: twelve Grok responses, two OpenAI
worker responses, sixteen local tool calls and fifteen minutes. Qualified start
was 2026-11-15T19:45:25Z; the original deadline remains 20:00:25Z. This is manual
monitoring, not independently enforced external supervision. No allowance reset.

Official Grok 1.0.77 device sign-in succeeded. The pinned official model listing
completed successfully and advertised grok-4.7 as default. Authentication presence
and catalog access do not qualify inference or coding capabilities. No tokens,
verification material, credential files or private working history are copied
into this receipt. Native package hashes were rechecked against all six files.

The first standalone native probe failed before inference because Wake rejected
the official native auth lock's 0644 mode. The credential file remains 0600.
The existing public CLI/private-bearer regression was extended with that actual
lock mode and failed before the fix. Wake now accepts other-user read permission
on the nonsecret synchronization file while retaining owner, regular-file,
no-symlink, inode and flock checks; other-user write permission still fails.
The lock is not chmodded or replaced. Focused auth checks: twelve PASS in 2.123s;
existing catalog check: one PASS in 3.326s; diff check PASS. A private, no-refresh
real native bearer read passed without exposing the value.

A second fresh native probe then failed with `inference request outcome unknown;
automatic replay withheld`. No assistant answer or local coding tool execution
was observed. The resulting tree is held, aggregate usage remains unknown, and
no replay or further paid work is authorized on that tree. Bootstrap auth-command
invocations are not response counts: twelve failed emissions in the first probe
are retained separately, and successful emissions in the second are also retained.
No OpenAI worker inference was dispatched. Current diagnostics suppress HTTP
status for generic failures; a bounded local diagnostic regression is in progress
before any decision about another provider request. Do not infer an HTTP status
or provider outcome from this generic message.

Native source/package remains at the prior qualified revision until that pending
diagnostic change is validated. The Wake auth fix changes runtime code, so the
previous wheel's auth acceptance must be rerun against a newly identified wheel;
unaffected UID1017 native package gates remain historical evidence, not proof of
a changed native package. T8 #639 and parent #628 remain OPEN. Seven children are
closed; broad review and post-review remediation counters remain zero. No working
profile installation, restart, deployment, provider logout or automatic login retry.

Private execution receipts are under the existing p233-t8 state directory;
raw synthetic histories and process/job identifiers remain workstation-local.

## Diagnostic source accepted; changed package pending

Native commit `df4a89bbd7df49691df280674130e3f5e8eedc7e` retains numeric HTTP
status for generic HTTP failures without provider bodies, headers, URLs or token
material. Unknown outcome and no automatic replay remain explicit. Local RED
compiled successfully and failed the missing-status assertion; GREEN passed all
four focused Grok client cases in 32.688s including compilation, 0.20s execution.
The exact patch reconstructs native tree
`bf1976b51b6f5a270696d4a9eb509eaad3463dce`; source hashes and private bundle digest
are retained in `runtime/grok-native-233/t8-source-manifest.json`.

The Wake auth fix was built from `a8a9e0c65cc7ab1c456ec787484b0467921eb8f1` into
wheel SHA256 `5d94731b6e5d00d8b69e41db12ca88f2b090996c1c546c4bc323922bf7d0ddc9`.
Installed under the existing isolated UID1017 prefix, all 336 module/resource
files match that exact wheel. Installed auth/catalog13 PASS7.253s and usage16
PASS1.057s. Initial installer invocation failed due to an inaccessible working
checkout; checks against the still-old installation correctly failed and are
retained. Corrected installation used the same declared environment, offline,
from an accessible directory with config discovery disabled. No working-profile
installation occurred.

The existing worker owns one causal complete-package rebuild and UID1017
runtime requalification using existing fixtures, preserving the prior immutable
package and rollback. No further provider request or replay is scheduled.
These local checks qualify the diagnostic change, not Grok inference readiness.

## Changed package requalified and verified by primary

The complete diagnostic package at native `df4a89bbd7` has entrypoint SHA256
`e69b170edb1ab87d7f398796746833bc43538bca34013c9420b6a92b0a0c8d6a` and content
digest `5443b8cf21ca6be7c6b613916b91f30bc8658e3d7b155934eaaacedeb4596c46`.
The original package and rollback remain preserved. Its immutable portable
inventory and job results are in `runtime/grok-native-233/t8-http-package-manifest.json`.

One serialized build passed in 1114.847s. Required UID1017 gates passed:
upgrade/history/multiclient/reconnect/rollback88.068s, failed-start repair and
rollback88.960s, saved-history22.856s, and private ownership/refusal10.102s.
Primary independently verified all six source-package hashes, 34 isolated-user
package/receipt file hashes, and all five terminal job results. A fresh OS
process readback matched the 13 protected persistent processes; no owned process
remained. Worker cache/artifact custody returned without repository edits.
The previously verified changed Wake wheel and its installed checks are reused.

This qualifies the changed package in the isolated environment, not live Grok
inference. The earlier manual live window expired at 20:00:25Z. No later provider
request, automatic replay, login, refresh or allowance reset was performed.
The next proposed gate is one new text-only diagnostic request using this exact
package, at most one Grok inference request, zero OpenAI responses, zero tool
calls and two minutes, subject to explicit operator authorization. It retains
prior unknown usage and the held tree; it does not resume or reset them. Auth
must validate without refresh before dispatch. Any renewed uncertainty holds.
T8 and parent remain OPEN, with broad review/remediation counters zero.

## One authorized text-only diagnostic: HTTP 426, held

The operator approved one fresh text-only request, capped at two minutes with
no tools or retries. All six exact package hashes and account-bound bearer
expiry were checked before dispatch, without refresh. The standalone fresh
session exited in 3.786s with HTTP426 and explicit unknown outcome/no replay.
No coding tool, worker or assistant completion was observed. Aggregate usage
remains unknown/null. The previous held histories are untouched; this result
neither resets their usage nor authorizes another request.

Official sampler source at revision
`2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8` sends
[`x-grok-client-version` for proxy version gating](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-sampler/src/client.rs#L524).
The native adapter currently omits that header. This is a concrete request
contract gap and the leading explanation for HTTP426; a live correction has
not been demonstrated. A focused regression extends the existing request test
to require an explicit reviewed wire-compatibility version and a distinct
`codex-wake-native` client identifier. The adapter must not claim to execute
the official Grok CLI or inherit ambient OpenAI headers. Local RED is pending;
no production header change or additional live request has been made.

## Version header source accepted; package qualification pending

Native `b77a743f7e07edbc5e2f7c30d4e20a56ea4f3df8` adds an explicit reviewed
Grok Build wire-compatibility profile (`1.0.77`) and the distinct
`codex-wake-native` client identifier. Codex product version/User-Agent remains
unchanged, and ambient provider headers are still excluded. This profile matches
the pinned official auth client used in this qualification; it is not a claim
that Codex runs the official Grok CLI. Profile changes require renewed protocol,
package and real-account qualification.

The existing native request/continuation test failed before the fix because the
version header was absent (three other cases passed). With the fix, all four
focused client cases passed in 20.469s including compilation, 0.21s execution.
Exact source patch/tree/file hashes and bundle digest are retained in
`runtime/grok-native-233/t8-version-header-source-manifest.json`. This proves
local header construction, not the live HTTP426 hypothesis.

The existing worker owns one new complete-package build and required UID1017
qualification, with the prior packages and rollback preserved. No additional
live request, retry, login or refresh is authorized. T8 remains OPEN.

## Header-enabled complete package accepted; live gate remains pending

The complete package at native `b77a743f7e` is qualified under isolated UID1017.
Entrypoint SHA256 is
`fc9439b45efc5e1005911d54260b0bc47e0e7b4842ba8bfcecf07d15a0a65f74`;
content digest is
`cdd772c6ace5f248452530b1ad3454d0abb3c956eaa25da112b74e9340715174`.
Exact inventory and job/receipt hashes are retained in
`runtime/grok-native-233/t8-version-header-package-manifest.json`.

One complete build passed881.851s. UID1017 upgrade/history/multiclient/reconnect/
rollback passed107.393s; failed-start repair/rollback108.029s; saved-history20.362s;
private ownership/refusal8.257s. Primary independently verified all six source
and isolated package hashes, 28 additional installed-package/receipt hashes,
and all five terminal jobs with their receipt digests. A fresh OS census showed
the original13 protected persistent processes and no owned leftovers. Prior
packages and complete rollback remain preserved; worker writer leases returned.
The unchanged Wake runtime's installed336 hashes/auth13+usage16 acceptance is
reused, rather than repeated.

This acceptance does not establish live HTTP426 resolution. The one-request
live diagnostic authorization has been consumed, with its held session retained.
A concrete fresh text-only diagnostic is prepared against this exact package:
one Grok inference request, zero OpenAI requests, zero tools, 120seconds,
no retry and no refresh, after explicit operator approval and fresh account/expiry
and package-hash checks. No additional live request is scheduled or dispatched.
T8 #639 and parent #628 remain OPEN; broad review/remediation counters remain0.

## Header-enabled live diagnostic: stream reached; usage held

The operator approved one fresh text-only request against the qualified header
package. It exited in4.597s without HTTP426, reached a Grok stream reporting
`grok-4.7-build`, then held on inconsistent usage. No tools, retries or refresh
occurred. There is still no accepted completion or qualified aggregate usage;
unknown remains null, and the held session is not replayed. The one-request
approval is consumed. This is evidence that the request progressed beyond the
prior version-gating failure, not completed coding or account readiness.

The displayed OpenAI cyber/fallback warning is not independent Grok moderation
evidence: the current Core `maybe_warn_on_server_model_mismatch` constructs that
specific warning and `HighRiskCyberActivity` reason for every differing server
model label. The Grok adapter emits the observed model as `ServerModel`, reaching
that shared path. An existing public Grok worker test is being extended with an
observed model alias to reproduce the false classification. Existing OpenAI
moderation behavior must remain intact; real provider refusals remain held.

The inconsistent-usage error currently omits the numeric counts needed to assess
the provider accounting contract. A small existing API-stream test extension
requires numeric-only diagnostic evidence while still rejecting inconsistent
usage and omitting opaque provider data. No accounting rule is relaxed and no
missing counts are invented. The exact provider counts were not retained by the
current diagnostic; their relationship remains unknown. Local RED checks are
running before production changes, with no additional live request authorized.

## Offline accounting contract evidence

The [official xAI Chat Completions reference](https://docs.x.ai/developers/rest-api-reference/inference/chat-completions)
contains a successful example with prompt32, completion9, reasoning94 and
reported total135; cached6 is a subset of prompt32. The current adapter rejects
this documented example because it checks32+9 against135 without accounting for
separately reported reasoning. This supplies an independent expected result for
a public native-stream regression without another paid probe. A corresponding
canonical representation would retain input32 (including cached6), output103
(including reasoning94), total135. Missing, negative, overflowing or otherwise
unreconciled counts must continue to hold; the reported total must reconcile to
explicit observed fields, not an invented residual. The actual previous live
usage numbers remain unknown, so this does not prove that precise live cause.

Current Cargo job remains in progress; native sources stay frozen until its
terminal result. The next accounting regression should exercise public
`GrokClient` stream events using the documented example, keeping the existing
harness. The temporary private-State numeric diagnostic test is not the desired
maintained public seam. Existing held histories and no-further-live-call boundary
remain unchanged.

## Demonstrated regressions; focused correction validation pending

The previous exact RED job compiled successfully, then reproduced both public
Grok worker cases emitting the false OpenAI cyber classification. It also
reproduced missing numeric diagnostics at a temporary internal seam; that new
internal test was removed in favor of a maintained public `GrokClient` stream
regression using xAI's independent documented32/9/94/135 example. The public
regression compiled and failed because no canonical completion was produced.
All original stream-unit coverage remains retained.

Current source normalizes separately reported reasoning only when explicit
nonnegative fields reconcile with the reported total. Already-inclusive output
is retained without double charging; cached input remains a bounded subset of
full input. Bad totals, overflow and invalid details still hold. Errors include
numeric counts only, excluding arbitrary provider metadata. A Grok-only model
mismatch warning reports the requested and observed labels without inventing a
moderation reason; the existing OpenAI branch remains unchanged.

Focused GREEN is pending: public Grok client cases, existing stream-unit cases,
existing mixed-worker cases with documented reasoning/cache counts in canonical
history, and existing OpenAI safety-routing regressions. New disposable canonical
captures will feed the unchanged Wake usage observer after success; a missing
child usage record must remain unknown/null. No package or live readiness is
claimed before those results. No new paid request, login, refresh or replay.

## Consolidated usage/warning source accepted

Native `212d798546aabffe65129464a61905e810fed248`, tree
`0ec65313faf6a60f74149da89e85be7f7a5ebb6f`, contains the four-file correction.
Exact source hashes, reconstructible patch and private bundle digest are in
`runtime/grok-native-233/t8-usage-routing-source-manifest.json`. Tested source
fingerprints match the committed files. Protocol/app-server/SDK schemas are
unchanged, so no generation is required.

The focused GREEN job passed5 public client checks,4 existing stream checks,
and11 Core checks including unchanged OpenAI safety routing,1043.295s total.
Test execution was0.85s,0.00s and3.500s respectively; compilation dominated.
Actual native captures joined through Wake's public usage observer qualify285
cache-inclusive tokens for Grok→OpenAI and405 for Grok→Grok, with child-owned
records present. Removing child numeric usage from copies makes both observations
unknown/null with `response_usage_missing`. Original captures remain retained.
This verifies accounting across the native/Wake boundary, not real-provider
inference, tools or billing. Historical live unknown totals remain unknown.

One complete package build and isolated UID1017 runtime qualification is now
assigned to the existing worker for these consolidated changes. Earlier complete
packages/rollback are preserved. No further live request, login, refresh or replay
is authorized, and T8/parent remain OPEN with reserved review/remediation0.

## Consolidated complete package accepted; remaining live packet prepared

Native source `212d798546` produced complete package entrypoint SHA256
`bdc780c81a0f62619b5b38037963e2f603e9b902c82211c37251bcad05ef1a8a` and content
digest `6172ec680e095f56dd35b476f3d2eec9a5f0af497f90c655684c1dfb82fb1cd5`.
Exact inventory and job receipts are retained in
`runtime/grok-native-233/t8-usage-routing-package-manifest.json`.

One build passed877.387s; required UID1017 upgrade/history/multiclient/reconnect/
rollback102.699s, failed-start repair/rollback102.221s, saved-history19.730s and
private ownership/refusal9.638s passed. Primary independently verified all six
source hashes,34 isolated-user package/receipt hashes, all five terminal jobs,
and matching native source. Fresh OS readback showed only the original13
protected processes. Prior packages and complete rollback remain preserved.
Unchanged installed Wake runtime checks are reused. A fresh private Grok auth
read remains valid without refresh, but does not qualify entitlement/inference.

The next proposed packet covers the remaining real-account acceptance in one
bounded run: at most12 Grok responses,2 OpenAI worker responses,16 local tool
calls and15 minutes, stopping at the first failure or uncertain accounting.
Use only the synthetic coding workspace and local MCP echo, then admitted native
model selection, mixed workers/linked handoff, known usage and a final owned
Stop/unknown-usage hold. Verify supported launch isolation and reuse current
OpenAI auth in place; do not copy credentials or private history, replace a
daemon, or alter working profiles. At most one reviewed official metadata refresh
is proposed if actually required; never repeat an uncertain attempt or retry
login. Qualified metadata reads and independent public qualification receipts
remain separate from inference evidence. Prior held trees/unknown usage are
retained; this packet creates no reset or assertion that they cost zero.
No live request is scheduled or authorized until the operator approves the packet.
T8 #639 and parent #628 remain OPEN with reserved review/remediation0.

## Approved live packet: coding PASS, selected-turn gate held

The operator approved the prepared12Grok/2OpenAI/16tool/15minute packet. Exact
native package hashes were checked, and a new synthetic coding workspace/home
used existing auth by reference. The native coding turn completed successfully:
file contents were read, the negative-count bug was fixed through the native
terminal tool, all three unittests passed, and local MCP echo returned the exact
probe. Four local tool calls and four Grok responses were observed. Native
`apply_patch` was requested but the agent used a terminal file edit instead;
this proves file editing through the native tool loop, not a distinct apply_patch
invocation. No worker or external business-data task was performed.

Wake's public observer qualified all four actual response records at40555
cache-inclusive tokens,28779 fresh and11776 cached input. These are this packet's
known charges; earlier held histories remain unknown and are not counted as zero.
Official authenticated model metadata supplied the actual grok-4.7 identifier,
label and256000 context window. Only demonstrated text/streaming/terminal/file
editing/MCP capability evidence was admitted to a bound qualification receipt,
and an explicit default was set. Actual native model/list returned the qualified
account/model snapshot alongside normal OpenAI models.

The next selected-turn submission was rejected before inference with
`selected account identity unavailable`. Primary diagnosed an error in the private
qualification driver: it sent an unsupported top-level `inferenceSelection` field
instead of the documented existing `config.inference_selection` override. The
initial short-lived client had also disconnected before an empty session could
materialize; its rejected submission was not retried as inference. Corrected
read-only model/list and thread/start using the supported config override passed,
without submitting another turn. No product source change or package rebuild is
needed for that driver correction.

The packet stopped at this failed admission as agreed. No OpenAI worker response,
linked handoff or final Stop proof was obtained, and no inference was replayed.
Owned qualification app-server processes exited; production daemons/profiles
were not replaced. No credential/history copy, login retry, refresh or provider
logout occurred. The budget receipt retains4/12 Grok responses and4/16 tools used,
0/2 OpenAI responses, original monotonic deadline and all prior unknown usage.
Continuation requires explicit operator direction under the remaining allocation;
no automatic renewal/reset is scheduled. T8 and parent remain OPEN,7/8 children
closed, broad review/remediation counters0.


## Continuing qualification: real mixed-worker defect found

The operator explicitly removed repeated time-window approval gates and directed
qualification to continue. Original numeric ceilings, cumulative known spend,
and every earlier unknown history remain retained. This supersedes the earlier
15-minute continuation hold; working-profile installation remains outside scope.

The official credential had expired. The approved single official metadata
refresh passed, retained the exact account binding, and a no-refresh private read
confirmed a current bearer. Fresh official model metadata was read. The prior
coding observation was explicitly re-admitted for the unchanged exact native
package/account with its original observation time; this is not a new coding run.

The corrected persistent native WebSocket used `config.inference_selection`.
A real Grok parent spawned an OpenAI worker with normal `spawn_agent`, preserving
provider and parent/session attribution. The child failed: its plain task text
was wrapped in an `encrypted_content` item, and OpenAI returned HTTP400
`invalid_encrypted_content`. The parent then held further work with
`provider_request_unobserved`. No uncertain request was replayed.

The Grok stream normalizer omits `encrypted_function_args`; the existing
collaboration router requires an explicitly empty list to identify plaintext
message arguments. A focused regression now requires that marker through the
public Grok client. Production source is unchanged pending the local failure.
The exact retained CargoSignal job is `job-20261116T013102Z-632a21f13a16`, with
`dev-small`, two jobs, offline/locked inputs and zero retries. It currently waits
for another task's existing build to release the shared Cargo artifact lock;
no duplicate build was launched.

The new root has one known response of63315 cache-inclusive tokens. Combined
with the earlier coding run this is103870 known tokens, **not** a qualified
worker-tree total. One OpenAI child request failed without a numeric completion.
Wake's public tree observer correctly reports unknown/null with
`provider_completion_unconfirmed`; earlier unknown usage remains retained.
T8 and parent stay OPEN,7/8 children closed, broad review/remediation0.


The regression compiled and failed on the expected `Null` versus `Array []`
marker assertion (0.09s test execution). A one-field Grok-only fix now supplies
`encrypted_function_args: []`. The next exact job,
`job-20261116T013931Z-cd82e54c799c`, has passed all five Grok API client checks
and four SSE checks; its Core worker/OpenAI safety selection remains building.
The existing worker test now also covers MultiAgentV2 and inspects the actual
OpenAI request for plaintext task content. This is pending validation, not a
passing live worker claim. A persistent completion wake is verified armed with
both native harness and monitor ready. No further provider requests were made.


On completion, `013931` reported API5/SSE4 and11 of12 Core checks passing.
The new MultiAgentV2 assertion expected a bare task string, but native
`AgentMessage::into_communication` correctly renders one attributed plaintext
NEW_TASK envelope with task name, sender and payload. This is an assertion
error, not evidence of another product defect. The assertion now expects that
exact envelope and still rejects encrypted content. Production code is unchanged
from the one-field fix. The retained follow-up `job-20261116T015131Z-ae24ab977b17`
runs the same12 Core checks with zero retries and a new synthetic-history capture
directory. Its result remains pending; no live request has been repeated.


The corrected run passed all12 Core checks in4.466s (730.153s total including
compilation). Together with unchanged API5/SSE4 results this validates21 focused
checks. Actual captured native histories join through Wake at285 tokens for
Grok→OpenAI,405 for inherited Grok and285 for MultiAgentV2 Grok→OpenAI; each has
an actual child numeric record. Every adverse missing-child copy returns
unknown/null. These are local synthetic-provider checks, not live acceptance.

Native source23bc20474a24e7afbb59a02e0e070017ef58080a, tree
3f0e6e7e99b0a463e466f744db396e3b80e03f2c is preserved in the additive full-index
zero-context patch and source manifest. Applying to exact212d reconstructs that
tree; the private incremental bundle verifies. Stable rustfmt followed validation
and made formatting-only changes; its existing nightly imports warnings remain.
No public schema shape changed. The previous212d package remains preserved and
qualified for its source; the new source requires its own exact package gates.

The live driver also retained a32k fixture context override although actual
metadata admits256k and its first request reported62556 input tokens. The next
disposable driver will use the admitted context window; this is a driver
correction, not an established cause of the earlier held parent or a production
fix. No failed inference is replayed. T8 and parent remain OPEN.


## Exact plaintext package accepted; real OpenAI child completes

All five package/runtime jobs passed for native23bc/tree3f0e and entrypoint
e9943677786cbb80a149ef22003bdbfbae105f6423f8b7db7d5656d1b81fe54d.
Primary independently checked six source package files,30 UID1017 candidate,
installed and rollback files, two runtime receipt hashes and all five terminal
job receipts. Installed upgrade, rollback, saved history, multi-client/ownership
and failed-start gates pass. Existing Wake runtime/wheel qualification is reused.
Worker leases are explicitly returned. No working installation was changed.

The historical13-process snapshot cannot serve as a current census: all13
recorded start times exceed current boot uptime and their PIDs are absent.
Primary retains that gap and does not claim preservation across reboot. Fresh
UID1017 census is empty, with no owned or unattributed processes; current runtime
case evidence remains valid. The worker's original held receipt is unchanged.

Using the exact new package, current no-refresh auth and the admitted256k context
window, a real Grok parent spawned a normal OpenAI worker. The child completed
`OPENAI_WORKER_OK` with its own numeric usage record17764. Three Grok responses
reported67819,68720 and68786 tokens. The parent made two malformed float timeout
wait calls and then held upon intake of the child's plaintext completion message.
Grok request conversion currently lacks `ResponseItem::AgentMessage` handling;
this is independently visible in source. No inference was replayed. The public
Wake observer retains unknown/null `provider_completion_unconfirmed` for this
tree. Known numeric records sum326959 across runs, not a qualified full total;
older unknown histories and original cumulative counts remain retained.

The existing public Grok client continuation test now includes an attributed
plaintext child notification and requires it to reach the request as explicitly
untrusted user content. Exact local RED job `job-20261116T023456Z-f9a33f3ceba9`
is pending; production source is unchanged while that failure is demonstrated.
No further live call, login or refresh occurred. T8 and parent remain OPEN.


The public continuation regression compiled and reproduced the exact unsupported
history rejection in `job-20261116T023456Z-f9a33f3ceba9`. Native request conversion
now admits only wholly plaintext agent messages, preserves sender and recipient,
and labels the content explicitly untrusted at user role. Mixed plaintext and
ciphertext messages remain rejected before HTTP; no provider-private data is
forwarded. The focused API5/SSE4 checks pass in
`job-20261116T023855Z-e409c6803175` (40.594s total,0.38s client execution). Unchanged
Core12 results are reused; no Core/schema surface changed in this delta.

Nativeee0e0b82ff88a3060d035782229931e8f9484ee9/tree
034e4da995a9e0b062d09f89a58d8a8243ac49b7 has exact additive patch reconstruction
and verified private bundle custody. The new source still needs its own package
qualification. This is source acceptance, not repaired live-parent acceptance.
Cumulative counters retain8/12 completed Grok responses,1/2 completed OpenAI worker
responses plus the earlier failed HTTP400 attempt with unconfirmed usage,8/16
tools and one official refresh. No historical unknown charge is zeroed.


## Exact notification package and real mixed-worker accounting PASS

Nativeee0e/tree034e package entrypoint
99447ea05fae83235988bbe37c11689231a5c061ff5b1464751f2c0b039ed03e passed all five
isolated runtime gates. A fresh preflight process baseline was captured before
fixtures on the current boot; expected/protected/owned/unattributed counts are
all0 at final same-boot verification. The earlier13-process snapshot is preserved
separately. Primary independently verified six source package files,30 UID files,
two actual runtime receipt hashes and all five terminal job receipts. The initial
failed-start fixture exceeded the UNIX socket path bound (109bytes); its failed
receipt is retained, and a shorter private fixture label passed without source
change or rebuild. Previous packages and rollback remain intact.

The real normal mixed-worker workflow now completes: parent `MIXED_WORKER_OK`,
OpenAI child `OPENAI_WORKER_OK`. Wake's public observer qualifies the actual
parent/child tree at223610 cache-inclusive tokens (143738 fresh,79872 cached),
using four actual numeric response records. This is real-account evidence.
Older failed histories remain unknown and are not reset or folded in as zero.

A subsequent public provider handoff rejected the child's completed plaintext
notification because the portable-context converter had no AgentMessage arm.
It held locally before any provider request. No inference was replayed, and the
owned qualification server exited. Positive handoff and final Stop remain open.
A minimal portable-context fix now retains only wholly plaintext notifications
as bounded, attributed, explicitly untrusted recent public context, not objective
authority. Opaque and credential-bearing content stays held. The actual public
failure serves as RED; a redundant standalone RED compile was intentionally
stopped while awaiting the shared artifact lock (retained exit143, not a behavior
failure). Exact `job-20261116T032223Z-2713407d75fe` runs one focused Core unit for
attribution, unchanged constraints, roundtrip context and ciphertext rejection.
No passing source or package claim is made for this pending fix.

Cumulative counters retain11/12 completed Grok responses,2/2 completed OpenAI
worker responses plus the earlier failed HTTP400 attempt with unknown usage,
10/16 tools and one refresh. The known numeric sum550569 is not a qualified
aggregate campaign total. T8 and parent remain OPEN,7/8 children closed, with
broad review/remediation counters0.


The focused portable-worker regression passed in
`job-20261116T032223Z-2713407d75fe` (784.095s including compilation,0.00s test).
Native1a2fb1df4cefdef9782cd82d8cceef8c70e1c05c/tree
fc3e28d007f1b9925b3f768d3e6d894f491d2ec3 retains attributed plaintext worker
notifications as bounded untrusted recent context, preserves constraints through
a roundtrip and rejects ciphertext. One accidentally duplicated immutable-context
assertion block was removed after GREEN; the same assertions remain once and
production did not change after validation. Exact additive patch reconstruction
and the private bundle verify. No public schema shape changed.
The source fix awaits one causal exact package/UID1017 qualification before the
remaining live handoff and Stop checks. Actual mixed-worker success and all older
unknown histories remain preserved. No new provider request was issued.


Exact native1a2fb1 complete package passed all five isolated UID1017 gates; primary independently verified six source files, thirty UID candidate/installed/rollback hashes, two runtime receipts and five terminal jobs. Current same-boot process census was zero before and after. No working-profile activation occurred.

Real native Grok→OpenAI→Grok linked handoff preserved session identity, parent/fork lineage, permissions and bounded operator-authored inert context. No OpenAI inference was issued. One final Grok stream was locally interrupted after an actual text delta; native state is interrupted/held, completion unconfirmed and replay forbidden. This proves local Stop, not provider-side cancellation. Original unknown histories and cumulative allowance remain retained.

The final public Wake observer exposed a real accounting defect: SQLite omits provider-fork edges, so it returned qualified zero for an interrupted descendant. The observer now uses private native continuation journals only as locators and verifies canonical rollout session/parent/fork identity. Missing ready successors, conflicting lineage and unconfirmed completion hold usage unknown; staged successors that have not materialized preserve current-source accounting. The public regression demonstrated qualified0 versus unknown; the corrected actual captured Stop reports unknown/null/provider_completion_unconfirmed. Focused local `PYTHONPATH=src:tests python -m unittest test_goal_usage test_self_limits test_goal_supervision -q`:62 PASS,19.354s, no retries. No further provider requests were issued. The updated Wake wheel still requires isolated installed qualification; native source/package gates remain causally unchanged. T8 and parent stay OPEN,7/8 children closed; broad review/remediation0.
