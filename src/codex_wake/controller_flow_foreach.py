"""Snapshot foreach membership into the run's existing immutable execution plan."""
import hashlib
from .managed_inventory import InventoryError


def validate(node):
    from .controller_conditions import limits
    if 'limits' in node:limits(node['limits'])
    if node.get('mode') not in ('new_session', 'sequential', 'fork'):
        raise InventoryError('unsupported_session_mode', 'explicit qualified foreach session mode required')
    if not isinstance(node.get('profile'), str) or not node['profile'] or not isinstance(node.get('expected_target'), dict):
        raise InventoryError('invalid_flow', 'foreach requires a named host session profile and pinned target')
    if 'items' not in node or 'prompt' not in node:
        raise InventoryError('invalid_flow', 'foreach requires explicit membership and prompt data')
    concurrency = node.get('parallelism', 1)
    if type(concurrency) is not int or not 1 <= concurrency <= 8 or (node['mode'] == 'sequential' and concurrency != 1):
        raise InventoryError('unsupported_parallelism', 'concurrency must be1..8; same-session prompts remain sequential')
    if node.get('join', 'all_success') not in ('all_success', 'all_complete'):
        raise InventoryError('unsupported_join', 'explicit qualified join policy required')
    if node['mode'] in ('sequential', 'fork') and not node['expected_target'].get('conversation_id'):
        raise InventoryError('invalid_flow', 'sequential prompts require an exact existing conversation')


def expand(definition, state, resolve, unknown):
    starts, expansions, memberships = {}, {}, {}
    for node in definition['nodes']:
        if node['type'] != 'foreach':
            continue
        validate(node)
        members = resolve(node['items'], state)
        if members is unknown or not isinstance(members, list) or len(members) > 32:
            raise InventoryError('invalid_membership', 'foreach requires a snapshot of at most32 input members')
        memberships[node['id']] = members
        prefix = 'each_' + hashlib.sha256(node['id'].encode()).hexdigest()[:16]
        generated, results = [], []
        def ref(path):
            return {'ref': 'steps.' + path}
        if members and node['mode'] == 'fork':
            generated.append(dict(id=prefix+'_checkpoint',type='call',operation='sessions.checkpoint',
                arguments=dict(profile=node['profile'],expected_target=node['expected_target'])))
        concurrency = node.get('parallelism', 1)
        for offset in range(0,len(members),concurrency):
            waits = []
            for index in range(offset,min(offset+concurrency,len(members))):
                member = members[index]
                base = prefix + '_' + str(index)
                def item_value(value):
                    if isinstance(value,dict) and set(value)=={'ref'} and value['ref'] in ('item','index'):
                        return member if value['ref']=='item' else index
                    if isinstance(value,dict):return {key:item_value(item) for key,item in value.items()}
                    if isinstance(value,list):return [item_value(item) for item in value]
                    return value
                prompt = resolve(item_value(node['prompt']),state)
                if prompt is unknown or not isinstance(prompt,str) or not 0<len(prompt.encode())<=32768:
                    raise InventoryError('invalid_prompt','foreach prompts must resolve to bounded text before execution')
                target = node['expected_target']
                if node['mode'] in ('new_session','fork'):
                    action = 'fork' if node['mode']=='fork' else 'create'
                    arguments = dict(profile=node['profile'],expected_target=target)
                    if action=='fork':arguments['checkpoint']=ref(prefix+'_checkpoint.result.checkpoint')
                    generated.append(dict(id=base+'_'+action,type='call',operation='sessions.'+action,arguments=arguments))
                    target = ref(base+'_'+action+'.result.operation.result.target')
                generated.append(dict(id=base+'_prompt',type='call',operation='sessions.prompt',
                    arguments=dict(profile=node['profile'],expected_target=target,prompt=prompt)))
                waits.append(dict(id=base+'_wait',type='wait',operation='sessions.wait',timeout=0,
                    operation_id=ref(base+'_prompt.result.operation.operation_id')))
                results.append(dict(index=index,member=member,target=target,result=ref(base+'_wait.result.operation')))
            generated.extend(waits)
        if 'limits' in node or 'max_tokens' in definition.get('limits',{}):
            from .controller_conditions import limits
            bounds=limits(node.get('limits',{}),state['condition_limits'])
            if (set(node.get('limits',{})) & {'max_tokens','max_seconds'} or 'max_tokens' in definition.get('limits',{})) and bounds['metering']!='estimate_opt_in':
                raise InventoryError('unsupported_iteration_limits','native exact per-iteration bounds are unqualified; explicit estimate opt-in required')
            for index in range(len(members)):
                identifier=node['id']+'.'+str(index)
                state.setdefault('iteration_frames',{})[identifier]=dict(foreach=node['id'],index=index,limits=bounds,
                    phase='pending',started_at=None,usage=dict(calls=0,tokens=0),token_estimate='max_tokens' in node.get('limits',{}) or 'max_tokens' in definition.get('limits',{}),enforcement='host_admission_and_owned_cancellation; native_exact_unqualified')
                for item in generated:
                    if item['id'].startswith(prefix+'_'+str(index)+'_'):item['iteration_id']=identifier
        starts[node['id']] = generated[0]['id'] if generated else node['id']
        for index,item in enumerate(generated):
            item['next'] = generated[index+1]['id'] if index+1<len(generated) else node['id']
        generated.append(dict(id=node['id'],type='collect',value=dict(mode=node['mode'],items=results),
            join=node.get('join','all_success'),next=node.get('next')))
        expansions[node['id']] = generated
    nodes = []
    original_ids = {node['id'] for node in definition['nodes']}
    for node in definition['nodes']:
        if node['type'] == 'foreach':
            generated = expansions[node['id']]
            if any(item['id'] in original_ids for item in generated[:-1]):
                raise InventoryError('invalid_flow', 'generated foreach node identity collides with definition')
            generated[-1]['next'] = starts.get(node.get('next'), node.get('next'))
            nodes.extend(generated)
        else:
            copied = dict(node)
            for edge in ('next', 'then', 'else', 'unknown', 'error', 'timeout'):
                if edge in copied:
                    copied[edge] = starts.get(copied[edge], copied[edge])
            nodes.append(copied)
    if len(nodes) > 1024:
        raise InventoryError('flow_capacity', 'expanded foreach plan exceeds1024 bounded nodes')
    return dict(definition, entry=starts.get(definition['entry'], definition['entry']), nodes=nodes), memberships
