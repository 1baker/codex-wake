"""Private host maintenance permits, separate from resource allocation authority.

Same-UID code is trusted by the host, as for the allocation policy. This is not a
security boundary against hostile same-UID processes. No MCP permit API exists.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import math

from . import measurements

from .goal_supervision import _directory, _heartbeat, _lock, _native, _private, _save
from .process import boot_id_value

# Runtime observations/effect acknowledgements may change during preparation;
# authority, stop latches and fixed accounting boundaries may not.
AUTHORITY = ('thread_id','generation','allocation_id','grant','policy_path','allocation_path',
    'goal_created_at','deadline','time_origin','token_limit','time_limit_seconds','token_accounting',
    'boot_id','started_upper','started_boottime','time_basis','clock_anchor','reset_anchor','stop_latched',
    'checkpoint_token_percent','checkpoint_seconds','winddown_deadline','allocation_winddown_deadline')
ALLOCATION_AUTHORITY=('allocation_id','grant','token_limit','time_limit_seconds','token_accounting',
    'time_origin','deadline','members','stop_latched','boot_id','winddown_deadline','time_basis','clock_anchor')


def _permit_path(directory):
    child=directory/'maintenance'
    child.mkdir(exist_ok=True,mode=0o700);_private(child,True)
    return child/'permit.json'


def _read(path):
    _private(path)
    return json.loads(path.read_text())


def _policy(path, root):
    path=Path(path).absolute()
    if path!=path.resolve():raise ValueError('maintenance policy cannot traverse symlinks')
    value=_read(path)
    if (set(value)!= {'version','enabled','controller_root','max_seconds'} or
            type(value['version']) is not int or value['version']!=1 or value['enabled'] is not True or
            value['controller_root']!=str(root) or type(value['max_seconds']) is not int or
            not 1<=value['max_seconds']<=60):
        raise ValueError('host maintenance policy unavailable or malformed')
    return value,hashlib.sha256(path.read_bytes()).hexdigest()


def window(directory,permit):
    """Caller holds maintenance lock; retain continuity without renewing authority."""
    path=_permit_path(directory)
    latched=permit.get('window_state')
    if latched in ('expired','unqualified'):
        return dict(state=latched,clock_status='qualified' if latched=='expired' else 'unqualified',
            elapsed_upper_seconds=permit.get('clock_elapsed_upper_seconds'),
            clock_observation=permit.get('clock_observation'))
    try:
        seconds=permit['duration_seconds'];previous=permit['clock_observation']
        highwater=permit['clock_elapsed_upper_seconds']
        if (permit.get('version')!=2 or permit.get('clock_basis')!='stable_time_host_counter_v1'
                or type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=60
                or type(highwater) not in (int,float) or not math.isfinite(highwater) or highwater<0):
            raise measurements.TimeUnavailable('maintenance_clock_unqualified')
        anchor=permit['clock_anchor'];current=measurements.snapshot()
        measurements.elapsed_bounds(previous,current)
        elapsed=max(highwater,measurements.elapsed_bounds(anchor,current)[1])
        state='eligible' if elapsed<seconds else 'expired'
    except (measurements.TimeUnavailable,OSError,ValueError,KeyError,TypeError):
        # A failed observation never replaces the retained evidence or high-water.
        permit.update(window_state='unqualified',clock_status='unqualified')
        _save(path,permit)
        return dict(state='unqualified',clock_status='unqualified',clock_observation=None)
    permit.update(clock_observation=current,clock_elapsed_upper_seconds=elapsed,
        window_state=state,clock_status='qualified')
    _save(path,permit)
    return dict(state=state,clock_status='qualified',elapsed_upper_seconds=elapsed,clock_observation=current)


def admission_guard(directory):
    path=_permit_path(directory)
    if path.exists():
        permit=_read(path)
        if permit.get('state') not in ('prepared','handoff','unqualified'):return
        decision=window(directory,permit)
        heartbeat=_heartbeat(directory)
        if (permit.get('state')=='prepared' and heartbeat.get('fresh') and
                heartbeat.get('generation')==permit['controller']['generation'] and
                decision['state']=='expired'):
            permit.update(state='preparation_expired',clock_status='qualified')
            _save(path,permit)
            return
        if decision['state']=='unqualified' or permit.get('state')=='unqualified':
            raise ValueError('controller maintenance clock unqualified; explicit host reconciliation required')
        raise ValueError('controller maintenance pending; wait for verified replacement')


def _receipts(directory):
    return sorted(p for p in directory.glob('*.json') if p.name!='controller.json')


def _snapshot(receipt):
    return {key:receipt.get(key) for key in AUTHORITY}


def prepare(root,policy_path,seconds):
    directory=_directory(root);root=directory.parent
    permission,digest=_policy(policy_path,root)
    if type(seconds) is not int or not 1<=seconds<=permission['max_seconds']:
        raise ValueError('maintenance interval exceeds host permission')
    with _lock(directory,'maintenance'),ExitStack() as stack:
        admission_guard(directory)
        heartbeat=_heartbeat(directory)
        if not heartbeat['fresh']:raise ValueError('fresh controller required for maintenance')
        receipts={};allocations={}
        for path in _receipts(directory):
            stack.enter_context(_lock(directory,path.stem));receipt=_read(path)
            if not receipt.get('stop_latched'):
                goal,active=_native(receipt['grant'],receipt['thread_id'])
                if (goal and goal.get('status') not in ('paused','blocked','complete','budgetLimited','usageLimited')) or active:
                    raise ValueError('all unlatched campaigns must be inactive before maintenance')
            receipts[path.name]=dict(authority=_snapshot(receipt),used_tokens=receipt['used_tokens'])
            if receipt.get('allocation_path'):
                allocation_path=Path(receipt['allocation_path'])
                with _lock(allocation_path.parent,allocation_path.stem):
                    allocation=_read(allocation_path)
                    allocations[str(allocation_path)]=dict(authority={key:allocation.get(key) for key in ALLOCATION_AUTHORITY},
                        used_tokens=allocation['used_tokens'])
        anchor=measurements.snapshot()
        measurements.elapsed_bounds(anchor,anchor)
        permit=dict(version=2,state='prepared',controller={key:heartbeat[key] for key in
            ('generation','pid','identity','boot_id')},policy_path=str(Path(policy_path).absolute()),
            policy_sha256=digest,prepared_boottime=None,expires_boottime=None,
            clock_basis='stable_time_host_counter_v1',clock_anchor=anchor,duration_seconds=seconds,
            clock_status='qualified',clock_observation=anchor,clock_elapsed_upper_seconds=0,
            window_state='eligible',receipts=receipts,allocations=allocations)
        _save(_permit_path(directory),permit)
        return dict(state='prepared',controller_generation=heartbeat['generation'],
            expires_boottime=None,clock_basis=permit['clock_basis'],seconds=seconds,receipt_count=len(receipts),
            next_action='Gracefully stop only the exact controller, then start its replacement within the fixed interval. Goals remain inactive; allocations and latches are preserved.')


def authorize_exit(directory,heartbeat):
    """Caller holds maintenance lock. Any uncertainty follows normal stop path."""
    path=_permit_path(directory)
    if not path.exists():return False
    try:
        permit=_read(path)
        if permit.get('state')!='prepared':return False
        decision=window(directory,permit)
        if decision['state']!='eligible':
            permit.update(clock_status=decision['clock_status'],handoff_refusal=decision['state'])
            _save(path,permit);return False
        if permit['controller']!={key:heartbeat[key] for key in ('generation','pid','identity','boot_id')}:return False
        _,digest=_policy(permit['policy_path'],directory.parent)
        if digest!=permit['policy_sha256']:return False
        paths=_receipts(directory)
        if {p.name for p in paths}!=set(permit['receipts']):return False
        with ExitStack() as stack:
            for receipt_path in paths:
                stack.enter_context(_lock(directory,receipt_path.stem));receipt=_read(receipt_path)
                before=permit['receipts'][receipt_path.name]
                if _snapshot(receipt)!=before['authority'] or receipt['used_tokens']<before['used_tokens']:return False
                from .goal_supervision import _grant
                if _grant(receipt['policy_path'],receipt['thread_id'],receipt['allocation_id'],directory.parent)!=receipt['grant']:return False
                if not receipt.get('stop_latched'):
                    goal,active=_native(receipt['grant'],receipt['thread_id'])
                    if (goal and goal.get('status') not in ('paused','blocked','complete','budgetLimited','usageLimited')) or active:return False
            for name,before in permit['allocations'].items():
                allocation_path=Path(name)
                with _lock(allocation_path.parent,allocation_path.stem):
                    allocation=_read(allocation_path)
                    if ({key:allocation.get(key) for key in ALLOCATION_AUTHORITY}!=before['authority'] or
                            allocation['used_tokens']<before['used_tokens']):return False
            # The controller is exiting, not renewing authority. Public readiness
            # still fails on its inactive/stale heartbeat until a new poll succeeds.
            decision=window(directory,permit)
            if decision['state']!='eligible':
                permit.update(clock_status=decision['clock_status'],handoff_refusal=decision['state'])
                _save(path,permit);return False
            permit.update(state='handoff',departed_boottime=None,clock_status='qualified',
                departure_clock_observation=decision['clock_observation'])
            _save(path,permit)
            return True
    except (OSError,ValueError,KeyError,TypeError):return False


def replacement_observed(directory,heartbeat):
    with _lock(directory,'maintenance'):
        path=_permit_path(directory)
        if not path.exists():return
        permit=_read(path)
        if permit.get('state') not in ('handoff','prepared'):return
        decision=window(directory,permit)
        if permit['controller']['generation']==heartbeat['generation']:
            if permit['state']=='prepared' and decision['state']=='expired':
                permit.update(state='preparation_expired',clock_status='qualified');_save(path,permit)
            elif decision['state']=='unqualified':
                permit['clock_status']='unqualified';_save(path,permit)
            return
        # Unqualified time cannot authorize handover or erase protective stop.
        state=decision['state']
        if heartbeat['boot_id']!=permit['controller']['boot_id']:state='unqualified'
        if state!='eligible':
            from .goal_supervision import _stop
            for receipt_path in _receipts(directory):
                with _lock(directory,receipt_path.stem):
                    receipt=_read(receipt_path)
                    _stop(receipt_path,receipt,'maintenance_clock_unqualified' if state=='unqualified' else 'maintenance_expired')
        permit.update(state='replaced' if state=='eligible' else state,replacement_generation=heartbeat['generation'],
            replacement_boottime=None,replacement_clock_observation=decision['clock_observation'],
            clock_status='unqualified' if state=='unqualified' else 'qualified')
        _save(path,permit)
