# P241 final review and bounded remediation

One review run, frozen HEAD `fe449f35c1b812a0d674c7ed3a13dc832a0434e6`
against `882aae8007e71cc2641c66a742e340e6cf007310` using
`git diff 882aae8007e71cc2641c66a742e340e6cf007310...HEAD`.
Independent Standards and Spec reviewers used the same packet; root adjudicated
all candidates. No second review run occurred.

## Standards

- **blocking P2, resolved:** continuity acceptance reused `result.json`, risking
  loss of earlier failure evidence. New runs exclusively reserve a fresh
  destination before discovery or live effects; same-run checkpoints may update
  only that reserved receipt. Existing paths are refused. Public CLI regression
  was red before implementation and green after it, preserving existing bytes
  and rejecting the destination before live configuration is loaded.
- **nonblocking_backlog P3:** repeated native websocket correlation code in
  small opt-in acceptance scripts. This is a maintenance heuristic, not an
  observed product failure. No generalized helper/framework was introduced;
  consolidation remains outside this bounded acceptance task.

## Spec

- **blocking P2, resolved:** restricted-read proof only checked successful
  snapshot status. The deployed dev34 follow-up now asserts the conversation-only
  grant exposes no terminal resource collections, rejects target content without
  `content.observe`, and rejects an out-of-target read even with content scope.
  Native queue remains empty; temporary grants revoked, owned thread archived,
  protected operator grants/config unchanged. Evidence is appended to the
  existing connector-permissions README; no provider prompt was executed.
- **blocking P2, resolved:** existing ChatGPT final readback was missing from
  the frozen packet. A single fresh read-only request through the unchanged
  existing connection returned `completed`, `owner_observed`, original turn ID
  and `round-trip confirmed`. The latest completed turn visibly records tool
  activity. See [client evidence](0241-chatgpt-final-readback.md). The UI does not
  expose the raw RPC payload; no raw-call audit or payload is fabricated.

Accepted findings: Standards one resolved blocker and one nonblocking maintenance
item (highest P2); Spec two resolved blockers (highest P2). No blocking finding
remains. Exactly one bounded TDD remediation pass addressed the accepted blockers;
no new review loop or fixture platform was added.

Validation: the receipt CLI regression failed before the change (unsupported
receipt contract), then passed after exclusive reservation. Final local selected
presubmit: 107 tests PASS in43.533s, Python3.12/Linux; pinned ruff0.14.2 undefined
names, compileall, policy wiring and diff checks pass. This is a selected
presubmit, not the comprehensive suite or hosted Python3.11 matrix. Hosted CI
skipped under the repository cost policy. Product source/package remains the
qualified deployed dev34; remediation changes acceptance code/evidence only.
