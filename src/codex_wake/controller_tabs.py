"""Host-enrolled presentation attachments, separate from runtime identity/input.

No terminal discovery grants stdin ownership. Brokers are host-owned structured
connections; fallback is visible and separately selected for each request.
"""
import time

from .tab_identity import stable_snapshot

from .managed_inventory import InventoryError
from .tab_organization import TabOrganization, TabError, digest


class ControllerTabs:
    READS = frozenset(('tabs.family.list','tabs.family.show','tabs.session.list','tabs.session.show','tabs.relocate.status','tabs.route.list','tabs.route.show','tabs.route.status','tabs.format.status','tabs.format.inspect','tabs.format.override-inspect','tabs.list','tabs.show','tabs.view-list','tabs.view-show','tabs.view-evaluate','tabs.group-list','tabs.group-show','tabs.monitor.status','tabs.monitor.refresh','tabs.policy.status','tabs.recovery.preview','tabs.recovery.status','tabs.reattach-status'))
    MUTATIONS = frozenset(('tabs.preview', 'tabs.apply', 'tabs.undo', 'tabs.capture', 'tabs.input'))

    def __init__(self, root, *, workspaces, host, environment, host_managed=False, observation_cache=None):
        self.root, self.workspaces = root, dict(workspaces)
        self.host, self.environment = host, environment
        self.host_managed = host_managed
        from .tab_observation import ObservationCache
        self.observation_cache = observation_cache or ObservationCache(root)

    def format_target(self, *, scope='workspace', workspace=None):
        from .tab_formatting import TabFormatting
        return TabFormatting(self.root,tabs=self).target(scope=scope,workspace=workspace)

    def profile_owner(self):
        from .tab_profile_create import TabProfileCreate
        return TabProfileCreate(self.root,host=self.host,environment=self.environment)

    def reattach_owner(self):
        from .tab_reattach import TabReattach
        return TabReattach(self.root,workspaces=self.workspaces,host=self.host,environment=self.environment)

    def create_tab(self,arguments,*,defaults_resolved=False):
        from .terminal_launch_defaults import prepare
        from .tab_lifecycle import TabLifecycle
        payload=dict(arguments) if defaults_resolved else prepare(self,arguments)
        return TabLifecycle(self.root,workspaces=self.workspaces,host=self.host,environment=self.environment).execute('tabs.create',payload)

    def execute(self, operation, arguments, *, deadline=None):
        if operation.startswith('tabs.family.'):
            from .bot_families import BotFamilies
            return BotFamilies(self.root,tabs=self).execute(operation,arguments)
        if operation=='tabs.create':return self.create_tab(arguments)
        if operation.startswith('tabs.route.'):
            from .terminal_routing import TerminalRouting
            return TerminalRouting(self.root,tabs=self).execute(operation,arguments)
        if operation.startswith('tabs.relocate.'):
            from .terminal_relocation import TerminalRelocation
            return TerminalRelocation(self.root,tabs=self).execute(operation,arguments)
        if operation.startswith('tabs.session.'):
            from .terminal_sessions import TerminalSessions
            return TerminalSessions(self.root,tabs=self).execute(operation,arguments)
        if operation.startswith('tabs.format.'):
            from .tab_formatting import TabFormatting
            return TabFormatting(self.root,tabs=self).execute(operation,arguments)
        if operation.startswith('tabs.reattach-'):
            return self.reattach_owner().execute(operation,arguments)
        if operation.startswith('tabs.recovery.'):
            from .tab_recovery import TabRecovery
            from .tab_lifecycle import TabLifecycle
            payload=dict(arguments);expected=payload.pop('expected_target',None)
            lifecycle=TabLifecycle(self.root,workspaces=self.workspaces,host=self.host,environment=self.environment)
            if operation=='tabs.recovery.capture' and expected is not None:
                if expected!=lifecycle.inspect(payload.get('workspace'))['target']:
                    raise InventoryError('stale_target','Workspace changed before capture.')
            if operation=='tabs.recovery.apply':
                keys=('capture_id','capture_sha256','workspace','workspace_identity','presentation_generation')
                payload['expected_target']={k:expected[k] for k in keys if expected and k in expected}
            result=TabRecovery(self.root,tabs=self).execute(operation,payload)
            if operation=='tabs.recovery.preview':
                physical=lifecycle.inspect(payload['workspace'])['target']
                result['target'].update(physical)
            return result
        if operation.startswith('tabs.policy.'):
            from .tab_organization_policy import TabOrganizationPolicy
            payload=dict(arguments)
            expected=payload.pop('expected_target',None)
            if expected is not None and expected!=self.policy_target():
                raise InventoryError('stale_target','Physical policy changed; refresh before acting.')
            return TabOrganizationPolicy(self.root,workspaces=self.workspaces).execute(operation,payload)
        if operation.startswith('tabs.monitor.'):
            from .tab_monitor import TabMonitor
            payload=dict(arguments)
            expected=payload.pop('expected_target',None)
            if expected is not None and expected!=self.monitor_target():
                raise InventoryError('stale_target','Monitor generation changed; refresh status before controlling.')
            return TabMonitor(self.root).execute(operation,payload)
        from .tab_views import TabViews
        if operation in TabViews.READS|TabViews.MUTATIONS:
            payload=dict(arguments)
            expected=payload.pop('expected_target',None)
            if expected is not None and expected != self.logical_target():
                raise InventoryError('stale_target','Saved view definitions changed; refresh before applying.')
            resources=self.execute('tabs.list',{})['resources'] if operation in ('tabs.view-evaluate','tabs.group-save') else []
            return TabViews(self.root).execute(operation,payload,resources=resources)
        from .tab_lifecycle import TabLifecycle
        if operation in TabLifecycle.ARGUMENTS:
            return TabLifecycle(self.root,workspaces=self.workspaces,host=self.host,environment=self.environment).execute(operation,arguments)
        allowed = {
            'tabs.list': set(), 'tabs.show': {'workspace', 'selector'},
            'tabs.preview': {'workspace','expected_target','mode','pins','criteria'},
            'tabs.apply': {'workspace','expected_target','plan_id'},
            'tabs.undo': {'workspace','expected_target','receipt_id'},
            'tabs.capture': {'workspace','expected_target','window','pane','lines'},
            'tabs.input': {'workspace','expected_target','window','pane','input','custody','transport','mode','keys'},
        }
        if operation not in allowed:
            raise InventoryError('unsupported_operation', 'unsupported attachment operation')
        if not isinstance(arguments, dict) or set(arguments) - allowed[operation]:
            raise InventoryError('invalid_argument', 'unsupported attachment arguments')
        names = list(self.workspaces) if operation == 'tabs.list' else [arguments.get('workspace')]
        resources, unavailable = [], []
        deadline = min(time.monotonic() + 10, deadline) if deadline is not None else time.monotonic() + 10
        for name in names:
            if name not in self.workspaces:
                raise InventoryError('unsupported_target', 'workspace is not host enrolled')
            config = self.workspaces[name]
            transport = config['transport']
            try:
                snapshot = transport.snapshot(deadline)
                if config['kind'] in ('tmux', 'byobu'):
                    from .process import process_identity
                    for window in snapshot['windows']:
                        for pane in window['panes']:
                            pane['process_generation'] = process_identity(pane['pid'])
            except Exception as error:
                if getattr(error,'code',None) == 'stale_target':
                    raise
                if operation == 'tabs.list':
                    unavailable.append(dict(workspace=name,status='unavailable',code='attachment_unavailable'))
                    continue
                raise InventoryError('attachment_unavailable', 'host presentation observation failed') from error
            target = dict(host=self.host, environment=self.environment, workspace=name,
                          presentation=config['kind'], generation=digest(snapshot))
            lifecycle_target=dict(target,generation=digest(stable_snapshot(snapshot)))
            observation = None
            if operation in self.READS:
                initial, rows = self.observation_cache.observe(
                    name,snapshot,socket_path=config.get('socket_path'),transport=transport,
                    privacy=config.get('privacy'),deadline=deadline)
                if any(w.get('attach_intent') for w in snapshot['windows']):
                    from .tab_reattach_traits import observe_managed
                    managed=self.reattach_owner()
                    for window in snapshot['windows']:
                        key=window['window_id']
                        initial[key]=observe_managed(managed,name,window,initial[key],deadline)
                observation = (initial, rows)
            broker = config.get('broker')
            custody = broker.inspect() if broker else dict(available=False, transport='unowned', generation=None)
            if operation not in self.READS:
                accepted=(target,lifecycle_target) if operation in ('tabs.preview','tabs.apply','tabs.undo') else (target,)
                if arguments.get('expected_target') not in accepted:
                    raise InventoryError('stale_target', 'exact current presentation generation required')
            if operation in self.READS:
                selector = arguments.get('selector')
                windows = snapshot['windows']
                if selector:
                    windows = [w for w in windows if selector in (w['window_id'], w['name'])]
                    if len(windows) != 1:
                        raise InventoryError('ambiguous_target' if windows else 'target_not_found', 'friendly selector must identify one attachment')
                for w in windows:
                    observed, rows = observation
                    evidence = observed[w['window_id']]
                    resources.append(dict(target=target,lifecycle_target=lifecycle_target,
                                          window=w,input_custody=custody,
                                          traits=evidence,runtime_identity='unverified',fallback='explicit_only',
                                          observation_holds=rows['holds'],workspace_label=config.get('label',name)))
                continue
            if operation in ('tabs.input', 'tabs.capture'):
                pane = self._pane(snapshot, arguments.get('pane'), arguments.get('window'))
                privacy = config.get('privacy')
                if privacy is None or privacy(pane) != 'safe':
                    raise InventoryError('presentation_privacy_unknown', 'private input, draft or unqualified privacy prevents content access')
            if operation == 'tabs.input':
                result = self._input(broker, custody, pane, arguments)
                mode = custody['transport']
                return dict(target=target, pane=pane, transport=mode, fallback=mode == 'terminal', result=result)
            if operation == 'tabs.capture':
                if 'lines' not in arguments:
                    capture = getattr(transport, 'visible_screen', None)
                    if capture is None:
                        raise InventoryError('unsupported_target', 'presentation has no visible-screen capture adapter')
                    text = capture(pane, deadline)
                else:
                    lines = arguments['lines']
                    if type(lines) is not int or not 1 <= lines <= 200:
                        raise InventoryError('invalid_argument', 'scrollback must be between 1 and 200 lines')
                    if not hasattr(transport, 'capture'):
                        raise InventoryError('unsupported_target', 'presentation has no bounded capture adapter')
                    text = transport.capture(pane, lines, deadline)
                return dict(target=target, pane=pane, text=text[-32768:], truncated=len(text) > 32768,
                            transport='terminal', fallback=True, input_custody=custody)
            owner = TabOrganization(self.root, transport=transport, observer=config.get('observer'),
                                    authorize=lambda action: None)
            try:
                if operation == 'tabs.preview':
                    return dict(target=lifecycle_target, **owner.preview(mode=arguments.get('mode','activity'), pins=arguments.get('pins',[]), criteria=arguments.get('criteria',[]), deadline=deadline))
                if operation == 'tabs.apply':
                    return dict(target=lifecycle_target, **owner.apply(arguments['plan_id'], deadline=deadline))
                return dict(target=lifecycle_target, **owner.undo(arguments['receipt_id'], deadline=deadline))
            except TabError as error:
                raise InventoryError(error.code, str(error)) from error
        from .bot_families import BotFamilies
        BotFamilies(self.root,tabs=self).annotate(resources)
        value = dict(resources=resources)
        if unavailable:
            value['unavailable'] = unavailable
        if hasattr(self, 'discovery_diagnostics'):
            value['discovery'] = dict(source='automatic', status='ready' if resources else 'not_found',
                                     diagnostics=self.discovery_diagnostics,
                                     message='Existing owned workspaces discovered.' if resources else
                                     'No live owned workspace found; start Byobu/tmux or register a supported psmux bridge, then refresh.')
        return value

    def recovery_target(self):
        from pathlib import Path
        return dict(host=self.host,environment=self.environment,workspace='@recovery',presentation='logical',
                    generation=digest(str(Path(self.root).resolve())))

    def policy_target(self):
        from .tab_organization_policy import TabOrganizationPolicy
        state=TabOrganizationPolicy(self.root,workspaces=self.workspaces).execute('tabs.policy.status',{})['policy']
        return dict(host=self.host,environment=self.environment,workspace='@policy',presentation='logical',generation=str(state.get('control_revision',0)))

    def monitor_target(self):
        from .tab_monitor import TabMonitor
        monitor=TabMonitor(self.root).execute('tabs.monitor.status',{})['monitor']
        return dict(host=self.host,environment=self.environment,workspace='@monitor',presentation='logical',
                    generation=digest(dict(generation=monitor.get('generation'),status=monitor['status'],process=monitor.get('process'))))

    def logical_target(self):
        from .tab_views import TabViews
        return dict(host=self.host,environment=self.environment,workspace='@views',
                    presentation='logical',generation=digest(TabViews(self.root)._read()))

    @staticmethod
    def _pane(snapshot, pane, window):
        windows = [row for row in snapshot['windows'] if window is None or row['window_id'] == window]
        panes = {row['pane_id'] for tab in windows for row in tab['panes']}
        if pane is not None:
            if pane not in panes:
                raise InventoryError('stale_target', 'pane is absent from pinned presentation')
            return pane
        if not windows:
            raise InventoryError('stale_target', 'tab is absent from pinned presentation')
        if len(windows) != 1 or len(panes) != 1:
            raise InventoryError('ambiguous_target', 'select an exact pane for this presentation')
        return next(iter(panes))

    @staticmethod
    def _input(broker, custody, pane, arguments):
        from .unified_terminal import KEY_TOKENS

        if not broker or not custody.get('available') or arguments.get('custody') != custody:
            raise InventoryError('input_custody_required', 'host broker ownership generation required')
        transport = arguments.get('transport')
        if transport not in ('structured', 'terminal') or transport != custody.get('transport'):
            raise InventoryError('unsupported_transport', 'fallback requires explicit owned transport selection')
        mode = arguments.get('mode')
        text = arguments.get('input')
        if transport == 'structured' and mode is None:
            if 'keys' in arguments or not isinstance(text, str) or not text or len(text.encode()) > 16384:
                raise InventoryError('invalid_argument', 'input must be bounded text')
            return broker.send(pane, text, expected_custody=custody)
        if mode is None:
            mode = 'paste'
        if mode not in ('paste', 'keys'):
            raise InventoryError('invalid_argument', 'input mode must be paste or keys')
        if transport != 'terminal' or mode not in custody.get('input_modes', []):
            raise InventoryError('unsupported_transport', 'broker does not support this explicit terminal action')
        if mode == 'paste' and 'keys' not in arguments:
            if (not isinstance(text, str) or not text or len(text.encode()) > 16384
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in text)):
                raise InventoryError('invalid_argument', 'paste requires bounded literal text without control characters')
            return broker.paste(pane, text, expected_custody=custody)
        if mode == 'keys' and 'input' not in arguments:
            keys = arguments.get('keys')
            if (not isinstance(keys, list) or not 1 <= len(keys) <= 32
                    or any(not isinstance(key, str) or key not in KEY_TOKENS for key in keys)):
                raise InventoryError('invalid_argument', 'keys requires a bounded list of supported terminal key names')
            return broker.keys(pane, keys, expected_custody=custody)
        raise InventoryError('invalid_argument', 'input payload must match the explicit terminal mode')


