import copy
import io
import unittest
from unittest.mock import patch

from codex_wake.cli import main
from codex_wake.sessions import build_snapshot, resolve, revalidate_attachment, SelectionError


def pane(index='17', name='wake', pid=123, identifier='%15', title='Session | repo'):
    return dict(socket='/tmp/example', session_id='$1', session_name='byobu', window_id='@' + index,
                window_index=index, window_name=name, pane_id=identifier, pane_index='0',
                pane_title=title, pane_current_path='/repo', pane_tty='/dev/pts/1',
                client_pid=pid, client_start_time_ticks=456, evidence='process_generation')


def snapshot(threads=None, panes=None):
    if threads is None:
        threads = [dict(id='full-thread-id', name='Session', cwd='/repo', status={'type': 'idle'})]
    return build_snapshot(threads, [pane()] if panes is None else panes,
                          {key: dict(availability='available') for key in ['tmux', 'app_server']})


class SessionTests(unittest.TestCase):
    def test_all_exact_selector_forms(self):
        s = snapshot()
        for selector in ['17', 'wake', '17:wake', '17.0', '17:wake.0', 'tab:wake',
                         'pane:%15', 'window:@17', 'thread:full-thread-id']:
            with self.subTest(selector=selector):
                self.assertEqual(resolve(s, selector)['thread_id'], 'full-thread-id')

    def test_duplicate_name_including_shell_requires_qualification(self):
        s = snapshot(panes=[pane(), pane('27', 'wake', None, '%27')])
        with self.assertRaises(SelectionError) as error:
            resolve(s, 'wake')
        self.assertEqual(error.exception.code, 4)
        self.assertEqual(resolve(s, '17:wake')['thread_id'], 'full-thread-id')

    def test_collision_does_not_prefer_active_thread(self):
        s = snapshot(threads=[dict(id='a', name='Session', cwd='/repo', status={'type': 'idle'}),
                              dict(id='b', name='Session', cwd='/repo', status={'type': 'active'})])
        with self.assertRaises(SelectionError) as error:
            resolve(s, '17')
        self.assertEqual(error.exception.code, 4)

    def test_shell_show_and_resolve_have_distinct_outcomes(self):
        s = snapshot(panes=[pane(pid=None)])
        self.assertEqual(resolve(s, '17', eligible=False)['binding_status'], 'not_codex')
        with self.assertRaises(SelectionError) as error:
            resolve(s, '17')
        self.assertEqual(error.exception.code, 6)

    def test_source_loss_never_proves_not_found_or_unique(self):
        s = snapshot()
        s['complete'] = False
        s['sources']['app_server']['availability'] = 'unavailable'
        for ref in ['missing', '17', 'thread:full-thread-id']:
            with self.assertRaises(SelectionError) as error:
                resolve(s, ref)
            self.assertEqual(error.exception.code, 5)

    def test_split_window_requires_explicit_pane(self):
        second = pane(identifier='%16')
        second['pane_index'] = '1'
        s = snapshot(panes=[pane(), second])
        with self.assertRaises(SelectionError):
            resolve(s, '17')
        self.assertEqual(resolve(s, '17.1')['thread_id'], 'full-thread-id')
        self.assertEqual(len(resolve(s, 'thread:full-thread-id')['attachments']), 2)

    def test_literal_names_and_index_guard(self):
        s = snapshot(panes=[pane(name='16.name:literal')])
        self.assertEqual(resolve(s, 'tab:16.name:literal')['thread_id'], 'full-thread-id')
        with self.assertRaises(SelectionError) as error:
            resolve(s, '17:wake')
        self.assertEqual(error.exception.code, 3)

    def test_cli_json_exit_and_limit_do_not_change_resolution(self):
        with patch('codex_wake.sessions_cli.observe', return_value=snapshot()), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['sessions', 'resolve', '17:wake', '--json']), 0)
            self.assertIn('full-thread-id', out.getvalue())
        s = snapshot()
        s['complete'] = False
        with patch('codex_wake.sessions_cli.observe', return_value=s), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['sessions', 'list', '--json', '--limit', '1']), 5)
            self.assertIn('"complete": false', out.getvalue())

    def test_current_conflicting_inherited_parent_pane(self):
        s = snapshot(threads=[dict(id='parent', name='Session', cwd='/repo'), dict(id='child', name='Child', cwd='/repo')])
        with patch.dict('os.environ', {'CODEX_THREAD_ID': 'child', 'TMUX_PANE': '%15'}), patch('codex_wake.sessions_cli.observe', return_value=s), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main(['sessions', 'current', '--json']), 6)

    def test_watch_pins_thread_across_tab_replacement(self):
        original = snapshot()
        changed = snapshot(threads=[dict(id='new-thread', name='Session', cwd='/repo')])
        with patch('codex_wake.sessions_cli.observe', side_effect=[original, changed]), patch('codex_wake.sessions_cli.time.sleep'), patch('codex_wake.sessions_cli.time.monotonic', side_effect=[0, 0, 2]), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['sessions', 'watch', '17:wake', '--duration', '1s', '--interval', '1', '--json']), 0)
        self.assertIn('"event": "session_removed"', out.getvalue())
        self.assertNotIn('new-thread', out.getvalue())

    def test_watch_source_loss_is_not_thread_removal(self):
        original = snapshot()
        unavailable = snapshot(threads=[], panes=[])
        unavailable['complete'] = False
        unavailable['sources']['app_server']['availability'] = 'unavailable'
        with patch('codex_wake.sessions_cli.observe', side_effect=[original, unavailable]), patch('codex_wake.sessions_cli.time.sleep'), patch('codex_wake.sessions_cli.time.monotonic', side_effect=[0, 0, 2]), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['sessions', 'watch', '--duration', '1s', '--interval', '1', '--json']), 5)
        self.assertIn('source_unavailable', out.getvalue())
        self.assertNotIn('session_removed', out.getvalue())

    def test_reused_pane_fails_generation_revalidation(self):
        observed = pane()
        changed = dict(observed, client_start_time_ticks=999)
        with patch('codex_wake.sessions.tmux_inventory', return_value=[changed]):
            self.assertFalse(revalidate_attachment(observed))
        changed = dict(observed, window_index='18', window_name='renamed')
        with patch('codex_wake.sessions.tmux_inventory', return_value=[changed]):
            self.assertTrue(revalidate_attachment(observed))

    def test_subagent_path_and_unloaded_provider_status_are_preserved(self):
        s = snapshot(threads=[dict(id='child', name='Child', cwd='/repo', parentThreadId='parent',
                                  source={'subAgent': {'thread_spawn': {'agent_path': '/root/child'}}},
                                  status={'type': 'notLoaded'})], panes=[])
        row = s['sessions'][0]
        self.assertEqual(row['parent_thread_id'], 'parent')
        self.assertEqual(row['agent_path'], '/root/child')
        self.assertEqual(row['runtime_state'], 'not_loaded')

    def test_headless_exact_thread_requires_only_daemon_source(self):
        s = snapshot(panes=[])
        s['complete'] = False
        s['sources']['tmux']['availability'] = 'unavailable'
        self.assertEqual(resolve(s, 'thread:full-thread-id')['thread_id'], 'full-thread-id')
        with self.assertRaises(SelectionError) as error:
            resolve(s, 'wake')
        self.assertEqual(error.exception.code, 5)

    def test_invalid_reserved_selectors_are_argument_errors(self):
        for selector in ['thread:', 'tab:', 'pane:bad', 'window:17']:
            with self.assertRaises(SelectionError) as error:
                resolve(snapshot(), selector)
            self.assertEqual(error.exception.code, 2)

    def test_invalid_timeout_emits_json_before_observation(self):
        with patch('codex_wake.sessions_cli.observe') as observe, patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['sessions', 'list', '--timeout', 'nan', '--json']), 2)
        observe.assert_not_called()
        self.assertIn('"code": 2', out.getvalue())


