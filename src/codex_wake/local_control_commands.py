"""Local same-user controller CLI and shared operation/output contract."""
import json

from .cli_output import emit
import sys
import time

from .local_session_events import MODES
from .managed_inventory import InventoryError
from .local_control_routing import HARNESS_PROPERTIES,parser_options

_COMMON={'endpoint':{'type':'string'},'mode':{'type':'string','enum':list(MODES)},
    'timeout':{'type':'number','minimum':0,'maximum':30},'cursor':{'type':'integer','minimum':0},
    'limit':{'type':'integer','minimum':1,'maximum':100}}


def operation_schemas():
    def schema(properties,required):
        return dict(type='object',properties=properties,required=required,additionalProperties=False)
    return {
        'local.create':schema(dict(HARNESS_PROPERTIES,idempotency_key={'type':'string'}),[]),
        'local.load':schema(dict(HARNESS_PROPERTIES,selector={'type':'string'},idempotency_key={'type':'string'},expected_target={'type':'object'}),['selector']),
        'local.prompt':schema(dict(_COMMON,**HARNESS_PROPERTIES,selector={'type':'string'},prompt={'type':'string'},
            idempotency_key={'type':'string'},expected_target={'type':'object'}),['selector','prompt']),
        'local.output':schema(dict(_COMMON,operation_id={'type':'string'}),['operation_id']),
        'local.result':schema(dict(_COMMON,operation_id={'type':'string'}),['operation_id']),
        'local.cancel':schema({'operation_id':{'type':'string'}},['operation_id'])}


def tool_specs():
    return {'wake_'+name.replace('.','_'):('local',name.split('.')[1],
        ('Create an owned headless Grok ACP session with harness=grok; Codex creation is unsupported.' if name=='local.create' else 'Load an explicitly selected owned Grok conversation through its fresh ACP profile; Codex load is unsupported.' if name=='local.load' else 'Same-user durable session operation; output observes the original turn without replay.'),
        schema['properties'],schema['required'],name not in ('local.prompt','local.create','local.load','local.cancel'))
        for name,schema in operation_schemas().items()}


def execute(operation,arguments,root):
    from .local_control_routing import LocalSessionRouter
    if operation not in operation_schemas():raise InventoryError('unsupported_operation','unsupported local session operation')
    schema=operation_schemas()[operation]
    if not isinstance(arguments,dict) or set(arguments)-set(schema['properties']) or any(key not in arguments for key in schema['required']):
        raise InventoryError('invalid_argument','unsupported or missing local operation arguments')
    owner=LocalSessionRouter(root)
    mode=arguments.get('mode')
    if mode is not None and mode not in MODES:raise InventoryError('invalid_argument','unknown output mode')
    # Validate all presentation inputs before admitting any effect.
    timeout=arguments.get('timeout',0);cursor=arguments.get('cursor',0);limit=arguments.get('limit',100)
    if type(timeout) not in (int,float) or not 0<=timeout<=30 or type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=100:
        raise InventoryError('invalid_argument','bounded output timeout, cursor and limit required')
    if operation=='local.create':return owner.create(harness=arguments.get('harness','codex'),profile=arguments.get('profile'),key=arguments.get('idempotency_key'))
    if operation=='local.load':return owner.load(arguments['selector'],harness=arguments.get('harness','codex'),profile=arguments.get('profile'),key=arguments.get('idempotency_key'),expected_target=arguments.get('expected_target'))
    if operation=='local.prompt':
        value=owner.prompt(arguments['selector'],arguments['prompt'],arguments.get('idempotency_key'),
            endpoint=arguments.get('endpoint','unix://'),expected_target=arguments.get('expected_target'),harness=arguments.get('harness','codex'),profile=arguments.get('profile'))
        identifier=value['result']['operation']['operation_id']
    elif operation=='local.cancel':return owner.cancel(arguments['operation_id'])
    elif operation=='local.result' and mode is None:return owner.result(arguments['operation_id'],timeout)
    else:value=None;identifier=arguments['operation_id'];mode=mode or 'transcript'
    if mode is None:return value
    output=owner.output(identifier,mode=mode,timeout=timeout,cursor=cursor,limit=limit)
    return dict(schema_version=1,operation=operation,status='completed',result=dict(output=output))