class AuthorizedTabs:
    """ProtectedOperations plugin using existing durable operation admission."""
    def __init__(self, authority, tabs, runtime):
        self.authority, self.tabs, self.runtime = authority, tabs, runtime

    def execute(self, token, operation, arguments):
        from .controller_auth import AuthError
        actor = self.authority.authenticate(token)
        arguments=dict(arguments)
        if operation=='tabs.create':
            from .terminal_launch_defaults import prepare
            arguments=prepare(self.tabs,arguments)
        if 'control' not in actor.scopes:
            raise AuthError('insufficient_scope')
        target = arguments.get('expected_target') if isinstance(arguments, dict) else None
        required = {'host','environment','workspace','presentation'}
        targets=[target]
        if operation in ('tabs.move','tabs.park','tabs.restore','tabs.reattach-preview'):
            targets.append(arguments.get('expected_destination'))
        if operation in ('tabs.reattach-apply','tabs.reattach-status'):
            targets += self.tabs.reattach_owner().authorization_targets(arguments.get('plan_id'))
        for selected in targets:
            if not isinstance(selected,dict) or not (required|{'generation'})<=selected.keys() or not any(
                    required<=scope.keys() and all(selected.get(k)==v for k,v in scope.items()) for scope in actor.targets):
                raise AuthError('insufficient_scope')
        from .terminal_launch_defaults import session_profile
        profile=arguments.get('profile') if operation in ('tabs.create','tabs.family.open') else session_profile(self.tabs,operation,arguments)
        if profile and not actor.issuer.startswith('local://uid/'):
            from .controller_http import permitted
            if not permitted(actor,self.tabs.profile_owner().authorization_target(profile)):
                raise AuthError('insufficient_scope')
        def authorize():
            current = self.authority.authenticate(token)
            if current != actor: raise AuthError()
            return current
        def dispatch(operation,payload):
            if operation in ('tabs.destroy', 'tabs.unlink'):
                from .tab_lifecycle import TabLifecycle
                def authorize_appearances(affected):
                    current = authorize()
                    if 'control' not in current.scopes:
                        raise AuthError('insufficient_scope')
                    if current.issuer.startswith('local://uid/'):
                        return
                    for resource in affected:
                        if not any(required <= scope.keys() and all(resource.get(k) == v for k, v in scope.items())
                                   for scope in current.targets):
                            raise AuthError('insufficient_scope')
                owner = TabLifecycle(self.tabs.root, workspaces=self.tabs.workspaces,
                                     host=self.tabs.host, environment=self.tabs.environment)
                return owner.execute(operation, payload, authorize_appearances=authorize_appearances)
            if operation=='tabs.create':return self.tabs.create_tab(payload,defaults_resolved=True)
            if operation in ('tabs.format.override-set', 'tabs.format.override-clear'):
                from .tab_formatting import TabFormatting
                def authorize_linked(appearances):
                    current = authorize()
                    if current.issuer.startswith('local://uid/'):
                        return
                    if any(not any(required <= scope.keys() and all(
                            appearance.get(key) == value for key, value in scope.items())
                            for scope in current.targets) for appearance in appearances):
                        raise AuthError('insufficient_scope')
                return TabFormatting(self.tabs.root, tabs=self.tabs).override(
                    operation.removeprefix('tabs.format.'), payload, authorize_linked=authorize_linked)
            return self.tabs.execute(operation,payload)
        return self.runtime.execute(actor, operation, arguments, authorize=authorize, dispatch=dispatch)


