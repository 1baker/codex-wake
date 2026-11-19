"""Shared public harness tools; host authority stays outside model arguments."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from .records import WakeError

TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 256}
CALLER = {'type': 'string', 'pattern': '^[0-9a-f-]{36}$'}
ROUTES={'type':'array','minItems':1,'maxItems':4,'uniqueItems':True,'items':{'enum':['background','existing_tab','new_tab','fresh_task']}}
POLICY = {'session_mode': {'enum': ['session_only', 'reopen_live', 'background']}, 'routes':ROUTES,'wake_lifetime': {'enum': ['conversation', 'task', 'persistent']},
          'owner_id': TEXT, 'owner_end': {'enum': ['retire', 'hold', 'retain']},
          'recipient_startup': {'enum': ['active_tab', 'background_saved', 'create_load_run']}}


def tool_specs():
    result = {}
    for verb in ('list', 'show', 'enroll', 'reconcile'):
        properties = {}
        required = []
        if verb in ('enroll', 'reconcile'):
            properties.update(runtime={'enum': ['codex', 'grok']}, conversation_id=TEXT)
            required += ['runtime', 'conversation_id']
        if verb in ('show', 'reconcile'):
            properties['managed_agent_id'] = TEXT
            required.append('managed_agent_id')
        if verb == 'enroll':
            properties.update({k: TEXT for k in ('predecessor', 'task_id', 'allocation_id')})
        result['wake_agents_' + verb] = ('agents', verb,
            'Inspect or enroll exact managed conversations. Self-enrollment uses trusted native or host-bound identity; membership never grants additional operations.',
            properties, required, verb in ('list', 'show'))
    for verb in ('list', 'show', 'claim', 'check', 'release'):
        properties, required = {}, []
        if verb in ('show', 'check', 'release'):
            properties['claim_id'] = TEXT
            required.append('claim_id')
        if verb in ('claim', 'check', 'release'):
            properties['managed_agent_id'] = TEXT
            required.append('managed_agent_id')
        if verb in ('check', 'release'):
            properties['generation'] = {'type': 'integer', 'minimum': 1}
            required.append('generation')
        if verb == 'claim':
            properties.update(kind={'enum': ['worktree', 'build_prefix', 'install_prefix']},
                              path={'type': 'string', 'minLength': 1, 'maxLength': 4096})
            required += ['kind', 'path']
        result['wake_resources_' + verb] = ('resources', verb,
            'Declare cooperative resource custody using verified exact-owner identity. Check is point-in-time only; it grants no future mutation or filesystem permission.',
            properties, required, verb in ('list', 'show', 'check'))
    from .agent_observation import STATES
    for verb in ('observe', 'wait'):
        properties = dict(managed_agent_id=TEXT, freshness={'type': 'number', 'minimum': .1, 'maximum': 300},
                          timeout={'type': 'number', 'minimum': 0 if verb == 'wait' else .001,
                                   'maximum': 300 if verb == 'wait' else 60})
        required = ['managed_agent_id']
        if verb == 'wait':
            properties.update(state={'enum': list(STATES)}, interval={'type': 'number', 'minimum': .05, 'maximum': 5})
            required.append('state')
        result['wake_agents_' + verb] = ('agent-state', verb,
            'Observe or wait for exact managed-agent state using fresh runtime evidence. Unknown is not idle or completed; grants no operations.',
            properties, required, True)
    for verb in ('propose', 'approve', 'inspect', 'admit', 'pin'):
        properties = dict(caller_thread_id=CALLER, task_id=TEXT)
        required = ['caller_thread_id', 'task_id']
        if verb == 'propose':
            properties['brief'] = {'type': 'object'}
            required.append('brief')
        if verb in ('approve', 'admit'):
            properties['revision'] = {'type': 'integer', 'minimum': 1}
            if verb == 'approve':
                required.append('revision')
        if verb in ('admit', 'pin'):
            properties['assignment_id'] = TEXT
            required.append('assignment_id')
        result['wake_task_briefs_' + verb] = ('task-briefs', verb,
            'Propose, inspect or pin approved task scope. Approvals require exact task delegation in host policy; worker arguments cannot choose a role.',
            properties, required, verb in ('inspect', 'pin'))
    for verb in ('after', 'at', 'file'):
        result['wake_native_' + verb] = ('harness-native', verb,
            'Schedule one exact-self native wake with frozen lifetime/startup policy. Delays may exceed 24 hours; time-wake TTL starts after due. Select persistent lifetime to survive creator completion. Inspect armed/monitor state: retention is not readiness or delivery.',
            dict(caller_thread_id=CALLER, trigger={'type': 'string', 'minLength': 1, 'maxLength': 1024},
                 prompt={'type': 'string', 'minLength': 1, 'maxLength': 32768},
                 idempotency_key=TEXT, ttl=dict(TEXT, description='Delivery window after due for time wakes; from registration for file wakes.'), **POLICY),
            ['caller_thread_id', 'trigger', 'prompt', 'idempotency_key', 'session_mode'], False)
    for verb in ('register', 'list', 'show', 'revise', 'cancel'):
        properties = dict(caller_thread_id=CALLER)
        required = ['caller_thread_id']
        if verb in ('register', 'revise'):
            properties['request'] = {'type': 'object'}
            required.append('request')
        if verb in ('show', 'revise', 'cancel'):
            properties['schedule_id'] = TEXT
            required.append('schedule_id')
        if verb in ('revise', 'cancel'):
            properties['expected_revision'] = {'type': 'integer', 'minimum': 1}
            required.append('expected_revision')
        result['wake_schedules_' + verb] = ('harness-schedules', verb,
            'Manage explicit exact-self durable recurring schedules. Require agreed mode/cadence/end/missed/overlap/delivery fields. Retained is not armed; cancellation does not stop running turns.',
            properties, required, verb in ('list', 'show'))
    result['wake_owner_complete'] = ('harness-owner', 'complete',
        'Reconcile an explicit operator-approved owner completion. Caller identity alone cannot declare work complete. Never retract or replay uncertain effects.',
        dict(caller_thread_id=CALLER, owner_kind={'enum': ['conversation', 'task']}, owner_id=TEXT, event_id=TEXT),
        ['caller_thread_id', 'owner_kind', 'owner_id', 'event_id'], False)
    return result


def controller_tasks(runner, caller):
    if runner.harness_policy is None:
        return ()
    from .wake_policy import _read
    policy = _read(Path(runner.harness_policy))
    if (type(policy) is not dict or set(policy) != {'version', 'controllers'}
            or type(policy['version']) is not int or policy['version'] != 1
            or type(policy['controllers']) is not dict):
        raise WakeError('invalid_harness_controller_policy')
    tasks = policy['controllers'].get(caller, [])
    if type(tasks) is not list or len(tasks) > 256 or any(type(t) is not str or not t for t in tasks):
        raise WakeError('invalid_harness_task_delegation')
    return tuple(tasks)


def native_workspace(runner, caller):
    from .shared_app_server import SharedAppServerReader, locate_shared_endpoint
    endpoint = runner.app_server
    if endpoint == 'unix://':
        endpoint = locate_shared_endpoint(timeout=10)
    with SharedAppServerReader(endpoint, timeout=10) as reader:
        thread = reader.read_thread(caller)
    if thread.get('id') != caller or not isinstance(thread.get('cwd'), str) or not Path(thread['cwd']).is_absolute():
        raise WakeError('native_workspace_unavailable')
    return Path(thread['cwd']).resolve()


def call(runner, group, verb, arguments, native_context):
    if runner.wake_root is None:
        raise WakeError('host_wake_root_required')
    root = Path(runner.wake_root)
    if group == 'agent-state':
        from .agent_observation import RuntimeStateObserver, grok_source_from_actor
        from .agent_observation_commands import execute
        grok = None
        if runner.actor_runtime == 'grok' and runner.bus_root is not None and runner.capability is not None:
            grok = grok_source_from_actor(runner.bus_root, runner.capability)
        return execute(verb, arguments, root, observer=RuntimeStateObserver(endpoint=runner.app_server, grok_source=grok))
    if group == 'resources':
        from .managed_inventory_commands import RuntimeObserver
        from .resource_claim_commands import execute
        grok = bus = None
        if runner.actor_runtime == 'grok':
            from .runtime_a2a import GrokMailboxRuntime
            from .a2a_bus import BusStore
            if runner.bus_root is None or runner.capability is None:
                raise WakeError('host_bound_runtime_capability_required')
            bus = BusStore(runner.bus_root)
            grok = GrokMailboxRuntime.from_actor(bus, runner.capability)
        observer = RuntimeObserver(endpoint=runner.app_server, socket_path=runner.tmux_socket,
                                   grok_runtime=grok, bus=bus, capability=runner.capability)
        return execute(verb, arguments, root, native_context=native_context, observer=observer)
    if group == 'agents':
        from .managed_inventory_commands import RuntimeObserver, execute
        grok = bus = None
        if runner.actor_runtime == 'grok':
            from .runtime_a2a import GrokMailboxRuntime
            from .a2a_bus import BusStore
            if runner.bus_root is None or runner.capability is None:
                raise WakeError('host_bound_runtime_capability_required')
            bus = BusStore(runner.bus_root)
            grok = GrokMailboxRuntime.from_actor(bus, runner.capability)
        observer = RuntimeObserver(endpoint=runner.app_server, socket_path=runner.tmux_socket,
                                   grok_runtime=grok, bus=bus, capability=runner.capability)
        return execute(verb, arguments, root, native_context=native_context, observer=observer)
    from .goal_supervision import verified_native_caller
    caller = arguments['caller_thread_id']
    verified_native_caller(native_context, caller)
    if group == 'task-briefs':
        from .task_briefs import BriefAuthority
        from .task_brief_commands import execute_task_briefs
        tasks = controller_tasks(runner, caller)
        if arguments['task_id'] in tasks:
            authority = BriefAuthority('native:' + caller, 'controller', tasks)
        else:
            authority = BriefAuthority('native:' + caller, 'worker', (arguments['task_id'],),
                                       workspace=str(native_workspace(runner, caller)))
        args = SimpleNamespace(task_brief_command=verb, task_id=arguments['task_id'],
                               revision=arguments.get('revision'), assignment_id=arguments.get('assignment_id'),
                               brief_json=json.dumps(arguments.get('brief')) if 'brief' in arguments else None)
        return execute_task_briefs(args, root, authority=authority)
    if group == 'harness-schedules':
        from .recurring_schedules import ScheduleStore
        from .session_permissions import Principal
        store = ScheduleStore(root)
        tasks = controller_tasks(runner, caller)
        principal = Principal(caller, 'controller' if tasks else 'session', tuple(tasks))
        if verb in ('register', 'revise'):
            request = arguments['request']
            if request.get('thread_id') != caller:
                raise WakeError('schedule_exact_self_required')
            if verb == 'register':
                return store.register(request, endpoint=runner.app_server, principal=principal)
            return store.revise(arguments['schedule_id'], request, arguments['expected_revision'], endpoint=runner.app_server, principal=principal)
        if verb == 'cancel':
            return store.cancel(arguments['schedule_id'], arguments['expected_revision'], principal=principal)
        if verb == 'show':
            value = store.read(arguments['schedule_id'])
            store.authorize(value, principal)
            return store.receipt(value)
        values = []
        for value in store.records():
            try:
                store.authorize(value, principal)
                values.append(store.receipt(value))
            except WakeError:
                continue
        return dict(schedules=values)
    if group == 'harness-owner':
        kind, owner = arguments['owner_kind'], arguments['owner_id']
        if (kind == 'conversation' and owner != 'codex:' + caller) or (kind == 'task' and owner not in controller_tasks(runner, caller)):
            raise WakeError('owner_completion_authority_denied')
        from .wake_policy import reconcile_owner_completion
        return reconcile_owner_completion(root, dict(kind=kind, id=owner), arguments['event_id'])
    if group == 'harness-native':
        if arguments.get('session_mode') not in ('session_only', 'reopen_live', 'background'):
            raise WakeError('explicit_session_mode_required')
        if any(isinstance(arguments.get(key), str) and arguments[key].startswith('-') for key in ('trigger', 'owner_id', 'idempotency_key', 'ttl')):
            raise WakeError('invalid_option_prefixed_argument')
        from .cli import run
        argv = ['--wake-root', str(root), 'native', verb, '--endpoint', runner.app_server,
                '--json', '--idempotency-key', arguments['idempotency_key'], '--ttl', arguments.get('ttl', '24h')]
        for name in POLICY:
            if name=='routes':
                for route in arguments.get('routes',[]):argv+=['--wake-route',route]
            elif name in arguments:
                argv += ['--' + name.replace('_', '-'), arguments[name]]
        argv += [caller, arguments['trigger'], '--', arguments['prompt']]
        # A long-lived MCP process can retain a detached mount as its cwd.
        # Recover only from the already verified native caller, never tool input.
        registration_cwd = None
        try:
            Path.cwd().resolve()
        except OSError:
            registration_cwd = native_workspace(runner, caller)
            if not registration_cwd.is_dir():
                raise WakeError('native_workspace_unavailable')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            from .session_permissions import Principal
            tasks=controller_tasks(runner,caller)
            code = run(argv,permission_principal=Principal(caller,'controller' if tasks else 'session',tasks=tuple(tasks)),
                       registration_cwd=registration_cwd)
        if code:
            raise WakeError('wake_registration_not_ready')
        return json.loads(output.getvalue())
    raise WakeError('unknown_harness_operation')