def register_parser(subparsers):
    parser=subparsers.add_parser('control',help='control existing same-user sessions without manual profiles')
    verbs=parser.add_subparsers(dest='control_verb',required=True)
    for verb in ('list','resolve','create','load','prompt','result','output','cancel'):
        item=verbs.add_parser(verb,**({'help':'create an owned headless Grok ACP session (select --harness grok)'} if verb=='create' else {'help':'explicitly load a persisted owned Grok conversation'} if verb=='load' else {}))
        item.add_argument('--json', dest='as_json', action='store_true')
        if verb in ('list','resolve','prompt','create','load'):parser_options(item)
        item.add_argument('--endpoint',default='unix://',help='existing native Unix endpoint; default discovers running local daemons')
        if verb in ('resolve','prompt','load'):
            item.add_argument('selector');item.add_argument('--expected-target',type=json.loads)
        if verb=='prompt':item.add_argument('prompt')
        if verb in ('prompt','create','load'):item.add_argument('--idempotency-key')
        if verb in ('result','output','cancel'):item.add_argument('operation_id')
        if verb in ('prompt','result','output'):
            item.add_argument('--mode',choices=MODES,default='transcript' if verb=='output' else None)
            item.add_argument('--timeout',type=float,default=30 if verb=='prompt' else 0)
            item.add_argument('--cursor',type=int,default=0);item.add_argument('--limit',type=int,default=100)


def operation_exit_code(value):
    record=value.get('result',{}).get('operation',{})
    if record.get('phase')=='uncertain':return 3
    if value.get('status')=='failed' or record.get('execution') in ('failed','cancelled','not_started'):return 2
    return 0


def _exit(output):
    if output['execution'] in ('failed','cancelled'):return 2
    if output['phase']=='uncertain':return 3
    if not output['terminal']:return 124
    if output['mode'] in ('stream','transcript') and not output['retention'].get('history_complete',False):return 3
    if output['retention']['cursor_gap'] or output['retention']['truncated'] or output.get('truncated'):return 3
    return 0


def output_frames(owner,identifier,mode,timeout,cursor=0,limit=100):
    """One polling and diagnostic contract for direct and framed presentation."""
    # Advisory caller wait only; the owner enforces authorization and operation expiry.
    deadline=time.monotonic()+timeout if timeout>0 else None
    yield {'operation_id':identifier}
    def timed_out():
        yield {'stderr':json.dumps(dict(operation_id=identifier,reason='wait_timeout',next_cursor=cursor))+'\n'}
        yield {'exit_code':124}
    while True:
        remaining=deadline-time.monotonic() if deadline is not None else 0
        if deadline is not None and remaining<=0:
            yield from timed_out();return
        output=owner.output(identifier,mode=mode,cursor=cursor,limit=limit,timeout=max(0,min(30,remaining)))
        if deadline is not None and time.monotonic()>=deadline:
            yield from timed_out();return
        yield {'output':output}
        if deadline is not None and time.monotonic()>=deadline:
            yield from timed_out();return
        if mode=='stream' and output.get('text'):yield {'stdout':output['text']}
        elif mode=='transcript':yield {'stdout':json.dumps(output,sort_keys=True)+'\n'}
        elif mode=='final' and output['terminal']:yield {'stdout':output.get('text','')}
        if deadline is not None and time.monotonic()>=deadline:
            yield from timed_out();return
        cursor=output['next_cursor']
        # Terminal status does not discard already-retained pages.
        if mode in ('stream','transcript') and cursor<output['latest_cursor']:
            # The owner already reported completion. Remaining retained pages are
            # untimed inspection, never another wait or a renewed deadline.
            if output['terminal']:deadline=None
            continue
        if output['terminal'] or output['phase']=='uncertain' or deadline is None or time.monotonic()>=deadline:
            code=_exit(output)
            if code:
                reason=output['reason'] or ('native_turn_'+output['execution'] if output['execution'] in ('failed','cancelled') else 'output_incomplete' if output['terminal'] else 'wait_timeout')
                yield {'stderr':json.dumps(dict(operation_id=identifier,reason=reason,next_cursor=cursor,retention=output['retention']))+'\n'}
            yield {'exit_code':code};return


