"""One host-owned action policy. Identity/capability evidence comes from callers.

Principal values are private, verified host inputs, never deserialized tool roles.
An adoption revision selects this resolver; absent policy retains legacy guards.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import measurements
from .records import WakeError, parse_timestamp

ACTIONS = {
    'session.inspect': 'allow', 'refresh.self': 'allow',
    'refresh.connection': 'allow', 'refresh.shared': 'approval_required',
    'handoff.self': 'allow', 'resume.self': 'allow', 'resume.recover': 'approval_required',
    'enforcement.self_watch': 'allow', 'enforcement.enroll': 'allow', 'enforcement.watcher_start': 'approval_required', 'enforcement.increase': 'approval_required',
    'enforcement.disable': 'approval_required', 'enforcement.recover': 'approval_required',
    'a2a.send': 'allow', 'a2a.receive': 'allow', 'a2a.claim': 'allow', 'a2a.reply': 'allow',
    'wake.background': 'allow', 'wake.existing_tab': 'allow',
    'wake.new_tab': 'allow', 'wake.fresh_task': 'allow',
    'acceptance.verify': 'approval_required', 'job.launch': 'approval_required',
    'job.cancel': 'approval_required', 'attention.request': 'allow',
    'attention.respond': 'approval_required', 'attention.consume': 'allow',
    'workspace.order': 'approval_required', 'workspace.undo': 'approval_required',
    'workspace.navigate': 'approval_required', 'terminal.menu': 'approval_required',
    'terminal.takeover': 'approval_required', 'terminal.return': 'approval_required',
}
DECISIONS = {'allow', 'deny', 'approval_required', 'inherit'}
RELATIONSHIPS = {'self', 'peer', 'successor', 'shared'}
MAX_BYTES = 262144


class PermissionDenied(WakeError):
    def __init__(self, reason, decision=None):
        super().__init__(reason)
        self.code = reason
        self.decision = decision


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str = 'session'
    tasks: tuple[str, ...] = ()
    # Only host/controller construction may supply this verified relationship.
    predecessor: str | None = None
    ancestors: tuple[str, ...] = ()

    def __post_init__(self):
        if (not isinstance(self.subject, str) or not self.subject
                or self.role not in ('session', 'operator', 'controller')):
            raise PermissionDenied('permission_identity_unverified')
        if (type(self.tasks) is not tuple or any(not isinstance(x,str) or not x for x in self.tasks)
                or type(self.ancestors) is not tuple or len(self.ancestors)>256
                or len(set(self.ancestors))!=len(self.ancestors)
                or any(not isinstance(x,str) or not x for x in self.ancestors)
                or (self.predecessor is not None and (not isinstance(self.predecessor,str) or not self.predecessor))):
            raise PermissionDenied('permission_identity_unverified')


def _layer(layer):
    if not isinstance(layer, dict) or set(layer) - {'default', 'actions', 'profile', 'authorized_profiles'}:
        raise ValueError('invalid permission layer')
    if layer.get('default', 'inherit') not in DECISIONS:
        raise ValueError('invalid permission default')
    actions = layer.get('actions', {})
    if not isinstance(actions, dict):
        raise ValueError('invalid permission actions')
    for action, value in actions.items():
        if action not in ACTIONS:
            raise ValueError('unknown permission action: ' + str(action))
        if isinstance(value, str):
            if value not in DECISIONS:
                raise ValueError('invalid permission decision')
        elif isinstance(value, dict):
            if set(value) - {'decision', 'relationships', 'targets', 'tasks'} or value.get('decision') not in DECISIONS:
                raise ValueError('invalid scoped permission rule')
            for key in ('relationships', 'targets', 'tasks'):
                if key in value and (not isinstance(value[key], list) or not value[key]
                        or any(not isinstance(x, str) or not x for x in value[key])):
                    raise ValueError('invalid permission scope')
            if set(value.get('relationships', [])) - RELATIONSHIPS:
                raise ValueError('invalid permission relationship')
        else:
            raise ValueError('invalid permission rule')
    if 'profile' in layer and (not isinstance(layer['profile'], str) or not layer['profile']):
        raise ValueError('invalid profile selection')
    if 'authorized_profiles' in layer and (not isinstance(layer['authorized_profiles'], list)
            or any(not isinstance(x, str) or not x for x in layer['authorized_profiles'])):
        raise ValueError('invalid profile authority')


def _validate(policy):
    if len(json.dumps(policy).encode())>MAX_BYTES:
        raise ValueError('permission policy exceeds size limit')
    fields = {'version', 'global', 'profiles', 'sessions', 'assignments', 'mandatory',
              'approvals', 'delegations', 'known_actions', 'future_actions_inherit', 'adoption'}
    if not isinstance(policy, dict) or set(policy) - fields or type(policy.get('version')) is not int or policy['version'] != 1:
        raise ValueError('invalid common permission policy')
    if type(policy.get('future_actions_inherit', False)) is not bool:
        raise ValueError('invalid future-action policy')
    _layer(policy.get('global', {}))
    for group in ('profiles', 'sessions', 'assignments'):
        values = policy.get(group, {})
        if not isinstance(values, dict):
            raise ValueError('invalid policy group')
        for name, layer in values.items():
            if not isinstance(name, str) or not name:
                raise ValueError('invalid permission selector')
            _layer(layer)
    known = policy.get('known_actions', list(ACTIONS))
    if not isinstance(known, list) or any(x not in ACTIONS for x in known) or len(set(known)) != len(known):
        raise ValueError('invalid known-action catalog')
    mandatory = policy.get('mandatory', [])
    if not isinstance(mandatory, list) or any(x not in ACTIONS for x in mandatory):
        raise ValueError('invalid mandatory prohibition')
    approvals = policy.get('approvals', [])
    if not isinstance(approvals, list):
        raise ValueError('invalid approvals')
    seen = set()
    for approval in approvals:
        required = {'id', 'action', 'subject', 'scope', 'issuer'}
        allowed = required | {'task_id', 'expires_at', 'target', 'successors'}
        if (not isinstance(approval, dict) or set(approval)-allowed or not required <= set(approval)
                or approval['action'] not in ACTIONS or approval['scope'] not in ('operation', 'task', 'standing')
                or any(not isinstance(approval[k], str) or not approval[k] for k in required)
                or approval['id'] in seen or type(approval.get('successors', False)) is not bool):
            raise ValueError('invalid approval')
        seen.add(approval['id'])
        if approval['scope'] != 'standing' and ('expires_at' not in approval or 'task_id' not in approval):
            raise ValueError('bounded approval requires task and expiry')
        if 'expires_at' in approval:
            parse_timestamp(approval['expires_at'])
    delegations = policy.get('delegations', {})
    if not isinstance(delegations, dict):
        raise ValueError('invalid delegation policy')
    for value in delegations.values():
        if (not isinstance(value, dict) or set(value) != {'actions', 'sessions'}
                or not isinstance(value['actions'], list) or not isinstance(value['sessions'], list)
                or any(x not in ACTIONS for x in value['actions'])
                or any(not isinstance(x, str) or not x for x in value['sessions'])):
            raise ValueError('invalid delegation scope')
    profiles = policy.get('profiles', {})
    for layer in [policy.get('global', {}), *policy.get('sessions', {}).values(), *policy.get('assignments', {}).values()]:
        if layer.get('profile', 'permissive') not in profiles and layer.get('profile', 'permissive') != 'permissive':
            raise ValueError('unknown permission profile')
    adoption=policy.get('adoption')
    if adoption is not None:
        if (not isinstance(adoption,dict) or set(adoption)!={'version','source_sha256','legacy_profile_grants'}
                or type(adoption['version']) is not int or adoption['version']!=1
                or not isinstance(adoption['source_sha256'],str) or len(adoption['source_sha256'])!=64
                or any(c not in '0123456789abcdef' for c in adoption['source_sha256'])
                or not isinstance(adoption['legacy_profile_grants'],dict)):
            raise ValueError('invalid legacy adoption provenance')
        for subject,grants in adoption['legacy_profile_grants'].items():
            if not isinstance(subject,str) or not subject or not isinstance(grants,list) or any(not isinstance(x,str) or not x for x in grants):
                raise ValueError('invalid legacy profile mapping')
    return policy


class PermissionStore:
    def __init__(self, root, *, now=None):
        self.root = Path(root).absolute()
        if self.root != self.root.resolve():
            raise PermissionDenied('permission_root_not_canonical')
        self.execution_root=self.root
        self.routing_error=None
        link=self.root/'session-permissions-root.json'
        if link.exists() or link.is_symlink():
            try:
                from .wake_policy import _read
                from .goal_supervision import _private
                _private(self.root,True)
                routing=_read(link)
                if (not isinstance(routing,dict) or set(routing)!={'version','root','issuer'}
                        or type(routing['version']) is not int or routing['version']!=1
                        or not isinstance(routing['issuer'],str) or not routing['issuer']):
                    raise ValueError('invalid policy root binding')
                target=Path(routing['root'])
                if (not target.is_absolute() or target!=target.resolve() or target==self.root
                        or (target/'session-permissions-root.json').exists()
                        or (target/'session-permissions-root.json').is_symlink()):
                    raise ValueError('policy root routing must be canonical and single-hop')
                self.root=target
            except (OSError,ValueError,TypeError,KeyError,WakeError) as exc:
                self.routing_error=exc
        self.directory = self.root / 'session-permissions'
        self.path = self.directory / 'policy.json'
        self.now = measurements.utc_time if now is None else now

    def active(self):
        return (self.routing_error is not None or self.execution_root!=self.root or self.path.exists() or self.path.is_symlink() or self.directory.is_symlink()
                or (self.directory/'adopted.json').exists() or (self.directory/'adopted.json').is_symlink())

    def _read(self):
        from .wake_policy import _read
        from .goal_supervision import _private
        if self.routing_error is not None:raise PermissionDenied('permission_root_binding_invalid')
        _private(self.directory,True)
        if self.directory != self.directory.resolve():
            raise PermissionDenied('permission_directory_not_canonical')
        value = _read(self.path)
        if (not isinstance(value, dict) or set(value) != {'revision', 'issuer', 'policy', 'history'}
                or type(value['revision']) is not int or value['revision'] < 1):
            raise PermissionDenied('permission_policy_invalid')
        _validate(value['policy'])
        return value

    def configure(self, policy, principal, *, expected_revision):
        from .goal_supervision import _private, _lock, _save
        _validate(policy)
        if self.routing_error is not None:raise PermissionDenied('permission_root_binding_invalid')
        if not isinstance(principal, Principal) or principal.role != 'operator':
            raise PermissionDenied('permission_operator_required')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.mkdir(exist_ok=True, mode=0o700)
        _private(self.root, True)
        _private(self.directory, True)
        from .wake_policy import _owners
        _owners(self.root,initialize=True)
        with _lock(self.directory, 'policy'):
            old = self._read() if self.active() else {'revision': 0, 'history': []}
            if type(expected_revision) is not int or old['revision'] != expected_revision:
                raise PermissionDenied('permission_revision_conflict')
            policy = json.loads(json.dumps(policy))
            if old.get('policy',{}).get('adoption') and 'adoption' not in policy:
                policy['adoption']=old['policy']['adoption']
            policy.setdefault('known_actions', list(ACTIONS))
            digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            entry = dict(revision=old['revision']+1, issuer=principal.subject,
                         at=None, digest=digest)
            try:
                entry['at'] = self.now()
            except measurements.TimeUnavailable:
                # Audit metadata must not disable verified operator controls.
                entry['time_state'] = 'unavailable'
            value = dict(revision=entry['revision'], issuer=principal.subject,
                         policy=policy, history=[*old['history'], entry])
            _save(self.path, value)
            _save(self.directory/'adopted.json',dict(version=1,initial_issuer=principal.subject))
            return dict(revision=value['revision'], digest=digest, adopted=True)

    def bind_domain(self, domain_root, principal):
        from .goal_supervision import _private, _lock, _save
        from .wake_policy import _read
        if not isinstance(principal,Principal) or principal.role!='operator':
            raise PermissionDenied('permission_operator_required')
        self._read()
        domain=Path(domain_root).absolute()
        if domain!=domain.resolve():raise PermissionDenied('permission_root_not_canonical')
        if domain==self.root:return dict(bound=True,unchanged=True,root=str(self.root))
        domain.mkdir(parents=True,exist_ok=True,mode=0o700);_private(domain,True)
        link=domain/'session-permissions-root.json'
        with _lock(domain,'permission-root'):
            if link.exists() or link.is_symlink():
                old=_read(link)
                if old.get('root')!=str(self.root):raise PermissionDenied('permission_root_binding_conflict')
                PermissionStore(domain)._read()
                return dict(bound=True,unchanged=True,root=str(self.root))
            if PermissionStore(domain).active():raise PermissionDenied('permission_domain_migration_required')
            _save(link,dict(version=1,root=str(self.root),issuer=principal.subject))
        return dict(bound=True,root=str(self.root),domain=str(domain))

    def change_session(self, subject, layer, principal, *, expected_revision):
        _layer(layer)
        old = self._read()
        policy = json.loads(json.dumps(old['policy']))
        before = policy.get('sessions', {}).get(subject, {})
        if principal.role != 'operator':
            delegation = policy.get('delegations', {}).get(principal.subject, {}) if principal.role == 'controller' else {}
            if subject in delegation.get('sessions', []):
                if set(layer)-{'actions'} or set(layer.get('actions', {}))-set(delegation['actions']):
                    raise PermissionDenied('permission_delegation_exceeded')
            elif subject == principal.subject:
                authorized = before.get('authorized_profiles',policy.get('global',{}).get('authorized_profiles',[]))
                if set(layer)-{'actions', 'profile'} or ('profile' in layer and layer['profile'] not in authorized):
                    raise PermissionDenied('permission_self_promotion')
                if any(v != 'deny' for v in layer.get('actions', {}).values()):
                    raise PermissionDenied('permission_self_promotion')
            else:
                raise PermissionDenied('permission_delegation_exceeded')
        merged = {**before, **layer}
        merged['actions'] = {**before.get('actions', {}), **layer.get('actions', {})}
        policy.setdefault('sessions', {})[subject] = merged
        # Scope has been checked against the old host delegation; serialize CAS.
        return self.configure(policy, Principal(principal.subject, 'operator'), expected_revision=expected_revision)

    def evaluate(self, action, principal, *, target=None, relationship=None, task_id=None,
                 operation_id=None, capability='not_observed', readiness='not_observed', launch_profile=None):
        if not isinstance(principal, Principal):
            raise PermissionDenied('permission_identity_unverified')
        if action not in ACTIONS:
            raise PermissionDenied('permission_action_unknown')
        target = target or principal.subject
        relation = relationship or ('self' if target == principal.subject else 'peer')
        if relation not in RELATIONSHIPS or (relation == 'self' and target != principal.subject):
            raise PermissionDenied('permission_target_mismatch')
        if task_id is not None and principal.role != 'operator' and task_id not in principal.tasks:
            raise PermissionDenied('permission_task_scope_unverified')
        saved = self._read()
        p = saved['policy']
        session = p.get('sessions', {}).get(principal.subject, {})
        assignment = p.get('assignments', {}).get(task_id, {}) if task_id else {}
        selected = assignment.get('profile', session.get('profile', p.get('global', {}).get('profile', 'permissive')))
        profile = p.get('profiles', {}).get(selected, {})
        explicitly_configured=False
        decision, source, scope_failed = ACTIONS[action] if selected == 'permissive' else 'approval_required', 'profile:'+selected, False
        for name, layer in [('global', p.get('global', {})), ('profile:'+selected, profile),
                            ('session', session), ('assignment', assignment)]:
            explicitly_configured |= action in layer.get('actions',{})
            value = layer.get('actions', {}).get(action, layer.get('default', 'inherit'))
            if isinstance(value, str):
                value = {'decision': value}
            if value['decision'] != 'inherit':
                matches = all(key not in value or actual in value[key] for key, actual in
                              [('relationships', relation), ('targets', target), ('tasks', task_id)])
                decision = value['decision'] if matches else 'deny'
                source, scope_failed = name, not matches
        # Self-control actions cannot be converted into peer control by a profile.
        if action in ('session.inspect','refresh.self','refresh.connection','handoff.self','resume.self','enforcement.self_watch') and relation != 'self':
            decision, source = 'deny', 'exact_self_required'
        if action == 'refresh.shared' and relation != 'shared':
            decision, source = 'deny', 'shared_scope_required'
        if action in p.get('mandatory', []):
            decision, source = 'deny', 'mandatory'
        elif (action not in p.get('known_actions', list(ACTIONS)) and not explicitly_configured
              and not p.get('future_actions_inherit', False) and decision!='deny'):
            decision, source = 'approval_required', 'new_action'
        if task_id is not None:
            from .wake_policy import _owners, _owner_key
            terminal=_owners(self.root)['owners'].get(_owner_key({'kind':'task','id':task_id}))
            if terminal is not None:
                decision, source='deny','task_completed'
        from .permission_migration import LIFECYCLE_ACTIONS
        legacy_grants=p.get('adoption',{}).get('legacy_profile_grants',{})
        if action in LIFECYCLE_ACTIONS and principal.subject in legacy_grants and launch_profile not in legacy_grants[principal.subject]:
            decision,source='deny','legacy_profile_ceiling'
        approval_id = approval_scope = approval_issuer = None
        if decision == 'approval_required':
            approval_time_unavailable = False
            for a in p.get('approvals', []):
                subject_match = a['subject'] == principal.subject or (
                    a['subject'] in ((principal.predecessor,) + principal.ancestors) and a['scope'] == 'task' and a.get('successors', True) is True)
                if (a['action'] != action or not subject_match or a.get('target', target) != target
                        or (a['scope'] != 'standing' and a['task_id'] != task_id)
                        or (a['scope'] == 'operation' and a['id'] != operation_id)
                        or (action == 'refresh.shared' and a['scope'] != 'standing')):
                    continue
                if 'expires_at' in a:
                    try:
                        if parse_timestamp(a['expires_at']).timestamp() <= self.now():
                            continue
                    except measurements.TimeUnavailable:
                        approval_time_unavailable = True
                        continue
                decision, approval_id = 'allow', a['id']
                approval_scope, approval_issuer = a['scope'], a['issuer']
                break
            if decision == 'approval_required' and approval_time_unavailable:
                source = 'qualified_time_unavailable'
        return dict(permission=decision, action=action, subject=principal.subject, target=target,
                    relationship=relation, task_id=task_id, operation_id=operation_id, rule=source, revision=saved['revision'],
                    approval_id=approval_id, approval_scope=approval_scope, approval_issuer=approval_issuer, capability=capability, readiness=readiness,
                    scope_matched=not scope_failed, profile=selected)


def check_operation(root, action, principal, **context):
    """Effect owners call again immediately before I/O, not just admission."""
    store = PermissionStore(root)
    if not store.active():
        return {'permission': 'legacy', 'action': action}
    decision = store.evaluate(action, principal, **context)
    if decision['permission'] != 'allow':
        raise PermissionDenied('permission_'+decision['permission'], decision)
    return decision
