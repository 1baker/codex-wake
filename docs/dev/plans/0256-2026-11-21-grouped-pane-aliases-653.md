# LOCAL-P256-CONTINUATION | Grouped physical-pane aliases (PR653 port)

State: CLOSED
Owner: root/ecochran76; implementation worker merge_ui
Work item: PR653; LOCAL-P256-CONTINUATION
Branch: fix/grouped-pane-aliases-653
Target: origin/main
Base: 7b9e9d961dac02fb3568595bc053b8e72758fe59
Custody: INTEGRATED; PR728; source 4b4f51ce75f00dd8b51e61a18447f11d9a46883a

## Scope and acceptance

Port PR653's grouped-session physical-pane deduplication and background-painted
empty-composer support onto current main. Retain batched process identity lookup,
explicit private-socket absence semantics, exact client-birth/saved-primary fences,
and modern task/admission behavior. Profile membership recognizes grouped aliases;
ungrouped linked-window indices and distinct physical/process generations remain
separate. Alias serialization and primary selection are deterministic.

Use existing inventory/selector and spawn/refresh/handoff seams. Observe a failing
regression before each implementation slice; run the four focused test modules on
Python3.11/3.12 and a disposable real tmux grouped-session smoke. The smoke uses a
synthetic client identity and proves actual tmux grouping/field parsing, not a
native-provider lifecycle. No model requests, production tabs, credential work,
clock changes, installation, tracker closure, or merge belong to this worker.

## Current state

Inventory, painted-composer and clone-profile recovery failures were reproduced
before correction. Source port is locally validated: 141 focused tests pass on each Python3.11/3.12;
ruff undefined-name checks and whitespace checks pass. One missed-import failure
is retained separately from the final passing runs. The real
isolated tmux smoke passed: two grouped rows become one physical attachment;
both aliases resolve; the isolated server is unreachable after cleanup. Private
full logs and receipt: user state reconcile-status-20261121/pr653. Completion of
this packet means locally validated, committed and remotely verified source;
main integration, original PR653 closure and installation are separate root gates.

Evidence: [port receipt](../evidence/issue0653/port.json).

## Primary acceptance

PR728 merged ae58668788d39e34bbf13228699216af4be9878a; superseded PR653
closed without merging its obsolete base. One fixed-base Standards/Spec review
accepted zero findings. This closes current-main source acceptance only; the
synthetic-client tmux smoke does not prove real-client or fleet deployment.
