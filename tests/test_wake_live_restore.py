"""Live-mode preparation reuses an exact recipient and fails closed on ambiguity."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import tempfile
import unittest
import shutil
from unittest.mock import patch

from codex_wake.runtime_delivery import RuntimeTargetError
from codex_wake.wake_live_restore import LiveWakeRestorer

THREAD = '11111111-1111-4111-8111-111111111111'

class LiveWakeRestoreTests(unittest.TestCase):
    def target(self):
        return dict(transport='native', session_mode='reopen_live', thread_id=THREAD,
                    endpoint='unix:///fixture', codex_cmd='/bin/true')

    def test_live_exact_conversation_is_reused_without_launch_configuration(self):
        row = dict(thread_id=THREAD, binding_status='metadata_matched', cwd='/tmp',
                   attachments=[dict(pane_id='%1', client_pid=123, client_start_time_ticks=456)])
        with tempfile.TemporaryDirectory() as directory, patch('codex_wake.sessions.observe', return_value=dict(complete=True, sessions=[row])), patch('codex_wake.sessions.revalidate_attachment', return_value=True):
            result = LiveWakeRestorer(Path(directory)).prepare(self.target())
        self.assertEqual(result['thread_id'], THREAD)
        self.assertEqual(result['startup_policy'], 'active_tab')
        self.assertEqual(result['resume_policy'], 'hold')

    def test_public_binding_pins_profile_and_retains_live_reuse_on_drift(self):
        import contextlib
        import io
        from codex_wake.a2a_identity import RuntimeIdentity
        from codex_wake.cli import run
        from codex_wake.managed_inventory import ManagedInventory, Observation
        from codex_wake.mcp_server import CommandRunner
        from codex_wake.process import process_identity
        from codex_wake.session_permissions import Principal
        from codex_wake.unified_wakes import WakeControls
        from test_recurring_schedules import request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'account-home'
            home.mkdir()
            profile = dict(cwd=str(root), app_server='unix:///fixture',
                           codex_path=sys.executable, codex_home=str(home),
                           tmux_session='work', timeout=1)
            profiles = root / 'profiles.json'
            config = dict(version=1, profiles={'saved': profile})

            def save_profile():
                profiles.write_text(json.dumps(config))
                profiles.chmod(0o600)

            save_profile()
            from base64 import urlsafe_b64encode

            def cache_account(account_id):
                claims = {'https://api.openai.com/auth': {'chatgpt_account_id': account_id}}
                payload = urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
                cache = home / 'auth.json'
                cache.write_text(json.dumps({'tokens': {'id_token': 'test.' + payload + '.test',
                                                        'access_token': 'test'}}))
                cache.chmod(0o600)

            home.chmod(0o700)
            cache_account('original-account')
            thread = dict(id=THREAD, cwd=str(root), modelProvider='openai')
            metadata = dict(codexHome=str(home))
            identity = RuntimeIdentity.from_metadata(thread, metadata)
            process = process_identity(os.getpid())
            agent = ManagedInventory(root, now=time.time).enroll(Observation(
                'codex', identity.namespace, THREAD, str(root), 'ready', time.time(),
                'native_metadata', dict(pid=os.getpid(), start_ticks=process['start_time_ticks'],
                                        boot_id=process['boot_id']),
                [dict(pane_id='%7')], {'inspect': 'supported'}, profile='saved-account'))['agent']
            operator = Principal('local-operator', 'operator')
            owner = WakeControls(root, principal=operator, codex_path=sys.executable,
                                 endpoint='unix:///fixture')
            with patch('codex_wake.sessions.observe', return_value=dict(complete=True, sessions=[])):
                saved = owner.execute('wakes.schedules.register', {'request': request(session_mode='reopen_live')})
            self.assertEqual(saved['restoration']['status'], 'blocked')
            self.assertTrue(saved['persistence']['saved'])
            self.assertFalse(saved['armed'])
            self.assertFalse(saved['delivery']['uncertain'])

            output = io.StringIO()
            with (patch('codex_wake.permission_commands.verified_cli_principal', return_value=operator),
                  patch('codex_wake.shared_app_server.SharedAppServerReader') as reader,
                  contextlib.redirect_stdout(output)):
                endpoint = reader.return_value.__enter__.return_value
                endpoint.server_metadata = metadata
                endpoint.read_thread.return_value = thread
                self.assertEqual(run(['--wake-root', str(root), 'schedules', 'bind-restoration',
                    saved['id'], '--profiles', str(profiles), '--profile', 'saved',
                    '--managed-agent-id', agent['managed_agent_id']]), 0)
            bound = json.loads(output.getvalue())['restoration']
            self.assertEqual(bound['status'], 'configured')
            self.assertEqual(bound['profile'], 'saved')
            self.assertEqual(bound['account']['name'], 'saved-account')
            self.assertEqual(bound['account']['provider_identity'], 'cached_match')
            lookup = dict(schedule_id=saved['id'])
            self.assertEqual(owner.execute('wakes.schedules.show', lookup)['restoration'], bound)
            meta = dict(threadId=THREAD, sessionId=THREAD, callId='restore-inspection',
                        **{'x-codex-turn-metadata': dict(thread_id=THREAD, session_id=THREAD,
                                                         turn_id='test-turn')})
            result, failed = CommandRunner(wake_root=root).call('wake_schedules_show',
                dict(lookup, caller_thread_id=THREAD), native_context=meta)
            self.assertFalse(failed, result)
            self.assertEqual(result['restoration'], bound)

            cache_account('different-account')
            blocked = owner.execute('wakes.schedules.show', lookup)['restoration']
            self.assertEqual(blocked, dict(status='blocked', reason='live_restore_provider_account_changed'))
            cache_account('original-account')
            self.assertEqual(owner.execute('wakes.schedules.show', lookup)['restoration'], bound)

            profile['tmux_session'] = 'changed'
            save_profile()
            shown = owner.execute('wakes.schedules.show', lookup)['restoration']
            self.assertEqual(shown, dict(status='blocked', reason='live_restore_pinned_profile_changed'))
            row = dict(thread_id=THREAD, binding_status='metadata_matched', attachments=[{'pane_id': '%7'}])
            with (patch('codex_wake.sessions.observe', return_value=dict(complete=True, sessions=[row])),
                  patch('codex_wake.sessions.revalidate_attachment', return_value=True)):
                self.assertEqual(LiveWakeRestorer(root).prepare(saved['target'])['startup_policy'],
                                 'active_tab')

    def test_unknown_inventory_holds_without_launching(self):
        with tempfile.TemporaryDirectory() as directory, patch('codex_wake.sessions.observe', return_value=dict(complete=False, sessions=[])):
            with self.assertRaisesRegex(RuntimeTargetError, 'recipient_ownership_unknown'):
                LiveWakeRestorer(Path(directory)).prepare(self.target())

    def test_absent_recipient_requires_existing_host_profile_binding(self):
        with tempfile.TemporaryDirectory() as directory, patch('codex_wake.sessions.observe', return_value=dict(complete=True, sessions=[])):
            with self.assertRaisesRegex(RuntimeTargetError, 'live_restore_configuration_required'):
                LiveWakeRestorer(Path(directory)).prepare(self.target())

    def test_absent_recipient_uses_latest_private_profile_through_existing_resume_owner(self):
        self.exercise_restore()

    def test_idle_recipient_with_no_tab_is_restored_once(self):
        self.exercise_restore(idle_detached=True)

    def test_missing_pinned_byobu_server_is_recreated_before_exact_resume(self):
        self.exercise_restore(missing_server=True)

    def test_restore_observation_uses_authoritative_clock_when_guest_clock_is_ahead(self):
        self.exercise_restore(clock=lambda:time.time()-60)

    def test_visible_restore_reconciles_one_launch_until_native_attachment_is_ready(self):
        self.exercise_restore(delayed_attachment=True)

    def test_placement_reuses_vacant_original_slot_with_later_tab(self):
        from types import SimpleNamespace
        from codex_wake.session_lifecycle import tmux_command
        from codex_wake.wake_restore_placement import launch_placed

        with tempfile.TemporaryDirectory() as cwd:
            runtime = SimpleNamespace(tmux_socket=str(Path(cwd) / 'tmux.sock'), timeout=3)
            tmux_command(runtime, 'new-session', '-d', '-s', 'main', '-c', cwd)
            try:
                def launch(title, target):
                    return tmux_command(runtime, 'new-window', '-dP', '-F', '#{window_id}\t#{pane_id}',
                                        '-t', target, '-n', title, '-c', cwd, 'sleep 30')

                later_window, _ = launch('later', 'main:7').split('\t')
                actual = launch_placed(tmux_command, runtime, dict(session='main', title='wake', index=1),
                                       cwd, launch)
                self.assertEqual((actual['index'], actual['title']), (1, 'wake'))
                self.assertEqual(tmux_command(runtime, 'display-message', '-p', '-t', later_window,
                                              '#{window_index}:#{window_name}'), '7:later')
            finally:
                tmux_command(runtime, 'kill-server')

    def test_placement_reclaims_idle_shell_and_appends_when_slot_is_occupied(self):
        from types import SimpleNamespace
        from codex_wake.session_lifecycle import tmux_command
        from codex_wake.wake_restore_placement import _idle_shell, _panes, launch_placed

        for scenario in ('same_slot', 'moved_title', 'occupied'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as cwd:
                runtime = SimpleNamespace(tmux_socket=str(Path(cwd) / 'tmux.sock'), timeout=3)
                slot = 11 if scenario == 'moved_title' else 13
                saved = dict(session='main', title='wk-grok', index=13)
                tmux_command(runtime, 'new-session', '-d', '-s', 'main', '-c', cwd)
                try:
                    command = 'sleep 30' if scenario == 'occupied' else '/bin/bash --noprofile --norc'
                    output = tmux_command(runtime, 'new-window', '-dP', '-F', '#{pane_id}',
                                          '-t', f'main:{slot}', '-c', cwd, '-n', saved['title'], command)
                    limit = time.monotonic() + 3
                    if scenario != 'occupied':
                        while time.monotonic() < limit:
                            candidate = next(row for row in _panes(tmux_command, runtime, '=main')
                                             if row['pane_id'] == output)
                            if _idle_shell(candidate):
                                break
                            time.sleep(0.02)
                    before = next(row for row in _panes(tmux_command, runtime, '=main') if row['pane_id'] == output)

                    def launch(title, target):
                        return tmux_command(runtime, 'new-window', '-dP', '-F', '#{window_id}\t#{pane_id}',
                                            '-t', target, '-n', title, '-c', cwd, 'sleep 30')

                    actual = launch_placed(tmux_command, runtime, saved, cwd, launch)
                    old = next(row for row in _panes(tmux_command, runtime, '=main') if row['pane_id'] == output)
                    self.assertEqual(old['pane_pid'], before['pane_pid'])
                    self.assertEqual(old['window_id'], before['window_id'])
                    self.assertEqual(actual['title'], 'wk-grok-restored')
                    if scenario == 'occupied':
                        self.assertEqual(old['window_index'], '13')
                        self.assertEqual(actual['index'], 14)
                        self.assertIsNone(actual['placeholder'])
                    else:
                        self.assertEqual(actual['index'], slot)
                        self.assertEqual(actual['placeholder']['pane_id'], output)
                        self.assertEqual(int(old['window_index']), slot + 1)
                finally:
                    tmux_command(runtime, 'kill-server')

    @unittest.skipUnless(shutil.which('tmux'), 'requires tmux')
    def test_restored_window_visibly_marks_until_focus_and_retains_placement(self):
        from types import SimpleNamespace
        from codex_wake.session_lifecycle import tmux_command
        from codex_wake.tab_format_projection import project
        from codex_wake.tab_organization import TmuxTransport
        from codex_wake.tab_restore_marker import mark_restored

        with tempfile.TemporaryDirectory() as directory:
            socket = str(Path(directory) / 'tmux.sock')
            runtime = SimpleNamespace(tmux_socket=socket, timeout=3)
            tmux_command(runtime, 'new-session', '-d', '-s', 'main', '-n', 'original')
            try:
                ids = tmux_command(runtime, 'new-window', '-dP', '-F', '#{window_id}\t#{pane_id}',
                                   '-t', 'main:5', '-n', 'restored-title', 'sleep 30')
                window, pane = ids.split('\t')
                session = tmux_command(runtime, 'display-message', '-p', '-t', pane, '#{session_id}')
                placement = dict(session='main', session_id=session, window_id=window, pane_id=pane,
                                 index=5, title='restored-title', placeholder=None)
                # Keep an existing user hook active on the same selection.
                tmux_command(runtime, 'set-hook', '-g', 'after-select-window[7]',
                             'set-option -wq @user_focus_seen 1')
                mark_restored(tmux_command, runtime, placement)
                transport = TmuxTransport(socket, session)

                def inspect():
                    windows = transport.snapshot(time.monotonic() + 3)['windows']
                    return next(row for row in windows if row['window_id'] == window)

                shown = project(dict(target=dict(presentation='byobu'), window=inspect(),
                    bot_family=dict(root_bot_id='family', parent_bot_id='parent', parent_name='Parent')),
                    dict(preset='slate'))
                normal = shown['options']['window-status-format']
                render = lambda: tmux_command(runtime, 'display-message', '-p', '-t', pane, normal)
                self.assertIn('restored-title ↻', render())
                self.assertIn('<Parent', render())
                self.assertTrue(inspect()['restoration']['pending_focus'])
                for command in (('select-window', '-t', window), ('next-window', '-t', session),
                                ('previous-window', '-t', session), ('last-window', '-t', session)):
                    with self.subTest(command=command[0]):
                        tmux_command(runtime, *command)
                        self.assertEqual(tmux_command(runtime, 'show-options', '-wv', '-t', window,
                                                      '@user_focus_seen'), '1')
                        self.assertNotIn('↻', render())
                        self.assertEqual(inspect()['restoration'],
                                         dict(label='Restored by Wake', pending_focus=False, placement=placement))
                        tmux_command(runtime, 'select-window', '-t', session + ':0')
                        mark_restored(tmux_command, runtime, placement)
            finally:
                tmux_command(runtime, 'kill-server')

    def exercise_restore(self, missing_server=False, clock=time.time, delayed_attachment=False, idle_detached=False):
        from codex_wake.a2a_identity import RuntimeIdentity
        from codex_wake.managed_inventory import ManagedInventory, Observation
        from codex_wake.process import process_identity
        from codex_wake.session_permissions import PermissionStore, Principal
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root = base / 'wake'; home = base / 'home'; home.mkdir()
            cwd = base / 'latest-directory'; cwd.mkdir()
            thread = dict(id=THREAD, cwd=str(cwd), modelProvider='openai', status={'type':'idle'})
            metadata = dict(codexHome=str(home))
            namespace = RuntimeIdentity.from_metadata(thread, metadata).namespace
            identity = process_identity(os.getpid())
            process = dict(pid=os.getpid(), start_ticks=identity['start_time_ticks'], boot_id=identity['boot_id'])
            inv = ManagedInventory(root, now=clock)
            prior = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            try:
                prior_identity = process_identity(prior.pid)
                prior_process = dict(pid=prior.pid, start_ticks=prior_identity['start_time_ticks'], boot_id=prior_identity['boot_id'])
                agent = inv.enroll(Observation('codex', namespace, THREAD, str(cwd), 'ready', clock(),
                    'native_metadata', prior_process, [dict(pane_id='%7')], {'inspect':'supported'}))['agent']
            finally:
                prior.terminate(); prior.wait(timeout=5)
            PermissionStore(root).configure({'version':1}, Principal('operator','operator'), expected_revision=0)
            profiles = base / 'profiles.json'
            profiles.write_text(json.dumps(dict(version=1, profiles=dict(latest=dict(cwd=str(cwd),
                app_server='unix:///fixture', codex_path=sys.executable, tmux_session='work', timeout=1)),
                callers={THREAD:['latest']}))); profiles.chmod(0o600)
            mapping = root / 'wake-live-restore.json'
            mapping.write_text(json.dumps(dict(version=1, bindings={THREAD:dict(profiles=str(profiles),
                managed_agent_id=agent['managed_agent_id'], profile='latest')}))); mapping.chmod(0o600)
            socket = base / 'tmux.sock'
            if missing_server:
                config = json.loads(profiles.read_text())
                config['profiles']['latest']['tmux_socket'] = str(socket)
                profiles.write_text(json.dumps(config))
                host_config = root / 'controller-tabs.json'
                host_config.write_text(json.dumps(dict(schema_version=1, workspaces=dict(saved=dict(
                    kind='byobu', socket_path=str(socket), session_id='$0')))))
                host_config.chmod(0o600)
                self.addCleanup(lambda: subprocess.run(['tmux','-S',str(socket),'kill-server'], capture_output=True))
            target = self.target() | dict(codex_cmd='/missing-old-harness', _wake_permission_context=dict(
                subject=THREAD, role='session', tasks=[], target=THREAD, task_id=None, revision=1),
                _wake_expires_at='2035-01-01T00:00:00Z', _wake_occurrence_id='wake-original')
            if missing_server:
                target.update(tmux_socket=str(socket), session_origin=dict(pid=99999999, identity=dict(
                    boot_id='previous-boot', start_time_ticks=1)))
            live = False; commands = []; unready_samples = 1 if delayed_attachment else 0
            real_run = subprocess.run
            def observe(**kwargs):
                nonlocal unready_samples
                ready = live
                if live and unready_samples:
                    ready = False
                    unready_samples -= 1
                pane = dict(pane_id='%7', client_pid=os.getpid(), client_start_time_ticks=identity['start_time_ticks'])
                absent = missing_server and not socket.exists()
                return dict(complete=not absent, sources=dict(app_server=dict(availability='available'),
                    tmux=dict(availability='unavailable' if absent else 'available')),
                    sessions=[dict(thread_id=THREAD,cwd=str(cwd),runtime_state='idle' if ready else 'not_loaded',
                        binding_status='metadata_matched',attachments=[pane] if ready else [])])
            def terminal(argv, **kwargs):
                nonlocal live
                commands.append(argv)
                if 'new-window' in argv:
                    live = True
                    return subprocess.CompletedProcess(argv, 0, stdout='@4\t%7', stderr='')
                if missing_server:
                    return real_run(argv, **kwargs)
                return subprocess.CompletedProcess(argv, 0, stdout='@4\t%7', stderr='')
            with patch('codex_wake.sessions.observe', side_effect=observe), patch('codex_wake.sessions.revalidate_attachment', return_value=True), patch('codex_wake.shared_app_server.SharedAppServerReader') as reader, patch('codex_wake.session_lifecycle.subprocess.run', side_effect=terminal):
                reader.return_value.__enter__.return_value.read_thread.return_value = thread
                reader.return_value.__enter__.return_value.server_metadata = metadata
                thread['status'] = {'type':'active'}
                with self.assertRaises(RuntimeTargetError) as busy:
                    LiveWakeRestorer(root, now=clock).prepare(target)
                self.assertEqual(busy.exception.state, 'busy')
                self.assertEqual(commands, [])
                thread['status'] = {'type':'unknown'}
                with self.assertRaisesRegex(RuntimeTargetError, 'live_restore_runtime_state_unverified'):
                    LiveWakeRestorer(root, now=clock).prepare(target)
                self.assertEqual(commands, [])
                thread['status'] = {'type': 'idle' if idle_detached else 'notLoaded'}
                prepared = LiveWakeRestorer(root, now=clock).prepare(target)
                self.assertEqual(LiveWakeRestorer(root, now=clock).prepare(target)['thread_id'], THREAD)
            launches = [cmd for cmd in commands if 'new-window' in cmd]
            self.assertEqual(len(launches), 1)
            self.assertIn(THREAD, launches[0][-1])
            self.assertIn(str(cwd), launches[0][-1])
            self.assertEqual(prepared['codex_cmd'], sys.executable)
            self.assertEqual(prepared['startup_policy'], 'active_tab')
            if missing_server:
                self.assertEqual(len([cmd for cmd in commands if 'new-session' in cmd]), 1)
