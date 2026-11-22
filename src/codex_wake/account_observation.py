"""Sanitized local credential-cache observations, never provider authentication.

This is the sole credential-reading owner for structured account status. It does
not invoke native processes, keyrings, network clients or token refresh. Cached
identity claims are unverified display evidence, not proof of provider access.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat

from . import measurements
from .controller_accounts import ControllerAccounts
from .controller_auth import Actor, AuthError
from .managed_inventory import InventoryError

_MAX_CACHE = 131072
_TARGET_FIELDS = frozenset(('host', 'environment', 'provider', 'account', 'home', 'home_generation', 'configuration_revision'))


def _actor_is_current(actor):
    try:
        return actor.expires_at > measurements.utc_time()
    except measurements.TimeUnavailable:
        raise AuthError('qualified_time_unavailable') from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _cached_claims(token):
    if not isinstance(token, str) or len(token) > 32768:
        return {}
    try:
        parts = token.split('.')
        if len(parts) != 3 or len(parts[1]) > 16384:
            return {}
        value = json.loads(base64.b64decode(parts[1] + '=' * (-len(parts[1]) % 4), altchars=b'-_', validate=True), object_pairs_hook=_object)
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def _observation(home, target, store, *, observe_freshness=True):
    result = dict(state='unknown', signed_in=None, credential_store=store,
                  identity=None, plan=None, freshness='unknown', provider_verified=False,
                  evidence='local_file_unverified', reason='credential_store_not_observable')
    if store != 'file':
        result['evidence'] = 'not_observed'
        return result
    directory = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if f'{info.st_dev}:{info.st_ino}' != target['home_generation']:
            raise InventoryError('stale_target', 'account home generation changed')
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            result.update(state='unavailable', reason='private_account_home_required')
            return result
        try:
            descriptor = os.open('auth.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            result.update(state='signed_out', signed_in=False, reason='file_credentials_absent', evidence='local_file_absence')
            return result
        except OSError:
            result.update(state='unavailable', reason='credential_cache_unavailable')
            return result
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1 or info.st_size > _MAX_CACHE):
                result.update(state='unavailable', reason='private_bounded_credential_file_required')
                return result
            raw = stream.read(_MAX_CACHE + 1)
            after = os.fstat(stream.fileno())
            current = os.stat('auth.json', dir_fd=directory, follow_symlinks=False)
            signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if len(raw) > _MAX_CACHE or signature(info) != signature(after) or signature(after) != signature(current):
                result.update(state='unavailable', reason='credential_cache_changed')
                return result
        try:
            cache = json.loads(raw, object_pairs_hook=_object)
        except (ValueError, UnicodeError):
            result.update(reason='credential_cache_unrecognized')
            return result
        if not isinstance(cache, dict):
            result.update(reason='credential_cache_unrecognized')
            return result
        # Only allowlisted presentation values leave this owner. Key material,
        # complete token payloads, unknown fields and parse errors never do.
        if isinstance(cache.get('OPENAI_API_KEY'), str) and cache['OPENAI_API_KEY'].strip():
            result.update(state='credentials_present', reason='cached_credentials_not_verified', auth_type='api_key')
            return result
        tokens = cache.get('tokens')
        if not isinstance(tokens, dict) or not isinstance(tokens.get('access_token'), str) or not tokens['access_token']:
            result.update(reason='credential_cache_unrecognized')
            return result
        result.update(state='credentials_present', reason='cached_credentials_not_verified', auth_type='chatgpt')
        claims = _cached_claims(tokens.get('id_token'))
        identity = {}
        email = claims.get('email')
        if isinstance(email, str) and len(email) <= 254 and re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+', email):
            identity['email'] = email
        account = claims.get('https://api.openai.com/auth')
        if isinstance(account, dict):
            account_id = account.get('chatgpt_account_id')
            if isinstance(account_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', account_id):
                identity['account_id'] = account_id
            plan = account.get('chatgpt_plan_type')
            if plan in ('free', 'plus', 'pro', 'team', 'business', 'enterprise', 'edu', 'go'):
                result['plan'] = plan
        result['identity'] = identity or None
        expires = claims.get('exp')
        if observe_freshness and type(expires) in (int, float):
            try:
                if expires <= measurements.utc_time():
                    result['freshness'] = 'stale'
            except measurements.TimeUnavailable:
                result['reason'] = 'qualified_time_unavailable'
        return result
    finally:
        os.close(directory)



def cached_account_fingerprint(home: Path, home_generation: str) -> str | None:
    """Return only a digest of the local ChatGPT account claim."""
    try:
        result = _observation(home, {'home_generation': home_generation}, 'file',
                              observe_freshness=False)
    except (OSError, InventoryError):
        return None
    account_id = (result.get('identity') or {}).get('account_id')
    return hashlib.sha256(account_id.encode()).hexdigest() if account_id else None

def execute(root, arguments, *, actor=None, authorize=None, accounts=None):
    """Observe one exact account, admitting remote callers before credential I/O."""
    if root is None:
        raise InventoryError('host_wake_root_required', 'host Wake root required')
    if (not isinstance(arguments, dict) or set(arguments) - {'selector', 'expected_target'}
            or not isinstance(arguments.get('selector'), str)):
        raise InventoryError('invalid_argument', 'account selector and optional exact target required')
    accounts = accounts or ControllerAccounts(Path(root) / 'controller-accounts.toml',
        host=socket.gethostname(), environment=os.environ.get('WSL_DISTRO_NAME') or os.name)
    account = accounts.execute('accounts.resolve', arguments)['account']
    target = account['target']
    def guard():
        if actor is not None:
            if (not isinstance(actor, Actor) or not _actor_is_current(actor) or authorize is None
                    or authorize() != actor or 'account.observe' not in actor.scopes
                    or not any(_TARGET_FIELDS <= scope.keys() and all(target.get(k) == v for k, v in scope.items()) for scope in actor.targets)):
                raise AuthError('insufficient_scope')
    guard()
    view = accounts.execute('configuration.explain', {'selector': arguments['selector'], 'expected_target': target})
    store = view['effective'].get('cli_auth_credentials_store', 'auto')
    try:
        observation = _observation(Path(account['home']), target, store)
    except OSError:
        observation = dict(state='unavailable', signed_in=None, credential_store=store,
            identity=None, plan=None, freshness='unknown', provider_verified=False,
            evidence='not_observed', reason='credential_cache_unavailable')
    accounts.execute('accounts.resolve', {'selector': arguments['selector'], 'expected_target': target})
    guard()
    return dict(schema_version=1, operation='accounts.status', status='completed',
                result=dict(account=account, authentication=observation))


def protected_execute(arguments, root):
    from .operation_commands import local_actor
    return execute(root, arguments, actor=local_actor(root), authorize=lambda: local_actor(root))


def tool_specs():
    return {'wake_controller_account_status': ('controller-account-status', 'accounts.status',
        'Inspect sanitized local credential-cache evidence for one account; cached identity is unverified. No login, network request or token refresh.',
        {'selector': {'type': 'string'}, 'expected_target': {'type': 'object'}}, ['selector'], True)}
