"""Canonical schedule controls retain stable public schedule identities."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_recurring_schedules import request

class UnifiedWakeTests(unittest.TestCase):
    def test_program_callable_schedule_revision_and_cancellation_preserve_identity(self):
        from codex_wake.unified_wakes import WakeControls
        from codex_wake.session_permissions import Principal
        with tempfile.TemporaryDirectory() as d,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            owner=WakeControls(Path(d),principal=Principal('local-operator','operator'),codex_path='/bin/true')
            created=owner.execute('wakes.schedules.register',{'request':request()})
            same=owner.execute('wakes.schedules.register',{'request':request()})
            self.assertEqual(created['id'],same['id'])
            revised=owner.execute('wakes.schedules.revise',{'schedule_id':created['id'],'expected_revision':1,'request':request(prompt='Revised check')})
            self.assertEqual(revised['revision'],2)
            cancelled=owner.execute('wakes.schedules.cancel',{'schedule_id':created['id'],'expected_revision':2})
            self.assertEqual(cancelled['state'],'cancelled')
            self.assertEqual(owner.execute('wakes.schedules.show',{'schedule_id':created['id']})['id'],created['id'])

    def test_delegated_retry_and_revision_recheck_current_thread_grant(self):
        from codex_wake.unified_wakes import WakeControls
        from codex_wake.session_permissions import Principal
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as d,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            allowed=[True]
            def grant(operation,args):
                if not allowed[0]:raise InventoryError('permission_denied','revoked')
            owner=WakeControls(Path(d),principal=Principal('connector','controller'),authorize=grant,codex_path='/bin/true')
            first=owner.execute('wakes.schedules.register',{'request':request()})
            same=owner.execute('wakes.schedules.register',{'request':request()})
            self.assertEqual(first['id'],same['id'])
            allowed[0]=False
            with self.assertRaisesRegex(InventoryError,'revoked'):owner.execute('wakes.schedules.cancel',{'schedule_id':first['id'],'expected_revision':1})

    def test_protected_schedule_operations_use_actual_actor_and_revoke_future_access(self):
        from types import SimpleNamespace
        from codex_wake.controller_auth import OAuthAuthority,AuthError
        from codex_wake.controller_http import ProtectedOperations
        from test_unified_connectors import ConnectorTests
        with tempfile.TemporaryDirectory() as d,patch('codex_wake.sessions.observe',return_value={'complete':False,'sessions':[]}):
            auth=OAuthAuthority(Path(d)/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            token=ConnectorTests().token(auth,['control','content.observe'],[dict(host='h',environment='e')])
            owner=ProtectedOperations(auth,SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=Path(d))))
            created=owner.execute(token,'wakes.schedules.register',{'request':request()})['result']
            same=owner.execute(token,'wakes.schedules.register',{'request':request()})['result']
            self.assertEqual(created['id'],same['id'])
            auth.revoke_grant(auth.authenticate(token).grant_id)
            with self.assertRaises(AuthError):owner.execute(token,'wakes.schedules.show',{'schedule_id':created['id']})
