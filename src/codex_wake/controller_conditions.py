"""Typed condition composition and accounting within the existing flow run.

Registry documents are trusted host data, never executable code. Native semantic
work uses the existing account/profile and operation owners; this ledger grants
no additional resources and cannot assert native exact metering without proof.
"""
import hashlib
import json
import math
from pathlib import Path
from .a2a_bus import private_path
from .managed_inventory import InventoryError

class ConditionPending(Exception):
    """An existing semantic turn needs another observation, never a resubmission."""


DEFAULTS=dict(max_calls=64,max_depth=8,max_seconds=300,max_tokens=1024,metering='exact')


def limits(value,parent=None):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):
        raise InventoryError('invalid_condition_limits','supported finite nested limits required')
    result=dict(parent or DEFAULTS)
    for key,item in value.items():
        if key=='metering':
            if item not in ('exact','estimate_opt_in'):raise InventoryError('invalid_condition_limits','explicit metering policy required')
            if parent and parent['metering']=='exact' and item!='exact':raise InventoryError('invalid_condition_limits','child cannot weaken exact metering')
            result[key]=item
        else:
            if type(item) not in (int,float) or not math.isfinite(item) or item<0 or (key!='max_seconds' and type(item) is not int):
                raise InventoryError('invalid_condition_limits','finite nonnegative bounds required')
            result[key]=min(result[key],item)
    return result


def validate_condition(value,depth=0):
    if depth>16:raise InventoryError('invalid_condition','condition syntax exceeds depth16')
    if type(value) is bool:return
    if not isinstance(value,dict):raise InventoryError('invalid_condition','typed condition required')
    if value.get('op') in ('and','or'):
        if set(value)-{'op','operands','parallel'} or value.get('parallel',False) is not False:
            raise InventoryError('unsupported_parallel_condition','parallel predicates require a qualified scheduler')
        if not isinstance(value.get('operands'),list) or not 1<=len(value['operands'])<=32:
            raise InventoryError('invalid_condition','bounded ordered operands required')
        for child in value['operands']:validate_condition(child,depth+1)
        return
    if 'function' in value:
        if set(value)-{'function','version','arguments','limits'} or not isinstance(value['function'],str) or not value['function'] or type(value.get('version')) is not int or value['version']<1 or not isinstance(value.get('arguments'),dict):
            raise InventoryError('invalid_condition','named versioned typed function call required')
        limits(value.get('limits',{}))
        return
    if set(value)!={'op','left','right'} or value['op'] not in ('eq','ne','lt','lte','gt','gte'):
        raise InventoryError('invalid_condition','typed comparison required')


