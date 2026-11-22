"""Resume an exact live-mode recipient through the existing durable resume owner.

The host-owned mapping selects existing private profiles; it grants no operation.
Ephemeral _wake_* context is supplied by dispatch from the admitted wake record,
never by model registration arguments or a saved target field.
"""
import os
from pathlib import Path
import time
from uuid import UUID

from .agent_resume import SavedRuntime, fingerprint, resume_profile
from .runtime_delivery import RuntimeTargetError
from .records import WakeError
from .wake_restore_placement import capture_placement, launch_placed, valid_placement


PINNED_IDENTITY_FIELDS = {
    'conversation_id', 'harness', 'cwd', 'namespace', 'codex_home',
    'home_generation', 'account', 'profile_sha256',
}


class LiveWakeRestorer:
    def __init__(self, root, *, now=None):
        self.root = Path(root)
        self.now = now

    def prepare(self, target):
        from .sessions import observe, revalidate_attachment
        try:
            if target.get('session_mode') != 'reopen_live' or str(UUID(target['thread_id'])) != target['thread_id']:
                raise RuntimeTargetError('unavailable', 'live_recipient_identity_unverified')
            snapshot = observe(endpoint=target['endpoint'], socket_path=target.get('tmux_socket'), timeout=5)
            rows = [row for row in snapshot.get('sessions', []) if row.get('thread_id') == target['thread_id']]
            ambiguous = any(target['thread_id'] in row.get('candidates', []) for row in snapshot.get('sessions', []))
            if not snapshot.get('complete'):
                from .wake_mode_runtime import observe_mode_presence
                if observe_mode_presence(target) != 'background':
                    raise RuntimeTargetError('unavailable', 'live_recipient_ownership_unverified')
            if len(rows) > 1 or ambiguous:
                raise RuntimeTargetError('unavailable', 'live_recipient_ownership_unverified')
            if rows and rows[0].get('attachments'):
                row = rows[0]
                if (row.get('binding_status') != 'metadata_matched' or len(row['attachments']) != 1
                        or not revalidate_attachment(row['attachments'][0])):
                    raise RuntimeTargetError('unavailable', 'live_recipient_ownership_unverified')
                return dict(target, startup_policy='active_tab', resume_policy='hold')
            return self._restore(target)
        except RuntimeTargetError:
            raise
        except (WakeError, OSError, ValueError, KeyError, TypeError):
            raise RuntimeTargetError('unavailable', 'live_restore_unavailable') from None

    @property
    def binding_path(self):
        return self.root / 'wake-live-restore.json'

    def _bindings(self):
        from .wake_policy import _read
        value = _read(self.binding_path)
        if (type(value) is not dict or set(value) != {'version', 'bindings'}
                or type(value['version']) is not int or value['version'] != 1
                or type(value['bindings']) is not dict):
            raise WakeError('live_restore_configuration_invalid')
        return value

    def _configuration(self, thread_id):
        from .agent_resume_commands import load_profiles
        try:
            binding = self._bindings()['bindings'][thread_id]
            required = {'profiles', 'managed_agent_id', 'profile'}
            if type(binding) is not dict or set(binding) not in (
                    required, required | {'identity'}, required | {'identity', 'placement'}):
                raise ValueError
            profiles = Path(binding['profiles'])
            if not profiles.is_absolute():
                raise ValueError
            config = load_profiles(profiles)
        except (WakeError, OSError, ValueError, KeyError, TypeError):
            raise RuntimeTargetError('unavailable', 'live_restore_configuration_required') from None
        if 'placement' in binding and not valid_placement(binding['placement']):
            raise RuntimeTargetError('unavailable', 'live_restore_placement_invalid')
        if 'identity' in binding:
            profile = resume_profile(config, binding['profile'])
            identity = binding['identity']
            if (not isinstance(identity, dict) or set(identity) not in (
                        PINNED_IDENTITY_FIELDS, PINNED_IDENTITY_FIELDS | {'provider_account_sha256'})
                    or identity.get('profile_sha256') != fingerprint(profile)
                    or identity.get('conversation_id') != thread_id or identity.get('harness') != 'codex'
                    or identity.get('cwd') != profile['cwd']):
                raise RuntimeTargetError('unavailable', 'live_restore_pinned_profile_changed')
            if _home_generation(identity['codex_home']) != identity['home_generation']:
                raise RuntimeTargetError('unavailable', 'live_restore_account_home_changed')
            if 'provider_account_sha256' in identity:
                if _provider_account_fingerprint(identity) != identity['provider_account_sha256']:
                    raise RuntimeTargetError('unavailable', 'live_restore_provider_account_changed')
        return binding, config

    def inspect(self, target):
        from .managed_inventory import ManagedInventory
        if target['session_mode'] != 'reopen_live':
            return dict(status='not_required')
        try:
            binding, config = self._configuration(target['thread_id'])
            profile = resume_profile(config, binding['profile'])
            if not (self.root / 'managed-inventory' / 'inventory.json').exists():
                raise WakeError('live_restore_managed_identity_unavailable')
            inventory = ManagedInventory(self.root, now=self.now)
            agent = inventory.inspect(binding['managed_agent_id'])['agent']
            self._validate_binding(target, agent, profile)
        except RuntimeTargetError as error:
            return dict(status='blocked', reason=error.reason)
        except (WakeError, OSError, ValueError, TypeError, KeyError) as error:
            return dict(status='blocked', reason=getattr(error, 'code', None) or 'live_restore_binding_unavailable')
        identity = binding.get('identity')
        return dict(status='configured' if identity else 'configured_legacy',
                    conversation_id=agent['conversation_id'], harness=agent['runtime'],
                    cwd=profile['cwd'], profile=binding['profile'],
                    account=dict(status='home_pinned' if identity else 'unpinned',
                                 name=identity['account'] if identity else None,
                                 provider_identity='cached_match' if identity and 'provider_account_sha256' in identity
                                 else 'unverified',
                                 codex_home=identity['codex_home'] if identity else profile.get('codex_home')),
                    managed_agent_id=binding['managed_agent_id'],
                    placement=binding.get('placement'))

    @staticmethod
    def _validate_binding(target, agent, profile):
        if (agent['conversation_id'] != target['thread_id'] or agent['runtime'] != 'codex'
                or agent['enrollment'] != 'enrolled'):
            raise RuntimeTargetError('unavailable', 'live_restore_managed_identity_changed')
        if target.get('tmux_socket') is not None and profile.get('tmux_socket') != target['tmux_socket']:
            raise RuntimeTargetError('unavailable', 'live_restore_terminal_server_changed')
        if profile['cwd'] != agent['root']:
            raise RuntimeTargetError('unavailable', 'live_restore_workspace_unverified')

    def bind(self, target, *, profiles, managed_agent_id, profile, authorize):
        from .agent_resume_commands import load_profiles
        from .managed_inventory import ManagedInventory
        from .records import WakeLifecycleLock
        from .wake_policy import _write
        if target['session_mode'] != 'reopen_live':
            raise WakeError('live_restore_reopen_live_required')
        profiles = Path(profiles)
        if not profiles.is_absolute():
            raise WakeError('live_restore_absolute_profiles_path_required')
        with WakeLifecycleLock(self.root, 'wake-live-restore'):
            try:
                saved = self._bindings()
            except FileNotFoundError:
                saved = dict(version=1, bindings={})
            config = load_profiles(profiles)
            selected = resume_profile(config, profile)
            agent = ManagedInventory(self.root, now=self.now).inspect(managed_agent_id)['agent']
            self._validate_binding(target, agent, selected)
            from .app_server import resolve_codex_cmd
            selected_cmd = resolve_codex_cmd(selected['codex_path'], required=True, preserve_launcher=True)
            if (selected_cmd != target['codex_cmd']
                    or target['endpoint'] not in ('unix://', selected['app_server'])):
                raise WakeError('live_restore_selected_harness_changed')
            observed = _saved_identity(agent, selected)
            if observed['namespace'] != agent['namespace']:
                raise WakeError('live_restore_managed_identity_changed')
            observed['profile_sha256'] = fingerprint(selected)
            entry = dict(profiles=str(profiles), managed_agent_id=managed_agent_id,
                         profile=profile, identity=observed)
            placement = capture_placement(target['thread_id'], selected)
            previous = saved['bindings'].get(target['thread_id'], {})
            if placement:
                entry['placement'] = placement
            elif previous.get('identity') == observed and valid_placement(previous.get('placement')):
                entry['placement'] = previous['placement']
            saved['bindings'][target['thread_id']] = entry
            authorize()
            _write(self.binding_path, saved)

    def _restore(self, target):
        from .agent_resume import AgentResume
        from .app_server import resolve_codex_cmd
        from .codex_runtime import read_codex_thread
        from .managed_inventory import ManagedInventory
        from .permission_wake import valid_context
        from .records import parse_timestamp
        from .session_permissions import Principal, check_operation
        binding, config = self._configuration(target['thread_id'])
        context = target.get('_wake_permission_context')
        if not valid_context(context) or context['target'] != target['thread_id']:
            raise RuntimeTargetError('unavailable', 'live_restore_permission_context_required')
        principal = Principal(context['subject'], context['role'], tuple(context['tasks']))
        occurrence = target.get('_wake_occurrence_id')
        expires = target.get('_wake_expires_at')
        if not isinstance(occurrence, str) or not occurrence or not isinstance(expires, str):
            raise RuntimeTargetError('unavailable', 'live_restore_original_deadline_required')
        parse_timestamp(expires)
        kwargs = dict(now=self.now) if self.now is not None else {}
        inventory = ManagedInventory(self.root, **kwargs)
        agent = inventory.inspect(binding['managed_agent_id'])['agent']
        profile = resume_profile(config, binding['profile'])
        self._validate_binding(target, agent, profile)
        pinned = binding.get('identity')
        latest = dict(target, endpoint=profile['app_server'],
                      codex_cmd=resolve_codex_cmd(profile['codex_path'], required=True, preserve_launcher=True))
        thread = read_codex_thread(latest)
        if thread.get('id') != target['thread_id'] or thread.get('cwd') != profile.get('cwd') or profile.get('cwd') != agent['root']:
            raise RuntimeTargetError('unavailable', 'live_restore_workspace_unverified')
        if _requires_provider_account(thread, agent, profile) and not (
                pinned and pinned.get('provider_account_sha256')):
            raise RuntimeTargetError('unavailable', 'live_restore_provider_account_binding_required')
        state = thread.get('status', {}).get('type')
        if state == 'active':
            raise RuntimeTargetError('busy', 'live_restore_background_check_running')
        if state not in ('idle', 'notLoaded'):
            raise RuntimeTargetError('unavailable', 'live_restore_runtime_state_unverified')
        check_operation(self.root, 'wake.new_tab', principal, target=target['thread_id'],
                        task_id=context['task_id'])

        def current_config():
            check_operation(self.root, 'wake.new_tab', principal, target=target['thread_id'],
                            task_id=context['task_id'])
            current_binding, current = self._configuration(target['thread_id'])
            if current_binding != binding:
                raise WakeError('live_restore_binding_changed')
            return current

        owner = AgentResume(self.root, config, runtime=_RestoreRuntime(self.root, now=self.now, identity=pinned,
                                                                       placement=binding.get('placement')),
                            config_loader=current_config, **kwargs)
        arguments = dict(managed_agent_id=binding['managed_agent_id'], profile=binding['profile'],
                         intent='wake-live:' + occurrence, expires_at=expires)
        deadline = time.monotonic() + profile['timeout']
        result = owner.resume(arguments, principal)
        # tmux acknowledges window creation before its frontend connects. Reuse
        # the same journaled intent: AgentResume reconciles its one launch and
        # never repeats an ambiguous effect. Keep the original expiry unchanged.
        while (result.get('status') in ('starting', 'uncertain')
                and result.get('effects_attempted') == 1
                and time.monotonic() < deadline and owner.now() < parse_timestamp(expires).timestamp()):
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            result = owner.resume(arguments, principal)
        if result.get('status') != 'resumed':
            raise RuntimeTargetError('unavailable', result.get('reason') or 'live_restore_not_confirmed')
        if result.get('conversation_id') != target['thread_id']:
            raise RuntimeTargetError('unavailable', 'live_restore_recipient_changed')
        # AgentResume re-reads profiles and checks common permissions before every
        # terminal command; it keeps uncertain launches fenced across restarts.
        return dict(latest, startup_policy='active_tab', resume_policy='hold')