class GroupedSessionAliasTests(unittest.TestCase):
    def test_inventory_preserves_both_names_for_one_grouped_physical_pane(self):
        from codex_wake.sessions import tmux_inventory
        line = ['{sid}', '{name}', '@64', '7', 'helper', '%64', '0', 'Session', '/repo', '/dev/pts/7', 'byobu']
        output = "\n".join("\t".join(line).format(sid=sid, name=name)
                           for sid, name in [('$27', 'byobu-27'), ('$1', 'byobu')])
        with patch('codex_wake.sessions.subprocess.run', return_value=type('Result', (), {'stdout': output})()), \
                patch('codex_wake.sessions.codex_client_identities_for_ttys', return_value={'/dev/pts/7': (123,456)}):
            rows = tmux_inventory('/tmp/example', 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['session_aliases'], [['$1', 'byobu'], ['$27', 'byobu-27']])
        observed = snapshot(panes=rows)
        for session in ['byobu', 'byobu-27', '$1', '$27']:
            self.assertEqual(resolve(observed, 'pane:%64', session=session)['thread_id'], 'full-thread-id')


class GroupedAliasRegressionTests(unittest.TestCase):
    """#214: byobu grouped sessions list one physical pane twice; exactly-one checks refused a healthy idle tab."""

    def raw(self, session_id, session_name, group='byobu', **changes):
        row = pane(index='64', name='temp-source', identifier='%64', pid=2802727)
        row.update(session_id=session_id, session_name=session_name, session_group=group, **changes)
        return row

    def test_same_physical_pane_in_grouped_sessions_is_one_attachment(self):
        from codex_wake.sessions import merge_grouped_session_aliases
        rows = merge_grouped_session_aliases([self.raw('$27', 'byobu-27'), self.raw('$1', 'byobu')])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['session_name'], 'byobu')            # the group's own session is primary
        self.assertEqual(sorted(rows[0]['session_aliases']), [['$1', 'byobu'], ['$27', 'byobu-27']])
        threads = [dict(id='helper-thread', name='Session', cwd='/repo', status={'type': 'idle'})]
        s = build_snapshot(threads, rows, {k: dict(availability='available') for k in ['tmux', 'app_server']})
        self.assertEqual(len(s['sessions'][0]['attachments']), 1)
        self.assertEqual(resolve(s, 'pane:%64', session='byobu-27')['thread_id'], 'helper-thread')

    def test_distinct_panes_or_client_generations_are_never_merged(self):
        from codex_wake.sessions import merge_grouped_session_aliases
        for change in (dict(pane_id='%65'), dict(window_id='@65'), dict(pane_tty='/dev/pts/9'),
                       dict(client_pid=999), dict(client_start_time_ticks=1)):
            with self.subTest(change=change):
                rows = merge_grouped_session_aliases([self.raw('$1', 'byobu'), self.raw('$27', 'byobu-27', **change)])
                self.assertEqual(len(rows), 2)

    def test_tmux_inventory_merges_grouped_duplicates(self):
        from codex_wake import sessions
        line = '\t'.join(['{sid}', '{name}', '@64', '7', 'temp-source', '%64', '0', 'Session', '/repo', '/dev/pts/7', 'byobu'])
        out = '\n'.join([line.format(sid='$1', name='byobu'), line.format(sid='$27', name='byobu-27')]) + '\n'
        fake = type('R', (), {'stdout': out})()
        with patch('codex_wake.sessions.subprocess.run', return_value=fake), \
                patch('codex_wake.sessions.codex_client_identities_for_ttys', return_value={'/dev/pts/7': (2802727, 20886589)}):
            rows = sessions.tmux_inventory('/tmp/sock', 5)
        self.assertEqual([(r['pane_id'], r['session_name']) for r in rows], [('%64', 'byobu')])
        self.assertEqual(len(rows[0]['session_aliases']), 2)


