"""Connector delegation through the existing authenticated controller seam."""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

from codex_wake.controller_auth import OAuthAuthority, AuthError
from codex_wake.controller_http import ProtectedOperations
from codex_wake.managed_inventory import InventoryError


class ConnectorTests(unittest.TestCase):
    def token(self,auth,scopes,targets,*,kind='owner'):
        client=auth.register({'redirect_uris':['http://localhost/callback']})
        verifier='x'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        code=auth.authorize(subject='owner',principal_kind=kind,client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],resource=auth.resource,scopes=scopes,targets=targets,code_challenge=challenge)
        return auth.token(dict(grant_type='authorization_code',client_id=client['client_id'],code=code,redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource))['access_token']

    def test_operator_delegation_intersects_targets_actions_expiry_and_parent_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            auth=OAuthAuthority(Path(directory)/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller',now=lambda:100)
            owner=self.token(auth,['admin','observe','control'],[dict(host='h',environment='e',workspace='dev')])
            service=ProtectedOperations(auth,SimpleNamespace(host='h',environment='e'))
            client=auth.register({'redirect_uris':['http://localhost/callback']});verifier='y'*43
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            args=dict(mode='subset',client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],code_challenge=challenge,scopes=['observe'],targets=[dict(host='h',environment='e')],actions=['environment.snapshot'],expires_in=900,idempotency_key='delegation-one')
            value=service.execute(owner,'connectors.grants.create',args)['result']
            self.assertEqual(service.execute(owner,'connectors.grants.create',args)['result'],value)
            child=auth.token(dict(grant_type='authorization_code',client_id=client['client_id'],code=value['code'],redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource))['access_token']
            delegated=auth.authenticate(child)
            self.assertEqual(delegated.targets,[dict(host='h',environment='e',workspace='dev')])
            self.assertEqual(delegated.expires_at,auth.authenticate(owner).expires_at)
            with self.assertRaises(AuthError):service.execute(child,'inventory.list',{})
            with self.assertRaises(AuthError):service.execute(child,'connectors.grants.create',args)
            blocked=service.execute(owner,'connectors.grants.create',dict(args,scopes=['control'],actions=['tabs.capture','tabs.input'],idempotency_key='controls-only'))['result']
            restricted=auth.token(dict(grant_type='authorization_code',client_id=client['client_id'],code=blocked['code'],redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource))['access_token']
            for legacy in ('tabs.capture','environment.tabs.capture','tabs.input'):
                with self.assertRaises(AuthError):service.execute(restricted,legacy,{})
            auth.revoke_grant(auth.authenticate(owner).grant_id)
            with self.assertRaises(AuthError):auth.authenticate(child)

    def test_metadata_only_delegation_cannot_read_stored_program_definition(self):
        import socket,os
        host=socket.gethostname();environment=os.environ.get('WSL_DISTRO_NAME') or os.name
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            operator=self.token(auth,['admin','control','observe','content.observe'],[dict(host=host,environment=environment)])
            api=ProtectedOperations(auth,SimpleNamespace(host=host,environment=environment,inventory=SimpleNamespace(root=root)))
            definition=dict(id='private-plan',version=1,entry='done',nodes=[dict(id='done',type='end',value='private prompt')])
            api.execute(operator,'programs.definitions.publish',dict(definition=definition))
            client=auth.register({'redirect_uris':['http://localhost/callback']});verifier='z'*43
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            for scopes in (['observe'],['observe','content.observe']):
                grant=api.execute(operator,'connectors.grants.create',dict(mode='subset',client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],code_challenge=challenge,scopes=scopes,targets=[dict(host=host,environment=environment)],actions=['programs.definitions.show'],expires_in=900,idempotency_key='read-'+str(len(scopes))))['result']
                token=auth.token(dict(grant_type='authorization_code',client_id=client['client_id'],code=grant['code'],redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource))['access_token']
                for operation in ('flows.definition','programs.definitions.show'):
                    if 'content.observe' not in scopes:
                        with self.assertRaises(AuthError):api.execute(token,operation,dict(flow_id='private-plan',version=1))
                    else:
                        value=api.execute(token,operation,dict(flow_id='private-plan',version=1))
                        self.assertEqual(value['result']['definition']['nodes'][0]['value'],'private prompt')

    def test_environment_projection_honors_resource_scope_and_legacy_action_names(self):
        from codex_wake.controller_tabs import ControllerTabs
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            tabs=ControllerTabs(root,workspaces={},host='h',environment='e')
            tabs.execute('tabs.session.create',{'name':'dev tabs'});tabs.execute('tabs.session.create',{'name':'codex-bots'})
            ops=SimpleNamespace(host='h',environment='e',tabs=tabs)
            api=ProtectedOperations(auth,ops)
            full=self.token(auth,['observe'],[dict(host='h',environment='e')])
            view=api.execute(full,'environment.snapshot',{})['result'];selected=next(s for s in view['sessions'] if s['name']=='dev tabs')
            narrow=self.token(auth,['observe'],[dict(host='h',environment='e',resource_id=selected['id'])])
            visible=api.execute(narrow,'environment.snapshot',{})['result']
            self.assertEqual([s['name'] for s in visible['sessions']],['dev tabs'])
            self.assertEqual(visible['agents'],[])
            with self.assertRaises(InventoryError):api.execute(narrow,'environment.children',dict(resource_id=next(s['id'] for s in view['sessions'] if s['name']=='codex-bots')))

    def test_content_observation_requires_content_scope_and_rechecks_revocation_on_page(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);auth=OAuthAuthority(root/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            target=dict(host='h',environment='e',uid=os.getuid(),home=str(root),process=dict(pid=os.getpid()),conversation_id='conversation')
            row=dict(thread_id='conversation',target=target,endpoint='unix:///owned.sock',codex_cmd=['codex'])
            ops=SimpleNamespace(host='h',environment='e',inventory=SimpleNamespace(root=root))
            api=ProtectedOperations(auth,ops)
            content=self.token(auth,['content.observe'],[dict(host='h',environment='e',conversation_id='conversation')])
            metadata=self.token(auth,['observe'],[dict(host='h',environment='e')])
            args=dict(selector='thread:conversation',turn_id='turn',expected_target=target)
            with patch('codex_wake.local_session_observation.resolve',return_value=row),patch('codex_wake.local_session_observation.native_request',return_value={'thread':{'id':'conversation','turns':[dict(id='turn',status='inProgress',items=[])]}}) as native:
                with self.assertRaises(AuthError):api.execute(metadata,'environment.conversations.observe',args)
                attached=api.execute(content,'environment.conversations.observe',args)['result'];count=native.call_count
                auth.revoke_grant(auth.authenticate(content).grant_id)
                with self.assertRaises(AuthError):api.execute(content,'environment.conversations.observation.output',dict(observation_id=attached['observation_id']))
                self.assertEqual(native.call_count,count)

    def test_host_route_carries_action_attenuation_and_never_falls_back_offline(self):
        from codex_wake.controller_hosts import HostRegistry,HostOperations
        from codex_wake.controller_auth import Actor
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as directory:
            registry=HostRegistry(Path(directory)/'hosts.sqlite',now=lambda:100)
            row=registry.register('remote','byobu',kind='remote',authority='remote-authority',destination='registered-peer',capabilities=['environment.snapshot'],operator=True)
            sent=[]
            class Transport:
                def send(self,registered,request):
                    sent.append(request)
                    return dict(schema_version=1,operation='environment.snapshot',status='completed',result=dict(sessions=[]))
            actor=Actor('owner','service','client','grant','https://wake.test','https://wake.test/controller',frozenset({'observe'}),[dict(row['target'])],200,frozenset({'environment.snapshot'}))
            owner=HostOperations(registry,transport=Transport())
            args=dict(target=row['target'],operation='environment.snapshot',arguments={},operation_id='one',idempotency_key='one')
            first=owner.route(args,actor=actor,authorize=lambda:actor)
            self.assertEqual(first['route']['delivery'],'received')
            self.assertEqual(sent[0]['constraints']['actions'],['environment.snapshot'])
            self.assertEqual(owner.route(args,actor=actor),first);self.assertEqual(len(sent),1)
            registry.observe(row['target'],online=False,operator=True)
            with self.assertRaises(InventoryError) as caught:owner.route(dict(args,operation_id='two',idempotency_key='two'),actor=actor)
            self.assertEqual(caught.exception.code,'offline_target');self.assertEqual(len(sent),1)

    def test_registered_management_route_executes_real_owner_once_with_narrowed_rights(self):
        from codex_wake.controller_hosts import HostRegistry,HostOperations,SSHReceiver
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.managed_inventory import ManagedInventory
        from codex_wake.controller_auth import Actor
        with tempfile.TemporaryDirectory() as directory:
            import time
            root=Path(directory);registry=HostRegistry(root/'hosts.sqlite')
            import socket,os
            host=socket.gethostname();environment=os.environ.get('WSL_DISTRO_NAME') or os.name
            operations=['flows.publish','flows.definition']
            registered=registry.register(host,environment,kind='remote',authority='authority',destination='fixed-peer',capabilities=operations,operator=True)
            registry.map_principal('connector',subject='operator',scopes=['control','observe','content.observe'],targets=[dict(host=host,environment=environment,flow_id='owned')],expires_at=time.time()+300,operator=True)
            receiver=SSHReceiver(registry,ControllerOperations(ManagedInventory(root/'wake'),host=host,environment=environment),principal_id='connector',target=registered['target'])
            sent=[]
            class Transport:
                def send(self,registered,request):sent.append(request);return receiver.execute(request)
            actor=Actor('owner','service','client','grant','https://wake.test','https://wake.test/controller',frozenset({'control','observe','content.observe'}),[dict(registered['target'],flow_id='owned')],time.time()+200,frozenset({'programs.definitions.publish','programs.definitions.show'}))
            owner=HostOperations(registry,transport=Transport())
            definition=dict(id='owned',version=1,entry='done',nodes=[dict(id='done',type='end',value='published')])
            args=dict(target=registered['target'],operation='flows.publish',arguments={'definition':definition},operation_id='publish',idempotency_key='publish')
            first=owner.route(args,actor=actor,authorize=lambda:actor)
            self.assertEqual(first['route']['execution'],'completed')
            self.assertEqual(first['route']['effect'],'management_action')
            self.assertEqual(owner.route(args,actor=actor),first);self.assertEqual(len(sent),1)
            denied=owner.route(dict(args,operation='flows.definition',arguments=dict(flow_id='owned',version=1),operation_id='metadata-only',idempotency_key='metadata-only'),actor=replace(actor,scopes=frozenset({'control','observe'})))
            self.assertEqual(denied['route']['execution'],'not_started')
            read=owner.route(dict(args,operation='flows.definition',arguments=dict(flow_id='owned',version=1),operation_id='read',idempotency_key='read'),actor=actor)
            self.assertEqual(read['route']['result']['result']['definition'],definition)
            with self.assertRaises(AuthError):owner.route(dict(args,operation='flows.publish',operation_id='denied',idempotency_key='denied'),actor=replace(actor,actions=frozenset({'programs.definitions.show'})))

class DelegatedCredentialCompatibilityTests(unittest.TestCase):
    def test_published_legacy_reader_refuses_new_code_access_and_refresh_credentials(self):
        # Exercise the actual immutable prior public reader, not a current-schema proxy.
        import subprocess
        import sys
        import types
        baseline='1aa498674a4907f93b5216a4a98dd75a22c6ecec'
        try:
            source=subprocess.check_output(['git','-C',str(Path(__file__).resolve().parents[1]),'show',baseline+':src/codex_wake/controller_auth.py'],text=True,stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError,FileNotFoundError):
            self.skipTest('Historical-reader qualification requires the recorded Git baseline.')
        module=types.ModuleType('wake_legacy_auth_reader');sys.modules[module.__name__]=module
        exec(compile(source,'git:'+baseline,'exec'),module.__dict__)
        with tempfile.TemporaryDirectory() as directory:
            auth=OAuthAuthority(Path(directory)/'auth.sqlite',issuer='https://wake.test',resource='https://wake.test/controller')
            parent=ConnectorTests().token(auth,['observe','control','admin'],[dict(host='h',environment='e')])
            client=auth.register({'redirect_uris':['http://localhost/callback']});verifier='z'*43
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            child=auth.delegate(auth.authenticate(parent),client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],code_challenge=challenge,mode='subset',scopes=['observe'],targets=[dict(host='h',environment='e')],actions=['inventory.resolve'])
            legacy=module.OAuthAuthority(auth.path,issuer=auth.issuer,resource=auth.resource)
            args=dict(grant_type='authorization_code',client_id=client['client_id'],code=child['code'],redirect_uri=client['redirect_uris'][0],code_verifier=verifier,resource=auth.resource)
            with self.assertRaises(module.AuthError):legacy.token(args)
            tokens=auth.token(args)
            self.assertEqual(auth.authenticate(tokens['access_token']).actions,frozenset({'environment.resources.resolve'}))
            with self.assertRaises(module.AuthError):legacy.authenticate(tokens['access_token'])
            refresh=dict(grant_type='refresh_token',client_id=client['client_id'],refresh_token=tokens['refresh_token'],resource=auth.resource)
            with self.assertRaises(module.AuthError):legacy.token(refresh)
            renewed=auth.token(refresh)
            self.assertEqual(auth.authenticate(renewed['access_token']).actions,frozenset({'environment.resources.resolve'}))
            auth.revoke_grant(auth.authenticate(parent).grant_id)
            with self.assertRaises(AuthError):auth.authenticate(renewed['access_token'])