def _home_generation(home):
    if not isinstance(home, str):
        raise RuntimeTargetError('unavailable', 'live_restore_account_home_unavailable')
    path = Path(home)
    try:
        info = path.stat()
    except OSError:
        raise RuntimeTargetError('unavailable', 'live_restore_account_home_unavailable') from None
    if not path.is_absolute() or path != path.resolve() or not path.is_dir() or info.st_uid != os.geteuid():
        raise RuntimeTargetError('unavailable', 'live_restore_account_home_unavailable')
    return f'{info.st_dev}:{info.st_ino}'


def _saved_identity(agent, profile):
    from .a2a_identity import RuntimeIdentity
    from .shared_app_server import SharedAppServerReader
    with SharedAppServerReader(profile['app_server'], timeout=profile['timeout']) as reader:
        thread = reader.read_thread(agent['conversation_id'])
        identity = RuntimeIdentity.from_metadata(thread, reader.server_metadata)
        codex_home = reader.server_metadata.get('codexHome')
        if (identity.thread_id != agent['conversation_id'] or identity.cwd != profile['cwd']
                or profile.get('codex_home', codex_home) != codex_home):
            raise RuntimeTargetError('unavailable', 'live_restore_saved_identity_changed')
        saved = dict(conversation_id=identity.thread_id, harness='codex', cwd=identity.cwd,
                     namespace=identity.namespace, codex_home=codex_home,
                     home_generation=_home_generation(codex_home),
                     account=agent.get('profile') or Path(codex_home).name)
        if _requires_provider_account(thread, agent, profile):
            saved['provider_account_sha256'] = _provider_account_fingerprint(saved)
        return saved


