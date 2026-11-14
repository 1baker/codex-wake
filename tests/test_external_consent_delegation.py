"""Delegated consent through the actual browser OAuth transport."""
import asyncio,base64,hashlib,json,re,tempfile,time,unittest
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import httpx2 as httpx
import test_external_oauth_connector as fixtures

class DelegatedConsentTests(unittest.TestCase):
 def test_explicit_agent_consent_rechecks_policy_and_preserves_owner(self):
  from codex_wake.external_connector import create_app,ConnectorVerifier
  from codex_wake.controller_auth import OAuthAuthority,AuthError
  fixture=fixtures.ExternalConnectorTests()
  async def scenario(root):
   config=fixture.config(); identity=['agent'];app=create_app(config,root,identify=lambda req:identity[0],operations=fixture.operations(root))
   authority=OAuthAuthority(root/'external-oauth/authority.sqlite',issuer=config['issuer'],resource=config['issuer']+'/mcp')
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=config['issuer']) as c:
    registered=await c.post('/register',json={'redirect_uris':config['redirect_uris']});cid=registered.json()['client_id']
    challenge=base64.urlsafe_b64encode(hashlib.sha256(b'v'*43).digest()).decode().rstrip('=')
    params=dict(client_id=cid,redirect_uri=config['redirect_uris'][0],resource=config['issuer']+'/mcp',response_type='code',code_challenge_method='S256',code_challenge=challenge,scope='observe')
    self.assertEqual((await c.get('/authorize',params=params)).status_code,403)
    delegation=dict(id='setup',principal='agent',client_ids=[cid],scopes=['observe'],targets=config['targets'],modes=['subset'],expires_at=time.time()+600,reason='Operator approved exact connector setup')
    config['consent_delegations']=[delegation]
    page=await c.get('/authorize',params=params);self.assertEqual(page.status_code,200)
    self.assertIn('agent',page.text);self.assertNotIn('name="mode" value="subset" checked',page.text)
    flow=re.search(r'name="flow" value="([^"]+)"',page.text)[1]
    form=dict(flow=flow,decision='approve',mode='subset',scopes='observe',targets='0',actions='environment.snapshot')
    identity[0]='other';self.assertEqual((await c.post('/authorize',data=form,headers={'Origin':config['issuer']})).status_code,403)
    identity[0]='agent'
    approved=await c.post('/authorize',data=form,headers={'Origin':config['issuer']});self.assertEqual(approved.status_code,303)
    code=parse_qs(urlsplit(approved.headers['location']).query)['code'][0]
    token=(await c.post('/token',data=dict(grant_type='authorization_code',client_id=cid,code=code,redirect_uri=params['redirect_uri'],resource=params['resource'],code_verifier='v'*43))).json()['access_token']
    actor=ConnectorVerifier(authority,config).actor(token);self.assertEqual(actor.subject,'operator')
    with authority.connect() as db:
     audit=db.execute('SELECT consenter,delegation_id FROM connector_consent_audit WHERE grant_id=?',(actor.grant_id,)).fetchone()
    self.assertEqual(tuple(audit),('agent','setup'))
    config['consent_delegations']=[]
    with self.assertRaises(AuthError):ConnectorVerifier(authority,config).actor(token)
    identity[0]='operator';self.assertEqual((await c.get('/authorize',params=params)).status_code,200)
  with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(Path(root)))

 def test_delegate_denials_at_browser_boundary(self):
  from codex_wake.external_connector import create_app
  fixture=fixtures.ExternalConnectorTests()
  async def scenario(root):
   config=fixture.config();identity=['agent'];app=create_app(config,root,identify=lambda req:identity[0],operations=fixture.operations(root))
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=config['issuer']) as c:
    cid=(await c.post('/register',json={'redirect_uris':config['redirect_uris']})).json()['client_id']
    rule=dict(id='setup',principal='agent',client_ids=[cid],scopes=['observe'],targets=config['targets'],modes=['subset'],expires_at=time.time()+600,reason='Owner approved setup')
    config['consent_delegations']=[rule]
    params=dict(client_id=cid,redirect_uri=config['redirect_uris'][0],resource=config['issuer']+'/mcp',response_type='code',code_challenge_method='S256',code_challenge='x'*43,scope='observe content.observe')
    async def landing():
     response=await c.get('/authorize',params=params);self.assertEqual(response.status_code,200)
     self.assertNotIn('value="content.observe"',response.text)
     return re.search(r'name="flow" value="([^"]+)"',response.text)[1]
    headers={'Origin':config['issuer']}
    for changes,status in [({'mode':'operator'},403),({'scopes':'content.observe'},400),({'targets':'1'},400),({'mode':''},400)]:
     form=dict(flow=await landing(),decision='approve',mode='subset',scopes='observe',targets='0',actions='environment.snapshot');form.update(changes)
     self.assertEqual((await c.post('/authorize',data=form,headers=headers)).status_code,status)
    flow=await landing();rule['reason']='Changed authority requires fresh review'
    form=dict(flow=flow,decision='approve',mode='subset',scopes='observe',targets='0',actions='environment.snapshot')
    self.assertEqual((await c.post('/authorize',data=form,headers=headers)).status_code,403)
    for change in ['expiry','client','identity']:
     rule['expires_at']=time.time()+600;rule['client_ids']=[cid];identity[0]='agent'
     if change=='expiry':rule['expires_at']=time.time()-1
     if change=='client':rule['client_ids']=['different-client']
     if change=='identity':identity[0]='unlisted-agent'
     response=await c.get('/authorize',params=params,headers={'Remote-User':'operator'})
     self.assertEqual(response.status_code,403)
  with tempfile.TemporaryDirectory() as root:asyncio.run(scenario(Path(root)))

 def test_delegation_policy_rejects_ambiguous_or_unbounded_identity(self):
  from codex_wake.external_connector import validate_config
  import copy
  config=fixtures.ExternalConnectorTests().config()
  row=dict(id='setup',principal='agent',client_ids=['client'],scopes=['observe'],targets=config['targets'],modes=['subset'],expires_at=time.time()+600,reason='Owner approved setup')
  for patch in [dict(expires_at=float('inf')),dict(expires_at=True),dict(client_ids=['*']),dict(scopes=['admin']),dict(modes=['default']),dict(targets=[dict(host='other',environment='e')]),dict(principal='operator')]:
   candidate=dict(config,consent_delegations=[dict(copy.deepcopy(row),**patch)])
   with self.assertRaises(ValueError):validate_config(candidate)
  with self.assertRaises(ValueError):validate_config(dict(config,consent_delegations=[row,row]))
