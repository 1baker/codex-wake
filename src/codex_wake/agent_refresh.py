"""Same-thread refresh with owned checkpoints and explicit resource proof."""
from __future__ import annotations

import hashlib
import json
import fcntl
import shlex
from pathlib import Path
from types import SimpleNamespace

from .records import WakeError, parse_timestamp
from .agent_lifecycle import save, before_effect
from .lifecycle_budget import operation_binding, track_refresh_budget


from .wake_control import guard_command


@guard_command
def refresh_command(args, root):
    from .session_permissions import PermissionStore
    if PermissionStore(root).active():
        from .permission_refresh import cli_request
        return cli_request(args,root,"refresh")
    try:
        config = json.loads(Path(args.profiles).read_text())
        profile = config['profiles'][args.profile]
        workspace = Path(profile['cwd']).resolve(strict=True)
        checkpoint = (workspace / args.checkpoint).resolve(strict=True)
        checkpoint.relative_to(workspace)
        content = checkpoint.read_bytes()
    except (OSError, ValueError, KeyError, TypeError):
        raise WakeError('approved profile and workspace checkpoint are required') from None
    if hashlib.sha256(content).hexdigest() != args.checkpoint_sha256:
        raise WakeError('checkpoint hash changed; original checkpoint must be preserved')
    if profile.get('refresh_mode') in ('shared_mcp_idle', 'client_idle', 'thread_mcp_idle'):
        from .shared_refresh import command
        from .sessions_cli import emit
        try:
            return command(args, root, config, profile, checkpoint, content)
        except WakeError as exc:
            emit({'error': {'code': 'shared_refresh_unavailable', 'message': str(exc)}}, args.as_json)
            return 2
        except (OSError, ValueError, TypeError, KeyError):
            emit({'error': {'code': 'shared_refresh_unavailable',
                           'message': 'Private host policy and checkpoint prerequisites are unavailable.'}}, args.as_json)
            return 2
    resources = profile.get('resources', {})
    if not resources or any(name not in resources for name in args.resource):
        raise WakeError('requested resources require host-approved proof checks')
    for name in args.resource:
        check = resources[name]
        if not isinstance(check, dict) or check.get('kind') not in ('skill', 'mcp','mcp_catalog'):
            raise WakeError('requested resource proof kind is unsupported')
        required = ({'kind','server','version','tools'} if check['kind']=='mcp_catalog' else
                    {'kind', 'path', 'description', 'sha256'} if check['kind'] == 'skill' else
                    {'kind', 'server', 'tool', 'arguments', 'read_only', 'expected_content'})
        if set(check) != required:
            raise WakeError('requested resource proof is incomplete or contains unsupported fields')
        if isinstance(check, dict) and check.get('kind') == 'mcp' and check.get('read_only') is not True:
            raise WakeError('MCP refresh proof requires a host-approved read-only check')
    if config.get('version') != 1:
        raise WakeError('approved profile registry version is required')
    if args.caller_thread_id:
        if (args.caller_thread_id != args.thread_id or args.profile not in
                config.get('callers', {}).get(args.caller_thread_id, [])):
            raise WakeError('refresh requires the host-granted source caller')
    try:
        body = json.loads(content)
        if body['source_thread_id'] != args.thread_id:
            raise ValueError
        if any(not body.get(k) for k in ('objective', 'authority', 'next_packet')):
            raise ValueError
        if body.get('pending_obligations') != []:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise WakeError('source checkpoint must preserve work and account for obligations') from None
    parse_timestamp(args.expires_at)
    intent = dict(operation='refresh', source_thread_id=args.thread_id, launch=profile,
                  checkpoint=str(checkpoint), checkpoint_sha256=args.checkpoint_sha256,
                  resources=args.resource, expires_at=args.expires_at)
    binding = operation_binding(config, args, source_ref=args.thread_id)
    if binding:
        intent.update(binding)
    fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    journal = Path(root) / 'lifecycle'
    journal.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(args.intent.encode()).hexdigest()
    path = journal / (key + '.json')
    with (journal / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt['fingerprint'] != fingerprint:
                raise WakeError('intent key already binds a different lifecycle assignment')
            if (receipt['state'] == 'uncertain'
                    and receipt.get('uncertain_effect') == 'tmux/kill-pane'):
                receipt['state'] = 'stopping'
                save(path, receipt)
        else:
            receipt = dict(version=1, intent_key=args.intent, fingerprint=fingerprint,
                           intent=intent, thread_id=args.thread_id, state='prepared')
            save(path, receipt)
        if args.rollback:
            rollback(path, receipt, profile)
        elif receipt['state'] == 'prepared' and before_effect(path, receipt):
            preflight(path, receipt, profile)
        if not args.rollback and receipt['state'] in ('stopping', 'starting', 'awaiting_preflight', 'restoring_goal', 'uncertain'):
            advance_refresh(path, receipt, profile)
        from .sessions_cli import emit
        emit(receipt, args.as_json)
        outcome = receipt.get('rollback', {}).get('state') if args.rollback else receipt['state']
        return 0 if outcome == 'completed' else 5


def rollback(path, receipt, profile):
    from .sessions import observe, revalidate_attachment, in_session
    from .app_server import resolve_codex_cmd
    from .native_protocol import native_request
    receipt['rollback'] = dict(state='awaiting_preflight', thread_id=receipt['thread_id'])
    snapshot = observe(endpoint=profile['app_server'], socket_path=profile.get('tmux_socket'),
                       timeout=profile['timeout'])
    rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
    panes = [p for r in rows for p in r['attachments']]
    pending_tabs = [p for r in snapshot['sessions'] for p in r['attachments']
                    if in_session(p, profile['tmux_session'])
                    and p['window_name'] == receipt.get('tab_name')]
    if (snapshot['complete'] and len(rows) == 1 and not panes and not pending_tabs
            and receipt.get('old_generation_exit_observed')):
        # Explicit rollback after complete absence proof restores only the
        # original conversation. An unobserved/pending tab never permits this.
        if not before_effect(path, receipt):
            receipt['rollback']['state'] = receipt['state']
            save(path, receipt)
            return
        receipt.pop('uncertain_effect', None)
        receipt['state'] = 'stopping'
        receipt['rollback']['state'] = 'starting'
        save(path, receipt)
        advance_refresh(path, receipt, profile)
        snapshot = observe(endpoint=profile['app_server'], socket_path=profile.get('tmux_socket'),
                           timeout=profile['timeout'])
        rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
        panes = [p for r in rows for p in r['attachments']]
    if not snapshot['complete'] or len(rows) != 1 or len(panes) != 1 or not revalidate_attachment(panes[0]):
        receipt['rollback'].update(state='blocked', reason='original_attachment_not_uniquely_observed')
        save(path, receipt)
        return
    goal = native_request(profile['app_server'], resolve_codex_cmd(profile['codex_path'], required=True),
                          'thread/goal/get', {'threadId': receipt['thread_id']}, profile['timeout'])['goal']
    baseline = receipt.get('goal_after', receipt.get('goal_before'))
    if goal != baseline or 'goal_before' not in receipt:
        receipt['rollback'].update(state='blocked', reason='original_goal_continuity_unproven', goal=goal)
    else:
        receipt['rollback'].update(state='completed', action='reused_original_conversation',
                                   attachment=panes[0], goal=goal)
    save(path, receipt)


def preflight(path, receipt, profile, effect_guard=None):
    from .sessions import observe, revalidate_attachment, in_session
    from .session_lifecycle import tmux_command
    runtime = SimpleNamespace(**(dict(tmux_socket=None) | profile), effect_guard=effect_guard)
    snapshot = observe(endpoint=runtime.app_server, socket_path=runtime.tmux_socket,
                       timeout=runtime.timeout)
    rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
    attachments = [p for r in rows for p in r['attachments']]
    if (not snapshot['complete'] or len(rows) != 1 or len(attachments) != 1
            or rows[0]['runtime_state'] != 'idle' or rows[0]['active_flags']
            or rows[0]['can_accept_direct_input'] is not True
            or rows[0]['cwd'] != str(Path(runtime.cwd).resolve())
            or not in_session(attachments[0], runtime.tmux_session)
            or not revalidate_attachment(attachments[0])):
        receipt.update(state='blocked', reason='exact_idle_owned_client_not_ready')
        save(path, receipt)
        return
    pane = attachments[0]
    frame = tmux_command(runtime, 'capture-pane', '-e', '-p', '-t', pane['pane_id'],
                         preserve_output=True)
    cursor = tmux_command(runtime, 'display-message', '-p', '-t', pane['pane_id'],
                          '#{cursor_x},#{cursor_y}')
    try:
        x, y = map(int, cursor.split(','))
        lines = frame.splitlines()
        from .refresh_goal import empty_composer_line
        empty = x == 2 and 0 <= y < len(lines) and empty_composer_line(lines[y])
    except ValueError:
        empty = False
    if not empty:
        receipt.update(state='blocked', reason='local_composer_not_proven_empty')
        save(path, receipt)
        return
    from .native_protocol import native_request
    from .app_server import resolve_codex_cmd
    from .session_lifecycle import close_session
    runtime.codex = resolve_codex_cmd(runtime.codex_path, required=True)
    goal = native_request(runtime.app_server, runtime.codex, 'thread/goal/get',
                          {'threadId': receipt['thread_id']}, runtime.timeout)['goal']
    if receipt['intent'].get('configuration'):
        if not track_refresh_budget(path.parent.parent, receipt, goal):
            save(path, receipt)
            return
    if not before_effect(path, receipt):
        return
    from .refresh_goal import pause
    receipt['goal_before'] = goal
    def request(method, params):
        if effect_guard:effect_guard()
        return native_request(runtime.app_server,runtime.codex,method,params,runtime.timeout)
    if not pause(path, receipt, profile, goal, request):
        return
    receipt.update(state='stopping', uncertain_effect='tmux/kill-pane',
                   old_attachment=pane, thread_name=rows[0]['name'])
    save(path, receipt)
    runtime.selector = 'thread:' + receipt['thread_id']
    runtime.force = False
    runtime.bus_root = []
    try:
        close_session(runtime, path.parent.parent)
    except WakeError as exc:
        receipt.update(state='blocked', reason=str(exc))
        # Close refuses its safety checks before the pane effect. A failed tmux
        # command remains uncertain because its external outcome is unknown.
        if 'tmux lifecycle command failed' in str(exc):
            receipt['state'] = 'uncertain'
        else:
            receipt.pop('uncertain_effect', None)
        save(path, receipt)


def advance_refresh(path, receipt, profile, effect_guard=None):
    from .app_server import resolve_codex_cmd
    from .native_protocol import native_request
    from .sessions import observe, revalidate_attachment, in_session
    from .session_lifecycle import tmux_command
    runtime = SimpleNamespace(**(dict(tmux_socket=None) | profile),
                              effect_guard=effect_guard,
                              codex=resolve_codex_cmd(profile['codex_path'], required=True))
    def request(method, params):
        if effect_guard:effect_guard()
        return native_request(runtime.app_server, runtime.codex, method, params, runtime.timeout)
    try:
        if receipt['state'] == 'restoring_goal' or receipt.get('uncertain_effect') == 'native/goal_resume':
            from .refresh_goal import restore
            if restore(path, receipt, profile, request):
                receipt.update(state='completed', reason=None)
            save(path, receipt)
            return
        if receipt.get('uncertain_effect') == 'tmux/new-window':
            snapshot = observe(endpoint=runtime.app_server, socket_path=runtime.tmux_socket,
                               timeout=runtime.timeout)
            rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
            candidates = [p for r in rows for p in r['attachments']
                          if in_session(p, runtime.tmux_session)
                          and p['window_name'] == receipt.get('tab_name')]
            if (not snapshot['complete'] or len(rows) != 1 or len(candidates) != 1
                    or not revalidate_attachment(candidates[0])):
                receipt.update(state='uncertain', reason='no_unique_existing_refresh_tab')
                save(path, receipt)
                return
            pane = candidates[0]
            receipt.update(state='awaiting_preflight', pane_id=pane['pane_id'],
                           window_id=pane['window_id'])
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt['state'] == 'stopping':
            old = receipt['old_attachment']
            try:
                fields = Path('/proc', str(old['client_pid']), 'stat').read_text().rsplit(')', 1)[1].split()
                gone = fields[0] == 'Z' or int(fields[19]) != old['client_start_time_ticks']
            except FileNotFoundError:
                gone = True
            except (PermissionError, ValueError, IndexError):
                gone = False
            if not gone:
                receipt['reason'] = 'old_generation_exit_not_observed'
                save(path, receipt)
                return
            receipt.pop('uncertain_effect', None)
            receipt['old_generation_exit_observed'] = True
            if not before_effect(path, receipt):
                return
            removed = ['CODEX_THREAD_ID', 'TMUX_PANE', 'CODEX_WAKE_A2A_CAPABILITY',
                       'CODEX_WAKE_A2A_BUS_ROOT', 'CODEX_WAKE_SENDER_RECEIPT_AUTHORITY']
            home = ['CODEX_HOME=' + profile['codex_home']] if 'codex_home' in profile else []
            connection=[] if profile.get('client_connection')=='managed_default' else ['--remote',runtime.app_server]
            command = shlex.join(['env', *[v for k in removed for v in ('-u', k)], *home,
                                  runtime.codex, 'resume', '--no-alt-screen', '-C', runtime.cwd,
                                  receipt['thread_id'], *connection])
            receipt.update(state='starting', uncertain_effect='tmux/new-window',
                           tab_name=old['window_name'] + '-refresh-' + receipt['fingerprint'][:12])
            save(path, receipt)
            created = tmux_command(runtime, 'new-window', '-d', '-P', '-F',
                                   '#{window_id}\t#{pane_id}', '-t', runtime.tmux_session + ':',
                                   '-n', receipt['tab_name'], '-c', runtime.cwd, command)
            window, pane = created.split('\t')
            receipt.update(state='awaiting_preflight', window_id=window, pane_id=pane)
            receipt.pop('uncertain_effect', None)
            save(path, receipt)
        if receipt['state'] == 'awaiting_preflight':
            snapshot = observe(endpoint=runtime.app_server, socket_path=runtime.tmux_socket,
                               timeout=runtime.timeout)
            rows = [r for r in snapshot['sessions'] if r['thread_id'] == receipt['thread_id']]
            panes = [p for r in rows for p in r['attachments']]
            if (not snapshot['complete'] or len(rows) != 1 or len(panes) != 1
                    or panes[0]['pane_id'] != receipt['pane_id']
                    or panes[0]['client_pid'] == receipt['old_attachment']['client_pid']
                    or not revalidate_attachment(panes[0])):
                receipt['reason'] = 'exact_replacement_client_not_ready'
                save(path, receipt)
                return
            receipt['attachment'] = panes[0]
            from .refresh_goal import settle_ui
            if not settle_ui(path, receipt, profile, panes[0], request, effect_guard=effect_guard):
                return
            receipt['goal_after'] = request('thread/goal/get', {'threadId': receipt['thread_id']})['goal']
            before, after = receipt['goal_before'], receipt['goal_after']
            changed = before != after
            if isinstance(before, dict) and isinstance(after, dict):
                accounting = {'tokensUsed', 'timeUsedSeconds', 'updatedAt'}
                changed = ({k: v for k, v in before.items() if k not in accounting} !=
                           {k: v for k, v in after.items() if k not in accounting}
                           or any(type(before.get(k)) not in (int, float)
                                  or type(after.get(k)) not in (int, float)
                                  or not after[k] >= before[k] for k in accounting))
            if changed:
                receipt.update(state='blocked', reason='goal_changed_during_refresh')
                save(path, receipt)
                return
            if receipt['intent'].get('configuration'):
                if not track_refresh_budget(path.parent.parent, receipt, after):
                    save(path, receipt)
                    return
            checks = {}
            catalog = request('skills/list', {'cwds': [runtime.cwd], 'forceReload': True})['data']
            for name in receipt['intent']['resources']:
                check = profile['resources'][name]
                ready = False
                if check['kind'] == 'skill':
                    skills = [s for row in catalog if row['cwd'] == runtime.cwd and not row['errors']
                              for s in row['skills'] if s['path'] == check['path'] and s['enabled']]
                    digest = hashlib.sha256(Path(check['path']).read_bytes()).hexdigest()
                    ready = (len(skills) == 1 and skills[0]['description'] == check['description']
                             and digest == check['sha256'])
                    checks[name] = dict(state='ready' if ready else 'blocked',
                                        catalog=skills, observed_sha256=digest)
                elif check['kind'] == 'mcp' and check.get('read_only') is True:
                    result = request('mcpServer/tool/call', dict(threadId=receipt['thread_id'],
                        server=check['server'], tool=check['tool'], arguments=check['arguments']))
                    ready = (result.get('isError') is not True
                             and result['content'] == check['expected_content'])
                    checks[name] = dict(state='ready' if ready else 'blocked',
                                        server=check['server'], tool=check['tool'],
                                        observed_content=result['content'], is_error=result.get('isError'))
                elif check['kind']=='mcp_catalog':
                    from .refresh_resources import catalog_ready
                    ready=catalog_ready(check,request,receipt['thread_id'])
                    checks[name]=dict(state='ready' if ready else 'blocked',server=check['server'],kind='mcp_catalog')
                else:
                    checks[name] = dict(state='blocked', reason='resource_proof_unavailable')
            receipt.update(resources=checks, state='restoring_goal' if all(
                c['state'] == 'ready' for c in checks.values()) else 'blocked')
            if receipt['state'] == 'restoring_goal':
                receipt.pop('reason', None)
                if not before_effect(path, receipt):
                    return
                from .refresh_goal import restore
                if restore(path, receipt, profile, request):
                    receipt['state'] = 'completed'
            else:
                receipt['reason'] = 'requested_resources_not_ready'
            save(path, receipt)
    except Exception as exc:
        receipt.update(state='uncertain' if receipt.get('uncertain_effect') else 'blocked',
                       reason=type(exc).__name__)
        save(path, receipt)