class Conditions:
    def __init__(self,root,*,registry=None):
        if registry is None:
            path=Path(root)/'controller-conditions.json'
            private_path(path)
            if path.stat().st_size>262144:raise InventoryError('configuration_unavailable','bounded condition registry required')
            config=json.loads(path.read_text())
            if config.get('version')!=1:raise InventoryError('configuration_unavailable','unsupported registry version')
            registry=config['functions']
        if not isinstance(registry,dict):raise InventoryError('configuration_unavailable','function registry required')
        self.registry=registry
        self.revision=hashlib.sha256(json.dumps(registry,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def evaluate(self,expression,state,*,resolve,compare,save,now,semantic=None,evaluation_id=None,resume=False,predicate=True):
        overall=limits(state.get('condition_limits',{}))
        usage=state.setdefault('condition_usage',dict(calls=0,tokens=0))
        retained={tuple(item['path']):item for item in state.get('condition_trace',[])
                  if resume and item.get('evaluation_id')==evaluation_id and isinstance(item.get('path'),list)}
        frames=[(overall,0,0,state['created_at'])]
        def result(status,value=None,**extra):return dict(type='boolean',status=status,value=value,**extra)
        def local(value,arguments):
            if isinstance(value,dict) and set(value)=={'ref'} and value['ref'].startswith('arguments.'):
                return arguments.get(value['ref'].split('.',1)[1])
            if isinstance(value,dict):return {k:local(v,arguments) for k,v in value.items()}
            if isinstance(value,list):return [local(v,arguments) for v in value]
            return value
        def run(value,parent,depth=0,path=()):
            previous=retained.get(path)
            if previous and 'outcome' in previous:return dict(previous['outcome'],function=previous['function'])
            if not previous and any(now()-began>=bounds['max_seconds'] for bounds,calls,tokens,began in frames):
                return result('timeout',reason='condition_time_limit')
            if type(value) is bool:return result('known',value)
            if value.get('op') in ('and','or'):
                trace=[];answer=True if value['op']=='and' else False
                for index,child in enumerate(value['operands']):
                    item=run(child,parent,depth,path+(index,))
                    if item['status']=='known' and type(item.get('value')) is not bool:
                        item=result('error',reason='semantic_boolean_type')
                    trace.append(item)
                    stop=item['status']!='known' or (value['op']=='and' and item['value'] is False) or (value['op']=='or' and item['value'] is True)
                    answer=item['value']
                    if stop:
                        trace.extend(result('unevaluated',reason='short_circuit' if item['status']=='known' else 'prior_'+item['status']) for _ in value['operands'][index+1:])
                        return result(item['status'],answer,trace=trace)
                return result('known',answer,trace=trace)
            if 'function' not in value:
                answer=compare(value)
                return result('unknown' if answer is None else 'known',answer)
            nested=limits(value.get('limits',{}),parent)
            if not previous and (depth>=nested['max_depth'] or any(usage['calls']-calls>=bounds['max_calls'] for bounds,calls,tokens,began in frames)):
                return result('error',reason='condition_call_limit')
            key=value['function']+'@'+str(value['version'])
            function=self.registry.get(key)
            if not isinstance(function,dict):return result('error',reason='function_version_not_found',function=key)
            from .controller_function_results import output_schema,typed_outcome
            try:schema=output_schema(function)
            except InventoryError as error:return result('error',reason=error.code,function=key)
            nested=limits(function.get('limits',{}),nested)
            if not previous and (depth>=nested['max_depth'] or nested['max_calls']<=0 or any(usage['calls']-calls>=bounds['max_calls'] for bounds,calls,tokens,began in frames)):
                return result('error',reason='condition_call_limit')
            args=resolve(value['arguments'])
            types={'string':str,'boolean':bool,'integer':int,'number':(int,float),'object':dict,'array':list}
            declared=function.get('inputs',{})
            if not isinstance(args,dict) or set(args)!=set(declared) or any(t not in types or type(args[k]) not in ((types[t],) if isinstance(types[t],type) else types[t]) for k,t in declared.items()):
                return result('error',reason='function_argument_type',function=key)
            if function.get('effects','observe') not in ('observe','action'):
                return result('error',reason='function_effect_declaration',function=key)
            if previous:
                receipt=previous
                if receipt.get('function')!=key or receipt.get('arguments')!=args or receipt.get('limits')!=nested:
                    raise InventoryError('condition_continuation_invalid','retained function admission differs from pinned evaluation')
                frame=receipt['frame']
                frames.append((nested,frame['calls'],frame['tokens'],frame['began']))
            else:
                frame=dict(calls=usage['calls'],tokens=usage['tokens'],began=now())
                frames.append((nested,frame['calls'],frame['tokens'],frame['began']))
                usage['calls']+=1
                receipt=dict(function=key,depth=depth+1,effects=function.get('effects','observe'),status='admitted',value=None,
                             evaluation_id=evaluation_id,path=list(path),arguments=args,limits=nested,frame=frame,output_schema=schema)
                state.setdefault('condition_trace',[]).append(receipt)
                save()  # durable admission before nested calls, including failures
            if function.get('kind')=='deterministic':
                if 'value' in function:
                    outcome=dict(type=schema['type'],status='known',value=local(function['value'],args))
                else:
                    expression=local(function['expression'],args)
                    validate_condition(expression)
                    outcome=run(expression,nested,depth+1,path+(-1,))
            elif function.get('kind')=='semantic' and semantic:
                if 'semantic_outcome' in receipt:
                    outcome=receipt['semantic_outcome']
                else:
                    if previous and not receipt.get('native_operation_id'):
                        raise ConditionPending('original semantic operation handle unavailable')
                    remaining=receipt.get('reserved_tokens')
                    if remaining is None:
                        remaining=min(bounds['max_tokens']-(usage['tokens']-tokens) for bounds,calls,tokens,began in frames)
                        estimate=function.get('estimated_tokens',remaining)
                        remaining=min(remaining,estimate) if type(estimate) is int and estimate>0 else 0
                        if remaining>0:
                            usage['tokens']+=remaining;receipt['reserved_tokens']=remaining;save()
                    if remaining<=0:outcome=result('error',reason='condition_token_limit')
                    else:
                        try:
                            bounded=dict(nested,max_seconds=max(0,min(bounds['max_seconds']-(now()-began) for bounds,calls,tokens,began in frames)))
                            outcome=semantic(function,args,bounded,remaining,receipt)
                            consumed=outcome.get('usage',{}).get('tokens')
                            if type(consumed) is not int or not 0<=consumed<=remaining:
                                outcome=result('error',reason='semantic_usage_unavailable')
                            else:
                                usage['tokens']-=remaining-consumed
                                receipt['charged_tokens']=consumed
                        except ConditionPending:
                            raise
                        except Exception as error:
                            outcome=result('timeout' if isinstance(error,TimeoutError) else 'error',reason=getattr(error,'code','semantic_effect_uncertain'))
                    receipt['semantic_outcome']=outcome;save()
            else:outcome=result('error',reason='unsupported_function_kind')
            if outcome.get('status')=='delegate':
                call=outcome.get('call')
                key_requested=str(call.get('function'))+'@'+str(call.get('version')) if isinstance(call,dict) else ''
                if key_requested not in function.get('callees',[]) or not isinstance(call,dict) or set(call)!={'function','version','arguments'}:
                    outcome=result('error',reason='semantic_callee_not_allowed')
                else:
                    validate_condition(call)
                    receipt['delegation']=call
                    outcome=run(call,nested,depth+1,path+(-1,))
            outcome=typed_outcome(outcome,schema)
            frames.pop()
            receipt.update({key:value for key,value in outcome.items() if key!='function'});receipt['outcome']=outcome;save()
            return dict(outcome,function=key)
        outcome=run(expression,overall)
        if predicate and outcome.get('status')=='known' and type(outcome.get('value')) is not bool:
            return result('error',reason='semantic_boolean_type')
        return outcome
