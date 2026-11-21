"""Controller action notices on the existing no-turn native notice protocol.

Text comes from an owned, completed controller operation, never caller prose.
The operation journal is the only notice custody store. Uncertain append is
read back by original event ID and is never silently appended again.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import struct

from .controller_auth import AuthError
from .controller_health import ControllerHealth, _image_hash, _process_matches, _TARGET_FIELDS
from .controller_runtime import ControllerRuntime, encoded
from .managed_inventory import InventoryError
from .native_protocol import native_request, NativeCapabilityUnavailable


def flat_target(raw):
    result = {key: value for key, value in raw.items() if key != 'process'}
    process = raw['process']
    result.update(process_pid=str(process['pid']), process_start_ticks=str(process['start_ticks']),
        process_boot_id=process['boot_id'])
    return result


class ControllerNotices:
    def __init__(self, root, *, request=None, binding=None):
        self.root, self.request = Path(root), request
        self.runtime = ControllerRuntime(root)
        self.binding = binding or self._binding

    def _binding(self, target):
        matches = [row for row in ControllerHealth(self.root).bindings()
            if set(row['target']) == _TARGET_FIELDS and flat_target(row['target']) == target]
        if len(matches) != 1:
            raise InventoryError('stale_target', 'exact native notice binding unavailable')
        row, raw = matches[0], matches[0]['target']
        if raw['runtime'] != 'codex' or not _process_matches(raw) or _image_hash(raw['process']['pid']) != raw['build_sha256']:
            raise InventoryError('stale_target', 'native notice process/build changed')
        if not isinstance(row.get('endpoint'), str) or not row['endpoint'].startswith('unix:///') or not isinstance(row.get('codex_cmd'), list) or not row['codex_cmd']:
            raise InventoryError('unsupported_operation', 'existing native notice endpoint required')
        return row

    def _authorize(self, actor, target, capability, authorize):
        required = (_TARGET_FIELDS - {'process'}) | {'process_pid','process_start_ticks','process_boot_id'}
        if not isinstance(target, dict) or set(target) != required or any(not isinstance(v,str) or not v or len(v)>4096 for v in target.values()):
            raise InventoryError('invalid_argument', 'complete flat native notice target required')
        if not any(required <= scope.keys() and all(target.get(k)==v for k,v in scope.items()) for scope in actor.targets):
            raise AuthError('insufficient_scope')
        self.runtime.check_authority(actor, target, capability, authorize=authorize)

    def _event(self, actor, target, source_id, authorize):
        source = self.runtime.operation(actor, 'operations.result', dict(operation_id=source_id),
            authorize=authorize)['result']['operation']
        if source['target'] != target or source['phase'] != 'terminal' or source['execution'] != 'completed':
            raise InventoryError('source_unavailable', 'completed same-target controller action required')
        if source['operation'] not in {'recovery.disable','recovery.enable','recovery.apply',
                'builds.launch','builds.select','builds.rollback','operations.cancel','flows.cancel'}:
            raise InventoryError('unsupported_operation', 'source action does not support controller notices')
        value = source.get('result')
        if not isinstance(value,dict):
            raise InventoryError('source_unavailable', 'source action has no retained structured outcome')
        fields = dict(action=source['operation'], policy_id=value.get('policy_id','controller'),
            mode=value.get('mode','not_reported'), reason=value.get('reason','not_reported'),
            outcome=value.get('outcome',source['execution']))
        if any(not isinstance(v,str) or len(v)>4096 for v in fields.values()):
            raise InventoryError('source_unavailable', 'source action notice fields exceed bounds')
        # JSON quoting makes embedded control characters visible instead of terminal commands.
        event_id = 'notice_' + hashlib.sha256(encoded([target, source_id]).encode()).hexdigest()
        suffix = ' [External supervision event ' + event_id + ']'
        text = 'Codex Wake controller: ' + encoded(fields)
        budget = 768 - len(suffix.encode())
        if len(text.encode()) > budget:
            text = text.encode()[:budget-3].decode('utf-8',errors='ignore') + '...'
        text += suffix
        return dict(event_id=event_id,text=text,source=fields,source_operation_id=source_id)

    def _native(self, target, event, *, read=False):
        binding = self.binding(target)
        params = dict(threadId=target['conversation_id'], eventId=event['event_id'])
        if not read: params['text'] = event['text']
        method = 'thread/notice/read' if read else 'thread/notice/append'
        if self.request is None:
            def verify(connection, metadata):
                peer = connection.socket.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i'))
                pid, uid, unused = struct.unpack('3i',peer)
                if uid != os.geteuid() or metadata.get('codexHome') != target['home'] or _image_hash(pid) != target['build_sha256']:
                    raise InventoryError('stale_target','native notice endpoint account/build differs')
            reply = native_request(binding['endpoint'],binding['codex_cmd'],method,params,5,verify_connection=verify)
        else:
            reply = self.request(binding['endpoint'],binding['codex_cmd'],method,params,5)
        if read:
            if reply.get('notice') != dict(eventId=event['event_id'],text=event['text']): return None
        elif reply.get('eventId') != event['event_id'] or reply.get('recorded') is not True:
            raise InventoryError('effect_uncertain', 'native notice acknowledgement differs')
        self.binding(target)  # A replaced process cannot provide qualified delivery proof.
        return dict(event,delivery=dict(status='recorded',transcript=True,
            model_context=reply.get('modelContextAvailable') is True,
            notification_published=None if read else reply.get('notificationPublished') is True))

    def authorize_upgrade_notice(self, actor, target, *, authorize):
        """Validate an exact registered operator attachment before append intent."""
        self._authorize(actor,target,'control',authorize)
        self.binding(target)

    def deliver_upgrade_event(self, actor, target, source_event_id, *, authorize,
                              read=False, expected_source_digest=None):
        """Deliver retained upgrade state; this method accepts no caller prose."""
        from .upgrade_notices import source_event
        event=source_event(self.root,source_event_id,target)
        if expected_source_digest is not None and event['source_digest']!=expected_source_digest:
            raise InventoryError('source_changed','original upgrade notice source changed')
        self._authorize(actor,target,'observe' if read else 'control',authorize)
        try:
            return self._native(target,event,read=read)
        except NativeCapabilityUnavailable:
            if read:
                raise
            return dict(event,delivery=dict(status='unsupported',transcript=False,
                model_context=False,notification_published=False))

    def execute(self, actor, operation, arguments, *, authorize):
        if not isinstance(arguments,dict):
            raise InventoryError('invalid_argument', 'notice arguments must be an object')
        allowed = {'notices.publish':{'expected_target','source_operation_id','_request'},
            'notices.list':{'expected_target','cursor'},'notices.reconcile':{'expected_target','operation_id'}}
        if operation not in allowed or set(arguments)-allowed[operation]:
            raise InventoryError('invalid_argument', 'unsupported notice operation/arguments')
        target = arguments.get('expected_target')
        self._authorize(actor,target,'observe',authorize)
        if operation == 'notices.list':
            records, cursor = self.runtime.owned_operations(actor,target,'notices.publish',
                authorize=authorize,cursor=arguments.get('cursor',0))
            return dict(schema_version=1,operation=operation,status='completed',result=dict(
                notices=[dict(operation_id=r['operation_id'],phase=r['phase'],
                    **(r['result'] or dict(delivery=dict(status='uncertain')))) for r in records], next_cursor=cursor))
        if operation == 'notices.publish':
            event = self._event(actor,target,arguments.get('source_operation_id'),authorize)
            capability = 'recovery' if event['source']['action'].startswith('recovery.') else 'control'
            self._authorize(actor,target,capability,authorize)
            def dispatch(unused, payload):
                self._authorize(actor,target,capability,authorize)
                try:
                    return self._native(target,event)
                except NativeCapabilityUnavailable:
                    return dict(event,delivery=dict(status='unsupported',transcript=False,
                        model_context=False,notification_published=False))
            return self.runtime.execute(actor,operation,arguments,authorize=authorize,dispatch=dispatch,
                required_capability=capability)
        original = self.runtime.operation(actor,'operations.result',dict(operation_id=arguments.get('operation_id')),
            authorize=authorize)['result']['operation']
        if original['operation'] != 'notices.publish' or original['target'] != target:
            raise InventoryError('stale_target','original notice owner/target differs')
        payload = self.runtime._load(original['operation_id'])['payload']
        event = self._event(actor,target,payload['source_operation_id'],authorize)
        capability = 'recovery' if event['source']['action'].startswith('recovery.') else 'control'
        self._authorize(actor,target,capability,authorize)
        def observe(record):
            if record['target'] != target:
                raise InventoryError('stale_target','notice belongs to another target')
            # The journal owns immutable source inputs; callers cannot substitute text.
            self._authorize(actor,target,capability,authorize)
            return self._native(target,event,read=True)
        return self.runtime.reconcile_result(actor,arguments.get('operation_id'),
            expected_operation='notices.publish',authorize=authorize,observe=observe,capability=capability)
