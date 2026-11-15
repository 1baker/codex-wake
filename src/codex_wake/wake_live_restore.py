"""Resume an exact live-mode recipient through the existing durable resume owner.

The host-owned mapping selects existing private profiles; it grants no operation.
Ephemeral _wake_* context is supplied by dispatch from the admitted wake record,
never by model registration arguments or a saved target field.
"""
from pathlib import Path
import time
from uuid import UUID

from .agent_resume import SavedRuntime
from .runtime_delivery import RuntimeTargetError
from .records import WakeError


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

    def _configuration(self, thread_id):
        from .wake_policy import _read
        from .agent_resume_commands import load_profiles
        try:
            value = _read(self.root / 'wake-live-restore.json')
            if type(value) is not dict or set(value) != {'version', 'bindings'} or type(value['version']) is not int or value['version'] != 1:
                raise ValueError
            binding = value['bindings'][thread_id]
            if type(binding) is not dict or set(binding) != {'profiles', 'managed_agent_id', 'profile'}:
                raise ValueError
            profiles = Path(binding['profiles'])
            if not profiles.is_absolute():
                raise ValueError
            return binding, load_profiles(profiles)
        except (WakeError, OSError, ValueError, KeyError, TypeError):
            raise RuntimeTargetError('unavailable', 'live_restore_configuration_required') from None

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
        if agent['conversation_id'] != target['thread_id'] or agent['runtime'] != 'codex':
            raise RuntimeTargetError('unavailable', 'live_restore_managed_identity_changed')
        profile = config['profiles'][binding['profile']]
        if target.get('tmux_socket') is not None and profile.get('tmux_socket') != target['tmux_socket']:
            raise RuntimeTargetError('unavailable', 'live_restore_terminal_server_changed')
        latest = dict(target, endpoint=profile['app_server'],
                      codex_cmd=resolve_codex_cmd(profile['codex_path'], required=True, preserve_launcher=True))
        thread = read_codex_thread(latest)
        if thread.get('id') != target['thread_id'] or thread.get('cwd') != profile.get('cwd') or profile.get('cwd') != agent['root']:
            raise RuntimeTargetError('unavailable', 'live_restore_workspace_unverified')
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

        owner = AgentResume(self.root, config, runtime=_RestoreRuntime(self.root, now=self.now),
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


class _RestoreRuntime(SavedRuntime):
    """Reopen a host-declared terminal container before the existing exact resume.

    AgentResume journals the launch before entering this method, so lost session
    creation responses retain the same crash fence as lost tab creation responses.
    """
    def __init__(self, root, *, now=None):
        super().__init__(now=now)
        self.root = root

    def launch(self, record, profile, guard, name):
        from types import SimpleNamespace
        from .session_lifecycle import tmux_command
        runtime = SimpleNamespace(**({'tmux_socket': None} | profile), effect_guard=guard)
        try:
            tmux_command(runtime, 'has-session', '-t', profile['tmux_session'])
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
                server=socket, start=True, defaults=dict(cwd=profile['cwd'])))
        return super().launch(record, profile, guard, name)
