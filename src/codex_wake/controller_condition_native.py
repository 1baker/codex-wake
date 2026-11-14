"""Typed semantic predicates through supported session prompt/wait operations.

No invented native RPC or new execution owner. Exact native budget enforcement is
not qualified, so semantic work requires explicit conservative-estimate policy.
"""
import json
import time
from .controller_flow_sessions import ControllerFlowSessions
from .managed_inventory import InventoryError
from .controller_conditions import ConditionPending


def invoke(root,actor,function,arguments,bounds,tokens,receipt,*,authorize,request_id,binding):
    if bounds['metering']!='estimate_opt_in':
        raise InventoryError('unsupported_condition_metering','existing native turn API has no qualified exact token/time enforcement; no turn submitted')
    target=function.get('expected_target')
    if not isinstance(target,dict) or not target.get('conversation_id'):
        raise InventoryError('invalid_argument','semantic function requires a pinned existing private conversation')
    if function.get('effects','observe')!='action':
        raise InventoryError('unsupported_observation_tool_policy','native sandbox alone cannot deny external MCP/app tools; observation-only semantic dispatch is unqualified')
    if function.get('tools')!='inherited':
        raise InventoryError('unsupported_condition_tools','semantic action requires explicit inherited native tools; narrower per-turn allowlists are unqualified')
    receipt['tools']='inherited'
    deadline=time.monotonic()+bounds['max_seconds']
    original_authorize=authorize
    def authorize():
        if time.monotonic()>=deadline:raise TimeoutError('condition admission deadline expired')
        return original_authorize()
    owner=ControllerFlowSessions(root)
    profile=owner._context(actor,function['profile'],target,authorize,'control')
    rubric=function.get('prompt')
    if not isinstance(rubric,str) or not 0<len(rubric.encode())<=16384:
        raise InventoryError('configuration_unavailable','bounded host-authored semantic predicate required')
    receipt.update(authority='inherited',target=target,metering='estimate_opt_in',enforcement='estimate_only_no_native_stop',operation_id=request_id)
    from .controller_function_results import output_schema
    schema=output_schema(function);receipt['output_schema']=schema
    prompt=rubric+'\nDeclared output schema: '+json.dumps(schema,sort_keys=True)+'\nTyped input: '+json.dumps(arguments,sort_keys=True)+'\nReturn only JSON {"value": RESULT} matching the declared output schema. If evidence is insufficient return {"status":"unknown"}. You may request one host-allowed nested callee with JSON {"call":{"function":"name","version":1,"arguments":{}}}; no other execution directives are accepted.'
    request=dict(operation_id=request_id,idempotency_key=request_id,correlation_id=request_id,binding=binding,target=target)
    usage=dict(tokens=tokens,kind='estimate',enforcement='estimate_only_no_native_stop')
    def stop_timeout():
        # Cleanup retains the original grant and exact native owner handle. The
        # expired admission deadline stops new work, never blocks owned cleanup.
        try:
            cancelled=owner.execute(actor,'sessions.cancel',dict(operation_id=request_id),authorize=original_authorize)['result']['operation']
            confirmed=cancelled.get('cancellation')=='confirmed' and cancelled.get('phase')=='terminal'
            receipt.update(limit_cancellation='confirmed' if confirmed else 'uncertain',
                native_execution=cancelled.get('execution','unknown'),native_phase=cancelled.get('phase'),
                cancellation_request=cancelled.get('cancellation','uncertain'),hard_stop_claim=False)
        except Exception as error:
            receipt.update(limit_cancellation='uncertain',cancellation_error=getattr(error,'code','cleanup_uncertain'),hard_stop_claim=False)
        return dict(type='boolean',status='timeout',value=None,usage=usage,operation_id=request_id)
    try:
        submitted=owner.execute(actor,'sessions.prompt',dict(profile=function['profile'],expected_target=target,prompt=prompt,_request=request),authorize=authorize)
        operation=submitted['result']['operation']
        receipt['native_phase']=operation['phase']
        receipt['native_reason']=operation.get('reason')
        if operation['phase'] not in ('terminal','waiting') or not isinstance(operation.get('result'),dict):
            raise ConditionPending('native predicate turn submission uncertain; observe original operation only')
        waited=owner.execute(actor,'sessions.wait',dict(operation_id=request_id,timeout=max(0,min(30,deadline-time.monotonic()))),authorize=authorize)
        record=waited['result']['operation']
        receipt['native_execution']=record.get('execution','unknown')
    except TimeoutError:
        return stop_timeout()
    if waited['result'].get('wait',{}).get('status')=='timeout':
        return stop_timeout()
    if record.get('phase')!='terminal' or record.get('execution') not in ('completed','failed','cancelled'):
        raise ConditionPending('native predicate turn result uncertain; observe original operation only')
    return _outcome(record,usage,request_id,schema)


def _outcome(record,usage,request_id,schema=None):
    from .controller_function_results import typed_outcome
    schema=schema or {"type":"boolean"}
    if record.get('execution')!='completed':
        return dict(type='boolean',status='error',value=None,usage=usage,operation_id=request_id)
    try:
        text=record['answer']['text']
        if len(text.encode())>32768:raise ValueError()
        value=json.loads(text)
    except (ValueError,KeyError,TypeError):value=None
    if isinstance(value,dict) and set(value)=={'value'}:
        return typed_outcome(dict(status='known',value=value['value'],usage=usage,operation_id=request_id),schema)
    if isinstance(value,dict) and set(value)=={'call'}:
        return dict(type='boolean',status='delegate',value=None,call=value['call'],usage=usage,operation_id=request_id)
    if value=={'status':'unknown'}:
        return dict(type='boolean',status='unknown',value=None,usage=usage,operation_id=request_id)
    return dict(type='boolean',status='error',value=None,reason='semantic_boolean_type',usage=usage,operation_id=request_id)


def recover(root,actor,receipt,*,authorize):
    """Observe the original durable owner only; no prompt or resource admission."""
    from .controller_conditions import ConditionPending
    identifier=receipt.get('native_operation_id')
    if not isinstance(identifier,str) or not identifier:
        raise ConditionPending('original semantic operation handle unavailable')
    try:
        waited=ControllerFlowSessions(root).execute(actor,'sessions.wait',
            dict(operation_id=identifier,timeout=0),authorize=authorize)
    except InventoryError as error:
        if error.code=='operation_not_found':
            raise ConditionPending('original semantic operation unavailable') from None
        raise
    record=waited['result']['operation']
    receipt.update(native_phase=record.get('phase'),native_execution=record.get('execution','unknown'))
    if record.get('phase')!='terminal' or record.get('execution') not in ('completed','failed','cancelled'):
        raise ConditionPending('original semantic operation pending or uncertain')
    usage=dict(tokens=receipt['reserved_tokens'],kind='estimate',enforcement='estimate_only_no_native_stop')
    return _outcome(record,usage,identifier,receipt.get('output_schema'))
