# Tab destruction and unlinking

A tab can be linked into more than one terminal session, so closing its underlying
panes can affect operators outside the requesting session. Destruction targets
the entire tab and identifies every affected session and pane before execution.
Unlinking removes one appearance while allowing the underlying tab and its
processes to remain live. This distinction gives callers an explicit choice
between editing a session's tab list and ending shared terminal work.