def _requires_provider_account(thread, agent, profile):
    return thread.get('modelProvider') == 'openai' and bool(agent.get('profile') or profile.get('codex_home'))


def _provider_account_fingerprint(identity):
    from .account_observation import cached_account_fingerprint
    observed = cached_account_fingerprint(Path(identity['codex_home']), identity['home_generation'])
    if not observed:
        raise RuntimeTargetError('unavailable', 'live_restore_provider_account_unavailable')
    return observed


class _RestoreRuntime(SavedRuntime):
    """Reopen a host-declared terminal container before the existing exact resume.

    AgentResume journals the launch before entering this method, so lost session
    creation responses retain the same crash fence as lost tab creation responses.
    """
    def __init__(self, root, *, now=None, identity=None, placement=None):
        super().__init__(now=now)
        self.root = root
        self.pinned_identity = identity
        self.placement = placement

    def identity(self, record, profile):
        if self.pinned_identity is None:
            return super().identity(record, profile)
        from .agent_resume import ResumeError
        try:
            observed = _saved_identity(record, profile)
        except RuntimeTargetError as error:
            raise ResumeError(error.reason) from None
        if observed != {key: value for key, value in self.pinned_identity.items() if key != 'profile_sha256'}:
            raise ResumeError('live_restore_saved_identity_changed')
        return dict(runtime='codex', namespace=observed['namespace'],
                    conversation_id=observed['conversation_id'], root=observed['cwd'])


    def launch(self, record, profile, guard, name):
        from types import SimpleNamespace
        from .session_lifecycle import tmux_command
        if self.pinned_identity is not None:
            profile = dict(profile, codex_home=self.pinned_identity['codex_home'])
        if self.placement is not None:
            profile = dict(profile, tmux_session=self.placement['session'])
        runtime = SimpleNamespace(**({'tmux_socket': None} | profile), effect_guard=guard)
        recreated = False
        try:
            tmux_command(runtime, 'has-session', '-t', '=' + profile['tmux_session'])
        except WakeError:
            socket = profile.get('tmux_socket')
            if not isinstance(socket, str) or not Path(socket).is_absolute():
                raise RuntimeTargetError('unavailable', 'live_restore_terminal_server_required')
            # The fixed host attachment configuration authorizes which server is
            # managed. It is not inferred from a name or the daemon environment.
            from .wake_policy import _read
            host = _read(self.root / 'controller-tabs.json')
            workspaces = host.get('workspaces', {})
            if host.get('schema_version') != 1 or not any(
                    row.get('kind') in ('tmux', 'byobu') and row.get('socket_path') == socket
                    for row in workspaces.values()):
                raise RuntimeTargetError('unavailable', 'live_restore_terminal_server_unqualified')
            from .controller_tabs import controller_tabs_from_root
            from .terminal_sessions import TerminalSessions
            guard()
            tabs = controller_tabs_from_root(self.root)
            sessions = TerminalSessions(self.root, tabs=tabs)
            sessions.execute('tabs.session.ensure', dict(name=profile['tmux_session'], backend='byobu',
                server=socket, start=True, defaults=dict(cwd=profile['cwd'])), container_only=True)
            recreated = True
        from .tab_restore_marker import mark_restored, read_launched_placement
        launcher = super().launch
        if self.placement is None:
            actual = launcher(record, profile, guard, name)
            try:
                actual = read_launched_placement(tmux_command, runtime, actual) or actual
            except WakeError:
                pass
        else:
            actual = launch_placed(tmux_command, runtime, self.placement, record['root'],
                                   lambda title, target: launcher(record, profile, guard, title,
                                                                  window_target=target), recreated=recreated)
        if isinstance(actual, dict):
            try:
                mark_restored(tmux_command, runtime, actual)
            except WakeError:
                # Presentation failure must preserve the acknowledged launch receipt.
                pass
        return actual
