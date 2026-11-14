"""Bulk management through the existing protected owner and durable flow seam."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_wake.controller_auth import OAuthAuthority,AuthError
from codex_wake.controller_http import ProtectedOperations
from test_recurring_schedules import request


class BulkTests(unittest.TestCase):
    def test_bulk_registers_distinct_owned_schedules_and_reconnects_to_same_results(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        with tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            threads=['11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222']
            token=ConnectorTests().token(auth,['control','observe','content.observe'],[dict(host='h',environment='e',conversation_id=t) for t in threads])
            operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root))
            def owner():return BulkControls(auth,operations,token)
            members=[dict(id='check-'+str(i),target=dict(host='h',environment='e',conversation_id=t),operation='wakes.schedules.register',arguments={'request':request(thread_id=t)},completion='admission') for i,t in enumerate(threads)]
            args=dict(members=members,policies=dict(failure='stop',join='all_success',uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='register-checks',binding='connector')
            started=owner().start(**args);run=started['run_id']
            self.assertEqual(started['phase'],'ready')
            owner().advance(run)
            result=owner().result(run)
            self.assertEqual(result['phase'],'completed')
            self.assertEqual([m['state'] for m in result['members']],['completed','completed'])
            ids=[m['result']['id'] for m in result['members']]
            self.assertEqual(len(set(ids)),2)
            for item in result['members']:
                stored=ProtectedOperations(auth,operations).execute(token,'wakes.schedules.show',dict(schedule_id=item['result']['id']))['result']
                self.assertEqual(stored['request']['idempotency_key'],item['domain_key'])
            self.assertEqual(owner().start(**args)['run_id'],run)
            self.assertEqual(owner().advance(run)['members'],owner().status(run)['members'])
            auth.revoke_grant(auth.authenticate(token).grant_id)
            with self.assertRaises(AuthError):owner().result(run)

    def test_bulk_known_failure_obeys_stop_or_continue_and_join_policy(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        original=ProtectedOperations.execute
        for failure,join,phase,states in [('stop','all_success','failed',['failed','not_started']),('continue','all_complete','completed',['failed','completed'])]:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
                root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
                threads=['11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222']
                token=ConnectorTests().token(auth,['control','observe','content.observe'],[dict(host='h',environment='e',conversation_id=t) for t in threads])
                operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root))
                members=[dict(id='check-'+str(i),target=dict(host='h',environment='e',conversation_id=t),operation='wakes.schedules.register',arguments={'request':request(thread_id=t)},completion='admission') for i,t in enumerate(threads)]
                def response(owner,token,operation,args):
                    if operation=='wakes.schedules.register' and args['request']['thread_id']==threads[0]:
                        return dict(schema_version=1,operation=operation,status='failed',error=dict(code='known_refusal'))
                    return original(owner,token,operation,args)
                owner=BulkControls(auth,operations,token)
                run=owner.start(members=members,policies=dict(failure=failure,join=join,uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='checks',binding='connector')['run_id']
                with patch('codex_wake.controller_http.ProtectedOperations.execute',response):owner.advance(run)
                result=BulkControls(auth,operations,token).result(run)
                self.assertEqual(result['phase'],phase);self.assertEqual([m['state'] for m in result['members']],states)

    def test_interrupted_registration_reconciles_exact_domain_key_without_replay(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        original=ProtectedOperations.execute
        with tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            thread='11111111-1111-4111-8111-111111111111'
            token=ConnectorTests().token(auth,['control','observe','content.observe'],[dict(host='h',environment='e',conversation_id=thread)])
            operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root))
            members=[dict(id='check',target=dict(host='h',environment='e',conversation_id=thread),operation='wakes.schedules.register',arguments={'request':request(thread_id=thread)},completion='admission')]
            def owner():return BulkControls(auth,operations,token)
            run=owner().start(members=members,policies=dict(failure='stop',join='all_success',uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='checks',binding='connector')['run_id']
            submissions=[]
            def lost_reply(service,token,operation,args):
                value=original(service,token,operation,args)
                if operation=='wakes.schedules.register':submissions.append(value['result']['id']);raise SystemExit('lost after schedule owner persisted')
                return value
            with patch('codex_wake.controller_http.ProtectedOperations.execute',lost_reply):
                with self.assertRaises(SystemExit):owner().advance(run)
            self.assertEqual(owner().advance(run)['members'][0]['state'],'uncertain')
            owner().reconcile(run);owner().advance(run)
            result=owner().result(run)
            self.assertEqual(result['phase'],'completed');self.assertEqual(result['members'][0]['result']['id'],submissions[0]);self.assertEqual(len(submissions),1)

    def test_terminal_completion_waits_for_original_session_handle_before_next_action(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        original=ProtectedOperations.execute
        with tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            thread='11111111-1111-4111-8111-111111111111';target=dict(host='h',environment='e',conversation_id=thread)
            token=ConnectorTests().token(auth,['control','observe','content.observe'],[target]);operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root));ready=[False];submitted=[]
            members=[dict(id='prompt',target=target,operation='environment.conversations.input.submit',arguments=dict(selector='thread:'+thread,prompt='Check status',policy='reject'),completion='terminal',wait_operation='environment.conversations.input.result'),
                dict(id='wake',target=target,operation='wakes.schedules.register',arguments={'request':request(thread_id=thread)},completion='admission')]
            def native(service,token,operation,args):
                if operation=='environment.conversations.input.submit':
                    submitted.append(args['idempotency_key']);return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='waiting',execution='queued')))
                if operation=='environment.conversations.input.result':
                    self.assertEqual(args['operation_id'],'native-original')
                    return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='terminal' if ready[0] else 'waiting',execution='completed' if ready[0] else 'running',answer={'text':'Done.'} if ready[0] else None)))
                return original(service,token,operation,args)
            def owner():return BulkControls(auth,operations,token)
            run=owner().start(members=members,policies=dict(failure='stop',join='all_success',uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='prompt-and-wake',binding='connector')['run_id']
            with patch('codex_wake.controller_http.ProtectedOperations.execute',native):
                waiting=owner().advance(run);self.assertEqual(waiting['phase'],'waiting');self.assertEqual(waiting['members'][1]['state'],'not_started')
                ready[0]=True;owner().advance(run);result=owner().result(run)
            self.assertEqual(result['phase'],'completed');self.assertEqual(result['members'][0]['result']['operation']['answer']['text'],'Done.');self.assertEqual(len(submitted),1)

    def test_terminal_wait_reconciles_original_handle_after_uncertainty_or_disconnect(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        original=ProtectedOperations.execute
        for lost_reply in (False,True):
            with self.subTest(lost_reply=lost_reply),tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
                root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
                thread='11111111-1111-4111-8111-111111111111';target=dict(host='h',environment='e',conversation_id=thread)
                token=ConnectorTests().token(auth,['control','observe','content.observe'],[target])
                operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root));ready=[False];submitted=[]
                members=[dict(id='prompt',target=target,operation='environment.conversations.input.submit',arguments=dict(selector='thread:'+thread,prompt='Check status',policy='reject'),completion='terminal',wait_operation='environment.conversations.input.result')]
                def native(service,token,operation,args):
                    if operation=='environment.conversations.input.submit':
                        submitted.append(args['idempotency_key'])
                        return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='waiting',execution='queued')))
                    if operation=='environment.conversations.input.result':
                        self.assertEqual(args['operation_id'],'native-original')
                        if lost_reply and not ready[0]:raise SystemExit('disconnect during original wait')
                        return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='terminal' if ready[0] else 'uncertain',execution='completed' if ready[0] else 'unknown',answer='Done' if ready[0] else None)))
                    return original(service,token,operation,args)
                def owner():return BulkControls(auth,operations,token)
                run=owner().start(members=members,policies=dict(failure='stop',join='all_success',uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='wait-recovery',binding='connector')['run_id']
                with patch('codex_wake.controller_http.ProtectedOperations.execute',native):
                    if lost_reply:
                        with self.assertRaises(SystemExit):owner().advance(run)
                    else:
                        uncertain=owner().advance(run)
                        self.assertEqual(uncertain['phase'],'uncertain')
                        self.assertEqual(uncertain['members'][0]['state'],'uncertain')
                    ready[0]=True
                    owner().reconcile(run);owner().advance(run)
                result=owner().result(run)
                self.assertEqual(result['phase'],'completed')
                self.assertEqual(result['members'][0]['result']['operation']['answer'],'Done')
                self.assertEqual(len(submitted),1)

    def test_explicit_safe_read_retry_is_bounded_and_effect_retries_are_refused(self):
        from codex_wake.unified_bulk import BulkControls
        from codex_wake.managed_inventory import InventoryError
        from test_unified_connectors import ConnectorTests
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            token=ConnectorTests().token(auth,['control','observe','content.observe'],[dict(host='h',environment='e')]);operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root))
            policies=dict(failure='stop',join='all_success',uncertain='hold',retry=dict(max_attempts=2,when=['unavailable']))
            members=[dict(id='read',target=dict(host='h',environment='e'),operation='inventory.list',arguments={},completion='admission')]
            owner=BulkControls(auth,operations,token);run=owner.start(members=members,policies=policies,inputs={},limits={},intent='read',binding='connector')['run_id']
            calls=[]
            def read(service,token,operation,args):
                calls.append(operation)
                return dict(schema_version=1,operation=operation,status='failed',error=dict(code='unavailable')) if len(calls)==1 else dict(schema_version=1,operation=operation,status='completed',result=dict(resources=[]))
            with patch('codex_wake.controller_http.ProtectedOperations.execute',read):
                owner.advance(run);owner.advance(run)
            self.assertEqual(owner.result(run)['phase'],'completed');self.assertEqual(calls,['inventory.list','inventory.list'])
            member=dict(members[0],operation='wakes.schedules.register',target=dict(host='h',environment='e',conversation_id='11111111-1111-4111-8111-111111111111'),arguments={'request':request()})
            with self.assertRaises(InventoryError) as caught:owner.start(members=[member],policies=policies,inputs={},limits={},intent='effect',binding='connector')
            self.assertEqual(caught.exception.code,'unsafe_retry')

    def test_uncertain_native_admission_holds_then_reconciles_original_owner_without_resubmit(self):
        from codex_wake.unified_bulk import BulkControls
        from test_unified_connectors import ConnectorTests
        original=ProtectedOperations.execute
        with tempfile.TemporaryDirectory() as directory,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            thread='11111111-1111-4111-8111-111111111111';target=dict(host='h',environment='e',conversation_id=thread)
            token=ConnectorTests().token(auth,['control','observe','content.observe'],[target]);operations=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root));submissions=[];observations=[]
            members=[dict(id='prompt',target=target,operation='environment.conversations.input.submit',arguments=dict(selector='thread:'+thread,prompt='Check status',policy='reject'),completion='admission'),dict(id='wake',target=target,operation='wakes.schedules.register',arguments={'request':request(thread_id=thread)},completion='admission')]
            def native(service,token,operation,args):
                if operation=='environment.conversations.input.submit':
                    submissions.append(args['idempotency_key']);return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='uncertain',execution='unknown')))
                if operation=='environment.conversations.input.result':
                    observations.append(args['operation_id']);return dict(schema_version=1,operation=operation,status='completed',result=dict(operation=dict(operation_id='native-original',phase='terminal',execution='completed')))
                return original(service,token,operation,args)
            def owner():return BulkControls(auth,operations,token)
            run=owner().start(members=members,policies=dict(failure='continue',join='all_complete',uncertain='hold',retry=dict(max_attempts=1,when=[])),inputs={},limits={},intent='uncertain',binding='connector')['run_id']
            with patch('codex_wake.controller_http.ProtectedOperations.execute',native):
                uncertain=owner().advance(run);self.assertEqual(uncertain['phase'],'uncertain');self.assertEqual(uncertain['members'][1]['state'],'not_started')
                owner().reconcile(run);owner().advance(run)
            self.assertEqual(owner().result(run)['phase'],'completed');self.assertEqual(len(submissions),1);self.assertEqual(observations,['native-original'])
