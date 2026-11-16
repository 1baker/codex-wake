"""Public accounting contract using sanitized 0.163 rollout shapes."""
import json
import tempfile
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path

from codex_wake.goal_usage import observe_usage

START = '2026-10-16T22:00:00Z'
CREATED = 1792188000


def row(kind, payload, timestamp=START):
    return dict(type=kind, timestamp=timestamp, payload=payload)


def event(kind, **payload):
    return row('event_msg', dict(type=kind, **payload))


def response(thread, turn, response_id, total, root_turn=None, cached=0):
    return row('token_usage_record', dict(thread_id=thread, turn_id=turn,
        session_id='root', root_turn_id=root_turn or turn, response_id=response_id,
        usage=dict(input_tokens=total-2, cached_input_tokens=cached,
                   output_tokens=2, total_tokens=total),
        turn_token_usage={}, thread_token_usage={}))


def rollout(home, thread, rows, **meta):
    path=home/'sessions'/f'rollout-{thread}.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(json.dumps(x) for x in [row('session_meta',
        dict(id=thread,session_id='root',source='cli',**meta))]+rows)+'\n')
    return path


def goal():
    return event('thread_goal_updated',threadId='root',goal=dict(
        threadId='root',createdAt=CREATED,status='active',tokensUsed=0))


class GoalUsageTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name)

    def test_interrupted_grok_session_keeps_unobserved_usage_unknown(self):
        from codex_wake.goal_usage import observe_session_usage
        for prior_usage in (False, True):
            rows = []
            if prior_usage:
                rows += [event('task_started', turn_id='before'),
                         response('root', 'before', 'known', 40),
                         event('task_complete', turn_id='before')]
            rows += [event('task_started', turn_id='uncertain'),
                     event('turn_aborted', turn_id='uncertain', reason='interrupted')]
            rollout(self.home, 'root', rows, model_provider='grok__personal')
            result = observe_session_usage(self.home, 'root', token_accounting='cache_inclusive')
            self.assertEqual(result['state'], 'unknown', result)
            self.assertIsNone(result['used_tokens'])
            self.assertEqual(result['reason'], 'provider_completion_unconfirmed')

    def test_failed_grok_request_keeps_unobserved_usage_unknown(self):
        from codex_wake.goal_usage import observe_session_usage
        for prior_usage in (False, True):
            rows = []
            if prior_usage:
                rows += [event('task_started', turn_id='before'),
                         response('root', 'before', 'known', 40),
                         event('task_complete', turn_id='before')]
            rows += [event('task_started', turn_id='uncertain'),
                     event('task_complete', turn_id='uncertain', error={
                         'message': 'Grok work held: request completion unobserved',
                         'codex_error_info': 'other'})]
            rollout(self.home, 'root', rows, model_provider='grok__personal')
            result = observe_session_usage(self.home, 'root', token_accounting='cache_inclusive')
            self.assertEqual(result['state'], 'unknown', result)
            self.assertIsNone(result['used_tokens'])
            self.assertEqual(result['reason'], 'provider_completion_unconfirmed')

    def test_observed_grok_budget_hold_retains_known_charge(self):
        from codex_wake.goal_usage import observe_session_usage
        rollout(self.home, 'root', [event('task_started', turn_id='known'),
                response('root', 'known', 'charged', 40),
                event('task_complete', turn_id='known', error={
                    'message': 'shared rollout token budget exhausted',
                    'codex_error_info': 'session_budget_exceeded'})], model_provider='grok__personal')
        result = observe_session_usage(self.home, 'root', token_accounting='cache_inclusive')
        self.assertEqual(result['state'], 'qualified', result)
        self.assertEqual(result['used_tokens'], 40)

    def test_tool_payload_volume_does_not_exhaust_accounting_evidence_budget(self):
        rollout(self.home,'root',[goal(),event('task_started',turn_id='work'),
            row('response_item',dict(type='message',content='x'*12000)),
            response('root','work','new',40),event('task_complete',turn_id='work')])
        with patch('codex_wake.goal_usage.MAX_HISTORY_BYTES',4096):
            result=observe_usage(self.home,'root',CREATED)
        self.assertEqual(result['state'],'qualified',result)
        self.assertEqual(result['used_tokens'],40)

    def test_goal_start_counts_fresh_input_and_output_by_default(self):
        tmp_path = self.home
        rollout(tmp_path,'root',[response('root','before','old',100),goal(),
            event('task_started',turn_id='work'),response('root','work','new',40,cached=37),
            event('task_complete',turn_id='work')])
        result=observe_usage(tmp_path,'root',CREATED)
        assert result['state']=='qualified'
        assert result['used_tokens']==3
        assert result['token_accounting']=='fresh'
        assert observe_usage(tmp_path,'root',CREATED,token_accounting='cache_inclusive')['used_tokens']==40
        assert result['sampled'] is True


    def test_child_inherited_parent_records_not_double_charged(self):
        tmp_path = self.home
        inherited=response('root','before','old',100)
        rollout(tmp_path,'root',[inherited,goal(),event('task_started',turn_id='work'),
            event('collab_agent_spawn_end',call_id='spawn',sender_thread_id='root',new_thread_id='child'),
            response('root','work','parent',40)])
        rollout(tmp_path,'child',[inherited,response('child','child-work','child-response',20,'work'),
            event('task_started',turn_id='child-resumed'),response('child','child-resumed','child-later',25)],
                parent_thread_id='root',source_override='unused')
        result=observe_usage(tmp_path,'root',CREATED)
        assert result['state']=='qualified'
        assert result['used_tokens']==85


    def test_reset_excludes_verified_snapshot_without_goal_reset(self):
        tmp_path = self.home
        path=rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),
            response('root','work','first',40),event('task_complete',turn_id='work')])
        baseline=observe_usage(tmp_path,'root',CREATED)['anchor']
        with path.open('a') as stream:
            for item in [event('task_started',turn_id='later'),response('root','later','second',25)]:
                stream.write(json.dumps(item)+'\n')
        assert observe_usage(tmp_path,'root',CREATED)['used_tokens']==65
        assert observe_usage(tmp_path,'root',CREATED,reset_anchor=baseline)['used_tokens']==25


    def test_goal_creation_inside_active_turn_is_unknown(self):
        tmp_path = self.home
        rollout(tmp_path,'root',[event('task_started',turn_id='ambiguous'),goal(),
            response('root','ambiguous','spanning',40)])
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'


    def test_incomplete_or_unattributed_usage_never_becomes_known_zero(self):
        tmp_path = self.home
        path=rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),
            event('raw_response_completed',response_id='missing',token_usage={'total_tokens':10})])
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'
        path.write_text(path.read_text()+json.dumps(response('root','unowned','missing',10))+'\n')
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'


    def test_missing_descendant_or_referenced_history_holds(self):
        tmp_path = self.home
        path=rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),
            response('root','work','r',40),event('collab_agent_spawn_end',new_thread_id='missing')])
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'
        rollout(tmp_path,'root',[goal()],history_base=dict(thread_id='missing',end_ordinal_exclusive=3,end_byte_offset=300))
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'


    def test_replacement_goal_does_not_reset_and_anchor_tampering_holds(self):
        tmp_path = self.home
        path=rollout(tmp_path,'root',[goal(),event('task_started',turn_id='one'),
            response('root','one','r1',40),event('task_complete',turn_id='one')])
        baseline=observe_usage(tmp_path,'root',CREATED)['anchor']
        with path.open('a') as stream:
            replacement=goal();replacement['payload']['goal']['createdAt']=CREATED+1
            for item in [replacement,event('task_started',turn_id='two'),
                         response('root','two','r2',25)]:
                stream.write(json.dumps(item)+'\n')
        assert observe_usage(tmp_path,'root',CREATED)['used_tokens']==65
        assert observe_usage(tmp_path,'root',CREATED,reset_anchor=baseline)['used_tokens']==25
        baseline['response_hashes']={}
        assert observe_usage(tmp_path,'root',CREATED,reset_anchor=baseline)['state']=='unknown'


    def test_response_conflicts_and_truncated_json_hold(self):
        tmp_path = self.home
        first=response('root','work','r1',40)
        path=rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),first,
            response('root','work','r1',41)])
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'
        path.write_text(path.read_text()+'{"type":')
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'


    def test_completed_response_has_matching_usage_record(self):
        tmp_path = self.home
        record=response('root','work','r1',40)
        rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),
            event('raw_response_completed',response_id='r1',token_usage=record['payload']['usage']),record])
        assert observe_usage(tmp_path,'root',CREATED)['used_tokens']==40


    def test_wrong_goal_identity_is_not_an_accounting_boundary(self):
        tmp_path = self.home
        boundary=goal();boundary['payload']['goal']['threadId']='other'
        rollout(tmp_path,'root',[boundary])
        assert observe_usage(tmp_path,'root',CREATED)['state']=='unknown'


    def test_unrelated_large_corrupt_history_is_excluded(self):
        tmp_path = self.home
        rollout(tmp_path,'root',[goal(),event('task_started',turn_id='work'),
            response('root','work','r1',40)])
        unrelated=rollout(tmp_path,'unrelated',[])
        with unrelated.open('a') as stream:
            stream.write('not-json-unrelated-history\n' * 800000)
        assert observe_usage(tmp_path,'root',CREATED)['used_tokens']==40


    def test_indexed_provider_continuation_stop_is_not_free_work(self):
        root = rollout(self.home, 'root', [], model_provider='grok__personal', timestamp=START)
        middle = rollout(self.home, 'openai-route', [], parent_thread_id='root',
                         forked_from_id='root', model_provider='openai')
        stopped = rollout(self.home, 'grok-return', [
            event('task_started', turn_id='stopped'),
            event('turn_aborted', turn_id='stopped', reason='interrupted')],
            parent_thread_id='openai-route', forked_from_id='openai-route',
            model_provider='grok__personal')
        connection = sqlite3.connect(self.home/'state_5.sqlite')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT)')
        connection.executemany('INSERT INTO threads VALUES(?,?,?)', [
            ('root', str(root), 'cli'), ('openai-route', str(middle), 'cli'),
            ('grok-return', str(stopped), 'cli')])
        connection.commit()
        directory = self.home/'provider_continuations'; directory.mkdir(mode=0o700)
        for source, successor in [('root', 'openai-route'), ('openai-route', 'grok-return')]:
            journal = directory/(source+'.json')
            journal.write_text(json.dumps(dict(version=1, source=source, successor=successor,
                session_id='root', state='ready', authority_revision='a'*64, context_revision='b'*64)))
            journal.chmod(0o600)
        result = observe_usage(self.home, 'root', 0, session_scope=True,
                               token_accounting='cache_inclusive')
        self.assertEqual(result['state'], 'unknown', result)
        self.assertIsNone(result['used_tokens'])
        self.assertEqual(result['reason'], 'provider_completion_unconfirmed')

        rollout(self.home, 'grok-return', [event('task_started', turn_id='settled'),
            response('grok-return', 'settled', 'actual-charge', 20),
            event('task_complete', turn_id='settled')], parent_thread_id='openai-route',
            forked_from_id='openai-route', model_provider='grok__personal')
        settled = observe_usage(self.home, 'root', 0, session_scope=True,
                                token_accounting='cache_inclusive')
        self.assertEqual(settled['state'], 'qualified', settled)
        self.assertEqual(settled['used_tokens'], 20)
        self.assertEqual(set(settled['thread_ids']), {'root', 'openai-route', 'grok-return'})
        journal = directory/'openai-route.json'; good = json.loads(journal.read_text())
        for change in ({'state': 'held'}, {'session_id': 'foreign-session'}):
            with self.subTest(invalid_journal=change):
                journal.write_text(json.dumps(dict(good, **change)))
                held = observe_usage(self.home, 'root', 0, session_scope=True)
                self.assertEqual(held['state'], 'unknown', held)
                self.assertIsNone(held['used_tokens'])
        journal.write_text(json.dumps(good))
        connection.execute("DELETE FROM threads WHERE id='grok-return'"); connection.commit()
        missing = observe_usage(self.home, 'root', 0, session_scope=True)
        self.assertEqual(missing['state'], 'unknown', missing)
        self.assertIsNone(missing['used_tokens'])

    def test_staged_continuation_keeps_current_source_accounting(self):
        root = rollout(self.home, 'root', [event('task_started', turn_id='work'),
            response('root', 'work', 'settled', 40)], timestamp=START)
        connection = sqlite3.connect(self.home/'state_5.sqlite')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT)')
        connection.execute('INSERT INTO threads VALUES(?,?,?)', ('root', str(root), 'cli'))
        connection.commit()
        directory = self.home/'provider_continuations'; directory.mkdir(mode=0o700)
        journal = directory/'root.json'
        for state in ('staged', 'preparing', 'ready'):
            journal.write_text(json.dumps(dict(version=1, source='root', successor='not-created',
                session_id='root', state=state, authority_revision='a'*64, context_revision='b'*64)))
            journal.chmod(0o600)
            result = observe_usage(self.home, 'root', 0, session_scope=True,
                                   token_accounting='cache_inclusive')
            if state == 'ready':
                self.assertEqual(result['state'], 'unknown', result)
                self.assertIsNone(result['used_tokens'])
            else:
                self.assertEqual(result['state'], 'qualified', result)
                self.assertEqual(result['used_tokens'], 40)

    def test_indexed_shared_home_excludes_thousands_of_unrelated_rollouts(self):
        root=rollout(self.home,'root',[goal(),event('task_started',turn_id='work'),
            event('collab_agent_spawn_end',new_thread_id='child'),response('root','work','parent',40)])
        child=rollout(self.home,'child',[response('child','child-work','child-response',20,'work')],
                      parent_thread_id='root')
        connection=sqlite3.connect(self.home/'state_5.sqlite')
        self.addCleanup(connection.close)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT)')
        connection.execute('CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT,status TEXT)')
        connection.executemany('INSERT INTO threads VALUES(?,?,?)',[
            ('root',str(root),'cli'),('child',str(child),json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':'root'}}}))])
        # Match the native indexed source exactly in canonical child metadata.
        rows=child.read_text().splitlines();meta=json.loads(rows[0]);meta['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':'root'}}};rows[0]=json.dumps(meta);child.write_text('\n'.join(rows)+'\n')
        for index in range(4100):
            path=self.home/'sessions'/f'unrelated-{index}.jsonl'
            path.write_text(json.dumps(row('session_meta',dict(id=f'unrelated-{index}',source='cli',session_id='other')))+'\ncorrupt unrelated body\n')
            connection.execute('INSERT INTO threads VALUES(?,?,?)',(f'unrelated-{index}',str(path),'cli'))
        connection.commit()
        # Leave committed rows in a live WAL; immutable=1 would miss this index.
        result=observe_usage(self.home,'root',CREATED)
        self.assertEqual(result['state'],'qualified',result)
        self.assertEqual(result['used_tokens'],60)
        connection.execute("DELETE FROM threads WHERE id='child'")
        connection.commit()
        self.assertEqual(observe_usage(self.home,'root',CREATED)['state'],'unknown')
        outside=self.home/'outside.jsonl';outside.write_bytes(root.read_bytes())
        connection.execute("UPDATE threads SET rollout_path=? WHERE id='root'",(str(outside),))
        connection.commit()
        self.assertEqual(observe_usage(self.home,'root',CREATED)['state'],'unknown')