def _restore_terminal_sessions(owner):
    from .terminal_sessions import TerminalSessions
    TerminalSessions(owner.root,tabs=owner)
    from .tab_traits import WorkspaceTraitsObserver
    for workspace in owner.workspaces.values():
        if 'observer' not in workspace:
            workspace['observer']=WorkspaceTraitsObserver(owner.root,workspace['transport'],workspace.get('privacy'))
    return owner


def controller_tabs_from_root(root, *, host=None, environment=None):
    """Construct host-owned adapters from fixed private controller-tabs.json.

    Production content privacy is unknown by default. Disposable fixture
    qualification may explicitly declare safe input; this never changes a native
    privacy observer or grants access to production terminal content.
    """
    import json
    import os
    import socket
    import stat
    from pathlib import Path
    from .controller_tab_adapters import (TmuxAttachmentTransport,
        PsmuxAttachmentTransport, ConfiguredBridge, UnixInputBroker, UnavailableAttachmentTransport)
    from .shortcut_store import default_root
    root = default_root(root)
    path = root / 'controller-tabs.json'
    try:
        fd = os.open(path,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        from .tab_workspace_discovery import discover
        workspaces, diagnostics = discover()
        owner = ControllerTabs(root,workspaces=workspaces,host=host or socket.gethostname(),
                               environment=environment or os.environ.get('WSL_DISTRO_NAME') or os.name,host_managed=True)
        from .tab_traits import WorkspaceTraitsObserver
        for workspace in workspaces.values():
            workspace['observer']=WorkspaceTraitsObserver(root,workspace['transport'],workspace.get('privacy'))
        owner.discovery_diagnostics = diagnostics
        return _restore_terminal_sessions(owner)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise InventoryError('configuration_unavailable','host attachment configuration must be private')
        with os.fdopen(os.dup(fd)) as stream:
            raw = stream.read(262145)
        if len(raw)>262144: raise ValueError('configuration exceeds bound')
        try:
            config = json.loads(raw)
        except ValueError:
            raise InventoryError('configuration_unavailable', 'Tab configuration is invalid; repair the selected controller configuration.') from None
    finally:
        os.close(fd)
    if config.get('schema_version') != 1 or not isinstance(config.get('workspaces'),dict):
        raise ValueError('unsupported attachment configuration')
    workspaces = {}
    for name,row in config['workspaces'].items():
        kind = row['kind']
        if kind in ('tmux','byobu'):
            try:transport = TmuxAttachmentTransport(row['socket_path'],row['session_id'])
            except FileNotFoundError:transport = UnavailableAttachmentTransport()
        elif kind in ('psmux','stdio'):
            transport = PsmuxAttachmentTransport(ConfiguredBridge(row['bridge_command']),generation=row['bridge_generation'])
        else:
            raise ValueError('unsupported host presentation')
        workspace = dict(kind=kind,transport=transport)
        if kind in ('tmux','byobu'):
            workspace.update(socket_path=row['socket_path'], session_id=row['session_id'])
        if row.get('input_broker_socket'):
            workspace['broker'] = UnixInputBroker(row['input_broker_socket'])
        if row.get('evidence_scope') == 'disposable_fixture' and row.get('privacy') == 'safe':
            workspace['privacy'] = lambda pane:'safe'
        from .tab_traits import WorkspaceTraitsObserver
        workspace['observer']=WorkspaceTraitsObserver(root,transport,workspace.get('privacy'))
        workspaces[name] = workspace
    return _restore_terminal_sessions(ControllerTabs(root,workspaces=workspaces,host=host or socket.gethostname(),
                          environment=environment or os.environ.get('WSL_DISTRO_NAME') or os.name,host_managed=True))
