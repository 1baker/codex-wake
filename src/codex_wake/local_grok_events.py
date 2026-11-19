"""One detached ACP prompt owner; original journal intent is never redispatched."""
import argparse
import base64
import hashlib
import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .controller_grok import ControllerGrok
from .daemon_commands import local_operator
from .grok_acp import ACPRefusal
from .local_session_events import TurnEvents, MAX_EVENT_BYTES
from .controller_runtime import encoded
from .process import process_identity


def launch(root, identifier):
    # Called only by the journal's once-only admission dispatcher.
    process = subprocess.Popen([sys.executable, '-m', 'codex_wake.local_grok_events',
        '--root', str(Path(root).resolve()), '--operation', identifier], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    threading.Thread(target=process.wait, daemon=True).start()
    return dict(kind='grok_acp_collecting', collector_pid=process.pid, collector_process=process_identity(process.pid), native_request_id=identifier)


def _metadata(store, identifier, event):
    if len(encoded(event).encode()) <= MAX_EVENT_BYTES:
        store.append(identifier, 'grok/session/metadata', event)
        return
    # Native event identity is the occurrence, not its content hash: identical
    # consecutive catalog updates must remain independently reconstructable.
    payload = json.dumps(event, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    first = store.state(identifier)['sequence'] + 1
    group = hashlib.sha256((identifier + ':' + str(first)).encode()).hexdigest()
    digest = hashlib.sha256(payload).hexdigest()
    count = (len(payload) + 8191) // 8192
    for index in range(count):
        fragment = dict(operation_id=identifier, group_id=group,
            occurrence_first_sequence=first, part_index=index, part_count=count,
            encoding='base64', serialization='canonical_json_utf8',
            native_kind='available_commands_update', total_bytes=len(payload), sha256=digest,
            data=base64.b64encode(payload[index * 8192:(index + 1) * 8192]).decode('ascii'))
        if len(encoded(fragment).encode()) > MAX_EVENT_BYTES:
            raise ValueError('native metadata fragment exceeds unchanged event bound')
        store.append(identifier, 'grok/session/metadata_fragment', fragment)


def collect(root, identifier):
    from .local_grok_control import LocalGrokControl
    local = LocalGrokControl(root); actor = local._actor(identifier)
    store = TurnEvents(root); runtime = local.runtime
    lock_path = runtime.path.parent / (identifier + '.collector.lock')
    with lock_path.open('a') as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if store.state(identifier)['status'] != 'unavailable':
            return
        store.update(identifier, status='connecting', pid=os.getpid(), process=process_identity(os.getpid()),
                     provider='grok', unsupported_event_kinds=[])
        try:
            # Protective custody handoff wait; actor and provider guards own authorization expiry.
            deadline = time.monotonic() + 10
            while True:
                if time.monotonic() >= deadline:
                    raise RuntimeError('original admission did not publish collector custody')
                record = runtime._load(identifier)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('original admission did not publish collector custody')
                if record['phase'] == 'waiting':
                    break
                if record['phase'] != 'dispatching':
                    raise RuntimeError('original admission did not publish collector custody')
                time.sleep(min(.01, remaining))
            payload = record['payload']; target = record['target']
            row = local.resolve('grok:' + target['conversation_id'], target, payload['profile'])
            def update(event):
                change = event.get('update', {}); kind = change.get('sessionUpdate')
                if kind == 'agent_message_chunk' and change.get('content', {}).get('type') == 'text':
                    store.append(identifier, 'grok/session/update', event)
                elif kind == 'available_commands_update':
                    _metadata(store, identifier, event)
                elif kind not in ('agent_thought_chunk', 'user_message_chunk'):
                    state = store.state(identifier)
                    store.update(identifier, unsupported_event_kinds=sorted(set(state.get('unsupported_event_kinds', []) + [str(kind)])))
                store.update(identifier, status='running')
            owner = ControllerGrok(root, on_update=update)
            selected, guard = local._connection(row['profile'], target)
            if time.monotonic() >= deadline:
                raise RuntimeError('original admission collector custody deadline elapsed')
            with owner._connection(selected, guard) as connection:
                owner._negotiation(connection, selected)
                store.update(identifier, status='running', transmitted=True)
                result = owner.prompt_native(connection, target['conversation_id'], payload['prompt'], identifier)
            current = runtime._load(identifier)
            current['result'] = result
            owner.observe_native_owned(current)
            # Publish complete retention before a caller can observe terminal work.
            store.update(identifier, status='completed')
            runtime._save(current)
        except ACPRefusal as error:
            current = runtime._load(identifier)
            current['result'] = dict(kind='grok_acp_refusal', reason=error.code,
                native_error_code=error.native_code, execution='not_started', provider_work=False)
            local.owner.observe_native_owned(current); runtime._save(current)
            store.update(identifier, status='failed', reason=error.code)
        except Exception as error:
            current = runtime._load(identifier)
            if current['phase'] != 'terminal':
                current.update(phase='uncertain', execution='unknown', reason=getattr(error, 'code', 'native_owner_unavailable'))
                runtime._save(current)
            store.update(identifier, status='uncertain', reason=getattr(error, 'code', 'native_owner_unavailable'))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', required=True); parser.add_argument('--operation', required=True)
    arguments = parser.parse_args(); collect(arguments.root, arguments.operation)


if __name__ == '__main__':
    main()
