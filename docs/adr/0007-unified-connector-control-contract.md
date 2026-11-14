# One connector control contract with distinct resource identities

Operator accepted a shared hierarchical resource/action contract for CLI, API and
MCP so external connectors can manage the same Byobu environment without learning
separate control models. Preserve physical session/tab/pane identities and explicit
conversation/runtime/account/agent-family links, rather than treating "session"
as interchangeable across them; compatibility entry points retain existing clients.

Structured harness actions and direct terminal input remain separate advertised
capabilities and permissions. This retains native outcomes where available while
allowing explicit terminal control elsewhere, at the cost of exposing route-specific
limits; unsupported structured operations never silently fall back to keystrokes.
Specification derives from Plan0234's19accepted interview decisions; implementation
and live effects are separate work.
