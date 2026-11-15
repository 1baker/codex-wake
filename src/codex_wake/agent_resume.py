"""Crash-safe exact-conversation resume; never submits work or renews allowance."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shlex
from types import SimpleNamespace

from .goal_supervision import _lock, _private, _save
from .managed_inventory import ManagedInventory, InventoryError
from .records import WakeError, parse_timestamp
from .session_permissions import PermissionStore, Principal, PermissionDenied, check_operation


class ResumeError(WakeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class SavedRuntime:
    """Existing owned Unix protocol plus exact terminal/process observation."""
    def __init__(self, *, binding_source=None, terminal=None, now=None):
        from .lifecycle_budget import trusted_upper
        self.now = now or trusted_upper
        self.binding_source = binding_source
        self.terminal = terminal

    def identity(self, record, profile):
        from .shared_app_server import SharedAppServerReader
        from .a2a_identity import RuntimeIdentity
        with SharedAppServerReader(profile['app_server'], timeout=profile['timeout']) as reader:
            thread = reader.read_thread(record['conversation_id'])
            identity = RuntimeIdentity.from_metadata(thread, reader.server_metadata)
        return dict(runtime='codex', namespace=identity.namespace,
                    conversation_id=identity.thread_id, root=identity.cwd)

    def binding(self, record, profile):
        if self.binding_source is not None:
            return self.binding_source(record, profile)
        from .managed_inventory_commands import RuntimeObserver
        sample = RuntimeObserver(endpoint=profile['app_server'], socket_path=profile.get('tmux_socket'),
                                 timeout=profile['timeout'], now=self.now)({'conversation_id': record['conversation_id']})
        if not sample.attachments and sample.capabilities.get('saved_resume') != 'supported':
            raise InventoryError('identity_unavailable', 'saved recovery requires native notLoaded evidence')
        return sample

    def launch(self, record, profile, guard, name):
        from .app_server import resolve_codex_cmd
        from .session_lifecycle import tmux_command
        from .sessions import explicit_terminal_absent
        terminal = self.terminal or tmux_command
        runtime = SimpleNamespace(**({'tmux_socket': None} | profile), effect_guard=guard)
        absent = explicit_terminal_absent(profile.get('tmux_socket'))
        if not absent:
            terminal(runtime, 'has-session', '-t', profile['tmux_session'])
        codex = resolve_codex_cmd(profile['codex_path'], required=True)
        argv = ['env', '-u', 'CODEX_THREAD_ID', '-u', 'TMUX_PANE']
        if profile.get('codex_home'):
            argv.append('CODEX_HOME=' + profile['codex_home'])
        argv += [codex, 'resume', '--no-alt-screen', '-C', record['root'],
                 record['conversation_id'], '--remote', profile['app_server']]
        if absent:
            # One atomic create with the saved recipient as its only window;
            # a competing creator fails rather than attaching or duplicating.
            return terminal(runtime, 'new-session', '-d', '-P', '-F', '#{window_id}\t#{pane_id}',
                            '-s', profile['tmux_session'], '-n', name, '-c', record['root'], shlex.join(argv))
        return terminal(runtime, 'new-window', '-d', '-P', '-F', '#{window_id}\t#{pane_id}',
                        '-t', profile['tmux_session'] + ':', '-n', name, '-c', record['root'], shlex.join(argv))


class AgentResume:
    def __init__(self, root, config, *, runtime=None, now=None, config_loader=None):
        from .lifecycle_budget import trusted_upper
        self.inventory = ManagedInventory(root, now=now or trusted_upper)
        self.root, self.config = self.inventory.root, config
        self.config_loader = config_loader
        self.now = now or trusted_upper
        self.runtime = runtime or SavedRuntime(now=self.now)
        self.directory = self.root / 'agent-resume'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        _private(self.directory, True)

    def _profile(self, name):
        try:
            p = self.config['profiles'][name]
            required = {'cwd', 'app_server', 'codex_path', 'tmux_session', 'timeout'}
            if (self.config['version'] != 1 or not required <= set(p)
                    or set(p) - required - {'tmux_socket', 'codex_home', 'resources', 'strict_execution'}):
                raise ValueError
            for key in required - {'timeout'} | (set(p) & {'tmux_socket', 'codex_home'}):
                if not isinstance(p[key], str) or not p[key] or any(ord(c)<32 for c in p[key]):raise ValueError
            if (type(p['timeout']) not in (int,float) or not math.isfinite(p['timeout'])
                    or not 0 < p['timeout'] <= 30 or not p['app_server'].startswith('unix:///')
                    or not Path(p['codex_path']).is_absolute()
                    or Path(p['cwd']).resolve() != Path(p['cwd']) or not Path(p['cwd']).is_dir()):raise ValueError
            if 'strict_execution' in p:
                # Restarting a contained executor is a separate recovery operation.
                raise ResumeError('resume_strict_executor_recovery_unqualified')
            return p
        except (KeyError, TypeError, ValueError):
            raise ResumeError('resume_profile_unavailable') from None

    def _permission(self, principal, agent, profile, intent):
        if not isinstance(principal, Principal):raise ResumeError('resume_identity_unverified')
        recovery = principal.subject != agent['conversation_id']
        if recovery and (principal.role not in ('operator','controller') or
                agent['managed_agent_id'] not in self.config.get('recovery_callers',{}).get(principal.subject, [])):
            raise ResumeError('resume_recovery_authority_required')
        if not recovery and self.config.get('callers') and profile not in self.config['callers'].get(principal.subject, []):
            raise ResumeError('resume_profile_not_authorized')
        if not PermissionStore(self.root).active():raise ResumeError('resume_common_policy_required')
        return check_operation(self.root, 'resume.recover' if recovery else 'resume.self', principal, target=agent['conversation_id'],
                               launch_profile=profile, operation_id=intent, task_id=agent.get('task_id'))

    def resume(self, arguments, principal):
        for name in ('managed_agent_id', 'profile', 'intent', 'expires_at'):
            value = arguments.get(name)
            if not isinstance(value,str) or not value or len(value)>256 or any(ord(c)<32 for c in value):
                raise ResumeError('resume_invalid_argument')
        selected = {key: arguments[key] for key in ('managed_agent_id','profile','intent','expires_at')}
        if arguments.get('record_sha256') is not None:selected['record_sha256']=arguments['record_sha256']
        key = fingerprint(arguments['intent'])
        path = self.directory / (key + '.json')
        # Agent-wide custody prevents competing intents from racing a new attachment.
        with _lock(self.directory, 'intent-'+key), _lock(self.directory, 'agent-'+fingerprint(arguments['managed_agent_id'])):
            agent = self.inventory.inspect(arguments['managed_agent_id'])['agent']
            if agent['enrollment'] != 'enrolled':raise ResumeError('resume_agent_suppressed')
            if agent['runtime'] != 'codex':raise ResumeError('resume_runtime_unsupported')
            profile = self._profile(arguments['profile'])
            if profile['cwd'] != agent['root']:raise ResumeError('resume_workspace_changed')
            permission = self._permission(principal, agent, arguments['profile'], arguments['intent'])
            profile_hash = fingerprint(profile)
            def guard():
                if self.config_loader is not None:
                    self.config = self.config_loader()
                if fingerprint(self._profile(arguments['profile'])) != profile_hash:
                    raise ResumeError('resume_profile_changed')
                current = self.inventory.inspect(agent['managed_agent_id'])['agent']
                if current['enrollment'] != 'enrolled':raise ResumeError('resume_agent_suppressed')
                self._permission(principal, current, arguments['profile'], arguments['intent'])
                if self.now() >= parse_timestamp(arguments['expires_at']).timestamp():raise ResumeError('resume_expired')
            guard()
            expected = {key:agent[key] for key in ('runtime','namespace','conversation_id','root')}
            intent = dict(selected, subject=principal.subject, profile_sha256=fingerprint(profile))
            if path.exists():
                _private(path)
                receipt = json.loads(path.read_text())
                if receipt.get('version') != 1 or receipt.get('intent') != intent:
                    raise ResumeError('resume_intent_conflict')
            else:
                confirmed = [r for r in agent['history'] if r.get('event')=='binding_observed' and r.get('state')=='ready']
                if not confirmed:raise ResumeError('resume_no_confirmed_record')
                chosen = confirmed[-1]
                if 'record_sha256' in selected:
                    matches=[r for r in confirmed if fingerprint(r)==selected['record_sha256']]
                    if len(matches)!=1:raise ResumeError('resume_record_not_found')
                    chosen=matches[0]
                # An unresolved effect for this agent fences every differently keyed retry.
                for other in self.directory.glob('*.json'):
                    _private(other)
                    saved=json.loads(other.read_text())
                    if saved.get('managed_agent_id')==agent['managed_agent_id'] and saved.get('status') in ('starting','uncertain'):
                        raise ResumeError('resume_original_intent_required')
                receipt=dict(version=1,intent=intent,managed_agent_id=agent['managed_agent_id'],
                             conversation_id=agent['conversation_id'],status='prepared',
                             record_sha256=fingerprint(chosen),prior_process=chosen['process'],
                             permission_revision=permission.get('revision'),effects_attempted=0)
                _save(path,receipt)
            try:
                if self.runtime.identity(agent,profile)!=expected:raise ResumeError('resume_identity_changed')
                sample=self.runtime.binding(agent,profile)
                sample.validated(self.now())
                if {key:getattr(sample,key) for key in expected}!=expected:raise ResumeError('resume_identity_changed')
                if sample.state=='ambiguous':raise ResumeError('resume_binding_ambiguous')
                if sample.state=='ready':
                    # Positive current process observation, never the stored PID alone.
                    guard();self.inventory.reconcile(agent['managed_agent_id'],sample)
                    receipt.update(status='resumed',reason=None,process=sample.process)
                    _save(path,receipt);return self._public(receipt)
                if sample.attachments:
                    raise ResumeError('resume_existing_attachment_unqualified')
                if receipt['status'] in ('starting','uncertain','resumed') or receipt['effects_attempted']:
                    receipt.update(status='uncertain',reason='resume_binding_not_confirmed')
                    _save(path,receipt);return self._public(receipt)
                from .process import process_identity, process_exists
                prior = receipt['prior_process']
                generation = process_identity(prior['pid'])
                if generation is None and process_exists(prior['pid']):
                    raise ResumeError('resume_prior_process_unqualified')
                if (generation is not None and generation.get('boot_id') == prior['boot_id']
                        and generation.get('start_time_ticks') == prior['start_ticks']):
                    raise ResumeError('resume_prior_process_still_live')
                guard()
                receipt.update(status='starting',reason='resume_binding_not_confirmed',effects_attempted=1)
                _save(path,receipt)
                try:
                    self.runtime.launch(agent,profile,guard,'resume-'+key[:12])
                except Exception:
                    receipt.update(status='uncertain',reason='resume_launch_outcome_unknown')
                    _save(path,receipt);return self._public(receipt)
                sample=self.runtime.binding(agent,profile)
                sample.validated(self.now())
                if sample.state=='ready' and {key:getattr(sample,key) for key in expected}==expected:
                    guard();self.inventory.reconcile(agent['managed_agent_id'],sample)
                    receipt.update(status='resumed',reason=None,process=sample.process)
                _save(path,receipt)
                return self._public(receipt)
            except (OSError,ValueError,KeyError,TypeError,WakeError) as error:
                receipt.update(status='uncertain' if receipt['effects_attempted'] else 'held',
                               reason=getattr(error,'code','resume_history_or_binding_unavailable'))
                _save(path,receipt);return self._public(receipt)

    @staticmethod
    def _public(receipt):
        return {key:receipt[key] for key in ('status','managed_agent_id','conversation_id','record_sha256',
                                            'effects_attempted','reason') if key in receipt}
