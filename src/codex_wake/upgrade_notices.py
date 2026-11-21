"""Attributable upgrade event notices, using the existing native no-turn owner.

Canonical events and host-registered exact recipients supply all text and targets.
The delivery journal retains append intent before I/O. Unknown append outcomes
are read back under the original ID and never automatically appended a second time.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path

from codex_profiles.upgrades import _atomic
from .controller_notices import ControllerNotices
from .controller_runtime import encoded
from .managed_inventory import InventoryError


def _hash(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def _configuration(root):
    config=json.loads((Path(root)/'upgrade-bot.json').read_text())
    if config.get('schema_version')!=1:
        raise InventoryError('invalid_configuration','unsupported upgrade notice configuration')
    recipients=config.get('notice_recipients',[])
    if not isinstance(recipients,list) or len(recipients)>64 or any(not isinstance(r,dict) or set(r)!={'target'} or not isinstance(r['target'],dict) for r in recipients):
        raise InventoryError('invalid_configuration','registered exact upgrade notice targets required')
    targets=[r['target'] for r in recipients]
    if len({_hash(t) for t in targets})!=len(targets):
        raise InventoryError('invalid_configuration','duplicate upgrade notice recipients')
    return config,targets


def source_event(root, source_id, target):
    """Derive a bounded notice solely from an immutable retained upgrade event."""
    config,targets=_configuration(root)
    if target not in targets:
        raise InventoryError('unauthorized_target','recipient is not a registered operator session')
    if type(source_id) is not int or source_id<=0:
        raise InventoryError('invalid_argument','positive upgrade event identity required')
    state=json.loads((Path(root)/'upgrade-jobs/state.json').read_text())
    if state.get('schema_version')!=1:
        raise InventoryError('unsupported_schema','upgrade event schema unsupported')
    matches=[event for event in state.get('events',[]) if event.get('id')==source_id]
    if len(matches)!=1:
        raise InventoryError('source_unavailable','one retained upgrade event required')
    raw=matches[0]
    job=state.get('jobs',{}).get(raw.get('job_id'),{})
    fields=dict(action='upgrades.'+raw.get('kind','unknown'),job_id=raw.get('job_id') or 'policy',
        release=job.get('version') or 'not_applicable',reason=raw.get('reason','not_reported'),
        upgrade_target=job.get('target',config.get('target',{})))
    if any(not isinstance(fields[k],str) or len(fields[k])>4096 for k in ('action','job_id','release','reason')):
        raise InventoryError('source_unavailable','retained upgrade fields exceed notice bounds')
    event_id='upgrade_notice_'+_hash([str(Path(root).resolve()),source_id,target])
    suffix=' [External supervision event '+event_id+']'
    text='Codex Wake upgrade bot: '+encoded(fields)
    budget=768-len(suffix.encode())
    if len(text.encode())>budget:
        text=text.encode()[:budget-3].decode('utf-8',errors='ignore')+'...'
    return dict(event_id=event_id,text=text+suffix,source=fields,source_event_id=source_id,
        source_digest=_hash([raw,fields]))


class UpgradeNotices:
    def __init__(self,root,*,owner=None):
        self.root=Path(root)
        self.store=self.root/'upgrade-jobs'
        self.path=self.store/'notices.json'
        self.owner=owner or ControllerNotices(root)

    @contextmanager
    def locked(self):
        self.store.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (self.store/'.notices.lock').open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    def _load(self):
        if not self.path.exists():
            return dict(schema_version=1,deliveries={},no_recipient_events=[])
        value=json.loads(self.path.read_text())
        if value.get('schema_version')!=1:
            raise InventoryError('unsupported_schema','upgrade notice journal schema unsupported')
        return value

    def summary(self):
        with self.locked():
            journal=self._load()
        return dict(deliveries=list(journal['deliveries'].values()),no_recipient_events=journal['no_recipient_events'])

    def drain(self,actor,*,authorize,guard=None):
        guard=guard or (lambda:None)
        config,targets=_configuration(self.root)
        authority_stamp=_hash([actor.subject,actor.client_id,actor.grant_id,sorted(actor.scopes),actor.targets,config])
        state=json.loads((self.store/'state.json').read_text())
        events=state.get('events',[])
        if not isinstance(events,list):
            raise InventoryError('unsupported_schema','upgrade events must be retained as an ordered list')
        processed=0
        with self.locked():
            journal=self._load()
            for raw in events:
                if not targets:
                    if raw['id'] not in journal['no_recipient_events']:
                        journal['no_recipient_events'].append(raw['id'])
                    continue
                for target in targets:
                    key=_hash([raw['id'],target])
                    prior=journal['deliveries'].get(key)
                    if prior and prior.get('event_record_digest') is not None and prior['event_record_digest']!=_hash(raw):
                        prior.update(status='source_changed',reason='original_notice_source_changed')
                        _atomic(self.path,journal)
                    if prior and prior['status'] in ('recorded','unsupported','source_changed'):
                        continue
                    history=[]
                    if prior and prior['status']=='failed':
                        if prior.get('authority_stamp')==authority_stamp:
                            continue
                        history=prior.get('history',[])+[dict(status=prior['status'],reason=prior['reason'])]
                        prior=None
                    if processed>=32:
                        continue
                    processed+=1
                    try:
                        guard()
                        event=source_event(self.root,raw['id'],target)
                        if prior and prior['source_digest']!=event['source_digest']:
                            prior.update(status='source_changed',reason='original_notice_source_changed')
                            _atomic(self.path,journal)
                            continue
                        read=prior is not None
                        if prior is None:
                            # Authorization is checked before recording an append intent,
                            # distinguishing a known pre-effect refusal from uncertainty.
                            self.owner.authorize_upgrade_notice(actor,target,authorize=authorize)
                            prior=dict(source_event_id=raw['id'],target=target,event_id=event['event_id'],
                                source_digest=event['source_digest'],event_record_digest=_hash(raw),status='intent',authority_stamp=authority_stamp,history=history)
                            journal['deliveries'][key]=prior
                            _atomic(self.path,journal)
                        delivered=self.owner.deliver_upgrade_event(actor,target,raw['id'],authorize=authorize,
                            read=read,expected_source_digest=prior['source_digest'])
                        if delivered is None:
                            prior.update(status='uncertain',reason='original_notice_not_observed')
                        else:
                            prior.update(status=delivered['delivery']['status'],delivery=delivered['delivery'])
                            prior.pop('reason',None)
                    except (OSError,ValueError,KeyError,TypeError) as error:
                        reason=getattr(error,'code',type(error).__name__)
                        if prior is None:
                            prior=dict(source_event_id=raw.get('id'),target=target,event_id=None,
                                source_digest=None,event_record_digest=_hash(raw),status='failed',reason=reason,authority_stamp=authority_stamp,history=history)
                            journal['deliveries'][key]=prior
                        else:
                            prior.update(status='uncertain',reason=reason)
                    _atomic(self.path,journal)
            _atomic(self.path,journal)
            return dict(deliveries=list(journal['deliveries'].values()),no_recipient_events=journal['no_recipient_events'])
