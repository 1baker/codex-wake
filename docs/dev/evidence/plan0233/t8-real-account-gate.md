# P233 T8 real-account gate — not executed

The exact source/package and isolated acceptance packet is in
`t8-isolated-package-acceptance.md`. T8 #639 remains OPEN. No credential presence,
model metadata, successful package build or localhost fixture qualifies a real
account. Primary retains login, refresh, provider inference and revocation effect
authority. This packet authorizes none of those effects by itself.

## Required identities before dispatch

1. Select the operator's exact Grok account ID and label, official executable and
   owned native auth path. Reinspect/hash the official executable before use;
   historical T1 version/source review is not current interoperability proof.
   The historical device flow50843 ended without sign-in and must not be blindly
   retried. Current sanitized default-store inspection is unavailable/
   `native_auth_missing`, with logout unconfirmed and entitlement/inference
   unverified. No credential was printed or copied.
2. Choose an isolated account/native home and bounded disposable workspace. The
   UID1017 prepared workspace contains `TASK.md`, `totals.py` and three standard
   unittest cases, with no personal data or credentials. Its task is a small
   negative-count validation fix, native terminal/file editing and an MCP echo.
   A different approved disposable home needs equivalent public fixture data,
   never copied working credentials/history. Independent OpenAI readiness is also
   required in the chosen home for real mixed-provider proof; do not assume it.
3. Pin native package entrypoint SHA
   `a54f0739611354fcdd535f5a6a391197c4c0fe92615ade9f4bfd6bb725713792`
   and all six package-file hashes in `runtime/grok-native-233/t8-package-manifest.json`.
   Pin the candidate Wake wheel SHA
   `48675871d83010a29f6499a84f0a17a4d051e8470642116fef7b0ad7351d1ae0`.
   The staged existing `test_stdio_server` MCP echo helper SHA is
   `fda8fcef03ac2ad123602d2f056c850a10a47aed5e33d1501ee39662354f2ef3`;
   it is a qualification resource, not an extra package executable.
4. Record the original numeric remaining allowance and permissions before any
   paid request. Proposed additional ceilings: at most one explicitly approved
   device flow, one reviewed metadata refresh if needed, twelve Grok responses,
   two OpenAI worker responses, sixteen local tool calls and fifteen minutes.
   These ceilings do not grant, raise or reset an allowance. Use stricter existing
   limits and hold if attribution or budget cannot survive.

## Bounded primary workflow

- With operator participation and the exact official executable/auth-path binding,
  use the installed Wake CLI: `grok auth login --executable OFFICIAL
  --auth-path AUTH_PATH`. This command has no account positional argument.
  After successful official sign-in creates the native store, bind that existing
  identity with `grok auth register ACCOUNT --label LABEL --auth-path AUTH_PATH
  --executable OFFICIAL`. Registration cannot precede a missing native store.
  Wake invokes official device auth; keep verification data private. Use sanitized
  status and the reviewed native refresh owner. Do not add API-key fallback or
  copy tokens. The private bearer command remains account/revision pinned:
  `codex-wake --wake-root ROOT grok auth token ACCOUNT
  --expected-account-revision REV`; its stdout goes only to native command-auth.
- Obtain the actual entitled model ID and metadata through the reviewed official
  account path; do not guess a model from synthetic fixture names. Import metadata
  with `grok models import ACCOUNT --metadata FILE`. This remains unverified.
- Run only an explicitly authorized prequalification native probe through the
  official Grok-specific transport and existing tool loop. Verify actual streamed
  text, file edit, terminal result and local MCP echo. No separate Grok CLI worker,
  general proxy or fabricated response is acceptable evidence. Unsupported
  optional tools remain disabled individually; a required coding capability
  failure blocks readiness.
- Admit only evidence actually obtained. The existing operator qualification
  receipt has `schema:1`, attributable `source`, `account`, `account_revision`,
  `catalog_revision`, `model`, qualified-time `issued_at`/`expires_at`, and observed
  `entitlement`, `inference`, `capabilities` (`text`, `streaming`, `terminal`,
  `file_editing`, `mcp`). Booleans are results, not defaults. Then use
  `grok models qualify ACCOUNT --receipt FILE`, explicitly set
  `grok models default ACCOUNT MODEL`, and read the native `model/list` choice.
- Use that actual native selection snapshot through the normal picker/app-server
  pathway. Verify exact label/account/model/source revisions in canonical session
  and response usage records. Run a real Grok parent/native OpenAI worker/Grok
  continuation within the same original allowance and permissions. Provider/
  account changes stage at a safe boundary and create linked successors carrying
  bounded objective, constraints and completed tool results. Source opaque history
  stays retained; uncertain actions are never replayed.
- Verify known completed usage attribution before the final Stop case. Stop an
  accepted bounded Grok turn last. Verify no further owned local tool scheduling,
  explicit provider-completion/usage uncertainty, and held resume without replay
  or a fresh budget. Unknown aggregate usage must remain null, never zero. Do not
  issue more paid work on that uncertain tree.
- Any adverse revocation must target only an explicitly approved isolated account
  registration with the exact current target. No working-account/provider logout
  is part of this gate. Local registration revocation does not prove provider
  cancellation/logout. Preserve the original cumulative allowance and unrelated
  OpenAI/account sessions.

Retain exact native/Wake/official-CLI identities, qualified time, account/model
binding revisions, public operation IDs, actual tool/worker/continuation lineage,
known/unknown usage and final owned-process census. No tokens, auth files or raw
private working histories belong in evidence. Primary must verify those results
before completing T8 or closing #639. Broad review/remediation counters stay zero
until all eight children close; later accepted remediation requires causal package
requalification before any working-profile installation.
