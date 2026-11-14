"""Read-only projection of physical placement and independent logical identities."""
from copy import deepcopy
from .managed_inventory import InventoryError

class Environment:
    def __init__(self,root,*,tabs=None):
        if tabs is None:
            from .controller_tabs import controller_tabs_from_root
            tabs=controller_tabs_from_root(root)
        self.tabs=tabs

    def snapshot(self):
        sessions=self.tabs.execute('tabs.session.list',{})['sessions']
        observed=self.tabs.execute('tabs.list',{})
        family=self.tabs.execute('tabs.family.list',{})
        resources=observed.get('resources',[])
        def tab(row):
            window=row['window'];target=row['lifecycle_target']
            identifier='|'.join(str(target[k]) for k in ('host','environment','workspace'))+'|'+window['window_id']
            return dict(id=identifier,native_id=window['window_id'],name=window.get('name'),target=deepcopy(target),
                panes=[{k:v for k,v in p.items() if k in ('pane_id','pid','process_generation','active','title','current_command','dead')} for p in window.get('panes',[])],
                traits=deepcopy(row.get('traits',{})),links=dict(placement_workspace=target['workspace'],conversation_evidence='traits',agent_bindings='agents.bindings'))
        items=[];assigned=set()
        for session in sessions:
            workspace=session.get('workspace');rows=[row for row in resources if row['target']['workspace']==workspace]
            assigned.update(id(row) for row in rows)
            items.append(dict(id=session['id'],name=session['name'],state=session.get('state','unknown'),
                server=session.get('server'),workspace=workspace,tabs=[tab(row) for row in rows]))
        # Keep observations visible even if saved terminal-session inventory was partial.
        unplaced=[tab(row) for row in resources if id(row) not in assigned]
        return dict(schema_version=1,host=self.tabs.host,environment=self.tabs.environment,
            sessions=items,unplaced_tabs=unplaced,agents=deepcopy(family.get('bots',[])),
            bindings=deepcopy(family.get('bindings',[])),unavailable=observed.get('unavailable',[]),
            grants_authority=False,identity_notes='Placement, lineage and conversation identity are independent; unknown links remain unknown.')

    def children(self,resource_id):
        view=self.snapshot()
        for session in view['sessions']:
            if session['id']==resource_id:return dict(kind='tabs',children=session['tabs'])
            for tab in session['tabs']:
                if tab['id']==resource_id:return dict(kind='panes',children=tab['panes'])
        agents=[a for a in view['agents'] if a.get('parent_bot_id')==resource_id]
        if agents or any(a.get('bot_id')==resource_id for a in view['agents']):return dict(kind='agents',children=agents)
        raise InventoryError('target_not_found','Resource is absent from this environment; refresh exact identity.')

def definitions():
    def invoke(verb,args,root):
        owner=Environment(root)
        return owner.snapshot() if verb=='snapshot' else owner.children(args['resource_id'])
    from functools import partial
    return {f'environment.{verb}':(f'wake_environment_{verb}',
        'Navigate host-owned terminal placement and explicit independent identity links.',
        dict(type='object',properties=({'resource_id':{'type':'string','minLength':1}} if verb=='children' else {}),required=(['resource_id'] if verb=='children' else []),additionalProperties=False),
        partial(invoke,verb),True) for verb in ('snapshot','children')}
