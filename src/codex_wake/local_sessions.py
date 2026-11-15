"""Same-user native session discovery, with pinned peer and conversation identity."""
import hashlib
import os
from pathlib import Path
import socket
import struct
import subprocess

from .managed_inventory import InventoryError
from .process import process_identity
from .shared_app_server import SharedAppServerReader, locate_shared_endpoint
from .sessions import build_snapshot, tmux_inventory


def _endpoints(root, endpoint):
    if endpoint != 'unix://':
        return [endpoint]
    values=[]
    try:values.append(locate_shared_endpoint(timeout=3))
    except (ValueError,OSError):pass
    if (Path(root)/'controller-accounts.toml').is_file():
        from .daemon_commands import owner_from_root
        owner=owner_from_root(root)
        for row in owner.execute('daemons.list',{})['daemons']:
            if row.get('state')=='running' and row.get('endpoint'):values.append(row['endpoint'])
    return sorted(set(values))


def discover(root, endpoint='unix://', socket_path=None):
    rows=[];holds=[]
    try:panes=tmux_inventory(socket_path,3)
    except (ValueError,OSError,subprocess.SubprocessError):
        # Native conversations remain discoverable without a terminal multiplexer.
        panes=[]
    for address in _endpoints(root,endpoint):
        try:
            with SharedAppServerReader(address,timeout=10) as reader:
                pid,uid,gid=struct.unpack('3i',reader.connection.socket.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid():raise InventoryError('foreign_target','native peer belongs to another user')
                home=Path(reader.server_metadata['codexHome'])
                if not home.is_absolute() or home.stat().st_uid!=uid:raise InventoryError('foreign_target','native account home is not locally owned')
                birth=process_identity(pid)
                if not birth:raise InventoryError('stale_target','native peer exited during discovery')
                executable=str(Path('/proc',str(pid),'exe').resolve(strict=True))
                from .controller_health import _image_hash
                digest=_image_hash(pid)
                info=reader.path.stat();generation=f'{info.st_dev}:{info.st_ino}'
                threads=reader.loaded_threads(maximum=1000)
                snapshot=build_snapshot(threads,panes,{'app_server':{'availability':'available'},'tmux':{'availability':'available'}})
                for row in snapshot['sessions']:
                    if not row.get('thread_id'):continue
                    h=home.stat()
                    target=dict(host=socket.gethostname(),environment=os.environ.get('WSL_DISTRO_NAME') or os.name,provider='codex',uid=uid,account=home.name,home=str(home),home_generation=f'{h.st_dev}:{h.st_ino}',executable=executable,build_sha256=digest,process=dict(pid=pid,start_ticks=birth['start_time_ticks'],boot_id=birth['boot_id']),socket_generation=generation,conversation_id=row['thread_id'])
                    rows.append(dict(row,target=target,endpoint='unix://'+str(reader.path),codex_cmd=[executable]))
        except (ValueError,OSError,KeyError,TypeError) as error:
            holds.append(dict(endpoint=address,reason=getattr(error,'code','source_unavailable')))
    return dict(schema_version=1,status='complete' if not holds else 'partial',sessions=rows,holds=holds)


def resolve(root, selector, expected_target=None, *, endpoint='unix://', socket_path=None):
    if not isinstance(selector,str) or not selector or len(selector)>1024 or any(ord(c)<32 for c in selector):raise InventoryError('invalid_selector','bounded session selector required')
    def matches(row):
        if selector.startswith('thread:'):return row['thread_id']==selector[7:]
        if selector==row['thread_id'] or selector==row.get('name'):return True
        for pane in row.get('attachments',[]):
            if selector in ('pane:'+pane['pane_id'],'window:'+pane['window_id'],pane['window_name'],pane['pane_title']):return True
        return False
    # A complete pinned identity can resolve through the host-selected shared
    # endpoint without depending on discovery of unrelated registered accounts.
    # Explicit discovery retains peer ownership and process/socket fencing.
    if endpoint == 'unix://' and expected_target is not None:
        try:shared=locate_shared_endpoint(timeout=3)
        except (ValueError,OSError):shared=None
        if shared and shared != 'unix://':
            pinned=[row for row in discover(root,shared,socket_path)['sessions']
                    if matches(row) and row['target']==expected_target]
            if len(pinned)==1:return pinned[0]
            if len(pinned)>1:raise InventoryError('ambiguous_target','pinned identity matches multiple owned sessions')
    view=discover(root,endpoint,socket_path)
    rows=[row for row in view['sessions'] if matches(row)]
    if len(rows)>1:raise InventoryError('ambiguous_target','selector matches multiple owned sessions; use an exact thread UUID')
    if not rows:raise InventoryError('target_unavailable','no owned live session matches the selector')
    row=rows[0]
    if expected_target is not None and row['target']!=expected_target:raise InventoryError('stale_target','selected session generation changed')
    return row
