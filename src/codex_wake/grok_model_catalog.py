"""Operator-owned model evidence; public catalog output contains no credentials."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import stat

from .grok_provider_auth import GrokAccounts

REQUIRED = ('text', 'streaming', 'terminal', 'file_editing', 'mcp')
OPTIONAL = ('image_generation', 'web_search', 'reasoning_summary')


def qualified_time():
    from .time_inspection import stable_time_config
    from .stable_time import service_time_decision
    from .time_provider import require_time_decision
    config = stable_time_config()
    try:
        return require_time_decision(service_time_decision(config)) if config else None
    except (OSError, ValueError):
        return None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('invalid_model_metadata')
    return value


def _read(path, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError('invalid_model_metadata')
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('insecure_model_state')
        return json.load(stream)


class GrokModels:
    def __init__(self, root):
        self.root = Path(root)
        self.accounts = GrokAccounts(root)
        self.directory = self.root / 'grok-provider-models'
        try:
            info = self.directory.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('insecure_model_state')

    def _path(self, account):
        self.accounts._path(account)
        return self.directory / (account + '.json')

    def _save(self, account, record):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('insecure_model_state')
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.model-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(account))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def import_metadata(self, account, metadata):
        registration = self.accounts._record(account)
        if set(metadata) != {'schema', 'source', 'issued_at', 'expires_at', 'models'} or metadata['schema'] != 1:
            raise ValueError('invalid_model_metadata')
        _text(metadata['source'], 2048)
        if any(type(metadata[k]) not in (int, float) or not math.isfinite(metadata[k]) for k in ('issued_at', 'expires_at')) or metadata['issued_at'] >= metadata['expires_at']:
            raise ValueError('invalid_model_validity')
        models = metadata['models']
        if not isinstance(models, list) or not 1 <= len(models) <= 200:
            raise ValueError('invalid_model_metadata')
        seen = set()
        for model in models:
            if set(model) != {'id', 'label', 'context_window', 'capabilities'}:
                raise ValueError('invalid_model_metadata')
            model_id = _text(model['id'], 128)
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', model_id) or model_id in seen:
                raise ValueError('invalid_model_identity')
            seen.add(model_id)
            _text(model['label'])
            if type(model['context_window']) is not int or not 8192 <= model['context_window'] <= 2000000:
                raise ValueError('invalid_model_context')
            caps = model['capabilities']
            if not isinstance(caps, dict) or set(caps) - set(REQUIRED + OPTIONAL) or any(type(v) is not bool for v in caps.values()):
                raise ValueError('invalid_model_capabilities')
        record = dict(schema=1, account=account, registration_revision=digest(registration),
                      metadata=metadata, catalog_revision=digest(metadata), qualifications={}, default_model=None)
        self._save(account, record)
        return self.catalog(account)

    def qualify(self, account, receipt):
        registration = self.accounts._record(account)
        record = _read(self._path(account), private=True)
        fields = {'schema', 'source', 'account', 'account_revision', 'catalog_revision', 'model',
                  'issued_at', 'expires_at', 'entitlement', 'inference', 'capabilities'}
        if set(receipt) != fields or receipt['schema'] != 1:
            raise ValueError('invalid_qualification_receipt')
        if (receipt['account'] != account or receipt['account_revision'] != digest(registration)
                or receipt['catalog_revision'] != record['catalog_revision']
                or receipt['model'] not in {m['id'] for m in record['metadata']['models']}):
            raise ValueError('qualification_binding_mismatch')
        _text(receipt['source'], 2048)
        if any(type(receipt[k]) not in (int, float) or not math.isfinite(receipt[k]) for k in ('issued_at', 'expires_at')) or receipt['issued_at'] >= receipt['expires_at']:
            raise ValueError('invalid_qualification_validity')
        if any(type(receipt[k]) is not bool for k in ('entitlement', 'inference')):
            raise ValueError('invalid_qualification_receipt')
        caps = receipt['capabilities']
        if not isinstance(caps, dict) or set(caps) != set(REQUIRED) or any(type(v) is not bool for v in caps.values()):
            raise ValueError('invalid_qualification_capabilities')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        evidence = self.directory / ('evidence-' + digest(receipt) + '.json')
        try:
            fd = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if _read(evidence, private=True) != receipt:
                raise ValueError('qualification_evidence_changed')
        else:
            with os.fdopen(fd, 'w') as stream:
                json.dump(receipt, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        record['qualifications'][receipt['model']] = receipt
        self._save(account, record)
        return self.catalog(account)

    def resolve(self, account, model=None, selection_id=None):
        if model is not None and selection_id is not None:
            raise ValueError('conflicting_model_selectors')
        record = _read(self._path(account), private=True)
        catalog = self.catalog(account)
        if selection_id:
            choices = [v for v in catalog['selections'] if v['selectionId'] == selection_id]
            if not choices:
                raise ValueError('stale_inference_selection')
        else:
            model = model or record.get('default_model')
            if not model:
                raise ValueError('explicit_account_default_required')
            choices = [v for v in catalog['selections'] if v['modelId'] == model]
            if not choices:
                raise ValueError('model_not_registered')
        choice = choices[0]
        if choice['readiness'] != 'qualified':
            raise ValueError('inference_selection_' + choice['readiness'])
        return dict(schemaVersion=1, sourceRevision=catalog['sourceRevision'], selection=choice)

    def set_default(self, account, model):
        self.resolve(account, model)
        record = _read(self._path(account), private=True)
        record['default_model'] = model
        self._save(account, record)
        return self.resolve(account)

    def catalog(self, account, *, time=None):
        registration = self.accounts._record(account)
        try:
            record = _read(self._path(account), private=True)
        except FileNotFoundError:
            return dict(schemaVersion=1, sourceRevision=digest(registration), selections=[])
        clock = qualified_time() if time is None else time
        _text(registration['label'])
        authentication = self.accounts.status(account)
        revision = digest(record)
        selections = []
        for model in record['metadata']['models']:
            caps = {name: model['capabilities'].get(name, False) for name in REQUIRED + OPTIONAL}
            readiness, reasons = 'unverified', ['entitlement_and_inference_unverified']
            if authentication['authentication'] != 'present':
                readiness, reasons = 'unavailable', ['authentication_' + authentication['authentication']]
            elif record['registration_revision'] != digest(registration):
                readiness, reasons = 'stale', ['account_registration_changed']
            elif not all(caps[name] for name in REQUIRED):
                readiness, reasons = 'unavailable', ['required_capability_missing:' + name for name in REQUIRED if not caps[name]]
            elif clock is None:
                reasons = ['qualified_time_unavailable']
            elif clock.upper >= record['metadata']['expires_at']:
                readiness, reasons = 'stale', ['model_metadata_expired']
            elif clock.lower < record['metadata']['issued_at']:
                reasons = ['model_metadata_time_unverified']
            qualification = record['qualifications'].get(model['id'])
            if readiness == 'unverified' and reasons == ['entitlement_and_inference_unverified'] and qualification:
                if clock.upper >= qualification['expires_at']:
                    readiness, reasons = 'stale', ['qualification_expired']
                elif clock.lower < qualification['issued_at']:
                    reasons = ['qualification_time_unverified']
                elif not qualification['entitlement']:
                    readiness, reasons = 'unavailable', ['entitlement_unavailable']
                elif not qualification['inference'] or not all(qualification['capabilities'][name] for name in REQUIRED):
                    readiness, reasons = 'unavailable', ['required_coding_qualification_missing']
                else:
                    try:
                        # Read-only compatible native lock and expiry validation. Never refresh here.
                        self.accounts.bearer(account, clock.upper, refresh=False)
                    except (OSError, ValueError):
                        readiness, reasons = 'unavailable', ['native_auth_not_current']
                    else:
                        readiness, reasons = 'qualified', []
            identity = dict(providerId='grok__' + account, accountId=account, accountRevision=digest(registration),
                            modelId=model['id'], catalogRevision=record['catalog_revision'], evidenceRevision=digest(qualification) if qualification else 'unverified')
            selections.append(dict(**identity, selectionId=digest(identity), accountLabel=registration['label'],
                displayName=model['label'], contextWindow=model['context_window'], readiness=readiness,
                reasons=reasons, capabilities=caps, disabledFeatures=list(OPTIONAL),
                defaultForAccount=record.get('default_model') == model['id'], source=record['metadata']['source']))
        return dict(schemaVersion=1, sourceRevision=revision, selections=selections)


    def native_catalog(self, wake_executable):
        executable = Path(wake_executable)
        if not executable.is_absolute():
            raise ValueError('absolute_wake_executable_required')
        selections, providers, revisions = [], {}, []
        for path in sorted(self.accounts.directory.glob('*.json')):
            account = path.stem
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', account):
                continue
            catalog = self.catalog(account)
            selections.extend(catalog['selections'])
            revisions.append([account, catalog['sourceRevision']])
            providers['grok__' + account] = dict(name='Grok',
                base_url='https://cli-chat-proxy.grok.com/v1', wire_api='grok',
                auth=dict(command=str(executable), args=['--wake-root', str(self.root.absolute()),
                    'grok', 'auth', 'token', account, '--expected-account-revision',
                    digest(self.accounts._record(account))], timeout_ms=25000,
                    refresh_interval_ms=0, cwd=str(self.root.absolute())),
                requires_openai_auth=False, supports_websockets=False)
        return dict(schemaVersion=1, sourceRevision=digest(revisions), selections=selections, providers=providers)


def register_parser(commands):
    group = commands.add_parser('models', help='Grok model/account qualification and native catalog')
    verbs = group.add_subparsers(dest='grok_models_command', required=True)
    item = verbs.add_parser('native-catalog', help='sanitized JSON source consumed by the native picker')
    item.add_argument('--wake-executable', required=True, type=Path)
    item = verbs.add_parser('import', help='operator-only model metadata admission; does not qualify inference')
    item.add_argument('account')
    item.add_argument('--metadata', type=Path, required=True)
    item = verbs.add_parser('list')
    item.add_argument('account')
    item = verbs.add_parser('qualify', help='operator-only independent account/model qualification receipt')
    item.add_argument('account')
    item.add_argument('--receipt', type=Path, required=True)
    item = verbs.add_parser('default', help='operator-only explicit validated default for this account')
    item.add_argument('account')
    item.add_argument('model')
    item = verbs.add_parser('resolve')
    item.add_argument('account')
    item.add_argument('--model')
    item.add_argument('--selection-id')


def command(args, root):
    try:
        models = GrokModels(root)
        if args.grok_models_command == 'native-catalog':
            result = models.native_catalog(args.wake_executable)
        elif args.grok_models_command == 'import':
            result = models.import_metadata(args.account, _read(args.metadata))
        elif args.grok_models_command == 'qualify':
            result = models.qualify(args.account, _read(args.receipt))
        elif args.grok_models_command == 'default':
            result = models.set_default(args.account, args.model)
        elif args.grok_models_command == 'resolve':
            result = models.resolve(args.account, args.model, args.selection_id)
        else:
            result = models.catalog(args.account)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        reason = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]+', str(error)) else 'model_catalog_unavailable'
        print(json.dumps(dict(status='held', reason=reason)))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


def tool_specs():
    from .grok_provider_auth import tool_specs as auth_specs
    properties = auth_specs()['wake_grok_auth_status'][3]
    return {name: ('grok-models', operation, description, dict(properties, **extra),
                   ['account', 'expected_target'], True)
        for name, operation, description, extra in (
            ('wake_grok_models_list', 'grok_models.list', 'List account-bound model readiness without inference or refresh.', {}),
            ('wake_grok_models_resolve', 'grok_models.resolve', 'Resolve a qualified explicit account/model selection.',
             {'model': {'type': 'string'}, 'selection_id': {'type': 'string'}}))}


def observe(root, operation, arguments, *, actor, authorize):
    from .grok_provider_auth import observe as auth_observe
    from .managed_inventory import InventoryError
    expected = {'account', 'expected_target'}
    allowed = expected | ({'model', 'selection_id'} if operation == 'grok_models.resolve' else set())
    if not expected <= arguments.keys() or arguments.keys() - allowed:
        raise InventoryError('invalid_argument', 'Exact Grok account target required.')
    auth_arguments = {key: arguments[key] for key in expected}
    auth_observe(root, auth_arguments, actor=actor, authorize=authorize)
    try:
        models = GrokModels(root)
        result = (models.resolve(arguments['account'], arguments.get('model'), arguments.get('selection_id'))
                  if operation == 'grok_models.resolve' else models.catalog(arguments['account']))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise InventoryError('model_selection_held', 'Model selection is unavailable or unqualified.') from None
    auth_observe(root, auth_arguments, actor=actor, authorize=authorize)
    return dict(schema_version=1, operation=operation, status='completed', result=result)


def protected_observe(root, operation, arguments):
    from .operation_commands import local_actor
    return observe(root, operation, arguments, actor=local_actor(root), authorize=lambda: local_actor(root))
