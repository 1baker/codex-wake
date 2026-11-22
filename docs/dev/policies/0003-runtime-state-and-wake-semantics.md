# Runtime State And Wake Semantics

## Policy

- Treat wake requests as durable runtime records, not transient prompts.
- Classify runtime material before deciding whether it belongs in git:
  - durable authoritative wake state
  - durable but derived indexes
  - ephemeral caches and logs
  - secrets, credentials, and sensitive transcript content
- Keep tracked repo files separate from user-scoped runtime state unless a plan explicitly makes a fixture or sample part of the product.
- Prefer structured, inspectable state such as JSON, SQLite, or YAML over opaque scheduler state when practical.
- Make state schema changes deliberate and documented.
- Keep secrets, raw credentials, and private transcript bodies out of tracked fixtures and examples.

## Codex Compatibility

- Offer Wake features to stock Codex wherever its standard interfaces support them. Gate advanced Wake Codex behavior on the specific capability it requires.
- For the default wait policy, submit to an idle stock Codex recipient within the wake's dispatch window and recheck busy recipients. Standard queue acceptance can precede execution beyond the deadline. Busy queueing with receiver-enforced expiry requires a qualified peer.

## Wake Record Contract

A wake record should make these fields explicit when applicable:

- stable wake id
- creating agent or session identifier
- creation time
- trigger definition
- earliest wake time or trigger polling policy
- status
- resume payload or retrieval pointer
- evidence path for trigger evaluation
- retry, timeout, and cancellation policy
- retention or cleanup expectation

## Status Semantics

- Use a small explicit status vocabulary.
- Completion, timeout, cancellation, and trigger failure must be distinguishable.
- Do not infer success from the presence of a wake record alone.
- Preserve enough evidence to explain why a wake fired, expired, or was cancelled.
