"""Program constructs through the public durable flow owner."""
import tempfile
import unittest
from pathlib import Path

from codex_wake.controller_auth import Actor
from codex_wake.controller_flows import ControllerFlows


def actor():
    return Actor('author','service','client','grant','local://test','wake:controller',
        frozenset({'observe','control'}),[dict(host='host',environment='test',flow_id='program')],10000)


class ProgramNodesTests(unittest.TestCase):
    def test_select_uses_first_matching_case_and_explicit_unknown_path(self):
        with tempfile.TemporaryDirectory() as directory:
            owner=ControllerFlows(Path(directory),host='host',environment='test',
                invoke=lambda *a,**kw:self.fail('selection invoked an effect'),authorize=actor,now=lambda:100)
            definition=dict(id='program',version=1,entry='choose',nodes=[
                dict(id='choose',type='select',cases=[dict(condition=True,then='first'),dict(condition=True,then='second')],default='other',unknown='missing'),
                dict(id='first',type='end',value='first'),dict(id='second',type='end',value='second'),
                dict(id='other',type='end',value='default'),dict(id='missing',type='end',value='unknown')])
            owner.publish(actor(),definition)
            run=owner.start(actor(),'program',1,inputs={},intent='one',binding='caller')
            self.assertEqual(owner.advance(actor(),run['run_id'])['result'],'first')
            definition['version']=2
            definition['nodes'][0]['cases'][0]['condition']=dict(op='eq',left={'ref':'inputs.missing'},right=1)
            owner.publish(actor(),definition)
            run=owner.start(actor(),'program',2,inputs={},intent='two',binding='caller')
            self.assertEqual(owner.advance(actor(),run['run_id'])['result'],'unknown')

    def test_bounded_while_reconciles_original_iteration_and_routes_exhaustion(self):
        from codex_wake.controller_runtime import ControllerRuntime
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=ControllerRuntime(root,now=lambda:100);effects=[];crash=[True]
            def invoke(operation,arguments,**kwargs):
                if operation=='operations.result':
                    return runtime.operation(actor(),operation,arguments,authorize=kwargs['authorize'])
                result=runtime.execute(actor(),operation,dict(arguments,_request=kwargs['request']),
                    authorize=kwargs['authorize'],dispatch=lambda op,args:effects.append(args['index']) or dict(index=args['index']))
                if crash[0]:crash[0]=False;raise SystemExit('caller lost after retained effect')
                return result
            def owner():return ControllerFlows(root,host='host',environment='test',invoke=invoke,authorize=actor,now=lambda:100)
            definition=dict(id='program',version=1,entry='repeat',nodes=[
                dict(id='repeat',type='while',condition=True,max_iterations=3,
                    body=dict(entry='act',nodes=[dict(id='act',type='call',operation='fixture.effect',arguments=dict(index={'ref':'iteration.index'}))]),
                    next='done',exhausted='bound'),dict(id='done',type='end',value='normal'),dict(id='bound',type='end',value='bounded')])
            owner().publish(actor(),definition)
            run=owner().start(actor(),'program',1,inputs={},intent='loop',binding='caller')
            with self.assertRaises(SystemExit):owner().advance(actor(),run['run_id'])
            self.assertEqual(owner().advance(actor(),run['run_id'])['phase'],'executing')
            owner().reconcile(actor(),run['run_id'])
            result=owner().advance(actor(),run['run_id'])
            self.assertEqual((result['phase'],result['result']),('completed','bounded'))
            self.assertEqual(effects,[0,1,2])
            self.assertEqual(owner().advance(actor(),run['run_id']),result)
            self.assertEqual(result['condition_usage']['calls'],3)

    def test_typed_function_output_is_reusable_but_not_a_boolean_condition(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=root/'controller-conditions.json'
            registry.write_text(json.dumps(dict(version=1,functions={'classify@1':dict(kind='deterministic',inputs={'label':'string'},output={'type':'object','properties':{'label':{'type':'string'}},'required':['label'],'additionalProperties':False},value={'label':{'ref':'arguments.label'}})})));registry.chmod(0o600)
            owner=ControllerFlows(root,host='host',environment='test',invoke=lambda *a,**kw:self.fail('pure function invoked effect'),authorize=actor,now=lambda:100)
            definition=dict(id='program',version=1,entry='classify',nodes=[
                dict(id='classify',type='function',function='classify',version=1,arguments={'label':'ready'},next='done'),
                dict(id='done',type='end',value={'ref':'steps.classify.value.label'})])
            owner.publish(actor(),definition);run=owner.start(actor(),'program',1,inputs={},intent='typed',binding='caller')
            result=owner.advance(actor(),run['run_id']);self.assertEqual(result['result'],'ready')
            self.assertEqual(result['steps']['classify']['type'],'object')
            self.assertEqual(result['condition_usage']['calls'],1)
            definition['version']=2;definition['nodes'][0]=dict(id='classify',type='branch',condition=dict(function='classify',version=1,arguments={'label':'ready'}),then='wrong',**{'else':'wrong'},error='done');definition['nodes'] += [dict(id='wrong',type='end',value='wrong')];definition['nodes'][1]['value']='typed-error'
            owner.publish(actor(),definition);run=owner.start(actor(),'program',2,inputs={},intent='predicate',binding='caller')
            result=owner.advance(actor(),run['run_id']);self.assertEqual(result['result'],'typed-error')
            self.assertEqual(result['steps']['classify']['reason'],'semantic_boolean_type')

    def test_native_typed_output_is_validated_and_retains_its_usage(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=root/'controller-conditions.json'
            registry.write_text(json.dumps(dict(version=1,functions={'classify@1':dict(kind='semantic',inputs={},output={'type':'object','properties':{'label':{'type':'string'}},'required':['label'],'additionalProperties':False},effects='action',tools='inherited',profile='owned',expected_target={'conversation_id':'existing'},prompt='Classify the input.',estimated_tokens=4)})));registry.chmod(0o600)
            def owner():return ControllerFlows(root,host='host',environment='test',invoke=lambda *a,**kw:self.fail('unrelated effect'),authorize=actor,now=lambda:100)
            definition=dict(id='program',version=1,entry='classify',limits=dict(max_tokens=8,metering='estimate_opt_in'),nodes=[
                dict(id='classify',type='function',function='classify',version=1,arguments={},next='done',error='invalid'),
                dict(id='done',type='end',value={'ref':'steps.classify.value.label'}),dict(id='invalid',type='end',value='schema-error')])
            owner().publish(actor(),definition)
            answer=[{'label':'ready'}];submissions=[]
            def native(actor,operation,args,**kwargs):
                kwargs['authorize']()
                if operation=='sessions.prompt':
                    submissions.append(args['prompt']);return dict(result=dict(operation=dict(phase='waiting',execution='queued',result={})))
                return dict(result=dict(operation=dict(phase='terminal',execution='completed',answer={'text':json.dumps({'value':answer[0]})})))
            with patch('codex_wake.controller_condition_native.ControllerFlowSessions._context',return_value={}),patch('codex_wake.controller_condition_native.ControllerFlowSessions.execute',side_effect=native):
                run=owner().start(actor(),'program',1,inputs={},intent='native-valid',binding='caller')
                self.assertEqual(owner().advance(actor(),run['run_id'])['result'],'ready')
                answer[0]={'label':7}
                run=owner().start(actor(),'program',1,inputs={},intent='native-invalid',binding='caller')
                result=owner().advance(actor(),run['run_id'])
            self.assertEqual(result['result'],'schema-error')
            self.assertEqual(result['steps']['classify']['reason'],'function_output_type')
            self.assertEqual(result['condition_usage'],dict(calls=1,tokens=4))
            self.assertEqual(len(submissions),2)

    def test_while_rechecks_condition_and_nested_effects_cannot_bypass_exact_limits(self):
        from codex_wake.managed_inventory import InventoryError
        with tempfile.TemporaryDirectory() as directory:
            effects=[]
            owner=ControllerFlows(Path(directory),host='host',environment='test',
                invoke=lambda operation,arguments,**kwargs:effects.append(arguments['index']) or {},authorize=actor,now=lambda:100)
            definition=dict(id='program',version=1,entry='repeat',nodes=[
                dict(id='repeat',type='while',condition=dict(op='lt',left={'ref':'iteration.index'},right=2),max_iterations=3,
                    body=dict(entry='act',nodes=[dict(id='act',type='call',operation='fixture.effect',arguments=dict(index={'ref':'iteration.index'}))]),
                    next='done',unknown='unknown'),dict(id='done',type='end',value='normal'),dict(id='unknown',type='end',value='unknown')])
            owner.publish(actor(),definition);run=owner.start(actor(),'program',1,inputs={},intent='normal',binding='caller')
            self.assertEqual(owner.advance(actor(),run['run_id'])['result'],'normal');self.assertEqual(effects,[0,1])
            definition['version']=2;definition['nodes'][0]['condition']=dict(op='eq',left={'ref':'inputs.missing'},right=1)
            owner.publish(actor(),definition);run=owner.start(actor(),'program',2,inputs={},intent='missing',binding='caller')
            self.assertEqual(owner.advance(actor(),run['run_id'])['result'],'unknown');self.assertEqual(effects,[0,1])
            definition['version']=3;definition['limits']=dict(max_tokens=0)
            owner.publish(actor(),definition)
            with self.assertRaises(InventoryError) as caught:owner.start(actor(),'program',3,inputs={},intent='exact',binding='caller')
            self.assertEqual(caught.exception.code,'unsupported_flow_limits')

    def test_semantic_action_requires_prompt_and_wait_actions_before_dispatch(self):
        import json
        from dataclasses import replace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=root/'controller-conditions.json'
            registry.write_text(json.dumps(dict(version=1,functions={'judge@1':dict(kind='semantic',inputs={},effects='action',estimated_tokens=4)})));registry.chmod(0o600)
            restricted=replace(actor(),actions=frozenset({'programs.runs.advance'}))
            owner=ControllerFlows(root,host='host',environment='test',invoke=lambda *a,**kw:self.fail('unrelated operation'),authorize=lambda:restricted,now=lambda:100)
            definition=dict(id='program',version=1,entry='judge',limits=dict(max_tokens=4,metering='estimate_opt_in'),nodes=[dict(id='judge',type='branch',condition=dict(function='judge',version=1,arguments={}),then='wrong',**{'else':'wrong'},error='denied'),dict(id='wrong',type='end',value='wrong'),dict(id='denied',type='end',value='denied')])
            owner.publish(restricted,definition);run=owner.start(restricted,'program',1,inputs={},intent='restricted',binding='caller')
            with patch('codex_wake.controller_condition_native.invoke',side_effect=AssertionError('unauthorized native action')) as native:
                result=owner.advance(restricted,run['run_id'])
            self.assertEqual(result['result'],'denied');self.assertEqual(result['steps']['judge']['reason'],'insufficient_scope');self.assertEqual(native.call_count,0)