class LinkedWindowIndexTests(unittest.TestCase):
    """Review finding S214-SESSION-INDEX-01: ungrouped sessions that link the same window (tmux link-window) can
    use different indices; merging them kept one session's index and mis-resolved session-qualified selectors."""

    def rows(self):
        def r(sid, name, index, pane_id, window, thread_title):
            row = pane(index=index, name='w' + pane_id[1:], identifier=pane_id, title=thread_title)
            row.update(session_id=sid, session_name=name, window_id=window, session_group='',
                       pane_tty='/dev/pts/' + pane_id[1:])
            return row
        # A: W at 1, X at 2.  B: X at 1, W at 2 (swapped indices, no session group).
        return [r('$1', 'A', '1', '%10', '@10', 'Wthread | repo'), r('$1', 'A', '2', '%11', '@11', 'Xthread | repo'),
                r('$2', 'B', '1', '%11', '@11', 'Xthread | repo'), r('$2', 'B', '2', '%10', '@10', 'Wthread | repo')]

    def test_ungrouped_linked_windows_keep_per_session_indices(self):
        from codex_wake.sessions import merge_grouped_session_aliases
        rows = merge_grouped_session_aliases(self.rows())
        self.assertEqual(len(rows), 4)                                  # nothing merged across ungrouped sessions
        threads = [dict(id='W', name='Wthread', cwd='/repo', status={'type': 'idle'}),
                   dict(id='X', name='Xthread', cwd='/repo', status={'type': 'idle'})]
        s = build_snapshot(threads, rows, {k: dict(availability='available') for k in ['tmux', 'app_server']})
        self.assertEqual(resolve(s, '1', session='B')['thread_id'], 'X')  # B:1 is X, not W
        self.assertEqual(resolve(s, '2', session='B')['thread_id'], 'W')
        self.assertEqual(resolve(s, '1', session='A')['thread_id'], 'W')

    def test_a_window_linked_at_a_different_index_still_resolves_there(self):
        from codex_wake.sessions import merge_grouped_session_aliases
        a = pane(index='1', identifier='%20', title='Session | repo')
        b = dict(a, session_id='$2', session_name='B', window_index='7')
        a.update(session_group=''); b.update(session_group='')
        threads = [dict(id='T', name='Session', cwd='/repo', status={'type': 'idle'})]
        rows = merge_grouped_session_aliases([a, b])
        self.assertEqual(len(rows), 2)


