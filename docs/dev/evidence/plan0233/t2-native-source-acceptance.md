# P233 T2 integrated source acceptance

Issue #630, native commit `7699650e005abe2bcedc138434c59aa95bfbf044`, base
`f986f6ed53d6b324aedbd7e32991e0185eacae14`.

Primary verified the completion marker exists, tracked source is clean, all 19
changed-file hashes match committed objects, and the published patch reconstructs
complete source tree `bd92911d261f37aa1e2f125f8d0a5ccc8f4af0d9` from the exact base
using an isolated Git index. A private Git bundle was created and verified. Source
custody is published in runtime/grok-native-233, separate from installed runtime.

Accepted focused local evidence:

- Native Grok terminal command, native file patch, existing MCP echo and linked
  final continuation PASS; two existing OpenAI command-auth/multi-turn regressions
  PASS. Three selected, 2776 unselected. This exercises the existing native loop.
- API/provider tests 274 PASS, none skipped, followed by affected API library
  clippy with warnings denied. Final stage receipt exit0, no compiler warnings or
  errors. Final API checks include the transparent alias added for lint.
- Remote configuration round-trip 1 PASS, 402 unselected; generated protocol
  comparison byte-equal after retaining the canonical lint header and formatting.
- Fourteen touched Rust files pass rustfmt; diff checks pass. Existing unrelated
  workspace formatting differences were preserved. The five-crate lint stage
  stopped at the corrected API type-complexity diagnostic; no full core/workspace
  lint pass is claimed. Exact commands/environment are in the source manifest.

The initial expected RED rejected the unknown Grok wire at the fixed base. An
actual RED also caught replay of an uncertain POST, corrected by disabling retry
count and retry flags. A first native test compile needed two test-only imports;
those failures are retained. Native behavior passed before the final private
return-type alias; API tests/lint passed afterward. The alias does not alter
native behavior, so an expensive native rebuild was not repeated.

GNU Linux, Rust1.95, dev-small, jobs2, offline dependencies and a shared serialized
cache differ from a complete hosted multi-platform matrix. No paid hosted CI,
package build, native installation/restart, real login or provider call occurred.
T4 model/account selection and joined T8 real-account/package qualification remain
open. This source acceptance does not qualify entitlement, usage, a release or
working-profile effects. Broad review/remediation counters remain zero.
