"""Lower bounded structured control into the existing durable flow graph."""
import hashlib
from .managed_inventory import InventoryError


def validate_select(node):
    from .controller_conditions import validate_condition
    cases=node.get('cases')
    if not isinstance(cases,list) or not 1<=len(cases)<=32 or 'default' not in node:
        raise InventoryError('invalid_flow','select requires1..32 ordered cases and an explicit default')
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'condition','then'}:
            raise InventoryError('invalid_flow','each select case requires condition and then')
        validate_condition(case['condition'])


def edges(node):
    if node['type']=='select':
        return [case['then'] for case in node['cases']]+[node.get(key) for key in ('default','unknown','error','timeout')]
    if node['type']=='function':return [node.get(key) for key in ('next','unknown','error','timeout')]
    if node['type']=='while':return [node.get(key) for key in ('next','unknown','error','timeout','exhausted')]
    return [node.get(key) for key in (('then','else','unknown','error','timeout') if node['type']=='branch' else ('next',))]


def expand(definition):
    nodes=[]
    originals={node['id'] for node in definition['nodes']}
    for node in definition['nodes']:
        if node['type']!='select':
            nodes.append(dict(node));continue
        prefix='select_'+hashlib.sha256(node['id'].encode()).hexdigest()[:16]
        identifiers=[node['id']]+[prefix+'_'+str(i) for i in range(1,len(node['cases']))]
        if any(identifier in originals for identifier in identifiers[1:]):
            raise InventoryError('invalid_flow','generated select identity collides with a definition node')
        for index,case in enumerate(node['cases']):
            branch=dict(id=identifiers[index],type='branch',condition=case['condition'],then=case['then'],
                **{'else':identifiers[index+1] if index+1<len(identifiers) else node['default']})
            branch.update({key:node[key] for key in ('unknown','error','timeout') if key in node})
            nodes.append(branch)
    return expand_loops(dict(definition,nodes=nodes))


def validate_while(node):
    from .controller_conditions import validate_condition
    from .controller_flows import FlowDefinition
    if type(node.get('max_iterations')) is not int or not 1<=node['max_iterations']<=64:
        raise InventoryError('invalid_flow','while requires a finite max_iterations from1 to64')
    if 'condition' not in node:
        raise InventoryError('invalid_flow','while requires a typed condition')
    validate_condition(node['condition'])
    body=node.get('body')
    if not isinstance(body,dict) or set(body)!={'entry','nodes'}:
        raise InventoryError('invalid_flow','while body requires entry and nodes')
    def bounded(nodes,depth=0):
        if depth>8:raise InventoryError('invalid_flow','structured loop nesting exceeds8')
        for child in nodes if isinstance(nodes,list) else []:
            if isinstance(child,dict) and child.get('type')=='while':bounded(child.get('body',{}).get('nodes'),depth+1)
    bounded(body['nodes'])
    FlowDefinition.compile(dict(id='while-body',version=1,**body))


def _references(value,mapping,index):
    if isinstance(value,dict) and set(value)=={'ref'}:
        ref=value['ref']
        if ref=='iteration.index':return index
        if isinstance(ref,str) and ref.startswith('steps.'):
            parts=ref.split('.',2)
            if len(parts)>1 and parts[1] in mapping:
                return {'ref':'steps.'+mapping[parts[1]]+('.'+parts[2] if len(parts)==3 else '')}
        return value
    if isinstance(value,dict):return {key:_references(item,mapping,index) for key,item in value.items()}
    if isinstance(value,list):return [_references(item,mapping,index) for item in value]
    return value


def expand_loops(definition):
    """Each admitted iteration has a distinct frozen node/effect identity."""
    originals={node['id'] for node in definition['nodes']};nodes=[]
    for node in definition['nodes']:
        if node['type']!='while':nodes.append(dict(node));continue
        prefix='while_'+hashlib.sha256(node['id'].encode()).hexdigest()[:16]
        body=expand(dict(id='while-body',version=1,**node['body']))
        maximum=node['max_iterations'];previous={}
        checks=[node['id']]+[prefix+'_check_'+str(i) for i in range(1,maximum+1)]
        hold=prefix+'_exhausted'
        for index in range(maximum+1):
            mapping={child['id']:prefix+'_'+str(index)+'_'+str(j) for j,child in enumerate(body['nodes'])}
            condition=_references(node['condition'],previous,index)
            then=mapping[body['entry']] if index<maximum else node.get('exhausted',hold)
            check=dict(id=checks[index],type='branch',condition=condition,then=then,**{'else':node.get('next')})
            check.update({key:node[key] for key in ('unknown','error','timeout') if key in node});nodes.append(check)
            if index==maximum:break
            for child in body['nodes']:
                copied=_references(child,mapping,index);copied['id']=mapping[child['id']]
                if copied['type']=='end':copied['type']='value';copied['next']=checks[index+1]
                elif copied['type']=='branch':
                    for edge in ('then','else','unknown','error','timeout'):
                        if edge in copied:copied[edge]=mapping.get(child[edge],child[edge])
                elif copied['type']!='hold':
                    copied['next']=mapping.get(child.get('next'),checks[index+1])
                    for edge in ('unknown','error','timeout'):
                        if edge in copied:copied[edge]=mapping.get(child[edge],child[edge])
                nodes.append(copied)
            previous=mapping
            if len(nodes)>1024:raise InventoryError('flow_capacity','expanded structured plan exceeds1024 nodes')
        if 'exhausted' not in node:nodes.append(dict(id=hold,type='hold',reason='while_iteration_limit'))
        generated=[child['id'] for child in nodes if child['id'].startswith(prefix)]
        if any(identifier in originals for identifier in generated):raise InventoryError('invalid_flow','generated while identity collides with a definition node')
    if len(nodes)>1024:raise InventoryError('flow_capacity','expanded structured plan exceeds1024 nodes')
    return dict(definition,nodes=nodes)
