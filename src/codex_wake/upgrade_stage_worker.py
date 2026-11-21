"""Private child entrypoint; invoked only with a pinned host-approved recipe."""
import os
import sys
from pathlib import Path
from codex_profiles.upgrades import stage, _atomic

if __name__ == '__main__':
    # Restrict this future owned child and all build/qualification descendants.
    os.umask(0o077)
    try:
        result=stage(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError,ValueError,KeyError) as error:
        result=dict(status='failed',reason=str(error))
    _atomic(Path(sys.argv[3]),result)
