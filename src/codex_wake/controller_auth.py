"""Private opaque OAuth authority for the single Wake protected resource.

Authorization is an explicit local operator act. Client registration never grants
an identity or capability. Provider credentials are outside this authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SCOPES = frozenset({'observe', 'control', 'recovery', 'admin', 'account.observe', 'configuration.observe', 'history.observe', 'history.resume', 'migration.observe', 'content.observe', 'terminal.input'})


class AuthError(ValueError):
    def __init__(self, code='invalid_token', message='authorization denied'):
        super().__init__(message)
        self.code = code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Actor:
    subject: str
    principal_kind: str
    client_id: str
    grant_id: str
    issuer: str
    resource: str
    scopes: frozenset
    targets: list
    expires_at: float
    actions: frozenset | None = None
    delegated: bool = False


class OAuthAuthority:
    def __init__(self, path, *, issuer, resource, now=time.time, on_revoke=None):
        self.on_revoke = on_revoke
        if urlsplit(issuer).path:
            raise ValueError('issuer must be a canonical origin without path or trailing slash')
        for value in (issuer, resource):
            if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
                raise ValueError('canonical issuer/resource required')
            url = urlsplit(value)
            if (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', '::1', 'localhost'))) or url.query or url.fragment or url.username or url.password or not url.netloc:
                raise ValueError('canonical HTTPS issuer/resource required (loopback HTTP fixtures allowed)')
        self.path, self.issuer, self.resource, self.now = Path(path), issuer, resource, now
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS authority (id INTEGER PRIMARY KEY CHECK(id=1), issuer TEXT, resource TEXT);
                CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, metadata TEXT);
                CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY, subject TEXT, kind TEXT, client TEXT, scopes TEXT, targets TEXT, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS delegation_intents (intent TEXT PRIMARY KEY, fingerprint TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS delegations (grant_id TEXT PRIMARY KEY, parent_id TEXT, expires REAL, actions TEXT);
                CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, grant_id TEXT, redirect TEXT, challenge TEXT, expires REAL, used INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS delegated_codes (hash TEXT PRIMARY KEY, grant_id TEXT, redirect TEXT, challenge TEXT, expires REAL, used INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, grant_id TEXT, kind TEXT, expires REAL, used INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS revocations (grant_id TEXT PRIMARY KEY, pending INTEGER, result TEXT, attempts INTEGER NOT NULL DEFAULT 0);
            ''')
            if 'attempts' not in {row[1] for row in db.execute('PRAGMA table_info(revocations)')}:
                db.execute('ALTER TABLE revocations ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')
            previous = db.execute('SELECT issuer,resource FROM authority WHERE id=1').fetchone()
            if previous and previous != (issuer, resource):
                raise ValueError('authority issuer/resource changed; explicit new authority required')
            db.execute('INSERT OR IGNORE INTO authority VALUES(1,?,?)', (issuer, resource))
            # Old readers must never redeem or authenticate attenuated grants.
            db.execute('INSERT OR IGNORE INTO delegated_codes SELECT * FROM codes WHERE grant_id IN (SELECT grant_id FROM delegations)')
            db.execute('DELETE FROM codes WHERE grant_id IN (SELECT grant_id FROM delegations)')
            db.execute("UPDATE tokens SET used=1 WHERE grant_id IN (SELECT grant_id FROM delegations) AND kind IN ('access','refresh')")
        self.recover_revocations()

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def metadata(self):
        return dict(issuer=self.issuer, authorization_endpoint=self.issuer + '/authorize',
            token_endpoint=self.issuer + '/token', registration_endpoint=self.issuer + '/register',
            revocation_endpoint=self.issuer + '/revoke', response_types_supported=['code'],
            grant_types_supported=['authorization_code', 'refresh_token'],
            code_challenge_methods_supported=['S256'], token_endpoint_auth_methods_supported=['none'],
            scopes_supported=sorted(SCOPES))

    def protected_metadata(self):
        return dict(resource=self.resource, authorization_servers=[self.issuer],
                    scopes_supported=sorted(SCOPES), bearer_methods_supported=['header'])

    def register(self, metadata):
        redirects = metadata.get('redirect_uris')
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 10:
            raise AuthError('invalid_client_metadata')
        for uri in redirects:
            if not isinstance(uri, str) or any(ord(c) <= 32 or ord(c) == 127 for c in uri): raise AuthError('invalid_client_metadata')
            url = urlsplit(uri)
            if not url.netloc or url.fragment or url.username or url.password or (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', '::1', 'localhost'))):
                raise AuthError('invalid_client_metadata')
        if metadata.get('token_endpoint_auth_method', 'none') != 'none':
            raise AuthError('invalid_client_metadata')
        value = dict(client_id=secrets.token_urlsafe(24), redirect_uris=redirects,
            client_name=str(metadata.get('client_name', ''))[:128], token_endpoint_auth_method='none',
            grant_types=['authorization_code', 'refresh_token'], response_types=['code'])
        with self.connect() as db:
            db.execute('INSERT INTO clients VALUES(?,?)', (value['client_id'], json.dumps(value)))
        return value

    def authorize(self, *, subject, principal_kind, client_id, redirect_uri, resource,
                  scopes, targets, code_challenge, _delegation=None):
        if resource != self.resource: raise AuthError('invalid_target')
        if not isinstance(subject, str) or not subject or principal_kind not in ('owner', 'service'):
            raise AuthError('invalid_request')
        if not scopes or not set(scopes) <= SCOPES: raise AuthError('invalid_scope')
        def valid_target(target):
            if not isinstance(target, dict) or not target or set(target) - {'host', 'environment', 'runtime', 'namespace', 'conversation_id', 'provider', 'account', 'home', 'home_generation', 'configuration_revision', 'rollout_revision', 'build_channel', 'build_sha256', 'build_revision', 'executable', 'recipe', 'recipe_sha256', 'authority', 'generation', 'workspace', 'presentation', 'fixture_id', 'migration_revision', 'migration_id', 'flow_id', 'backend_id', 'channel', 'connection_generation', 'process_pid', 'process_start_ticks', 'process_boot_id', 'registry', 'registry_revision', 'store_id', 'process', 'socket_generation', 'resource_id', 'pane_id', 'window_id', 'tab_id', 'terminal_session_id', 'bot_id'}:
                return False
            for key, value in target.items():
                if key == 'process':
                    if value is None:
                        continue
                    if (not isinstance(value, dict) or set(value) != {'pid', 'start_ticks', 'boot_id'}
                            or type(value['pid']) is not int or value['pid'] <= 0
                            or not isinstance(value['start_ticks'], str) or not value['start_ticks'].isdigit()
                            or not isinstance(value['boot_id'], str) or not re.fullmatch(r'[0-9a-f-]{36}', value['boot_id'])):
                        return False
                elif key == 'socket_generation' and value is None:
                    continue
                elif not isinstance(value, str) or not value:
                    return False
            return True
        if not isinstance(targets, list) or not targets or any(not valid_target(t) for t in targets):
            raise AuthError('invalid_target')
        if not isinstance(code_challenge, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code_challenge):
            raise AuthError('invalid_request', 'S256 challenge required')
        code, grant = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.connect() as db:
            row = db.execute('SELECT metadata FROM clients WHERE id=?', (client_id,)).fetchone()
            if not row or redirect_uri not in json.loads(row[0])['redirect_uris']: raise AuthError('invalid_client')
            db.execute('INSERT INTO grants(id,subject,kind,client,scopes,targets) VALUES(?,?,?,?,?,?)',
                       (grant, subject, principal_kind, client_id, json.dumps(sorted(scopes)), json.dumps(targets)))
            table='codes'
            if _delegation is not None:
                parent,until,actions=_delegation
                db.execute('INSERT INTO delegations VALUES(?,?,?,?)',(grant,parent,until,None if actions is None else json.dumps(sorted(actions))))
                table='delegated_codes'
            db.execute('INSERT INTO '+table+'(hash,grant_id,redirect,challenge,expires) VALUES(?,?,?,?,?)',
                       (digest(code), grant, redirect_uri, code_challenge, self.now() + 120))
        return code

    def token(self, args):
        if args.get('resource') != self.resource: raise AuthError('invalid_target')
        grant_type = args.get('grant_type')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if grant_type == 'authorization_code':
                table='codes'
                row = db.execute('SELECT grant_id,redirect,challenge,expires,used FROM codes WHERE hash=?', (digest(args.get('code', '')),)).fetchone()
                if row is None:
                    table='delegated_codes'
                    row=db.execute('SELECT grant_id,redirect,challenge,expires,used FROM delegated_codes WHERE hash=?',(digest(args.get('code','')),)).fetchone()
                verifier = args.get('code_verifier', '')
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                if not row or row[4] or row[3] <= self.now() or row[1] != args.get('redirect_uri') or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or not secrets.compare_digest(row[2], challenge):
                    raise AuthError('invalid_grant')
                grant = row[0]
            elif grant_type == 'refresh_token':
                row = db.execute("SELECT grant_id,expires,used FROM tokens WHERE hash=? AND kind IN ('refresh','delegated_refresh_v1')", (digest(args.get('refresh_token', '')),)).fetchone()
                if not row or row[1] <= self.now(): raise AuthError('invalid_grant')
                grant = row[0]
                if row[2]:
                    db.execute('UPDATE grants SET revoked=1 WHERE id=?', (grant,))
                    db.commit()
                    self.revoke_grant(grant)
                    raise AuthError('invalid_grant', 'refresh replay revoked grant')
            else: raise AuthError('unsupported_grant_type')
            current = db.execute('SELECT client,scopes,revoked FROM grants WHERE id=?', (grant,)).fetchone()
            boundary, unused_actions = self.delegation(grant, db=db)
            if not current or current[2] or current[0] != args.get('client_id'): raise AuthError('invalid_grant')
            if grant_type == 'authorization_code':
                db.execute('UPDATE '+table+' SET used=1 WHERE hash=?', (digest(args['code']),))
            # Rotation invalidates old access and refresh credentials, not operation identity.
            db.execute('UPDATE tokens SET used=1 WHERE grant_id=?', (grant,))
            access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            delegated=db.execute('SELECT 1 FROM delegations WHERE grant_id=?',(grant,)).fetchone() is not None
            for secret, kind, lifetime in ((access, 'delegated_access_v1' if delegated else 'access', 600), (refresh, 'delegated_refresh_v1' if delegated else 'refresh', 86400)):
                db.execute('INSERT INTO tokens VALUES(?,?,?,?,0)', (digest(secret), grant, kind, min(self.now() + lifetime,boundary)))
            return dict(access_token=access, refresh_token=refresh, token_type='Bearer', expires_in=min(600,boundary-self.now()),
                        scope=' '.join(json.loads(current[1])))

    def authenticate(self, token):
        with self.connect() as db:
            row = db.execute('''SELECT g.subject,g.kind,g.client,g.id,g.scopes,g.targets,t.expires
                FROM tokens t JOIN grants g ON g.id=t.grant_id
                WHERE t.hash=? AND t.kind IN ('access','delegated_access_v1') AND t.used=0 AND g.revoked=0''', (digest(token),)).fetchone()
        if not row or row[6] <= self.now(): raise AuthError()
        unused_expiry,actions=self.delegation(row[3])
        return Actor(*row[:4], self.issuer, self.resource, frozenset(json.loads(row[4])), json.loads(row[5]), row[6],actions,self.is_delegated(row[3]))

    def is_delegated(self,grant_id):
        with self.connect() as db:return db.execute('SELECT 1 FROM delegations WHERE grant_id=?',(grant_id,)).fetchone() is not None

    def delegation(self, grant_id, *, db=None):
        """Recheck the inherited grant chain, including parent revocation."""
        if db is None:
            with self.connect() as connection:return self.delegation(grant_id,db=connection)
        current=grant_id;seen=set();expiry=float('inf');actions=None
        while current is not None:
            if current in seen or len(seen)>=16:raise AuthError()
            seen.add(current)
            row=db.execute('SELECT revoked FROM grants WHERE id=?',(current,)).fetchone()
            if not row or row[0]:raise AuthError()
            value=db.execute('SELECT parent_id,expires,actions FROM delegations WHERE grant_id=?',(current,)).fetchone()
            if value is None:break
            current,until,declared=value
            expiry=min(expiry,until)
            if expiry<=self.now():raise AuthError()
            if declared is not None:
                permitted=frozenset(json.loads(declared));actions=permitted if actions is None else actions & permitted
        return expiry,actions

    def delegate(self, actor, *, client_id, redirect_uri, code_challenge, mode,
                 scopes=None, targets=None, actions=None, expires_in=600):
        from .unified_connectors import intersect_targets,canonical_actions
        if actor.principal_kind!='owner' or 'admin' not in actor.scopes:
            raise AuthError('operator_required','connector issuance requires authenticated operator administration')
        # A caller cannot manufacture an Actor with a more powerful role.
        self.revalidate_original(dict(issuer=actor.issuer,resource=actor.resource,subject=actor.subject,client_id=actor.client_id,grant_id=actor.grant_id),
            dict(scopes=sorted(actor.scopes),targets=actor.targets,expires_at=actor.expires_at,principal_kind=actor.principal_kind))
        if type(expires_in) is not int or not 1<=expires_in<=86400:raise AuthError('invalid_request')
        if mode=='full':
            if any(value is not None for value in (scopes,targets,actions)):raise AuthError('invalid_request')
            scopes=sorted(actor.scopes);targets=actor.targets;actions=actor.actions
        elif mode=='subset':
            if not isinstance(scopes,list) or not scopes or not set(scopes)<=actor.scopes:raise AuthError('invalid_scope')
            targets=intersect_targets(actor.targets,targets);actions=canonical_actions(actions)
            if actor.actions is not None and not actions<=actor.actions:raise AuthError('insufficient_scope')
        else:raise AuthError('invalid_request')
        until=min(actor.expires_at,self.now()+expires_in)
        code=self.authorize(subject=actor.subject,principal_kind='service',client_id=client_id,
            redirect_uri=redirect_uri,resource=self.resource,scopes=scopes,targets=targets,code_challenge=code_challenge,
            _delegation=(actor.grant_id,until,actions))
        with self.connect() as db:
            grant=db.execute('SELECT grant_id FROM delegated_codes WHERE hash=?',(digest(code),)).fetchone()[0]
        return dict(code=code,grant_id=grant,expires_at=until,principal_kind='service',scopes=sorted(scopes),targets=targets,
            actions=None if actions is None else sorted(actions),mode=mode)

    def grant_metadata(self, actor, grant_id=None):
        with self.connect() as db:
            rows=db.execute('SELECT g.id,g.subject,g.kind,g.client,g.scopes,g.targets,g.revoked,d.parent_id,d.expires,d.actions FROM grants g LEFT JOIN delegations d ON g.id=d.grant_id').fetchall()
        def visible(row):
            return row[0]==actor.grant_id or actor.principal_kind=='owner' and 'admin' in actor.scopes and row[7]==actor.grant_id
        values=[dict(grant_id=row[0],subject=row[1],principal_kind=row[2],client_id=row[3],scopes=json.loads(row[4]),targets=json.loads(row[5]),revoked=bool(row[6]),parent_grant_id=row[7],expires_at=row[8],actions=None if row[9] is None else json.loads(row[9])) for row in rows if visible(row) and (grant_id is None or row[0]==grant_id)]
        if grant_id is not None:
            if not values:raise AuthError('insufficient_scope')
            return values[0]
        return values

    def revalidate_original(self, principal, authorization):
        """Host-only scheduled-policy continuation, without issuing credentials.

        The private policy owns this immutable snapshot. Rotation does not change
        its identity or original deadline; revocation/current grant changes hold.
        This method is not an HTTP operation or a delegated-token exchange.
        """
        if not isinstance(principal,dict) or set(principal)!={'issuer','resource','subject','client_id','grant_id'}:
            raise AuthError()
        if not isinstance(authorization,dict) or set(authorization)!={'scopes','targets','expires_at','principal_kind'}:
            raise AuthError()
        if principal['issuer']!=self.issuer or principal['resource']!=self.resource:
            raise AuthError()
        expires=authorization['expires_at']
        if type(expires) not in (int,float) or not self.now()<expires<float('inf'):
            raise AuthError()
        with self.connect() as db:
            row=db.execute('SELECT subject,kind,client,scopes,targets,revoked FROM grants WHERE id=?',
                (principal['grant_id'],)).fetchone()
            issued=db.execute("SELECT 1 FROM tokens WHERE grant_id=? AND kind IN ('access','delegated_access_v1') AND expires=? LIMIT 1",
                (principal['grant_id'],expires)).fetchone()
        if not row or not issued or row[5] or (row[0],row[1],row[2])!=(principal['subject'],authorization['principal_kind'],principal['client_id']):
            raise AuthError()
        if json.loads(row[3])!=authorization['scopes'] or json.loads(row[4])!=authorization['targets']:
            raise AuthError()
        unused_expiry,actions=self.delegation(principal['grant_id'])
        return Actor(principal['subject'],authorization['principal_kind'],principal['client_id'],principal['grant_id'],
            self.issuer,self.resource,frozenset(authorization['scopes']),authorization['targets'],expires,actions,self.is_delegated(principal['grant_id']))

    def recover_revocations(self, *, limit=4, grant_id=None):
        if self.on_revoke is None:
            return
        with self.connect() as db:
            rows = db.execute('SELECT grant_id,attempts FROM revocations WHERE pending=1 '
                + ('AND grant_id=? ' if grant_id is not None else '') + 'ORDER BY rowid LIMIT ?',
                (grant_id, limit) if grant_id is not None else (limit,)).fetchall()
        for identifier, attempts in rows:
            with self.connect() as db:
                db.execute('UPDATE revocations SET attempts=attempts+1 WHERE grant_id=?', (identifier,))
            try:
                if attempts >= 3:
                    raise ValueError('cancellation attempt ceiling reached')
                result = self.on_revoke(identifier, issuer=self.issuer, resource=self.resource)
                if not isinstance(result, dict):
                    raise ValueError('revocation owner returned no outcome')
                pending = bool(result.get('remaining', result.get('remaining_count', 0)))
            except Exception:
                result = dict(cancellation='uncertain', uncertain_effects=['cancellation_owner_unavailable'])
                pending = attempts + 1 < 3
                if not pending:
                    result['reason'] = 'cancellation_attempt_limit_reached'
            with self.connect() as db:
                db.execute('UPDATE revocations SET pending=?,result=?,attempts=? WHERE grant_id=?',
                    (int(pending), json.dumps(result), 0 if result.get('cancellation') != 'uncertain' else attempts + 1, identifier))

    def revoke_grant(self, grant_id):
        with self.connect() as db:
            db.execute('UPDATE grants SET revoked=1 WHERE id=?', (grant_id,))
            db.execute('INSERT OR IGNORE INTO revocations(grant_id,pending,result) VALUES(?,1,NULL)', (grant_id,))
        # Cancellation is requested after revocation commits. An interrupted request
        # stays pending for bounded server maintenance/reconstruction.
        self.recover_revocations(grant_id=grant_id)
        with self.connect() as db:
            row = db.execute('SELECT result FROM revocations WHERE grant_id=?', (grant_id,)).fetchone()
        result = json.loads(row[0]) if row and row[0] else dict(cancellation='not_configured', uncertain_effects=[])
        return dict(result, grant_id=grant_id, status='revoked')

    def revoke_token(self, token, client_id):
        with self.connect() as db:
            row = db.execute('SELECT t.grant_id FROM tokens t JOIN grants g ON g.id=t.grant_id WHERE t.hash=? AND g.client=?', (digest(token), client_id)).fetchone()
        if row: self.revoke_grant(row[0])
