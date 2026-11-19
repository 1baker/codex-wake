"""Common A2A policy is enforced at admission, consumption and notification."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_wake.a2a_bus import BusStore
from codex_wake.a2a_identity import BusError, RuntimeIdentity
from codex_wake.a2a_mailbox import Mailbox
from codex_wake.session_permissions import PermissionStore, Principal


class A2APermissionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.bus,self.operator=BusStore.configure(self.root/'bus')
        self.bus.enroll(self.repo,self.operator,notify=True)
        self.identities=[RuntimeIdentity('fixture',x,str(self.repo)) for x in ('sender','recipient')]
        self.actors=[];self.caps=[]
        for identity in self.identities:
            cap,_=self.bus.issue_actor(identity,self.repo,self.operator)
            self.caps.append(cap)
            self.actors.append(self.bus.authenticate(cap,identity,invoking_cwd=self.repo))
        Mailbox.migrate(self.bus,self.operator)
        self.mailbox=Mailbox(self.bus,clock=lambda:1000,monotonic=lambda:1000)
        self.policy=PermissionStore(self.root/'wake',now=lambda:1000)

    def adopt(self,policy):
        self.policy.configure(policy,Principal('operator','operator'),expected_revision=0)
        self.bus.bind_permissions(self.policy.root,self.operator)

    def send(self,**kwargs):
        return self.mailbox.send(self.actors[0],self.identities[1],body='request',
            idempotency_key=kwargs.pop('idempotency_key','intent'),**kwargs)

    def test_public_send_refuses_denied_receiver_with_zero_mailbox_effect(self):
        from codex_wake.cli import run
        self.adopt({'version':1,'sessions':{'recipient':{'actions':{'a2a.receive':'deny'}}}})
        body=self.root/'body.txt';body.write_text('request')
        output=StringIO()
        with patch('codex_wake.messages_cli.invoking_actor',return_value=self.actors[0]), \
             patch('codex_wake.messages_cli.resolve_identity',return_value=self.identities[1]),redirect_stdout(output):
            code=run(['messages','send','--bus-root',str(self.bus.root),'--capability',str(self.caps[0]),
                '--to','thread:recipient','--body-file',str(body),'--idempotency-key','public',
                '--delivery','inbox','--wake-root',str(self.root/'untrusted-other-root'),'--json'])
        self.assertNotEqual(code,0,output.getvalue())
        value=json.loads(output.getvalue())
        self.assertEqual(value['error']['code'],'permission_deny')
        self.assertEqual(self.mailbox.list(self.actors[1])['messages'],[])

    def test_both_sides_and_claim_reply_are_separate_policy_actions(self):
        self.adopt({'version':1})
        original=self.send(delivery='inbox')
        identifier=original['message']['message_id']
        read=self.mailbox.read(self.actors[1],identifier)
        self.assertEqual(read['peer_content_trust'],'untrusted')
        self.assertIsNone(read['message']['claim_receipt_id'])
        claimed=self.mailbox.ack(self.actors[1],identifier,outcome='accepted')
        self.assertTrue(claimed['claimed'])
        self.assertFalse(self.mailbox.ack(self.actors[1],identifier,outcome='accepted')['claimed'])
        reply=self.mailbox.reply(self.actors[1],identifier,body='result',idempotency_key='reply',delivery='inbox')
        again=self.mailbox.reply(self.actors[1],identifier,body='result',idempotency_key='reply',delivery='inbox')
        self.assertEqual(reply['message']['message_id'],again['message']['message_id'])
        self.assertEqual(reply['message']['in_reply_to'],identifier)
        self.assertEqual(reply['message']['expires_at'],again['message']['expires_at'])
        self.policy.configure({'version':1,'sessions':{'recipient':{'actions':{'a2a.reply':'deny'}}}},
            Principal('operator','operator'),expected_revision=1)
        with self.assertRaises(BusError) as error:
            self.mailbox.reply(self.actors[1],identifier,body='second result',idempotency_key='reply2',delivery='inbox')
        self.assertEqual(error.exception.code,'permission_deny')
        self.assertEqual(len(self.mailbox.list(self.actors[0])['messages']),1)

    def test_revocation_blocks_body_claim_and_new_send_but_preserves_reconciliation(self):
        self.adopt({'version':1})
        identifier=self.send()['message']['message_id']
        self.policy.configure({'version':1,'mandatory':['a2a.receive']},Principal('op','operator'),expected_revision=1)
        reopened=Mailbox(BusStore(self.bus.root),clock=lambda:1000,monotonic=lambda:1000)
        for operation in (lambda:reopened.read(self.actors[1],identifier),
                          lambda:reopened.ack(self.actors[1],identifier,outcome='accepted'),
                          lambda:self.send(idempotency_key='new')):
            with self.assertRaises(BusError) as error:operation()
            self.assertEqual(error.exception.code,'permission_deny')
        reconciled=reopened.reconcile(self.actors[1],identifier)
        self.assertFalse(reconciled['grants_new_processing'])
        self.assertEqual(reconciled['message']['processing_claim']['state'],'unclaimed')
        self.assertEqual(reconciled['message']['idempotency_key'],'intent')

    def test_claim_deny_does_not_prevent_metadata_observation(self):
        self.adopt({'version':1,'sessions':{'recipient':{'actions':{'a2a.claim':'deny'}}}})
        identifier=self.send(delivery='inbox')['message']['message_id']
        self.mailbox.read(self.actors[1],identifier)
        with self.assertRaises(BusError):self.mailbox.ack(self.actors[1],identifier,outcome='accepted')
        self.assertEqual(self.mailbox.show(self.actors[1],identifier)['processing_claim']['state'],'unclaimed')

    def test_bound_policy_loss_cannot_restore_legacy_send(self):
        self.adopt({'version':1})
        self.policy.path.unlink()
        with self.assertRaises(BusError) as error:self.send()
        self.assertEqual(error.exception.code,'permission_policy_unavailable')

    @patch('codex_wake.measurements.utc_bounds', return_value=(1000, 1001))
    def test_task_scope_comes_only_from_operator_bound_approved_briefs(self, _clock):
        from codex_wake.task_briefs import TaskBriefStore,BriefAuthority
        self.adopt({'version':1,'global':{'actions':{
            'a2a.send':{'decision':'allow','tasks':['task'],'targets':['recipient']},
            'a2a.receive':{'decision':'allow','tasks':['task'],'targets':['sender']}}}})
        with self.assertRaises(BusError):self.send(delivery='inbox')
        with self.assertRaises(BusError):self.send(delivery='inbox',task_id='task')
        briefs=TaskBriefStore(self.policy.root);authority=BriefAuthority('operator','operator')
        brief=dict(objective='Approved task',phase='implementation',non_goals=['No provider'],
            acceptance=['Fixture passes'],context=[],workspace=str(self.repo),
            allocation_ref='existing',permission_ref='common')
        briefs.propose('task',brief,authority=authority);briefs.approve('task',1,authority=authority)
        self.bus.bind_permission_tasks(self.actors[0].actor_id,['task'],self.operator)
        with self.assertRaises(BusError):self.send(delivery='inbox',task_id='task')
        self.bus.bind_permission_tasks(self.actors[1].actor_id,['task'],self.operator)
        sent=self.send(delivery='inbox',task_id='task')
        self.assertEqual(sent['message']['task_id'],'task')
        with self.assertRaises(BusError) as error:self.send(delivery='inbox',task_id='other-task')
        self.assertEqual(error.exception.code,'idempotency_conflict')
        self.assertEqual(sent['message']['expires_at'],self.send(delivery='inbox',task_id='task')['message']['expires_at'])

    def test_operator_cli_binding_is_private_and_cannot_be_retargeted_by_actor(self):
        from codex_wake.cli import run
        self.policy.configure({'version':1},Principal('op','operator'),expected_revision=0)
        output=StringIO()
        with redirect_stdout(output):
            status=run(['a2a','permissions','--bus-root',str(self.bus.root),
                '--operator-capability',str(self.operator),'--wake-root',str(self.policy.root),'--json'])
        self.assertEqual(status,0,output.getvalue())
        self.assertTrue(json.loads(output.getvalue())['bound'])
        other=PermissionStore(self.root/'other')
        other.configure({'version':1},Principal('op','operator'),expected_revision=0)
        with self.assertRaises(BusError) as error:self.bus.bind_permissions(other.root,self.operator)
        self.assertEqual(error.exception.code,'permission_binding_conflict')
        with self.assertRaises(BusError):self.bus.bind_permissions(self.policy.root,self.caps[0])
        reopened=Mailbox(BusStore(self.bus.root),clock=lambda:1000,monotonic=lambda:1000)
        with self.assertRaises(BusError):
            reopened.send(self.actors[0],RuntimeIdentity('fixture','unknown',str(self.repo)),
                body='request',idempotency_key='unknown')
        self.assertEqual(reopened.list(self.actors[1])['messages'],[])
