"""Manual whole-tab lifecycle over the existing host-owned terminal adapters.

ControllerRuntime owns admission/replay and uncertain-operation reconciliation.
This owner stores only reversible placement/effect receipts in TabOrganization's
existing store; it never creates a second operation journal or conversation.
"""
from pathlib import Path
import re
import subprocess
import time
import uuid

from .managed_inventory import InventoryError
from .process import process_identity
from .tab_organization import TabOrganization, digest
from .tab_identity import stable_snapshot, stable_panes


class TabLifecycle:
    READS = frozenset()
    ARGUMENTS = {
        'tabs.create': {'workspace', 'expected_target', 'name', 'cwd', 'profile', 'argv', 'preview'},
        'tabs.rename': {'workspace', 'expected_target', 'window', 'name', 'preview'},
        'tabs.focus': {'workspace', 'expected_target', 'window', 'preview'},
        'tabs.move': {'workspace', 'expected_target', 'window', 'destination', 'expected_destination', 'index', 'force', 'preview'},
        'tabs.park': {'workspace', 'expected_target', 'window', 'destination', 'expected_destination', 'force', 'preview'},
        'tabs.restore': {'workspace', 'expected_target', 'window', 'destination', 'expected_destination', 'receipt_id', 'force', 'preview'},
        'tabs.close': {'workspace', 'expected_target', 'window', 'force', 'preview'},
    }

    def __init__(self, root, *, workspaces, host, environment):
        self.root = Path(root)
        self.workspaces = dict(workspaces)
        self.host, self.environment = host, environment
        self.records = TabOrganization(root, transport=None)

    def inspect(self, workspace, *, deadline=None, window_ids=None):
        """Read the complete roster; optionally fence only selected pane births.

        Lifecycle/input callers keep the default full check. The formatting
        owner uses the narrow read-only selection for windows it may change.
        """
        deadline = deadline or time.monotonic() + 10
        if window_ids is not None:
            if (not isinstance(window_ids,(list,tuple,set,frozenset)) or len(window_ids)>4096
                    or any(not isinstance(w,str) or not re.fullmatch(r'@[0-9]+',w) for w in window_ids)):
                raise InventoryError('invalid_argument','Bounded exact window identities required for read-only inspection.')
            window_ids=set(window_ids)
        if not isinstance(workspace, str) or workspace not in self.workspaces:
            raise InventoryError('unsupported_target', 'workspace is not host enrolled')
        config = self.workspaces[workspace]
        snapshot = config['transport'].snapshot(deadline)
        if config['kind'] in ('tmux', 'byobu'):
            for window in snapshot['windows']:
                if window_ids is not None and window['window_id'] not in window_ids:continue
                for pane in window['panes']:
                    pane['process_generation'] = process_identity(pane['pid'])
        target = dict(host=self.host, environment=self.environment, workspace=workspace,
                      presentation=config['kind'], generation=digest(stable_snapshot(snapshot)))
        return dict(target=target, snapshot=snapshot)

    @staticmethod
    def _window(snapshot, window):
        if not isinstance(window, str) or not re.fullmatch(r'@[0-9]+', window):
            raise InventoryError('invalid_argument', 'an exact native window ID is required')
        matches = [w for w in snapshot['windows'] if w['window_id'] == window]
        if len(matches) != 1:
            raise InventoryError('stale_target', 'window is absent from pinned workspace')
        return matches[0]

    @staticmethod
    def _name(value):
        if (not isinstance(value, str) or not value or len(value.encode()) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise InventoryError('invalid_argument', 'tab name must be bounded single-line text')
        return value

    @staticmethod
    def _collision(snapshot, name, *, except_window=None, index=None):
        if any(w['window_id'] != except_window and w['name'] == name for w in snapshot['windows']):
            raise InventoryError('name_conflict', 'destination contains a tab with that name')
        if index is not None and any(w['window_id'] != except_window and w['index'] == index for w in snapshot['windows']):
            raise InventoryError('placement_conflict', 'destination position is occupied; newer layout is preserved')

    def _protection(self, config, window, deadline):
        reasons = []
        if window.get('focused'):
            reasons.append('focused')
        if window.get('linked'):
            reasons.append('linked')
        if window.get('pins') or window['window_id'] in config.get('pins', []):
            reasons.append('pinned')
        observer = config.get('observer')
        try:
            evidence = observer(max(.001, deadline - time.monotonic())) if observer else {}
        except Exception:
            evidence = {}
        affected = []
        for pane in window['panes']:
            sample = evidence.get(pane['pane_id'], {})
            expected = sample.get('process') or {}
            # Like TabOrganization, trust the host observer's pane-to-client
            # relationship, then recheck that client's exact process generation.
            # A native client is commonly a descendant of the pane's shell.
            actual = process_identity(expected['pid']) if type(expected.get('pid')) is int else None
            identity_matches = bool(actual
                and expected.get('start_ticks') == actual.get('start_time_ticks')
                and expected.get('boot_id') == actual.get('boot_id'))
            if not sample.get('fresh') or not identity_matches:
                reasons.append('unknown_work')
                continue
            if sample.get('state') not in ('ready', 'idle'):
                reasons.append('active_or_waiting_work')
            if sample.get('conversation_id') and sample.get('root'):
                from .session_lifecycle import pending_thread_work
                row = dict(thread_id=sample['conversation_id'], cwd=sample['root'], attachments=[dict(
                    socket=config['transport'].socket, pane_id=pane['pane_id'])])
                work = pending_thread_work(row, self.root)
                affected.append(dict(pane=pane['pane_id'], **work))
                if work['pending'] or work['messages']:
                    reasons.append('pending_work')
        return sorted(set(reasons)), affected

    def execute(self, operation, arguments):
        if operation not in self.ARGUMENTS:
            raise InventoryError('unsupported_operation', 'unsupported manual tab lifecycle operation')
        if not isinstance(arguments, dict) or set(arguments) - self.ARGUMENTS[operation]:
            raise InventoryError('invalid_argument', 'unsupported tab lifecycle arguments')
        args = dict(arguments)
        for key in ('force', 'preview'):
            if key in args and type(args[key]) is not bool:
                raise InventoryError('invalid_argument', key + ' must be a Boolean')
        if 'index' in args and (type(args['index']) is not int or not 0 <= args['index'] <= 100000):
            raise InventoryError('invalid_argument', 'destination index must be a nonnegative bounded integer')
        argv=args.get('argv')
        if argv is not None and (not isinstance(argv,list) or not 1<=len(argv)<=64 or any(not isinstance(v,str) or '\0' in v or len(v)>4096 for v in argv)):
            raise InventoryError('invalid_argument','A bounded command argv is required.')
        deadline = time.monotonic() + 10
        with self.records.locked(deadline):
            return self._execute(operation, args, deadline)

    def _execute(self, operation, args, deadline):
        workspace = args.get('workspace')
        before = self.inspect(workspace, deadline=deadline)
        legacy_target=dict(before['target'],generation=digest(before['snapshot']))
        if args.get('expected_target') not in (before['target'],legacy_target):
            raise InventoryError('stale_target', 'exact current workspace generation required')
        config = self.workspaces[workspace]
        transport = config['transport']
        if operation=='tabs.create' and (args.get('profile') or args.get('argv')) and config['kind'] not in ('tmux','byobu'):
            raise InventoryError('unsupported_target','Selected profile creation is qualified only for Byobu/tmux; no fallback was launched.')
        if config['kind']=='psmux' and hasattr(transport,'lifecycle'):
            return self._psmux(operation,args,before,config,deadline)
        if config['kind'] not in ('tmux', 'byobu'):
            raise InventoryError('unsupported_target', 'manual lifecycle is not qualified for this backend')
        snapshot = before['snapshot']
        window = None if operation == 'tabs.create' else self._window(snapshot, args.get('window'))
        name = self._name(args.get('name')) if operation in ('tabs.create', 'tabs.rename') else window['name']
        destination, after_destination = None, None
        placement = None
        reasons, affected = [], []
        if operation in ('tabs.create', 'tabs.rename'):
            self._collision(snapshot, name, except_window=window['window_id'] if window else None)
        if operation == 'tabs.create':
            cwd_value = args.get('cwd', config.get('cwd', str(Path.home())))
            if not isinstance(cwd_value, str):
                raise InventoryError('invalid_argument', 'working directory must be an absolute path string')
            cwd = Path(cwd_value)
            if not cwd.is_absolute() or not cwd.is_dir():
                raise InventoryError('invalid_argument', 'create requires an existing absolute working directory')
        if operation in ('tabs.move', 'tabs.park', 'tabs.restore', 'tabs.close'):
            reasons, affected = self._protection(config, window, deadline)
            if window.get('linked'):
                raise InventoryError('tab_protected', 'linked tabs require explicit unlink ownership; refusing whole-tab operation')
            already_placed = (operation == 'tabs.move' and args.get('destination') == workspace
                              and args.get('index') == window['index'])
            if reasons and not already_placed and not args.get('force') and not args.get('preview'):
                raise InventoryError('tab_protected', 'tab is protected: ' + ', '.join(reasons))
        if operation in ('tabs.move', 'tabs.park', 'tabs.restore'):
            destination = args.get('destination')
            after_destination = self.inspect(destination, deadline=deadline)
            legacy_destination = dict(after_destination['target'], generation=digest(after_destination['snapshot']))
            if args.get('expected_destination') not in (after_destination['target'], legacy_destination):
                raise InventoryError('stale_target', 'exact current destination generation required')
            other = self.workspaces[destination]
            if (other['kind'] not in ('tmux', 'byobu')
                    or getattr(other['transport'], 'socket', None) != transport.socket):
                raise InventoryError('unsupported_target', 'whole-process moves require the same terminal server')
            same_session = destination == workspace
            if same_session and (operation != 'tabs.move' or 'index' not in args):
                raise InventoryError('invalid_argument', 'same-session placement requires tabs.move and an explicit index')
            if not same_session and len(snapshot['windows']) == 1:
                raise InventoryError('tab_protected', 'moving the last tab would destroy its source session; retain another tab first')
            index = args.get('index')
            if operation == 'tabs.restore':
                original = self.records.read(args.get('receipt_id'))
                if (original.get('action') != 'tabs.park' or original.get('status') != 'applied'
                        or original.get('workspace') != destination or original.get('destination') != workspace
                        or original.get('window', {}).get('window_id') != window['window_id']):
                    raise InventoryError('stale_target', 'parking receipt does not identify this exact source and original destination')
                original_panes = original['window']['panes']
                if stable_panes(original_panes) != stable_panes(window['panes']):
                    raise InventoryError('stale_target', 'parked native pane/process generation changed')
                index = original['window']['index']
            if same_session:
                ordered = sorted(snapshot['windows'], key=lambda w: w['index'])
                crossed = [w for w in ordered if min(window['index'], index) <= w['index'] <= max(window['index'], index)
                           and w['window_id'] != window['window_id']]
                if index < window['index']:
                    crossed.reverse()
                placement = dict(index=index, crossed=crossed)
                displaced = []
                for sibling in crossed:
                    if sibling.get('linked'):
                        raise InventoryError('tab_protected', 'placement would displace a linked tab')
                    protections, work = self._protection(config, sibling, deadline)
                    displaced.append(dict(window_id=sibling['window_id'], index=sibling['index'],
                                          protection=protections, affected_work=work))
                    reasons = sorted(set(reasons + protections))
                    affected.extend(work)
                placement['displaced_tabs'] = displaced
                if crossed and reasons and not args.get('force') and not args.get('preview'):
                    raise InventoryError('tab_protected', 'placement would displace protected tabs: ' + ', '.join(reasons))
            else:
                self._collision(after_destination['snapshot'], name, index=index)
        profile_owner=None
        if operation=='tabs.create' and args.get('profile'):
            from .tab_profile_create import TabProfileCreate
            profile_owner=TabProfileCreate(self.root,host=self.host,environment=self.environment)
            if args.get('preview'):
                return dict(profile_owner.create(args['profile'],transport=transport,name=name,cwd=str(cwd),deadline=deadline,guard=lambda:None,preview=True),target=before['target'])
        if args.get('preview'):
            return dict(status='preview', action=operation, target=before['target'],
                        destination=after_destination['target'] if after_destination else None,
                        window=window, name=name, protection=reasons, affected_work=affected,
                        requires_force=bool(reasons),
                        **({'displaced_tabs': placement['displaced_tabs']} if placement is not None else {}))
        # Reobserve both pinned workspaces immediately before admitting terminal I/O.
        if self.inspect(workspace, deadline=deadline)['target'] != before['target']:
            raise InventoryError('stale_target', 'source changed before lifecycle effect')
        if destination and self.inspect(destination, deadline=deadline)['target'] != after_destination['target']:
            raise InventoryError('stale_target', 'destination changed before lifecycle effect')
        if placement is not None and window['index'] == placement['index']:
            return dict(status='noop', action=operation, target=before['target'], window=window,
                        conversation='preserved', protection=reasons, affected_work=affected)
        closing_server=None
        if operation=='tabs.close' and len(snapshot['windows'])==1:
            server_pid=int(transport.command(deadline,'display-message','-p','#{pid}').strip())
            closing_server=(server_pid,process_identity(server_pid))
            if closing_server[1] is None:
                raise InventoryError('stale_target','Original terminal server process is unavailable.')
        receipt_id = 'receipt_' + uuid.uuid4().hex
        receipt = dict(version=1, receipt_id=receipt_id, status='pending', action=operation,
                       workspace=workspace, destination=destination, window=window,
                       before=before['target'], affected_work=affected, forced=bool(args.get('force')))
        self.records.save(receipt_id, receipt)
        try:
            if profile_owner is not None:
                def guard():
                    if self.inspect(workspace,deadline=deadline)['target']!=before['target']:
                        raise InventoryError('stale_target','Destination changed before profile launch.')
                selected=profile_owner.create(args['profile'],transport=transport,name=name,cwd=str(cwd),deadline=deadline,guard=guard)
                receipt.update(status=selected['status'],profile_target=selected.get('profile_target'),observed_window=selected.get('window'),profile_intent=selected.get('intent'))
                self.records.save(receipt_id,receipt)
                return dict(selected,target=before['target'],receipt_id=receipt_id,action=operation)
            if operation == 'tabs.create':
                wid = transport.command(deadline, 'new-window', '-d', '-P', '-F', '#{window_id}',
                    '-t', transport.session + ':', '-n', name, '-c', str(cwd), *(['--',*args['argv']] if args.get('argv') else [])).strip()
            else:
                wid = window['window_id']
                if operation == 'tabs.rename':
                    transport.command(deadline, 'rename-window', '-t', wid, name)
                elif operation == 'tabs.focus':
                    transport.command(deadline, 'select-window', '-t', transport.session + ':' + wid)
                elif operation == 'tabs.close':
                    transport.command(deadline, 'kill-window', '-t', wid)
                elif placement is not None:
                    for sibling in placement['crossed']:
                        transport.command(deadline, 'swap-window', '-d', '-s', wid, '-t', sibling['window_id'])
                    if not placement['crossed'] or placement['crossed'][-1]['index'] != index:
                        transport.command(deadline, 'move-window', '-d', '-s', wid, '-t', transport.session + ':' + str(index))
                else:
                    target_session = self.workspaces[destination]['transport'].session
                    position = str(index) if index is not None else ''
                    transport.command(deadline, 'move-window', '-d', '-s', wid, '-t', target_session + ':' + position)
            if placement is not None:
                focused = next((w['window_id'] for w in snapshot['windows'] if w['focused']), None)
                if focused:
                    transport.command(deadline, 'select-window', '-t', transport.session + ':' + focused)
            workspace_state = 'present'
            if operation == 'tabs.close' and len(snapshot['windows']) == 1:
                # tmux removes a session when its last window closes. Verify
                # window absence across the still-pinned server, or its socket
                # and exact server-process disappearance after acknowledged closure.
                try:
                    ids = transport.command(deadline, 'list-windows', '-a', '-F', '#{window_id}').splitlines()
                except (OSError,subprocess.CalledProcessError):
                    # A successful kill-window may end the last server while
                    # leaving its socket path behind. Require disappearance of
                    # the exact server process witnessed before that effect.
                    server_pid,server_birth=closing_server
                    until=min(deadline,time.monotonic()+1)
                    while process_identity(server_pid)==server_birth and time.monotonic()<until:
                        time.sleep(.01)
                    if process_identity(server_pid)==server_birth:
                        raise
                    ids = []
                if wid in ids:
                    raise InventoryError('effect_uncertain', 'closed tab remains on terminal server')
                after = dict(target=before['target'], snapshot=dict(windows=[]))
                workspace_state = 'removed'
            else:
                after = self.inspect(destination or workspace, deadline=deadline)
            observed = None if operation == 'tabs.close' else self._window(after['snapshot'], wid)
            if operation == 'tabs.close' and any(w['window_id'] == wid for w in after['snapshot']['windows']):
                raise InventoryError('effect_uncertain', 'closed tab remains present')
            if window and observed and stable_panes(observed['panes']) != stable_panes(window['panes']):
                raise InventoryError('effect_uncertain', 'native pane/process identity changed')
            if operation == 'tabs.rename' and observed['name'] != name:
                raise InventoryError('effect_uncertain', 'renamed tab was not observed')
            if operation == 'tabs.focus' and not observed['focused']:
                raise InventoryError('effect_uncertain', 'focused tab was not observed')
            if placement is not None:
                expected = sorted(snapshot['windows'], key=lambda w: w['index'])
                remaining = [w['window_id'] for w in expected if w['window_id'] != wid]
                actual = sorted(after['snapshot']['windows'], key=lambda w: w['index'])
                if (observed['index'] != index
                        or [w['window_id'] for w in actual if w['window_id'] != wid] != remaining
                        or {w['window_id']: stable_panes(w['panes']) for w in actual} != {w['window_id']: stable_panes(w['panes']) for w in expected}
                        or [w['window_id'] for w in actual if w['focused']] != [w['window_id'] for w in expected if w['focused']]):
                    raise InventoryError('effect_uncertain', 'same-session placement preservation readback failed')
                receipt['placement'] = dict(index=index, order=[w['window_id'] for w in actual])
            receipt.update(status='applied', after=after['target'], observed_window=observed, workspace_state=workspace_state)
            self.records.save(receipt_id, receipt)
            return dict(status='applied', action=operation, target=after['target'], window=observed,
                        receipt_id=receipt_id, forced=bool(args.get('force')), affected_work=affected, protection=reasons,
                        conversation='preserved', workspace_state=workspace_state)
        except Exception:
            receipt.update(status='uncertain')
            self.records.save(receipt_id, receipt)
            raise

    def _psmux(self,operation,args,before,config,deadline):
        transport=config['transport'];snapshot=before['snapshot'];workspace=args['workspace']
        window=None if operation=='tabs.create' else self._window(snapshot,args.get('window'))
        action=operation.split('.')[1]
        if action in ('move','park','restore'):
            destination=self.inspect(args.get('destination'),deadline=deadline)
            if args.get('expected_destination')!=destination['target']:
                raise InventoryError('stale_target','Destination changed; refresh before moving.')
            raise InventoryError('unsupported_target','psmux whole-window cross-session movement is unsupported; source preserved.')
        if window and window.get('linked'):
            raise InventoryError('tab_protected','Linked native windows require explicit unlink ownership.')
        payload={} if window is None else dict(window=window['window_id'])
        if action in ('create','rename'):
            payload['name']=self._name(args.get('name'))
            self._collision(snapshot,payload['name'],except_window=window['window_id'] if window else None)
        if action=='create' and 'cwd' in args:payload['cwd']=args['cwd']
        reasons=['native_work_unknown'] if action=='close' else []
        if action=='close' and not args.get('force') and not args.get('preview'):
            raise InventoryError('tab_protected','Native Windows work state is unknown; explicit --force is required to close this tab.')
        if args.get('preview'):
            return dict(status='preview',target=before['target'],action=operation,window=window,protection=reasons,requires_force=bool(reasons))
        if self.inspect(workspace,deadline=deadline)['target']!=before['target']:
            raise InventoryError('stale_target','Native Windows presentation changed before effect.')
        receipt_id='receipt_'+uuid.uuid4().hex
        receipt=dict(version=1,receipt_id=receipt_id,status='pending',action=operation,before=before['target'])
        self.records.save(receipt_id,receipt)
        try:
            result=transport.lifecycle(action,payload,deadline)
            after=result.get('snapshot')
            observed=None
            if after is not None:
                after=dict(after,bridge_generation=transport.generation)
                wid=result['window_id']
                observed=next((w for w in after['windows'] if w['window_id']==wid),None)
                if action=='close' and observed is not None:
                    raise InventoryError('effect_uncertain','Closed native window is still visible.')
                if action!='close' and observed is None:
                    raise InventoryError('effect_uncertain','Native lifecycle outcome was not observed.')
                target=dict(before['target'],generation=digest(after))
            else:target=before['target']
            receipt.update(status='applied',after=target,observed_window=observed)
            self.records.save(receipt_id,receipt)
            return dict(status='applied',action=operation,target=target,window=observed,receipt_id=receipt_id,
                        protection=reasons,affected_work=reasons,forced=bool(args.get('force')),
                        workspace_state=result.get('workspace_state','present'),conversation='preserved')
        except Exception:
            receipt['status']='uncertain';self.records.save(receipt_id,receipt)
            raise
