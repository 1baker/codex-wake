"""Operator-private consent delegation; identity remains distinct from the owner."""
import json
import math
from .controller_auth import AuthError,digest


def covers(target, allowed):
    return any(all(target.get(k)==v for k,v in boundary.items()) for boundary in allowed)


def validate_delegations(config):
    rows=config.get('consent_delegations',[])
    if not isinstance(rows,list) or len(rows)>32:raise ValueError('invalid consent delegations')
    seen=set();bindings=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','principal','client_ids','scopes','targets','modes','expires_at','reason'}:
            raise ValueError('explicit consent delegation fields required')
        if any(not isinstance(row[k],str) or not row[k].strip() or len(row[k])>512 for k in ('id','principal','reason')) or row['id'] in seen or row['principal']==config['owner']:
            raise ValueError('distinct named consent delegate required')
        seen.add(row['id'])
        for key,allowed in [('scopes',config['scopes']),('modes',['operator','subset'])]:
            if not isinstance(row[key],list) or not row[key] or any(not isinstance(v,str) for v in row[key]) or not set(row[key])<=set(allowed):raise ValueError('invalid delegation '+key)
        if not isinstance(row['client_ids'],list) or not row['client_ids'] or len(row['client_ids'])>32 or any(not isinstance(c,str) or not c or '*' in c for c in row['client_ids']):raise ValueError('exact delegated clients required')
        for cid in row['client_ids']:
            key=(row['principal'],cid)
            if key in bindings:raise ValueError('ambiguous consent delegation')
            bindings.add(key)
        if type(row['expires_at']) not in (int,float) or not math.isfinite(row['expires_at']) or row['expires_at']<=0:raise ValueError('finite consent expiry required')
        if not isinstance(row['targets'],list) or not row['targets'] or any(not isinstance(t,dict) or not t or not covers(t,config['targets']) for t in row['targets']):raise ValueError('invalid delegation targets')
        from .unified_connectors import intersect_targets
        intersect_targets(row['targets'],row['targets'])


def permission(config, principal, client_id, now):
    if principal==config['owner']:return None
    rows=[r for r in config.get('consent_delegations',[]) if r['principal']==principal and client_id in r['client_ids'] and r['expires_at']>now]
    if len(rows)!=1:raise AuthError('access_denied')
    return rows[0]


def flow_binding(config, principal, delegation):
    return digest(json.dumps([config['owner'],principal,delegation,config['scopes'],config['targets'],config['grant_seconds']],sort_keys=True))


def check_grant(authority, config, grant_id):
    """Follow original consent ancestry; config withdrawal also fences child grants."""
    with authority.connect() as db:
        current=grant_id
        for unused in range(16):
            row=db.execute('SELECT consenter,delegation_id,mode FROM connector_consent_audit WHERE grant_id=?',(current,)).fetchone()
            if row:
                delegated=permission(config,row[0],db.execute('SELECT client FROM grants WHERE id=?',(grant_id,)).fetchone()[0],authority.now())
                if delegated is None or delegated['id']!=row[1]:raise AuthError()
                grant=db.execute('SELECT scopes,targets FROM grants WHERE id=?',(grant_id,)).fetchone()
                if row[2] not in delegated['modes'] or not set(json.loads(grant[0]))<=set(delegated['scopes']) or any(not covers(t,delegated['targets']) for t in json.loads(grant[1])):raise AuthError()
                return
            parent=db.execute('SELECT parent_id FROM delegations WHERE grant_id=?',(current,)).fetchone()
            if not parent or parent[0] is None:return
            current=parent[0]
        raise AuthError()
