# Native Grok inference belongs in Codex's provider boundary

Accepted during the P233 design interview, 2026-11-14. Codex owns inference,
tools, conversation history and mixed-provider worker management; Wake coordinates
accounts, authentication and runtime control. A Grok-specific compatibility adapter
belongs at that native provider boundary, rather than introducing a second agent
loop or a general translation gateway: this increases native provider maintenance
but keeps tool execution, interruption and history semantics under one harness.

Existing Grok account sign-in leads the first release. Reuse the official provider
session with coordinated refresh and shared login/logout semantics, rather than
creating independent credential stores or per-worker copies. This reduces repeated
sign-in but requires qualifying concurrent refresh, rotation and revocation before
claiming safe shared operation. API-key access remains an explicitly selected
alternative; there is no silent authentication or billing fallback.

A cross-provider change creates an automatic linked continuation carrying portable
messages and tool results; original history and provider-specific opaque state
remain attributable to the source. This favors explicit provenance and reliable
resume over pretending provider-private inference state is interchangeable.

Source and open decisions: [P233](../dev/plans/0233-2026-11-14-grok-in-codex-design.md).
