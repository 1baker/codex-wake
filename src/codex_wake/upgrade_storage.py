"""Storage sizing for owned job roots while compilers create/remove temp files."""
import os
from pathlib import Path
import stat


def owned_storage_bytes(paths):
    """Count regular files once across overlapping roots; ignore vanished paths.

    Symlinks are not followed. A compiler deleting an entry between directory
    enumeration and stat is normal; other failures still make the budget unknown
    and propagate to its caller instead of silently undercounting inaccessible
    storage. This measures logical bytes, consistent with existing job budgets.
    """
    roots=set(Path(os.path.abspath(path)) for path in paths)
    roots={path for path in roots if not any(path!=other and path.is_relative_to(other) for other in roots)}
    pending=list(roots);total=0
    while pending:
        path=pending.pop()
        try:metadata=path.lstat()
        except FileNotFoundError:continue
        if stat.S_ISREG(metadata.st_mode):
            total+=metadata.st_size
        elif stat.S_ISDIR(metadata.st_mode):
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:item=entry.stat(follow_symlinks=False)
                        except FileNotFoundError:continue
                        if stat.S_ISREG(item.st_mode):total+=item.st_size
                        elif stat.S_ISDIR(item.st_mode):pending.append(Path(entry.path))
            except FileNotFoundError:continue
    return total
