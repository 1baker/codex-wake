"""Resolve host-owned new-tab defaults before authorization and intent freezing."""
from pathlib import Path
from .managed_inventory import InventoryError


def prepare(tabs,arguments):
    payload=dict(arguments)
    shell = payload.pop('shell', False)
    saved_defaults = payload.pop('saved_defaults', False)
    if (type(shell) is not bool or type(saved_defaults) is not bool
            or (shell and (saved_defaults or payload.get('profile') or 'argv' in payload))):
        raise InventoryError('invalid_argument', 'Choose the default shell, saved defaults, a profile, or explicit argv.')
    root=getattr(tabs,'root',None)
    if root is not None and (Path(root)/'terminal-sessions/registry.json').is_file():
        from .terminal_sessions import TerminalSessions
        records=TerminalSessions(tabs.root,tabs=tabs).inventory()
        session=next((v for v in records if v.get('workspace')==payload.get('workspace')),None)
        defaults=session.get('defaults',{}) if session else {}
        if 'cwd' not in payload and defaults.get('cwd'):payload['cwd']=defaults['cwd']
        if saved_defaults and not payload.get('profile') and 'argv' not in payload:
            if defaults.get('profile'):payload['profile']=defaults['profile']
            elif defaults.get('argv'):payload['argv']=list(defaults['argv'])
    if payload.get('profile') and 'argv' in payload:raise InventoryError('invalid_argument','Choose a profile or an explicit command argv, not both.')
    return payload


def session_profile(tabs,operation,arguments):
    """Identify the profile a session-opening operation would actually launch."""
    if not operation.startswith('tabs.session.') or not getattr(tabs,'root',None):return None
    from .terminal_sessions import TerminalSessions
    owner=TerminalSessions(tabs.root,tabs=tabs);verb=operation.rsplit('.',1)[1]
    if verb=='open':
        record=owner.resolve(arguments.get('session'),server=arguments.get('server'))
        return None if record['state']=='running' else record.get('defaults',{}).get('profile')
    if verb not in ('create','ensure') or not arguments.get('start',verb=='ensure'):return None
    selected=owner.creation_selection(arguments,ensure=verb=='ensure')
    # The journal and executor use this same selected server/backend. Registry
    # generation fencing rejects later edits to any saved profile definition.
    arguments['server']=selected['server'];arguments['backend']=selected['backend']
    if verb=='ensure' and selected['existing']:
        record=selected['existing'][0]
        return None if record['state']=='running' else record.get('defaults',{}).get('profile')
    return arguments.get('defaults',{}).get('profile')