def present(owner,identifier,*,mode,timeout,cursor=0,limit=100):
    """Write shared frames; caller timeout/disconnect never cancels native work."""
    for frame in output_frames(owner,identifier,mode,timeout,cursor,limit):
        if 'stdout' in frame:print(frame['stdout'],end='',flush=True)
        if 'stderr' in frame:print(frame['stderr'],end='',file=sys.stderr,flush=True)
        if 'exit_code' in frame:return frame['exit_code']


def command(args,root):
    from .local_control_service import LocalOperations
    from .local_control_routing import LocalSessionRouter
    try:
        if args.control_verb in ('list','resolve'):
            owner=LocalOperations(root);operation='local.'+args.control_verb
            value=owner.execute(operation,{key:value for key,value in vars(args).items() if key in owner.definitions[operation][2]['properties'] and value is not None})
        else:
            arguments={key:value for key,value in vars(args).items() if key in operation_schemas()['local.'+args.control_verb]['properties'] and value is not None}
            mode=arguments.pop('mode',None)
            if mode:
                # Admission returns its handle first; caller waiting belongs to presentation.
                if args.control_verb=='prompt':
                    submitted=execute('local.prompt',dict(arguments,timeout=0),root)
                    identifier=submitted['result']['operation']['operation_id']
                else:identifier=args.operation_id
                return present(LocalSessionRouter(root),identifier,mode=mode,timeout=args.timeout,cursor=args.cursor,limit=args.limit)
            value=execute('local.'+args.control_verb,arguments,root)
        emit(value, args)
        return operation_exit_code(value)
    except (ValueError,OSError) as error:
        value = {'status':'failed','error':{'code':getattr(error,'code','control_unavailable'),'message':str(error)}}
        if getattr(args,'mode',None):
            print(json.dumps(value), file=sys.stderr)
        else:
            emit(value, args)
        return 2


def receipt_output(envelope,mode='final',*,cursor=0):
    """Present a retained native command result, never a model-token transcript.

    The single stable event is the actual retained receipt/interaction, not an
    invented sequence of native turn lifecycle notifications.
    """
    if mode not in MODES or type(cursor) is not int or not 0<=cursor<=1:
        raise InventoryError('invalid_argument','command receipt mode and cursor0..1 required')
    record=envelope['result']['operation'];result=record.get('result')
    value=dict(operation_id=record['operation_id'],mode=mode,terminal=record['phase']=='terminal',
        execution=record['execution'],phase=record['phase'],reason=record.get('reason'),
        provenance='retained_native_command_receipt',next_cursor=1,
        retention=dict(max_events=1,truncated=False,cursor_gap=False,history_complete=True,status='retained'))
    if mode in ('stream','final'):value['text']=json.dumps(result,sort_keys=True)
    elif mode=='transcript':value['events']=[] if cursor else [dict(sequence=1,
        kind='controller_interaction' if isinstance(result,dict) and result.get('kind')=='controller_interaction' else 'native_command_receipt',
        source='retained_operation_result',operation_id=record['operation_id'],execution=record['execution'],result=result)]
    return value


def receipt_exit_code(value):
    code=2 if value['execution'] in ('failed','cancelled') else 3 if value['phase']=='uncertain' else 0
    return 3 if value['mode']=='silent' and not value['terminal'] else code


def present_receipt(envelope,mode='final',*,cursor=0):
    value=receipt_output(envelope,mode,cursor=cursor)
    if mode in ('stream','final'):print(value['text'],end='',flush=True)
    elif mode=='transcript':print(json.dumps(value,sort_keys=True),flush=True)
    code=receipt_exit_code(value)
    if code:print(json.dumps(dict(operation_id=value['operation_id'],execution=value['execution'],reason=value['reason'] or 'command_interaction_or_failure',result=envelope['result']['operation'].get('result'))),file=sys.stderr)
    return code


# Shared transports need status semantics without invoking CLI printing.
output_exit_code = _exit
