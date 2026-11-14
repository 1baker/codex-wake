"""Versioned structured flow definitions and durable host-owned run state.

Definitions are data. Invocation and current authorization are trusted host seams;
flow definitions cannot supply Python code, caller identity or new authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

from .a2a_bus import private_path
from .controller_runtime import ControllerRuntime, encoded, identity
from .managed_inventory import InventoryError

class _FlowLimitReached(Exception):
    pass


class _IterationLimitReached(Exception):
    def __init__(self,identifier,reason):self.identifier,self.reason=identifier,reason


_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def flow_error(code, message):
    raise InventoryError(code, message)


def name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        flow_error('invalid_argument', 'flow and node IDs must be bounded names')
    return value


@dataclass(frozen=True)
class FlowDefinition:
    document: str
    digest: str

    @classmethod
    def compile(cls, definition):
        if isinstance(definition, cls):
            definition = definition.as_dict()
        if not isinstance(definition, dict) or set(definition) - {'id', 'version', 'entry', 'nodes', 'limits'}:
            flow_error('invalid_flow', 'versioned structured definition required')
        name(definition.get('id'))
        if type(definition.get('version')) is not int or definition['version'] < 1:
            flow_error('invalid_flow', 'positive integer flow version required')
        nodes = definition.get('nodes')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 64:
            flow_error('invalid_flow', 'flow requires between one and 64 nodes')
        by_id = {}
        for node in nodes:
            if not isinstance(node, dict):
                flow_error('invalid_flow', 'node must be a structured object')
            identifier = name(node.get('id'))
            if identifier in by_id:
                flow_error('invalid_flow', 'node IDs must be unique')
            kind = node.get('type')
            fields = {
                'call': {'id', 'type', 'operation', 'arguments', 'next', 'retry', 'failure'},
                'branch': {'id', 'type', 'condition', 'then', 'else', 'unknown', 'error', 'timeout'},
                'function': {'id', 'type', 'function', 'version', 'arguments', 'limits', 'next', 'unknown', 'error', 'timeout'},
                'select': {'id', 'type', 'cases', 'default', 'unknown', 'error', 'timeout'},
                'while': {'id', 'type', 'condition', 'body', 'max_iterations', 'next', 'unknown', 'error', 'timeout', 'exhausted'},
                'wait': {'id', 'type', 'operation_id', 'timeout', 'next', 'operation', 'failure'},
                'foreach': {'id', 'type', 'items', 'mode', 'profile', 'expected_target', 'prompt', 'parallelism', 'join', 'next', 'limits'},
                'end': {'id', 'type', 'value'},
            }
            if kind not in fields or set(node) - fields[kind]:
                flow_error('unsupported_flow_node', 'node type or fields are unsupported')
            if kind == 'function':
                from .controller_conditions import validate_condition
                validate_condition({key:node[key] for key in ('function','version','arguments','limits') if key in node})
            if kind == 'while':
                from .controller_flow_structures import validate_while
                validate_while(node)
            if kind == 'select':
                from .controller_flow_structures import validate_select
                validate_select(node)
            if kind in ('call','wait') and node.get('failure','stop') not in ('stop','continue'):
                flow_error('invalid_flow','explicit failure policy must be stop or continue')
            if kind == 'call':
                from .controller_flow_retry import policy
                policy(node)
            if kind == 'foreach':
                from .controller_flow_foreach import validate
                validate(node)
            if kind == 'call' and (not isinstance(node.get('operation'), str) or not isinstance(node.get('arguments', {}), dict)):
                flow_error('invalid_flow', 'call requires an operation and object arguments')
            if kind == 'branch' and not {'condition', 'then', 'else'} <= node.keys():
                flow_error('invalid_flow', 'branch requires typed condition and explicit paths')
            if kind == 'branch':
                from .controller_conditions import validate_condition
                validate_condition(node['condition'])
            if kind == 'wait' and (type(node.get('timeout', 0)) not in (int, float) or not 0 <= node.get('timeout', 0) <= 30):
                flow_error('invalid_flow', 'wait timeout must be between zero and 30 seconds')
            by_id[identifier] = node
        entry = definition.get('entry')
        if entry not in by_id:
            flow_error('invalid_flow', 'entry must name a node')
        visited, active = set(), set()
        def visit(identifier):
            if identifier is None:
                return
            if identifier not in by_id:
                flow_error('invalid_flow', 'flow references a missing node')
            if identifier in active:
                flow_error('invalid_flow', 'unbounded cycles are unsupported')
            if identifier in visited:
                return
            active.add(identifier)
            node = by_id[identifier]
            from .controller_flow_structures import edges
            for selected in edges(node):
                visit(selected)
            active.remove(identifier)
            visited.add(identifier)
        for identifier in by_id:
            visit(identifier)
        if not isinstance(definition.get('limits', {}), dict):
            flow_error('invalid_flow', 'limits must be an explicit object')
        try:
            document = encoded(definition)
        except (ValueError, TypeError):
            flow_error('invalid_flow', 'definition must contain finite JSON data')
        if len(document.encode()) > 262144:
            flow_error('invalid_flow', 'definition exceeds its bounded size')
        return cls(document, hashlib.sha256(document.encode()).hexdigest())

    def as_dict(self):
        return json.loads(self.document)


class ControllerFlows:
    def __init__(self, root, *, host, environment, invoke, authorize, now=time.time, clock=None):
        self.root, self.host, self.environment = Path(root), host, environment
        self.invoke, self.authorize, self.now = invoke, authorize, now
        self.clock = clock or self._host_clock
        self.runtime = ControllerRuntime(self.root, now=now)
        directory = self.root / 'controller-flows'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_path(directory, directory=True)
        self.path = directory / 'flows.sqlite'
        if self.path.exists() or self.path.is_symlink():
            private_path(self.path)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        private_path(self.path)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS condition_definitions (
                function_key TEXT PRIMARY KEY, digest TEXT, definition TEXT);
                CREATE TABLE IF NOT EXISTS definitions (
                flow_id TEXT, version INTEGER, digest TEXT, definition TEXT,
                PRIMARY KEY(flow_id,version));
                CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, intent TEXT UNIQUE, fingerprint TEXT, state TEXT);''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def _host_clock():
        return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),seconds=time.monotonic())

    def _clock_value(self,state):
        from .controller_conditions import ConditionPending
        try:
            sample=self.clock();wall=self.now();anchor=state['elapsed_clock']
            counter=sample['seconds']
            if (not isinstance(sample['boot_id'],str) or not sample['boot_id'] or sample['boot_id']!=anchor['boot_id']
                or type(counter) not in (int,float) or not math.isfinite(counter) or counter<anchor['latest']
                or type(wall) not in (int,float) or not math.isfinite(wall)):
                raise ValueError('clock continuity lost')
            regressed=wall<anchor['wall_latest']
            high_water=max(anchor['wall_latest'],wall)
            anchor.update(latest=counter,wall_latest=high_water,wall_observed=wall,
                wall_observation='regressed' if regressed else 'nondecreasing',
                wall_regression_observations=anchor.get('wall_regression_observations',0)+int(regressed),
                elapsed=max(anchor['elapsed'],counter-anchor['start'],high_water-state['created_at']))
            return state['created_at']+anchor['elapsed']
        except (KeyError,OSError,TypeError,ValueError):
            raise ConditionPending('flow_clock_uncertain') from None

    def _observe_time(self,actor,run_id):
        from .controller_conditions import ConditionPending
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state=self._owned(actor,self._load(run_id,db),'control')
            if state['phase'] not in ('ready','waiting'):return None
            try:self._clock_value(state)
            except ConditionPending:
                state.update(phase='held',reason='flow_clock_uncertain')
                self._write(db,state)
                return self.projection(state)
            self._write(db,state)
        return None

    def target(self, flow_id):
        return dict(host=self.host, environment=self.environment, flow_id=name(flow_id))

    def check(self, actor, flow_id, capability):
        return self.runtime.check_authority(actor, self.target(flow_id), capability, authorize=self.authorize)

    def propose(self, actor, definition):
        compiled = FlowDefinition.compile(definition)
        value = compiled.as_dict()
        self.check(actor, value['id'], 'observe')
        return dict(definition=value, definition_sha256=compiled.digest, effects='none', executable=False)

    def publish(self, actor, definition):
        compiled = FlowDefinition.compile(definition)
        value = compiled.as_dict()
        self.check(actor, value['id'], 'control')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT digest FROM definitions WHERE flow_id=? AND version=?',
                (value['id'], value['version'])).fetchone()
            if previous and previous[0] != compiled.digest:
                flow_error('immutable_flow_version', 'published version cannot change; publish a new version')
            db.execute('INSERT OR IGNORE INTO definitions VALUES(?,?,?,?)',
                (value['id'], value['version'], compiled.digest, compiled.document))
        return dict(flow_id=value['id'], version=value['version'], definition_sha256=compiled.digest)

    def _definition(self, flow_id, version):
        with self.connect() as db:
            row = db.execute('SELECT definition,digest FROM definitions WHERE flow_id=? AND version=?',
                (name(flow_id), version)).fetchone()
        if row is None:
            flow_error('flow_version_not_found', 'published flow version is unavailable')
        compiled = FlowDefinition.compile(json.loads(row[0]))
        if compiled.digest != row[1]:
            flow_error('flow_store_invalid', 'definition revision changed')
        return compiled

    def definition(self, actor, flow_id, version):
        self.check(actor, flow_id, 'observe')
        compiled = self._definition(flow_id, version)
        return dict(definition=compiled.as_dict(), definition_sha256=compiled.digest)

    def _load(self, run_id, db=None):
        from .controller_runtime import bounded_id
        bounded_id(run_id)
        if db is None:
            with self.connect() as connection:
                return self._load(run_id, connection)
        row = db.execute('SELECT state FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            flow_error('flow_run_not_found', 'flow run is unavailable')
        return json.loads(row[0])

    @staticmethod
    def _write(db, state):
        text = encoded(state)
        if len(text.encode()) > 4194304:
            flow_error('flow_store_limit', 'retained flow state exceeds its declared bound')
        db.execute('UPDATE runs SET state=? WHERE run_id=?', (text, state['run_id']))

    def _owned(self, actor, state, capability):
        from .controller_auth import AuthError
        self.check(actor, state['flow_id'], capability)
        if identity(actor) != state['owner']:
            raise AuthError('insufficient_scope')
        return state

    @staticmethod
    def projection(state):
        return {key: value for key, value in state.items() if key not in ('owner', 'attempt', 'condition_registry_snapshot')}

    def inspect(self, actor, run_id):
        return self.projection(self._owned(actor, self._load(run_id), 'observe'))

    def start(self, actor, flow_id, version, *, inputs, intent, binding):
        from uuid import uuid4
        from .controller_runtime import bounded_id
        self.check(actor, flow_id, 'control')
        bounded_id(intent); bounded_id(binding)
        if not isinstance(inputs, dict) or len(encoded(inputs).encode()) > 65536:
            flow_error('invalid_argument', 'bounded object flow inputs required')
        compiled = self._definition(flow_id, version)
        definition = compiled.as_dict()
        from .controller_conditions import Conditions,limits
        configured_limits=limits(definition.get('limits',{}))
        from .controller_flow_structures import expand as expand_structures
        structured=expand_structures(definition)
        arbitrary=any(node['type'] in ('call','foreach') for node in structured['nodes'])
        from .controller_flow_retry import READ_OPERATIONS
        unmetered=any(node['type']=='call' and node['operation'] not in READ_OPERATIONS for node in structured['nodes'])
        if arbitrary and (('max_tokens' in definition.get('limits',{}) and (configured_limits['metering']!='estimate_opt_in' or unmetered)) or ('max_seconds' in definition.get('limits',{}) and configured_limits['metering']!='estimate_opt_in')):
            flow_error('unsupported_flow_limits','native exact or unestimated arbitrary-operation token bounds are unqualified; rejected before effects')
        def named(value):
            return isinstance(value,dict) and ('function' in value or any(named(v) for v in value.values())) or isinstance(value,list) and any(named(v) for v in value)
        uses_registry=any(node['type']=='function' or named(node.get('condition')) or node['type'] in ('select','while') and named(node) for node in definition['nodes'])
        registry=Conditions(self.root) if uses_registry else Conditions(self.root,registry={})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for function_key,function in registry.registry.items():
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}@[1-9][0-9]*',function_key):
                    flow_error('invalid_condition','function registry keys require bounded name@version')
                text=encoded(function);digest=hashlib.sha256(text.encode()).hexdigest()
                previous=db.execute('SELECT digest FROM condition_definitions WHERE function_key=?',(function_key,)).fetchone()
                if previous and previous[0]!=digest:
                    flow_error('immutable_condition_version','host function version changed; register a new version')
                db.execute('INSERT OR IGNORE INTO condition_definitions VALUES(?,?,?)',(function_key,digest,text))
        fingerprint = hashlib.sha256(encoded(dict(definition=compiled.digest, inputs=inputs, binding=binding)).encode()).hexdigest()
        key = hashlib.sha256(encoded(dict(owner=identity(actor), intent=intent)).encode()).hexdigest()
        state = dict(schema_version=1, run_id='flowrun_' + uuid4().hex, flow_id=flow_id, version=version,
            definition_sha256=compiled.digest, target=self.target(flow_id), owner=identity(actor), inputs=inputs,
            binding=binding, created_at=self.now(), phase='ready', cursor=definition['entry'],
            condition_enforcement='host_admission_bounds_only; native_exact_tokens_and_time_unqualified',
            condition_registry_used=uses_registry,condition_registry_revision=registry.revision,condition_registry_snapshot=json.loads(encoded(registry.registry)),condition_limits=configured_limits,condition_usage=dict(calls=0,tokens=0),condition_trace=[],
            steps={}, attempt_counts={}, attempt_history={}, result=None, reason=None, cancellation=False, completed_steps=0)
        try:
            sample=self.clock();counter=sample['seconds']
            if not isinstance(sample['boot_id'],str) or not sample['boot_id'] or type(counter) not in (int,float) or not math.isfinite(counter):raise ValueError()
        except (KeyError,OSError,TypeError,ValueError):flow_error('flow_clock_unavailable','host elapsed continuity is unavailable; no run admitted')
        state['elapsed_clock']=dict(boot_id=sample['boot_id'],start=counter,latest=counter,wall_latest=state['created_at'],elapsed=0)
        for node in structured['nodes']:
            if node['type'] == 'foreach':
                capabilities = self.invoke('sessions.capabilities',
                    dict(profile=node['profile'], expected_target=node['expected_target']),
                    authorize=lambda: self.check(actor, flow_id, 'control'))
                if node['mode'] not in capabilities.get('result', {}).get('modes', []):
                    flow_error('unsupported_session_mode', 'host cannot execute the requested foreach session mode')
                maximum=capabilities.get('result',{}).get('max_parallelism',8)
                if type(maximum) is not int or not 1<=maximum<=8 or node.get('parallelism',1)>maximum:
                    flow_error('unsupported_parallelism','requested foreach parallelism exceeds the negotiated runtime capability')
        from .controller_flow_foreach import expand
        execution, memberships = expand(structured, state, self._resolve, _UNKNOWN)
        state.update(execution_definition=execution, memberships=memberships, cursor=execution['entry'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT fingerprint,state FROM runs WHERE intent=?', (key,)).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    flow_error('idempotency_conflict', 'flow intent already names a different pinned definition or input')
                return self.projection(json.loads(previous[1]))
            if db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] >= 256:
                flow_error('flow_capacity', 'retained run capacity reached; no history was removed')
            db.execute('INSERT INTO runs VALUES(?,?,?,?)', (state['run_id'], key, fingerprint, encoded(state)))
        return self.projection(state)

    @staticmethod
    def _unknown_value(value):
        return isinstance(value, dict) and 'value' in value and (
            value.get('status') in ('unknown', 'unsupported', 'error', 'timeout')
            or ('observed_at' in value and value.get('value') in ('unknown', 'unsupported', 'unavailable', 'stale')))

    @staticmethod
    def _resolve(value, state):
        if isinstance(value, dict) and set(value) == {'ref'}:
            if not isinstance(value['ref'], str):
                flow_error('invalid_reference', 'reference must be a dotted context path')
            current = {'inputs': state['inputs'], 'steps': state['steps']}
            for key in value['ref'].split('.'):
                if key == 'value' and ControllerFlows._unknown_value(current):
                    return _UNKNOWN
                if not isinstance(current, dict) or key not in current:
                    return _UNKNOWN
                current = current[key]
            return current
        if isinstance(value, dict):
            result = {key: ControllerFlows._resolve(item, state) for key, item in value.items()}
            return _UNKNOWN if any(item is _UNKNOWN for item in result.values()) else result
        if isinstance(value, list):
            result = [ControllerFlows._resolve(item, state) for item in value]
            return _UNKNOWN if any(item is _UNKNOWN for item in result) else result
        return value

    def _condition(self, expression, state):
        if type(expression) is bool:
            return expression
        if not isinstance(expression, dict) or set(expression) != {'op', 'left', 'right'}:
            flow_error('invalid_condition', 'typed deterministic condition required')
        left, right = (self._resolve(expression[key], state) for key in ('left', 'right'))
        if self._unknown_value(left) or self._unknown_value(right):
            return None
        if left is _UNKNOWN or right is _UNKNOWN:
            return None
        operation = expression['op']
        if operation in ('eq', 'ne'):
            equal = type(left) is type(right) and left == right
            return equal if operation == 'eq' else not equal
        if operation not in ('lt', 'lte', 'gt', 'gte'):
            flow_error('invalid_condition', 'deterministic comparison is unsupported')
        if type(left) not in (int, float) or type(right) not in (int, float):
            return None
        return {'lt': left < right, 'lte': left <= right, 'gt': left > right, 'gte': left >= right}[operation]

    def _step_guard(self, actor, run_id, attempt=None):
        state = self._owned(actor, self._load(run_id), 'control')
        if attempt is not None and state.get('attempt') != attempt:
            flow_error('stale_flow_attempt', 'step ownership changed')
        if state['cancellation']:
            flow_error('flow_cancelled', 'flow cancellation prevents new steps')
        return actor

    def cancel(self, actor, run_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._owned(actor,self._load(run_id,db),'control')
            if state['phase'] in ('completed','cancelled','failed'):
                return self.projection(state)
            if not state['cancellation']:
                plan = state.get('execution_definition') or self._definition(state['flow_id'],state['version']).as_dict()
                nodes = {node['id']:node for node in plan['nodes']}
                finished = set()
                for key,value in state['steps'].items():
                    child = value.get('result',{}).get('operation',{}) if isinstance(value,dict) else {}
                    if nodes[key]['type']=='wait' and child.get('execution') in ('completed','cancelled','failed'):
                        finished.add(child.get('operation_id'))
                targets = {}
                for key,value in state['steps'].items():
                    operation = nodes[key].get('operation')
                    child = value.get('result',{}).get('operation',{}) if isinstance(value,dict) else {}
                    identifier = child.get('operation_id')
                    if identifier and identifier not in finished and operation in ('sessions.prompt','operations.send'):
                        targets[identifier] = 'sessions.cancel' if operation=='sessions.prompt' else 'operations.cancel'
                for receipt in state.get('condition_trace',[]):
                    identifier=receipt.get('native_operation_id')
                    if identifier and receipt.get('native_execution') not in ('completed','cancelled','failed'):
                        targets[identifier]='sessions.cancel'
                if state['phase']=='waiting' and state.get('waiting_on') not in finished:
                    targets[state['waiting_on']] = 'sessions.cancel' if state.get('waiting_operation')=='sessions.wait' else 'operations.cancel'
                from .controller_flow_retry import READ_OPERATIONS
                current = nodes.get(state.get('executing_node'),{})
                inflight = state['phase'] in ('executing','uncertain') and current.get('type')=='call' and current.get('operation') not in READ_OPERATIONS
                if inflight and state.get('child_operation_id'):
                    node = nodes[state['executing_node']]
                    if node['type']=='call':
                        targets.setdefault(state['child_operation_id'],'sessions.cancel' if node.get('operation')=='sessions.prompt' else 'operations.cancel')
                state.update(cancellation=True,cancel_inflight_unknown=inflight,
                    cancellations={key:dict(operation=value,status='not_requested') for key,value in targets.items()},
                    phase='uncertain',reason='child_cancellation_requested')
                self._write(db,state)
        # At most8 owner requests per call. Remaining or interrupted requests stay
        # visible; a later cancel call can request remaining, never replay ambiguous.
        for unused in range(8):
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state = self._owned(actor,self._load(run_id,db),'control')
                pending = [(key,value) for key,value in state.get('cancellations',{}).items() if value['status']=='not_requested']
                if not pending:break
                identifier,entry = pending[0]
                entry['status']='in_progress'
                self._write(db,state)
            try:
                value = self.invoke(entry['operation'],dict(operation_id=identifier),
                    authorize=lambda: self._owned(actor,self._load(run_id),'control') and actor)
                child = value.get('result',{}).get('operation',{})
                status = 'confirmed' if child.get('cancellation')=='confirmed' else 'requested' if child.get('cancellation')=='requested' else 'uncertain'
            except Exception:
                status='uncertain'
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state = self._owned(actor,self._load(run_id,db),'control')
                state['cancellations'][identifier]['status']=status
                self._write(db,state)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._owned(actor,self._load(run_id,db),'control')
            statuses = [item['status'] for item in state.get('cancellations',{}).values()]
            confirmed = all(status=='confirmed' for status in statuses) and not state.get('cancel_inflight_unknown')
            state.update(phase='cancelled' if confirmed else 'uncertain',
                reason='child_cancellation_confirmed' if confirmed else 'child_cancellation_pending_or_uncertain',
                cancellation_remaining=statuses.count('not_requested'))
            if confirmed:state.pop('attempt',None)
            self._write(db,state)
            return self.projection(state)

    def _reconcile_cancellation(self,actor,run_id,state):
        pending=[(key,value) for key,value in state.get('cancellations',{}).items() if value['status']!='confirmed']
        for identifier,entry in pending[:8]:
            method='sessions.wait' if entry['operation']=='sessions.cancel' else 'operations.result'
            arguments=dict(operation_id=identifier)
            if method=='sessions.wait':arguments['timeout']=0
            try:
                value=self.invoke(method,arguments,authorize=lambda:self._owned(actor,self._load(run_id),'control') and actor)
                child=value.get('result',{}).get('operation',{})
                terminal=child.get('phase')=='terminal' and child.get('execution') in ('completed','cancelled','failed')
            except Exception:
                terminal=False
            if terminal:
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    latest=self._owned(actor,self._load(run_id,db),'control')
                    latest['cancellations'][identifier].update(status='confirmed',outcome=child)
                    if identifier==latest.get('child_operation_id'):
                        latest['cancel_inflight_unknown']=False
                    self._write(db,latest)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=self._owned(actor,self._load(run_id,db),'control')
            confirmed=all(item['status']=='confirmed' for item in latest.get('cancellations',{}).values()) and not latest.get('cancel_inflight_unknown')
            latest.update(phase='cancelled' if confirmed else 'uncertain',reason='child_cancellation_confirmed' if confirmed else 'child_cancellation_pending_or_uncertain')
            latest['cancellation_remaining']=sum(item['status']=='not_requested' for item in latest.get('cancellations',{}).values())
            if confirmed:latest.pop('attempt',None)
            self._write(db,latest)
            return self.projection(latest)

    def _finish_iteration_stop(self,db,state,identifier):
        frame=state['iteration_frames'][identifier]
        confirmed=all(item['status']=='confirmed' for item in frame['cancellations'].values())
        if confirmed:
            frame.update(phase='failed',cancellation='confirmed')
            state.update(phase='ready',reason=None)
            state.pop('iteration_pending',None)
            state.pop('attempt',None)
            state.pop('executing_node',None)
        else:
            frame.update(phase='cancelling',cancellation='uncertain')
            state.update(phase='uncertain',reason='iteration_limit_cleanup_pending',iteration_pending=identifier)
        self._write(db,state)
        return self.projection(state)

    def _stop_iteration(self,actor,run_id,identifier,reason):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state=self._owned(actor,self._load(run_id,db),'control');frame=state['iteration_frames'][identifier]
            if frame['phase']!='cancelling':
                nodes={node['id']:node for node in state['execution_definition']['nodes']}
                finished={}
                for key,value in state['steps'].items():
                    node=nodes[key]
                    if node.get('iteration_id')!=identifier or node['type']!='wait':continue
                    child=value.get('result',{}).get('operation',{})
                    if child.get('phase')=='terminal' and child.get('execution') in ('completed','failed','cancelled'):
                        operation_id=self._resolve(node['operation_id'],state)
                        if isinstance(operation_id,str):finished[operation_id]=child
                targets={};outcomes=[]
                for key,value in state['steps'].items():
                    node=nodes[key]
                    if node.get('iteration_id')!=identifier:continue
                    child=value.get('result',{}).get('operation',{});operation_id=child.get('operation_id')
                    if operation_id in finished:outcomes.append(finished[operation_id]);continue
                    if child.get('phase')=='terminal':outcomes.append(child);continue
                    if node.get('operation')=='sessions.prompt' and operation_id:
                        targets[operation_id]=dict(method='sessions.cancel',status='not_requested')
                current=nodes.get(state.get('executing_node'),{})
                if current.get('iteration_id')==identifier and state.get('child_operation_id') and state['phase'] in ('executing','uncertain'):
                    targets.setdefault(state['child_operation_id'],dict(method='sessions.cancel' if current.get('operation')=='sessions.prompt' else 'operations.cancel',status='not_requested'))
                frame.update(phase='cancelling',reason=reason,cancellations=targets,owner_outcomes=outcomes)
                state.update(phase='uncertain',reason='iteration_limit_cleanup_pending',iteration_pending=identifier)
                self._write(db,state)
        for unused in range(8):
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE');state=self._owned(actor,self._load(run_id,db),'control');frame=state['iteration_frames'][identifier]
                pending=next(((key,value) for key,value in frame['cancellations'].items() if value['status']=='not_requested'),None)
                if not pending:break
                operation_id,entry=pending;entry['status']='in_progress';self._write(db,state)
            try:
                value=self.invoke(entry['method'],dict(operation_id=operation_id),authorize=lambda:self._owned(actor,self._load(run_id),'control') and actor)
                child=value.get('result',{}).get('operation',{})
                status='confirmed' if child.get('phase')=='terminal' and child.get('execution') in ('completed','failed','cancelled') else 'requested' if child.get('cancellation')=='requested' else 'uncertain'
            except Exception:status='uncertain';child={}
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE');state=self._owned(actor,self._load(run_id,db),'control')
                state['iteration_frames'][identifier]['cancellations'][operation_id].update(status=status,outcome=child)
                self._write(db,state)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');state=self._owned(actor,self._load(run_id,db),'control')
            return self._finish_iteration_stop(db,state,identifier)

    def _reconcile_iteration(self,actor,run_id,state):
        identifier=state['iteration_pending'];frame=state['iteration_frames'][identifier]
        for operation_id,entry in list(frame['cancellations'].items())[:8]:
            if entry['status']=='confirmed':continue
            method='sessions.wait' if entry['method']=='sessions.cancel' else 'operations.result'
            arguments=dict(operation_id=operation_id)
            if method=='sessions.wait':arguments['timeout']=0
            try:
                value=self.invoke(method,arguments,authorize=lambda:self._owned(actor,self._load(run_id),'control') and actor)
                child=value.get('result',{}).get('operation',{})
            except Exception:child={}
            if child.get('phase')=='terminal' and child.get('execution') in ('completed','failed','cancelled'):
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE');latest=self._owned(actor,self._load(run_id,db),'control')
                    latest['iteration_frames'][identifier]['cancellations'][operation_id].update(status='confirmed',outcome=child)
                    self._write(db,latest)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');state=self._owned(actor,self._load(run_id,db),'control')
            return self._finish_iteration_stop(db,state,identifier)

    def reconcile(self, actor, run_id):
        state = self._owned(actor, self._load(run_id), 'control')
        if state.get('iteration_pending'):
            return self._reconcile_iteration(actor,run_id,state)
        if state['cancellation']:
            return self._reconcile_cancellation(actor,run_id,state)
        if state['phase'] in ('executing','uncertain') and state.get('condition_attempt'):
            try:return self._advance_condition(actor,run_id,resume=True)
            except _FlowLimitReached as stopped:return self._stop_at_limit(actor,run_id,str(stopped))
        if state['phase'] not in ('executing', 'uncertain') or not state.get('child_operation_id'):
            return self.projection(state)
        attempt = state.get('attempt')
        value = self.invoke('operations.result', {'operation_id': state['child_operation_id']},
            authorize=lambda: self._step_guard(actor, run_id, attempt))
        child = value.get('result', {}).get('operation', {})
        if child.get('phase') != 'terminal':return self.projection(state)
        if child.get('execution') != 'completed':
            plan=state.get('execution_definition') or self._definition(state['flow_id'],state['version']).as_dict()
            node=next(item for item in plan['nodes'] if item['id']==state['cursor'])
            if 'failure' not in node or child.get('execution') not in ('failed','cancelled','not_started'):return self.projection(state)
            value=dict(value,status='failed')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = self._owned(actor, self._load(run_id, db), 'control')
            if latest.get('attempt') != attempt or latest['phase'] not in ('executing', 'uncertain'):
                return self.projection(latest)
            definition = latest.get('execution_definition') or self._definition(latest['flow_id'], latest['version']).as_dict()
            node = next(item for item in definition['nodes'] if item['id'] == latest['cursor'])
            latest['steps'][node['id']] = value
            selected = node.get('next')
            stopped=node.get('failure')=='stop' and value.get('status')=='failed'
            latest.update(cursor=selected, phase='failed' if stopped else 'ready' if selected is not None else 'completed', reason='child_failed' if stopped else None)
            latest['completed_steps'] += 1
            latest.pop('attempt', None)
            latest.pop('executing_node', None)
            self._write(db, latest)
            return self.projection(latest)

    def _advance_condition(self,actor,run_id,*,resume=False):
        # Process-scoped lock disappears on exit, so recovery needs no resource
        # reset and cannot race a still-running condition into another effect.
        import fcntl
        state=self._owned(actor,self._load(run_id),'control')
        if not resume and state['phase']!='ready':return None
        path=self.path.parent/('.condition-'+run_id+'.lock')
        descriptor=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            private_path(path)
            try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return self.projection(dict(state,reason='condition_in_progress'))
            return self._evaluate_condition(actor,run_id,resume=resume)
        finally:os.close(descriptor)

    def _evaluate_condition(self,actor,run_id,*,resume=False):
        from uuid import uuid4
        from .controller_conditions import Conditions
        state=self._owned(actor,self._load(run_id),'control')
        if state['phase']!='ready' and not (resume and state['phase'] in ('executing','uncertain') and state.get('condition_attempt')):return self.projection(state) if resume else None
        definition=state.get('execution_definition') or self._definition(state['flow_id'],state['version']).as_dict()
        node=next(item for item in definition['nodes'] if item['id']==state['cursor'])
        condition={key:node[key] for key in ('function','version','arguments','limits') if key in node} if node['type']=='function' else node.get('condition')
        if node['type'] not in ('branch','function') or node['type']=='branch' and (type(condition) is bool or ('function' not in condition and condition.get('op') not in ('and','or'))):return None
        snapshot=state.get('condition_registry_snapshot')
        registry=Conditions(self.root,registry=snapshot) if isinstance(snapshot,dict) else Conditions(self.root) if state.get('condition_registry_used') else Conditions(self.root,registry={})
        if registry.revision!=state.get('condition_registry_revision'):
            flow_error('stale_condition_registry','pinned function registry revision changed')
        attempt=uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=self._owned(actor,self._load(run_id,db),'control')
            if latest.get('attempt')!=state.get('attempt') or latest['cursor']!=node['id'] or latest['cancellation']:return self.projection(latest)
            latest.update(phase='executing',attempt=attempt,executing_node=node['id'],condition_attempt=True)
            self._write(db,latest);state=latest
        def save():
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                latest=self._owned(actor,self._load(run_id,db),'control')
                if latest.get('attempt')!=attempt or latest['cancellation']:
                    flow_error('stale_flow_attempt','condition ownership or authority changed')
                latest['condition_usage']=state['condition_usage'];latest['condition_trace']=state['condition_trace'];latest['elapsed_clock']=state.get('elapsed_clock')
                self._write(db,latest)
        def semantic(function,args,bounds,tokens,receipt):
            from .unified_connectors import check_action
            current=self._step_guard(actor,run_id,attempt)
            check_action(current,'sessions.wait')
            if not receipt.get('native_operation_id'):check_action(current,'sessions.prompt')
            from .controller_condition_native import invoke,recover
            if receipt.get('native_operation_id'):
                return recover(self.root,actor,receipt,authorize=lambda:self._step_guard(actor,run_id,attempt))
            identifier=run_id+'.'+node['id']+'.function'+str(state['condition_usage']['calls'])
            receipt['native_operation_id']=identifier
            receipt['native_execution']='unknown'
            save()
            return invoke(self.root,actor,function,args,bounds,tokens,receipt,
                authorize=lambda:self._step_guard(actor,run_id,attempt),request_id=identifier,binding=state['binding'])
        from .controller_conditions import ConditionPending
        if resume and any('evaluation_id' not in item for item in state.get('condition_trace',[])):
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                latest=self._owned(actor,self._load(run_id,db),'control')
                if latest.get('attempt')==attempt:
                    latest.update(phase='uncertain',reason='legacy_condition_interrupted_no_replay')
                    self._write(db,latest)
                return self.projection(latest)
        try:
            outcome=registry.evaluate(condition,state,resolve=lambda value:self._resolve(value,state),
                compare=lambda value:self._condition(value,state),save=save,now=lambda:self._clock_value(state),semantic=semantic,
                evaluation_id=node['id'],resume=resume,predicate=node['type']!='function')
        except ConditionPending as pending:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                latest=self._owned(actor,self._load(run_id,db),'control')
                if latest.get('attempt')==attempt:
                    latest.update(phase='uncertain',reason=str(pending),condition_usage=state['condition_usage'],condition_trace=state['condition_trace'],elapsed_clock=state.get('elapsed_clock'))
                    self._write(db,latest)
                pending_state=self.projection(latest)
            overall=state.get('condition_limits',{})
            try:budget_now=self._clock_value(state)
            except ConditionPending:budget_now=None
            timed_out=budget_now is not None and (budget_now-state['created_at']>=overall.get('max_seconds',300) or any('outcome' not in item and item.get('frame') and
                budget_now-item['frame']['began']>=item['limits']['max_seconds'] for item in state.get('condition_trace',[])))
            if timed_out:raise _FlowLimitReached('condition_time_limit')
            return pending_state
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=self._owned(actor,self._load(run_id,db),'control')
            if latest.get('attempt')!=attempt:return self.projection(latest)
            latest['condition_usage']=state['condition_usage'];latest['condition_trace']=state['condition_trace'];latest['elapsed_clock']=state.get('elapsed_clock')
            latest['steps'][node['id']]=outcome
            value=outcome['value'] if outcome['status']=='known' else None
            unresolved=outcome['status']!='known'
            selected=(node.get(outcome['status'],node.get('unknown')) if unresolved else node.get('next')) if node['type']=='function' else node.get(outcome['status'],node.get('unknown')) if value is None else node['then'] if value else node['else']
            latest.update(cursor=selected,phase='held' if unresolved and selected is None else 'ready' if selected is not None else 'completed',
                          reason='condition_'+outcome['status'] if value is None else None)
            latest['completed_steps']+=1
            for key in ('attempt','executing_node','condition_attempt'):latest.pop(key,None)
            self._write(db,latest)
            stopped=self.projection(latest)
        def limit_reason(value):
            if not isinstance(value,dict):return None
            if value.get('status')=='timeout':return 'condition_timeout'
            if value.get('reason') in ('condition_call_limit','condition_token_limit','condition_time_limit'):return value['reason']
            return next((reason for child in value.get('trace',[]) if (reason:=limit_reason(child))),None)
        reason=limit_reason(outcome)
        if reason:raise _FlowLimitReached(reason)
        return stopped

    def _stop_at_limit(self,actor,run_id,reason):
        cancelled=self.cancel(actor,run_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=self._owned(actor,self._load(run_id,db),'control')
            latest['limit_stop']=dict(reason=reason,new_work='stopped',cancellation='confirmed' if cancelled['phase']=='cancelled' else 'uncertain',hard_stop_claim=False)
            latest['reason']=reason
            self._write(db,latest)
            return self.projection(latest)

    def advance(self, actor, run_id):
        for unused in range(32):
            try:return self._advance(actor,run_id)
            except _FlowLimitReached as stopped:return self._stop_at_limit(actor,run_id,str(stopped))
            except _IterationLimitReached as stopped:
                state=self._stop_iteration(actor,run_id,stopped.identifier,stopped.reason)
                if state['phase']!='ready':return state
        return self.inspect(actor,run_id)

    def _advance(self, actor, run_id):
        from uuid import uuid4
        for unused in range(16):
            clock_state=self._observe_time(actor,run_id)
            if clock_state is not None:return clock_state
            condition_state=self._advance_condition(actor,run_id)
            if condition_state is not None:
                if condition_state['phase']!='ready':return condition_state
                continue
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state = self._owned(actor, self._load(run_id, db), 'control')
                if state['phase'] in ('completed', 'cancelled', 'failed', 'held', 'uncertain'):
                    return self.projection(state)
                if state['phase'] == 'executing':
                    # Never retry an effect merely because another caller resumed.
                    return self.projection(dict(state, reason='step_in_progress_or_interrupted'))
                if state['cancellation']:
                    state.update(phase='cancelled', reason='caller_cancelled')
                    self._write(db, state)
                    return self.projection(state)
                definition = self._definition(state['flow_id'], state['version']).as_dict()
                if state['definition_sha256'] != FlowDefinition.compile(definition).digest:
                    flow_error('flow_store_invalid', 'run definition pin changed')
                definition = state.get('execution_definition') or definition
                node = next(item for item in definition['nodes'] if item['id'] == state['cursor'])
                from .controller_conditions import ConditionPending
                try:iteration_now=self._clock_value(state)
                except ConditionPending:
                    state.update(phase='held',reason='flow_clock_uncertain');self._write(db,state);return self.projection(state)
                active=[(key,value) for key,value in state.get('iteration_frames',{}).items() if value['phase']=='active']
                if active and iteration_now-state['created_at']>=state['condition_limits']['max_seconds']:raise _FlowLimitReached('flow_time_limit')
                for identifier,frame in active:
                    if iteration_now-frame['started_at']>=frame['limits']['max_seconds']:raise _IterationLimitReached(identifier,'iteration_time_limit')
                frame=state.get('iteration_frames',{}).get(node.get('iteration_id'))
                if frame and frame['phase']=='failed':
                    state['steps'][node['id']]=dict(result=dict(operation=dict(phase='terminal',execution='failed',source='iteration_limit',reason=frame['reason'],owner_outcomes=frame['owner_outcomes'],result=dict(target=None))))
                    selected=node.get('next');state.update(cursor=selected,phase='ready' if selected else 'completed',reason=None)
                    state['completed_steps']+=1
                    state.pop('waiting_on',None);state.pop('waiting_operation',None)
                    self._write(db,state);continue
                if node['type'] == 'branch':
                    value = self._condition(node['condition'], state)
                    state['steps'][node['id']] = dict(type='boolean', value=value, status='unknown' if value is None else 'known')
                    selected = node.get('unknown') if value is None else node['then'] if value else node['else']
                    if value is None and selected is None:
                        state.update(phase='held', reason='condition_unknown')
                    else:
                        state.update(cursor=selected, phase='ready' if selected is not None else 'completed')
                    state['completed_steps'] += 1
                    self._write(db, state)
                    continue
                if node['type'] == 'collect':
                    value = self._resolve(node['value'], state)
                    if value is _UNKNOWN:
                        state.update(phase='held', reason='output_unknown')
                    else:
                        statuses = [item['result'].get('execution','unknown') for item in value['items']]
                        value['status'] = 'completed' if all(status=='completed' for status in statuses) else 'failed' if all(status in ('completed','failed','cancelled') for status in statuses) else 'unknown'
                        state['steps'][node['id']] = value
                        if value['status']=='unknown' or (value['status']=='failed' and node['join']=='all_success'):
                            state.update(phase='held' if value['status']=='unknown' else 'failed',reason='aggregate_'+value['status'],result=value)
                            self._write(db,state)
                            return self.projection(state)
                        selected = node.get('next')
                        state.update(cursor=selected, phase='ready' if selected is not None else 'completed')
                    state['completed_steps'] += 1
                    self._write(db, state)
                    continue
                if node['type'] == 'hold':
                    state.update(phase='held',reason=node['reason'])
                    self._write(db,state)
                    return self.projection(state)
                if node['type'] == 'value':
                    value=self._resolve(node.get('value'),state)
                    if value is _UNKNOWN:
                        state.update(phase='held',reason='output_unknown');self._write(db,state);return self.projection(state)
                    state['steps'][node['id']]=value
                    selected=node.get('next');state.update(cursor=selected,phase='ready' if selected else 'completed')
                    state['completed_steps']+=1;self._write(db,state);continue
                if node['type'] == 'end':
                    value = self._resolve(node.get('value'), state)
                    state.update(phase='held' if value is _UNKNOWN else 'completed',
                        result=None if value is _UNKNOWN else value, reason='output_unknown' if value is _UNKNOWN else None)
                    self._write(db, state)
                    return self.projection(state)
                if node['type'] == 'wait':
                    operation_id = self._resolve(node.get('operation_id'), state)
                    arguments = _UNKNOWN if operation_id is _UNKNOWN else {'operation_id': operation_id, 'timeout': node.get('timeout', 0)}
                    operation = node.get('operation', 'operations.wait')
                    if operation not in ('operations.wait', 'sessions.wait', 'environment.conversations.input.result'):
                        flow_error('unsupported_operation', 'wait operation is unsupported')
                else:
                    arguments = self._resolve(node.get('arguments', {}), state)
                    operation = node['operation']
                if arguments is _UNKNOWN:
                    state.update(phase='held', reason='input_unknown')
                    self._write(db, state)
                    return self.projection(state)
                from .controller_conditions import ConditionPending
                try:budget_now=self._clock_value(state)
                except ConditionPending:
                    state.update(phase='held',reason='flow_clock_uncertain')
                    self._write(db,state)
                    return self.projection(state)
                bounds=state.get('condition_limits')
                if bounds:
                    usage=state.setdefault('condition_usage',dict(calls=0,tokens=0))
                    if usage['calls']>=bounds['max_calls'] or budget_now-state['created_at']>=bounds['max_seconds']:
                        raise _FlowLimitReached('flow_nested_limit')
                    usage['calls']+=1
                frame=state.get('iteration_frames',{}).get(node.get('iteration_id'))
                if frame is not None:
                    if frame['phase']=='pending':
                        if frame['token_estimate'] and frame['limits']['max_tokens']<=0:raise _IterationLimitReached(node['iteration_id'],'iteration_token_limit')
                        if frame['token_estimate'] and frame['limits']['max_tokens']>bounds['max_tokens']-usage['tokens']:raise _FlowLimitReached('flow_token_limit')
                        frame.update(phase='active',started_at=budget_now)
                    if frame['usage']['calls']>=frame['limits']['max_calls'] or budget_now-frame['started_at']>=frame['limits']['max_seconds']:
                        raise _IterationLimitReached(node['iteration_id'],'iteration_call_limit' if frame['usage']['calls']>=frame['limits']['max_calls'] else 'iteration_time_limit')
                    cost=frame['limits']['max_tokens'] if frame['token_estimate'] and operation=='sessions.prompt' else 0
                    if cost>bounds['max_tokens']-usage['tokens']:raise _FlowLimitReached('flow_token_limit')
                    if frame['token_estimate'] and operation=='sessions.prompt' and (cost<=0 or cost>frame['limits']['max_tokens']-frame['usage']['tokens']):raise _IterationLimitReached(node['iteration_id'],'iteration_token_limit')
                    frame['usage']['calls']+=1;frame['usage']['tokens']+=cost;usage['tokens']+=cost
                count = state.setdefault('attempt_counts',{}).get(node['id'],0)+1
                state['attempt_counts'][node['id']] = count
                attempt = uuid4().hex
                child_id = state['run_id'] + '.' + node['id']
                if node.get('retry'):
                    child_id += '.try' + str(count)
                request = dict(operation_id=child_id, idempotency_key=child_id, correlation_id=child_id,
                    binding=state['binding'], target=arguments.get('expected_target', state['target']))
                state.update(phase='executing', attempt=attempt, executing_node=node['id'], child_operation_id=child_id)
                self._write(db, state)
            try:
                value = self.invoke(operation, arguments,
                    authorize=lambda: self._step_guard(actor, run_id, attempt), request=request)
                if not isinstance(value, dict):
                    flow_error('invalid_step_result', 'host invocation must return a typed object result')
                encoded(value)
            except Exception as error:
                with self.connect() as db:
                    latest = self._load(run_id, db)
                    if latest.get('attempt') == attempt:
                        from .controller_flow_retry import should_retry, error_code
                        code = error_code(error)
                        retry = node['type']=='call' and not latest['cancellation'] and should_retry(node,code,count)
                        latest.setdefault('attempt_history',{}).setdefault(node['id'],[]).append(dict(attempt=count,error=code,operation_id=child_id))
                        exhausted=bool(node.get('retry')) and not retry and code in node['retry']['when']
                        latest.update(phase='ready' if retry else 'held' if exhausted else 'uncertain',
                            reason='retry_scheduled' if retry else 'retry_exhausted' if exhausted else code)
                        if retry:
                            latest.pop('attempt',None)
                            latest.pop('executing_node',None)
                        self._write(db, latest)
                    return self.projection(latest)
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                latest = self._load(run_id, db)
                if latest.get('attempt') != attempt:
                    return self.projection(latest)
                child = value.get('result',{}).get('operation',{})
                if child.get('phase') in ('uncertain','executing','dispatching'):
                    latest['steps'][node['id']] = value
                    latest.update(phase='uncertain',reason='child_effect_uncertain')
                    self._write(db,latest)
                    return self.projection(latest)
                if 'failure' in node and (value.get('status')=='failed' or child.get('phase')=='terminal' and child.get('execution') in ('failed','cancelled','not_started')):
                    from .controller_flow_retry import should_retry
                    code=value.get('error',{}).get('code') or child.get('reason') or 'child_failed'
                    if node['type']=='call' and not latest['cancellation'] and should_retry(node,code,count):
                        latest.setdefault('attempt_history',{}).setdefault(node['id'],[]).append(dict(attempt=count,error=code,operation_id=child_id))
                        latest.update(phase='ready',reason='retry_scheduled');latest.pop('attempt',None);latest.pop('executing_node',None)
                        self._write(db,latest);return self.projection(latest)
                    latest['steps'][node['id']]=value;latest['completed_steps']+=1
                    selected=node.get('next');latest.update(cursor=selected,phase='failed' if node['failure']=='stop' else 'ready' if selected else 'completed',reason='child_failed')
                    latest.pop('attempt',None);latest.pop('executing_node',None);self._write(db,latest)
                    if latest['phase']=='ready':continue
                    return self.projection(latest)
                if value.get('status') in ('failed', 'held'):
                    from .controller_flow_retry import should_retry
                    code=value.get('error',{}).get('code','child_not_completed')
                    retry=node['type']=='call' and not latest['cancellation'] and should_retry(node,code,count)
                    latest.update(phase='ready' if retry else 'held',reason='retry_scheduled' if retry else code)
                    latest.setdefault('attempt_history',{}).setdefault(node['id'],[]).append(dict(attempt=count,error=code,operation_id=child_id))
                    latest['steps'][node['id']] = value
                    latest.pop('attempt', None)
                    self._write(db, latest)
                    return self.projection(latest)
                if node['type'] == 'wait' and (value.get('result', {}).get('wait', {}).get('status') == 'timeout' or child.get('phase')=='waiting'):
                    latest.update(phase='waiting', reason='wait_timeout', waiting_on=arguments['operation_id'], waiting_operation=operation)
                    latest.pop('attempt', None)
                    latest.pop('executing_node', None)
                    self._write(db, latest)
                    return self.projection(latest)
                latest['steps'][node['id']] = value
                if node.get('iteration_id') and node['type']=='wait':
                    frame=latest['iteration_frames'][node['iteration_id']]
                    try:finished=self._clock_value(latest)
                    except ConditionPending:
                        latest.update(phase='held',reason='flow_clock_uncertain');self._write(db,latest);return self.projection(latest)
                    if finished-frame['started_at']<frame['limits']['max_seconds']:frame.update(phase='completed',finished_at=finished)
                selected = node.get('next')
                latest.update(cursor=selected, phase='ready' if selected is not None else 'completed', reason=None)
                latest['completed_steps'] += 1
                latest.pop('attempt', None)
                latest.pop('executing_node', None)
                self._write(db, latest)
        return self.inspect(actor, run_id)


_UNKNOWN = object()