class AliasJsonStabilityTests(unittest.TestCase):
    """Review finding S214-ALIASES-JSON-STABILITY-02: saved attachments are JSON round-tripped and later compared to
    fresh observations (lifecycle_correction); tuple aliases made a fresh attachment never equal its saved copy."""

    def test_merged_attachment_survives_a_json_round_trip_unchanged(self):
        import json
        from codex_wake.sessions import merge_grouped_session_aliases
        base = pane(index='64', identifier='%64', pid=2802727)
        rows = merge_grouped_session_aliases([dict(base, session_id='$27', session_name='byobu-27', session_group='byobu'),
                                              dict(base, session_id='$1', session_name='byobu', session_group='byobu')])
        saved = json.loads(json.dumps(rows[0]))
        self.assertEqual(saved, rows[0])
        reordered = merge_grouped_session_aliases([dict(base, session_id='$1', session_name='byobu', session_group='byobu'),
                                                  dict(base, session_id='$27', session_name='byobu-27', session_group='byobu')])
        self.assertEqual(reordered, rows)
        single = merge_grouped_session_aliases([dict(base, session_group='')])[0]
        self.assertEqual(json.loads(json.dumps(single)), single)


class EmptyComposerRenderTests(unittest.TestCase):
    """#214 S214-EMPTY-COMPOSER-RENDER-03: the exact empty-composer frame captured from a held helper pane."""
    CAPTURED = '\x1b[1m›\x1b[0m\x1b[48;2;41;41;41m \x1b[2mAsk Codex to do anything\x1b[0m\x1b[48;2;41;41;41m'

    def test_background_paint_is_ignored_but_the_placeholder_proof_is_kept(self):
        from codex_wake.refresh_goal import empty_composer_line
        self.assertTrue(empty_composer_line(self.CAPTURED))
        self.assertTrue(empty_composer_line('\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m'))
        for draft in (self.CAPTURED.replace('Ask Codex to do anything', 'my unsent draft'),
                      '\x1b[1m›\x1b[0m\x1b[48;2;41;41;41m UNSUBMITTED_DRAFT',
                      self.CAPTURED.replace('\x1b[2m', '')):           # placeholder no longer dim = real text
            self.assertFalse(empty_composer_line(draft), draft)
