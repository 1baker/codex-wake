#!/usr/bin/env python3
"""Opt-in #691 deterministic installed calendar replay; never dispatches work."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


CHILD = r'''
import json,os,sys,time,importlib.metadata
from pathlib import Path
import codex_wake
from codex_wake.recurring_schedules import ScheduleStore,poll_schedules
from codex_wake.session_permissions import PermissionStore,Principal
from codex_wake.records import WakeError,all_records
p=json.load(sys.stdin);root=Path(p['root']);prefix=Path(p['prefix']).resolve()
assert Path(codex_wake.__file__).resolve().is_relative_to(prefix)
assert Path(sys.executable).absolute().parent==prefix/'bin'
if hasattr(time,'tzset'):time.tzset()
assert not (root/'missing.sock').exists()
principal=Principal('cw691-operator','operator');permissions=PermissionStore(root)
if not permissions.active():
 actions={a:{'decision':'allow','targets':[p['request']['thread_id']]} for a in ('wake.existing_tab','wake.background')}
 permissions.configure({'version':1,'global':{'default':'deny'},'sessions':{principal.subject:{'actions':actions}}},principal,expected_revision=0)
store=ScheduleStore(root);out={'action':p['action'],'pid':os.getpid(),'version':importlib.metadata.version('codex-wake'),'package':codex_wake.__file__,'child_TZ':os.environ.get('TZ'),'replay_only':True,'native_endpoint_missing':True}
if p['action'] in ('register','reject'):
 try:
  value=store.register(p['request'],codex_path=sys.executable,endpoint='unix://'+str(root/'missing.sock'),principal=principal)
  assert p['action']=='register','invalid request was accepted'
  assert not value['armed'];out['value']=value
 except WakeError as e:
  assert p['action']=='reject';assert not store.records();out['rejected']=str(e)
elif p['action']=='poll':
 from datetime import datetime
 at=datetime.fromisoformat(p['at'].replace('Z','+00:00')).timestamp()
 clock={'utc':{'lower':at,'upper':at,'status':'network','sources':['calendar-replay-a','calendar-replay-b'],'synthetic_replay':True},'counter':None}
 # API shape only: not authenticated network time and never sent to a dispatcher.
 poll_schedules(root,clock);out['clock_input']=clock;out['value']=store.read(p['id'])
elif p['action']=='read':out['value']=store.read(p['id'])
elif p['action']=='cleanup':
 out['before']=[r for r in store.records()]
 for value in out['before']:store.cancel(value['id'],value['revision'],principal=principal)
 out['value']=[r for r in store.records()]
 assert all(v['state']=='cancelled' for v in out['value'])
 permissions.configure({'version':1,'global':{'default':'deny'}},principal,expected_revision=1)
 out['wake_states']=[w.record['status'] for w in all_records(root,include_archive=True)]
 assert all(s=='cancelled' for s in out['wake_states'])
else:raise AssertionError('unknown replay action')
assert not (root/'missing.sock').exists();print(json.dumps(out))
'''


def clock(start, times, zone='America/Chicago', gap='skip', fold='first'):
    return dict(kind='clock', times=times, timezone=zone, start_at=start, gap_policy=gap, fold_policy=fold)


def vectors():
    spring='2027-03-13T00:00:00Z';fall='2027-11-06T00:00:00Z'
    return [
        ('spring-local',clock(spring,['20:00','08:00']),['2027-03-13T14:00:00Z','2027-03-14T02:00:00Z','2027-03-14T13:00:00Z','2027-03-15T01:00:00Z','2027-03-15T13:00:00Z']),
        ('spring-12h',dict(kind='interval',seconds=43200,start_at='2027-03-13T14:00:00Z'),['2027-03-13T14:00:00Z','2027-03-14T02:00:00Z','2027-03-14T14:00:00Z','2027-03-15T02:00:00Z','2027-03-15T14:00:00Z']),
        ('fall-local',clock(fall,['08:00','20:00']),['2027-11-06T13:00:00Z','2027-11-07T01:00:00Z','2027-11-07T14:00:00Z','2027-11-08T02:00:00Z','2027-11-08T14:00:00Z']),
        ('fall-12h',dict(kind='interval',seconds=43200,start_at='2027-11-06T13:00:00Z'),['2027-11-06T13:00:00Z','2027-11-07T01:00:00Z','2027-11-07T13:00:00Z','2027-11-08T01:00:00Z','2027-11-08T13:00:00Z']),
        ('gap-skip',clock('2027-03-14T00:00:00Z',['02:30']),['2027-03-15T07:30:00Z','2027-03-16T07:30:00Z','2027-03-17T07:30:00Z']),
        ('gap-shift',clock('2027-03-14T00:00:00Z',['02:30'],gap='shift_forward'),['2027-03-14T08:30:00Z','2027-03-15T07:30:00Z','2027-03-16T07:30:00Z']),
        ('fold-first',clock('2027-11-07T00:00:00Z',['01:30']),['2027-11-07T06:30:00Z','2027-11-08T07:30:00Z','2027-11-09T07:30:00Z']),
        ('fold-second',clock('2027-11-07T00:00:00Z',['01:30'],fold='second'),['2027-11-07T07:30:00Z','2027-11-08T07:30:00Z','2027-11-09T07:30:00Z']),
        ('fold-both',clock('2027-11-07T00:00:00Z',['01:30'],fold='both'),['2027-11-07T06:30:00Z','2027-11-07T07:30:00Z','2027-11-08T07:30:00Z','2027-11-09T07:30:00Z']),
        ('fold-utc-order',clock('2027-11-07T00:00:00Z',['01:30','01:00'],zone='America/New_York',fold='both'),['2027-11-07T05:00:00Z','2027-11-07T05:30:00Z','2027-11-07T06:00:00Z','2027-11-07T06:30:00Z','2027-11-08T06:00:00Z']),
        ('gap-collision',clock('2027-03-14T00:00:00Z',['02:30','03:30'],gap='shift_forward'),['2027-03-14T08:30:00Z','2027-03-15T07:30:00Z','2027-03-15T08:30:00Z','2027-03-16T07:30:00Z']),
    ]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-replay',action='store_true',required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--expected-prefix',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    prefix=args.expected_prefix.resolve(strict=True)
    assert Path(sys.executable).absolute().parent==prefix/'bin'
    import zoneinfo
    base=args.artifacts.absolute();base.mkdir(mode=0o700,parents=True,exist_ok=False)
    receipt=dict(ticket=691,state='running',replay_only=True,native_inputs=0,dispatchers_started=0,cases=[],rejections=[],steps=[])
    receipt['tzpath']=list(zoneinfo.TZPATH);receipt['zonefiles']={}
    for name in ('America/Chicago','America/New_York'):
        path=next(Path(p)/name for p in zoneinfo.TZPATH if (Path(p)/name).is_file())
        receipt['zonefiles'][name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    zi=Path('/usr/share/zoneinfo/tzdata.zi');receipt['system_tzdb_header']=zi.read_text().splitlines()[0] if zi.exists() else None
    roots=[]
    def request(name,cadence,count):
        return dict(idempotency_key='cw691-'+base.name+'-'+name,thread_id=str(uuid.uuid4()),prompt='Calendar replay only; never dispatch.',session_mode='background',cadence=cadence,end=dict(kind='count',count=count),missed=dict(policy='catch_up',limit=16,max_lateness_seconds=604800),overlap=dict(policy='queue',limit=16),delivery_window_seconds=604800)
    def step(root,req,action,**fields):
        payload=dict(root=str(root),prefix=str(prefix),request=req,action=action,**fields)
        env=dict(os.environ,TZ='UTC' if len(receipt['steps'])%2==0 else 'Pacific/Honolulu',TMUX=str(root/'missing.sock')+',0,0');env.pop('PYTHONPATH',None)
        r=subprocess.run([str(prefix/'bin/python'),'-c',CHILD],input=json.dumps(payload),capture_output=True,text=True,cwd=root,env=env,timeout=20)
        entry=dict(action=action,root=root.name,child_TZ=env['TZ'],code=r.returncode,stdout=r.stdout,stderr=r.stderr)
        receipt['steps'].append(entry)
        assert r.returncode==0, entry
        return json.loads(r.stdout)
    def anchors(value,expected):
        items=value['occurrences'];assert len(items)==len(expected)
        for index,(item,due) in enumerate(zip(items,expected)):
            assert item['id']==value['id']+':1:'+str(index) and item['due_at']==due
            expiry=(datetime.fromisoformat(due.replace('Z','+00:00'))+timedelta(seconds=604800)).isoformat().replace('+00:00','Z')
            assert item['expires_at']==expiry
    try:
        for name,cadence,expected in vectors():
            root=base/name;root.mkdir(mode=0o700);req=request(name,cadence,len(expected)-1);roots.append((root,req))
            registered=step(root,req,'register')['value'];assert registered['next_due_at']==expected[0]
            identifier=registered['id'];last=None;generations=[]
            for index,due in enumerate(expected[:-1]):
                value=step(root,req,'poll',id=identifier,at=due)['value']
                anchors(value,expected[:index+1]);assert value['next_due_at']==expected[index+1]
                generations.append(value['last_poll_generation'])
                repeat=step(root,req,'poll',id=identifier,at=due)['value']
                assert repeat['occurrences']==value['occurrences'] and repeat['next_due_at']==value['next_due_at']
                assert repeat['last_poll_generation']!=value['last_poll_generation']
                read=step(root,req,'read',id=identifier)['value'];assert read['occurrences']==value['occurrences']
                last=read
            assert last['state']=='exhausted' and last['next_index']==len(expected)-1
            same=step(root,req,'register')['value'];assert same['id']==identifier and same['occurrences']==last['occurrences'] and same['next_due_at']==last['next_due_at']
            assert all(a!=b for a,b in zip(generations,generations[1:]))
            receipt['cases'].append(dict(name=name,state='passed',expected_utc=expected,occurrences=len(expected)-1,request=req,final=last))
        root=base/'invalid';root.mkdir(mode=0o700);invalid=request('invalid',clock('2027-03-14T00:00:00Z',['02:30']),2);roots.append((root,invalid))
        for name in ('missing_timezone','missing_gap','missing_fold','unknown_zone','unknown_gap','unknown_fold','invalid_time','duplicate_time'):
            req=deepcopy(invalid);c=req['cadence']
            if name.startswith('missing_'):c.pop({'missing_timezone':'timezone','missing_gap':'gap_policy','missing_fold':'fold_policy'}[name])
            else:
                key,value={'unknown_zone':('timezone','No/Such_Zone'),'unknown_gap':('gap_policy','guess'),'unknown_fold':('fold_policy','guess'),'invalid_time':('times',['24:00']),'duplicate_time':('times',['02:30','02:30'])}[name];c[key]=value
            rejected=step(root,req,'reject');assert rejected['rejected'];receipt['rejections'].append(dict(name=name,reason=rejected['rejected']))
        receipt['state']='passed'
    except BaseException as e:
        receipt.update(state='failed',failure=type(e).__name__+': '+str(e));raise
    finally:
        receipt['cleanup']=[]
        for root,req in roots:
            try:
                cleaned=step(root,req,'cleanup');before=cleaned['before'];after=cleaned['value']
                assert len(before)==len(after)
                for a,b in zip(before,after):
                    assert [(i['id'],i['due_at'],i['expires_at']) for i in a['occurrences']]==[(i['id'],i['due_at'],i['expires_at']) for i in b['occurrences']]
                receipt['cleanup'].append(dict(root=root.name,state='passed',schedules=len(after),wake_states=cleaned['wake_states']))
            except Exception as e:receipt['cleanup'].append(dict(root=root.name,state='failed',error=str(e)));receipt['state']='failed'
        with (base/'receipt.json').open('x') as f:json.dump(receipt,f,indent=2)
        print(json.dumps(dict(state=receipt['state'],cases=len(receipt['cases']),rejections=len(receipt['rejections']),receipt=str(base/'receipt.json'))))


if __name__=='__main__':
    main()
