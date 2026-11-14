"""External connector behavior through its OAuth/HTTP interface."""
import asyncio
import base64
import hashlib
import json
import re
from urllib.parse import urlsplit,parse_qs,urlencode
from pathlib import Path
import tempfile
import unittest

import httpx2 as httpx


class ExternalConnectorTests(unittest.TestCase):
    def config(self):
        return dict(issuer='https://wake.example',owner='operator',host='h',environment='e',
                    targets=[dict(host='h',environment='e')],scopes=['observe','content.observe'],
                    redirect_uris=['https://client.example/callback'],grant_seconds=3600,
                    authelia_url='http://127.0.0.1:19097/api/authz/forward-auth')

    def operations(self,root):
        from codex_wake.controller_operations import ControllerOperations
        from codex_wake.managed_inventory import ManagedInventory
        from codex_wake.controller_tabs import ControllerTabs
        return ControllerOperations(ManagedInventory(root),host='h',environment='e',tabs=ControllerTabs(root,workspaces={},host='h',environment='e'))

    def test_discovery_and_anonymous_mcp_challenge_share_exact_resource(self):
        from codex_wake.external_connector import create_app
        async def scenario(root):
            app=create_app(self.config(),Path(root),identify=lambda request:'operator',operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                metadata=await client.get('/.well-known/oauth-protected-resource/mcp')
                self.assertEqual(metadata.status_code,200)
                self.assertEqual(metadata.json()['resource'],'https://wake.example/mcp')
                denied=await client.post('/mcp',json=dict(jsonrpc='2.0',id=1,method='initialize',params={}))
                self.assertEqual(denied.status_code,401)
                self.assertIn('https://wake.example/.well-known/oauth-protected-resource/mcp',denied.headers['www-authenticate'])
        with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))

    def test_explicit_subset_consent_pkce_and_refresh_retain_action_scope(self):
        from codex_wake.external_connector import create_app
        async def scenario(root):
            app=create_app(self.config(),Path(root),identify=lambda request:'operator',operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                registered=await client.post('/register',json=dict(redirect_uris=['https://client.example/callback'],client_name='My connector'))
                self.assertEqual(registered.status_code,201)
                client_id=registered.json()['client_id'];verifier='v'*43
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                params=dict(client_id=client_id,redirect_uri='https://client.example/callback',resource='https://wake.example/mcp',response_type='code',code_challenge_method='S256',code_challenge=challenge,state='client-state',scope='observe')
                landing=await client.get('/authorize',params=params)
                self.assertEqual(landing.status_code,200)
                self.assertIn('My connector',landing.text)
                flow=re.search(r'name="flow" value="([^"]+)"',landing.text)[1]
                form=dict(flow=flow,decision='approve',mode='subset',scopes='observe',targets='0',actions='environment.snapshot')
                approved=await client.post('/authorize',data=form,headers={'Origin':'https://wake.example'})
                self.assertEqual(approved.status_code,303)
                callback=parse_qs(urlsplit(approved.headers['location']).query)
                self.assertEqual(callback['state'],['client-state']);self.assertEqual(callback['iss'],['https://wake.example'])
                exchange=dict(grant_type='authorization_code',client_id=client_id,code=callback['code'][0],redirect_uri=params['redirect_uri'],code_verifier=verifier,resource=params['resource'])
                wrong=await client.post('/token',data=dict(exchange,code_verifier='wrong'*12));self.assertEqual(wrong.status_code,400)
                token=await client.post('/token',data=exchange);self.assertEqual(token.status_code,200)
                replay=await client.post('/token',data=exchange);self.assertEqual(replay.status_code,400)
                refresh=await client.post('/token',data=dict(grant_type='refresh_token',client_id=client_id,refresh_token=token.json()['refresh_token'],resource=params['resource']))
                self.assertEqual(refresh.status_code,200);self.assertEqual(refresh.json()['scope'],'observe')
                from mcp import ClientSession
                from mcp.client.streamable_http import streamable_http_client
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),headers={'Authorization':'Bearer '+refresh.json()['access_token']}) as mcp_http:
                        async with streamable_http_client('https://wake.example/mcp',http_client=mcp_http) as streams:
                            async with ClientSession(streams[0],streams[1]) as session:
                                await session.initialize()
                                tools=await session.list_tools()
                                self.assertEqual([tool.name for tool in tools.tools],['wake_environment_snapshot'])
                                read=await session.call_tool('wake_environment_snapshot',{})
                                self.assertFalse(read.is_error)
                                self.assertEqual(read.structured_content['result']['schema_version'],1)
                                denied=await session.call_tool('wake_wakes_schedules_list',{})
                                self.assertTrue(denied.is_error)
                revoked=await client.post('/revoke',data=dict(token=refresh.json()['access_token'],client_id=client_id))
                self.assertEqual(revoked.status_code,200)
                blocked=await client.post('/mcp',json=dict(jsonrpc='2.0',id=2,method='ping'),headers={'Authorization':'Bearer '+refresh.json()['access_token']})
                self.assertEqual(blocked.status_code,401)
                reused=await client.post('/authorize',data=form,headers={'Origin':'https://wake.example'});self.assertEqual(reused.status_code,400)
        with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))

    def test_owner_csrf_redirect_and_explicit_mode_are_required_before_consent(self):
        from codex_wake.external_connector import create_app
        identity=[None]
        async def scenario(root):
            app=create_app(self.config(),Path(root),identify=lambda request:identity[0],operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                bad=await client.post('/register',json=dict(redirect_uris=['https://unregistered.example/callback']))
                self.assertEqual(bad.status_code,400)
                registered=await client.post('/register',json=dict(redirect_uris=['https://client.example/callback']))
                params=dict(client_id=registered.json()['client_id'],redirect_uri='https://client.example/callback',resource='https://wake.example/mcp',response_type='code',code_challenge_method='S256',code_challenge='x'*43,scope='observe')
                spoofed=await client.get('/authorize',params=params,headers={'Remote-User':'operator'})
                self.assertEqual(spoofed.status_code,403)
                identity[0]='other-user'
                denied=await client.get('/authorize',params=params);self.assertEqual(denied.status_code,403)
                identity[0]='operator'
                wrong_redirect=await client.get('/authorize',params=dict(params,redirect_uri='https://unregistered.example/callback'))
                self.assertEqual(wrong_redirect.status_code,400)
                landing=await client.get('/authorize',params=params)
                self.assertIn('Secure',landing.headers['set-cookie']);self.assertIn('HttpOnly',landing.headers['set-cookie'])
                flow=re.search(r'name="flow" value="([^"]+)"',landing.text)[1]
                form=dict(flow=flow,decision='approve',mode='operator',scopes='observe',targets='0')
                no_origin=await client.post('/authorize',data=form);self.assertEqual(no_origin.status_code,403)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as attacker:
                    no_cookie=await attacker.post('/authorize',data=form,headers={'Origin':'https://wake.example'})
                    self.assertEqual(no_cookie.status_code,400)
                no_mode=await client.post('/authorize',data={k:v for k,v in form.items() if k!='mode'},headers={'Origin':'https://wake.example'})
                self.assertEqual(no_mode.status_code,400)
        with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))

    def test_wrong_signed_in_owner_gets_denial_without_login_loop(self):
        from codex_wake.external_connector import create_app
        async def scenario(root):
            config=dict(self.config(),login_url='https://auth.example/')
            app=create_app(config,Path(root),identify=lambda request:'other-user',operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                registered=await client.post('/register',json=dict(redirect_uris=['https://client.example/callback']))
                result=await client.get('/authorize',params=dict(client_id=registered.json()['client_id'],redirect_uri='https://client.example/callback',resource='https://wake.example/mcp',response_type='code',code_challenge_method='S256',code_challenge='x'*43,scope='observe'))
                self.assertEqual(result.status_code,403)
                self.assertNotIn('location',result.headers)
        with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))

    def test_deployment_policy_requires_private_file_and_fixed_client_redirect(self):
        from codex_wake.external_connector import load_config
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'policy.json'
            config=dict(self.config(),wake_root=directory,port=37186)
            p.write_text(json.dumps(config));p.chmod(0o644)
            with self.assertRaises(ValueError):load_config(p)
            p.chmod(0o600)
            self.assertEqual(load_config(p)['owner'],'operator')
            p.write_text(json.dumps(dict(config,redirect_uris=[])))
            with self.assertRaises(ValueError):load_config(p)

    def test_default_identity_verifier_uses_local_idp_not_headers_or_redirected_identity(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        from codex_wake.external_connector import create_app
        class IdentityProvider(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.headers.get('Cookie')=='synthetic-owner':
                    self.send_response(200);self.send_header('Remote-User','operator')
                elif self.path=='/redirected-identity':
                    self.send_response(200);self.send_header('Remote-User','operator')
                else:
                    self.send_response(302);self.send_header('Location','/redirected-identity')
                self.send_header('Content-Length','0');self.end_headers()
        idp=ThreadingHTTPServer(('127.0.0.1',0),IdentityProvider)
        worker=threading.Thread(target=idp.serve_forever,daemon=True);worker.start()
        async def scenario(root):
            config=dict(self.config(),authelia_url=f'http://127.0.0.1:{idp.server_port}/api/authz/forward-auth')
            app=create_app(config,Path(root),operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                registered=await client.post('/register',json=dict(redirect_uris=['https://client.example/callback']))
                params=dict(client_id=registered.json()['client_id'],redirect_uri='https://client.example/callback',resource='https://wake.example/mcp',response_type='code',code_challenge_method='S256',code_challenge='x'*43,scope='observe')
                denied=await client.get('/authorize',params=params,headers={'Remote-User':'operator'})
                self.assertEqual(denied.status_code,403)
                owner=await client.get('/authorize',params=params,headers={'Cookie':'synthetic-owner'})
                self.assertEqual(owner.status_code,200)
        try:
            with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))
        finally:idp.shutdown();idp.server_close();worker.join(3)

    def test_operator_consent_accepts_browser_multiselect_rights_without_widening_request(self):
        from codex_wake.external_connector import create_app
        async def scenario(root):
            app=create_app(self.config(),Path(root),identify=lambda request:'operator',operations=self.operations(Path(root)))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://wake.example') as client:
                registered=await client.post('/register',json=dict(redirect_uris=['https://client.example/callback']))
                verifier='o'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                params=dict(client_id=registered.json()['client_id'],redirect_uri='https://client.example/callback',resource='https://wake.example/mcp',response_type='code',code_challenge_method='S256',code_challenge=challenge,scope='observe content.observe')
                landing=await client.get('/authorize',params=params)
                self.assertIn('Read conversation and operation content',landing.text)
                flow=re.search(r'name="flow" value="([^"]+)"',landing.text)[1]
                form=urlencode([('flow',flow),('decision','approve'),('mode','operator'),('scopes','observe'),('scopes','content.observe'),('targets','0')])
                approved=await client.post('/authorize',content=form,headers={'Origin':'https://wake.example','Content-Type':'application/x-www-form-urlencoded'})
                self.assertEqual(approved.status_code,303)
                code=parse_qs(urlsplit(approved.headers['location']).query)['code'][0]
                token=await client.post('/token',data=dict(grant_type='authorization_code',client_id=params['client_id'],redirect_uri=params['redirect_uri'],resource=params['resource'],code=code,code_verifier=verifier))
                self.assertEqual(token.status_code,200)
                self.assertEqual(set(token.json()['scope'].split()),{'observe','content.observe'})
                wrong_resource=await client.post('/token',data=dict(grant_type='refresh_token',client_id=params['client_id'],refresh_token=token.json()['refresh_token'],resource='https://other.example/mcp'))
                self.assertEqual(wrong_resource.status_code,400)
        with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(root))
