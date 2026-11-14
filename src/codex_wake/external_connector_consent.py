"""Browser consent custody around the existing OAuth grant authority."""
import html
import inspect
import json
import secrets
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError

import anyio
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .controller_auth import AuthError, digest
from .unified_connectors import canonical_actions, intersect_targets

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
COOKIE = '__Host-codex-wake-consent'
RIGHTS = {'observe':'See environment and operation metadata', 'control':'Control sessions, wakes and programs',
          'content.observe':'Read conversation and operation content', 'terminal.input':'Write raw terminal input',
          'admin':'Administer connector grants and host configuration', 'recovery':'Perform explicit recovery',
          'account.observe':'Inspect accounts', 'configuration.observe':'Read configuration',
          'history.observe':'Inspect conversation history', 'history.resume':'Resume saved conversations',
          'migration.observe':'Inspect migrations'}


def escaped(value):
    return html.escape(str(value), quote=True)


class BrowserConsent:
    def __init__(self, authority, config, identify=None):
        self.authority, self.config = authority, config
        self.identify = identify or self.authelia_identity
        with authority.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS browser_flows (
                id TEXT PRIMARY KEY, cookie TEXT, params TEXT, expires REAL, owner TEXT);
                CREATE TABLE IF NOT EXISTS connector_rates (kind TEXT PRIMARY KEY, start REAL, count INTEGER);''')

    async def authelia_identity(self, request):
        """Verify cookies at the fixed local IdP; ignore client identity headers."""
        cookie = request.headers.get('cookie', '')
        def verify():
            probe = Request(self.config['authelia_url'], headers={
                'Cookie': cookie, 'X-Original-URL': self.authority.issuer + '/authorize',
                'X-Original-Method': 'GET', 'X-Forwarded-Method': 'GET',
                'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': urlsplit(self.authority.issuer).netloc,
                'X-Forwarded-Uri': '/authorize'})
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            try:
                with build_opener(ProxyHandler({}),NoRedirect()).open(probe, timeout=3) as response:
                    return response.headers.get('Remote-User') if response.status == 200 else None
            except HTTPError as error:
                if error.code in (301,302,303,307,308,401,403): return None
                raise AuthError('identity_provider_unavailable') from None
            except OSError:
                raise AuthError('identity_provider_unavailable') from None
        return await anyio.to_thread.run_sync(verify)

    async def identity(self, request):
        value = self.identify(request)
        value = await value if inspect.isawaitable(value) else value
        return value

    def rate(self, kind, maximum):
        now = self.authority.now()
        with self.authority.connect() as db:
            row = db.execute('SELECT start,count FROM connector_rates WHERE kind=?', (kind,)).fetchone()
            start, count = (row[0], row[1] + 1) if row and now - row[0] < 60 else (now, 1)
            db.execute('INSERT OR REPLACE INTO connector_rates VALUES(?,?,?)', (kind, start, count))
        if count > maximum: raise AuthError('rate_limited')

    async def body(self, request, *, repeated=()):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536: raise AuthError('invalid_request')
        if not raw: raise AuthError('invalid_request')
        if request.headers.get('content-type', '').split(';')[0] == 'application/json':
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise AuthError('invalid_request')
                    result[key] = value
                return result
            value = json.loads(raw, object_pairs_hook=unique)
            if not isinstance(value, dict): raise AuthError('invalid_request')
            return value
        if request.headers.get('content-type','').split(';')[0] != 'application/x-www-form-urlencoded':
            raise AuthError('invalid_request')
        from urllib.parse import parse_qs
        form = parse_qs(raw.decode(), keep_blank_values=True, max_num_fields=128)
        if any(len(values) != 1 and key not in repeated for key,values in form.items()): raise AuthError('invalid_request')
        return {key: ' '.join(values) if key in repeated else values[0] for key,values in form.items()}

    async def register(self, request):
        self.rate('register', 20)
        args = await self.body(request)
        redirects = args.get('redirect_uris', [])
        if not redirects or any(uri not in self.config['redirect_uris'] for uri in redirects):
            raise AuthError('invalid_client_metadata')
        grants = args.get('grant_types', ['authorization_code', 'refresh_token'])
        if not isinstance(grants,list) or 'authorization_code' not in grants or set(grants)-{'authorization_code','refresh_token'} or args.get('response_types', ['code']) != ['code']:
            raise AuthError('invalid_client_metadata')
        with self.authority.connect() as db:
            if db.execute('SELECT count(*) FROM clients').fetchone()[0] >= 1000:
                raise AuthError('registration_limit')
        return JSONResponse(self.authority.register(args), status_code=201, headers=NO_STORE)

    async def token(self, request):
        self.rate('token', 120)
        return JSONResponse(self.authority.token(await self.body(request)), headers=NO_STORE)

    async def revoke(self, request):
        self.rate('revoke', 120)
        args = await self.body(request)
        self.authority.revoke_token(args.get('token', ''), args.get('client_id'))
        return JSONResponse({}, headers=NO_STORE)

    def validate(self, params):
        if params.get('response_type') != 'code' or params.get('code_challenge_method') != 'S256':
            raise AuthError('invalid_request')
        if params.get('resource') != self.authority.resource: raise AuthError('invalid_target')
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', params.get('code_challenge', '')) or len(params.get('state', '')) > 2048:
            raise AuthError('invalid_request')
        scopes = params.get('scope', '').split()
        if scopes and not set(scopes) <= set(self.config['scopes']): raise AuthError('invalid_scope')
        with self.authority.connect() as db:
            row = db.execute('SELECT metadata FROM clients WHERE id=?', (params.get('client_id'),)).fetchone()
        if not row: raise AuthError('invalid_client')
        client = json.loads(row[0])
        if params.get('redirect_uri') not in client['redirect_uris'] or params.get('redirect_uri') not in self.config['redirect_uris']:
            raise AuthError('invalid_client')
        return client

    async def authorize(self, request):
        self.rate('authorize', 30)
        if request.method == 'GET':
            if len(str(request.url)) > 8192 or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
                raise AuthError('invalid_request')
            params = dict(request.query_params)
            client = self.validate(params)
            identity = await self.identity(request)
            if identity is not None and identity != self.config['owner']:
                raise AuthError('access_denied')
            if identity is None:
                login = self.config.get('login_url')
                if not login: raise AuthError('access_denied')
                return RedirectResponse(login + '?' + urlencode({'rd': self.authority.issuer + request.url.path + '?' + request.url.query}), status_code=303, headers=NO_STORE)
            flow, cookie = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with self.authority.connect() as db:
                db.execute('DELETE FROM browser_flows WHERE expires<=?', (self.authority.now(),))
                if db.execute('SELECT count(*) FROM browser_flows').fetchone()[0] >= 1000: raise AuthError('rate_limited')
                db.execute('INSERT INTO browser_flows VALUES(?,?,?,?,?)', (digest(flow), digest(cookie), json.dumps(params), self.authority.now()+300, self.config['owner']))
            scopes = params.get('scope', '').split() or self.config['scopes']
            scope_choices = ''.join('<option selected value="'+escaped(scope)+'">'+escaped(RIGHTS[scope])+'</option>' for scope in scopes)
            target_choices = ''.join('<option selected value="'+str(i)+'">'+escaped(' / '.join(str(value) for value in target.values()))+'</option>' for i,target in enumerate(self.config['targets']))
            text = ('<!doctype html><html><head><title>Connect Codex Wake</title></head><body><h1>Connect Codex Wake</h1>'
                '<p>Client: <strong>' + escaped(client['client_name']) + '</strong></p><p>Callback: ' + escaped(params['redirect_uri']) + '</p>'
                '<form method="post" action="/authorize"><input type="hidden" name="flow" value="' + escaped(flow) + '">'
                '<fieldset><legend>Choose authority explicitly</legend><label><input type="radio" name="mode" value="operator" required>Act as me with the selected rights</label><br>'
                '<label><input type="radio" name="mode" value="subset" required>Restricted connector; only named actions below</label></fieldset>'
                '<p><label>Selected rights (choose the rights this connector needs):<br><select name="scopes" multiple required size="6">'+scope_choices+'</select></label></p>'
                '<p><label>Selected environments:<br><select name="targets" multiple required>'+target_choices+'</select></label></p>'
                '<label>Restricted actions, one canonical operation per line:<textarea name="actions" rows="5" cols="70"></textarea></label>'
                '<p>This grant expires after ' + escaped(self.config['grant_seconds']) + ' seconds. Existing effects retain their original receipts.</p>'
                '<button name="decision" value="approve">Approve selected access</button> <button name="decision" value="deny" formnovalidate>Deny</button></form></body></html>')
            response = HTMLResponse(text, headers=dict(NO_STORE, **{'Content-Security-Policy': "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'", 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'}))
            response.set_cookie(COOKIE, cookie, secure=True, httponly=True, samesite='lax', path='/', max_age=300)
            return response
        if request.headers.get('origin') != self.authority.issuer: raise AuthError('invalid_origin')
        if await self.identity(request) != self.config['owner']: raise AuthError('access_denied')
        args = await self.body(request,repeated=('scopes','targets'))
        cookie = request.cookies.get(COOKIE, '')
        with self.authority.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT cookie,params,expires,owner FROM browser_flows WHERE id=?', (digest(args.get('flow', '')),)).fetchone()
            if not row or row[2] <= self.authority.now() or row[3] != self.config['owner'] or not secrets.compare_digest(row[0], digest(cookie)):
                raise AuthError('invalid_request')
            params = json.loads(row[1]);self.validate(params)
            if args.get('decision') not in ('approve', 'deny'): raise AuthError('invalid_request')
            # Consume only this browser-bound flow; a replay cannot mint another grant.
            db.execute('DELETE FROM browser_flows WHERE id=?', (digest(args['flow']),))
        values = dict(state=params.get('state', ''), iss=self.authority.issuer)
        if args['decision'] == 'deny': values['error'] = 'access_denied'
        else:
            mode = args.get('mode')
            if mode not in ('operator', 'subset'): raise AuthError('invalid_request')
            scopes = args.get('scopes', '').split()
            allowed = params.get('scope', '').split() or self.config['scopes']
            if not scopes or not set(scopes) <= set(allowed): raise AuthError('invalid_scope')
            try:
                indexes = [int(i) for i in args.get('targets', '').split()]
                if not indexes or any(i < 0 or i >= len(self.config['targets']) for i in indexes): raise ValueError()
                targets = intersect_targets(self.config['targets'], [self.config['targets'][i] for i in indexes])
            except (ValueError, IndexError): raise AuthError('invalid_target') from None
            actions = canonical_actions(args.get('actions', '').split()) if mode == 'subset' else None
            values['code'] = self.authority.authorize(subject=self.config['owner'], principal_kind='owner' if mode == 'operator' else 'service',
                client_id=params['client_id'], redirect_uri=params['redirect_uri'], resource=params['resource'], scopes=scopes,
                targets=targets, code_challenge=params['code_challenge'], _delegation=(None, self.authority.now()+self.config['grant_seconds'], actions))
        response = RedirectResponse(params['redirect_uri'] + ('&' if '?' in params['redirect_uri'] else '?') + urlencode(values), status_code=303, headers=NO_STORE)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax')
        return response
