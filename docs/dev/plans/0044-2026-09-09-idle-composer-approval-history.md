# Idle composer versus historical approval text

Scope: repair transcript-word false positives in tmux wake dispatch. Non-goals:
approval bypass, browser changes, new wake schemas, or broad UI support.

Cause: the entire captured pane was searched for approval words. Historical
output and the detector's own error could indefinitely block an idle composer.

Acceptance: recognize the bottom Codex composer plus context footer; ignore
historical words only with this positive UI evidence. Active work, drafts, modal
approval controls, and unrecognized layouts retain conservative blocking.
Use synthetic regression fixtures, not private terminal captures in git.

Definition of done: regression suite passes, installed detector matches source,
monitor loads the update, and a delayed real wake has acknowledgment and visible
prompt evidence. Tests alone do not prove live delivery.

State: 160 tests pass from source and the installed package. Installed injector
matches source byte-for-byte. User wake monitor restarted and monitor_ready is
true. Existing failed wake evidence is preserved. Replacement wake
wake_20260909_165953_527b fired at 17:00:38 UTC on its first attempt, produced
an acknowledgment, and recorded visible_prompt_observed. The resumed Codex turn
independently inspected all three and archived the successful one-off record.
Live delivery for the repaired idle-composer case is verified.
