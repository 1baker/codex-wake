#!/usr/bin/env python3
"""Fresh exact-package native journeys for a disposable upgrade job.

No stored older-package receipts are accepted. Native capability programs run
against CODEX_UPGRADE_PACKAGE; authenticated metadata belongs to the separate
UpgradeQualification executor. Scripted localhost requests are counted separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--history-probe',type=Path,required=True)
    args=parser.parse_args()
    package=Path(os.environ['CODEX_UPGRADE_PACKAGE']).resolve(strict=True)
    binary=package/'bin/codex'
    root=args.artifacts/uuid4().hex
    root.mkdir(parents=True,mode=0o700)
    with binary.open('rb') as stream:
        native_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    report=dict(schema_version=1,status='failed',native_sha256=native_sha,checks={},
        model_requests=0,external_provider_requests=0,scripted_provider_requests=0,
        owned_processes_remaining=[],artifacts=str(root))
    python=str(args.prefix/'bin/python')
    env=dict(os.environ,PYTHONPATH=str(args.source/'src'))
    env['PATH']=str(package/'bin')+':'+env.get('PATH','/usr/bin:/bin')
    def execute(name,argv,receipt):
        with (root/(name+'.stdout')).open('wb') as out,(root/(name+'.stderr')).open('wb') as err:
            process=subprocess.run(argv,env=env,stdout=out,stderr=err,timeout=600)
        if process.returncode:raise RuntimeError(name+' native journey failed; see '+str(root/(name+'.stderr')))
        value=json.loads(receipt.read_text())
        return value
    try:
        normal=execute('normal',[python,str(args.source/'scripts/upgrade_native_capability_probe.py'),'--codex',str(binary),'--models',str(args.models),'--artifacts',str(root/'normal')],root/'normal/receipt.json')
        assert normal['status']=='passed' and normal['native_sha256']==native_sha
        assert normal['model_requests']==normal['external_provider_requests']==0
        report['checks'].update(normal['checks'])
        report['scripted_provider_requests']+=normal['scripted_provider_requests']
        health=execute('health',[python,str(args.source/'scripts/controller_health_native_acceptance.py'),'--codex',str(binary),'--models',str(args.models),'--artifacts',str(root/'health'),'--core-only'],root/'health/receipt.json')
        assert health['native_sha256']==native_sha
        assert health['result']=='passed_core'
        assert all(health.get(k) is True for k in ('actual_ui_ack','fresh_post_resume_ack','main_loop_only_stall_denied','stopped_loop_background_rpc'))
        assert health['stalled_probe_statuses']==['unknown']
        report['checks']['tui_health']=True
        scoped=execute('scoped',[python,str(args.source/'scripts/scoped_refresh_native_qualification.py'),'--execute','--root',str(root/'scoped'),'--prefix',str(args.prefix)],root/'scoped/receipt.json')
        assert scoped['state']=='passed' and scoped['model_turns']==0
        assert all(scoped.get(k) is True for k in ('same_threads','goals_unchanged','selected_v2_peer_v1','selected_new_catalog_peer_unchanged','exact_toy_startups'))
        assert scoped['cleanup']['private_home_processes']==scoped['cleanup']['toy_process_survivors']==[]
        report['checks']['scoped_reload']=True
        history=execute('history',[python,str(args.history_probe),'--package',str(package),'--baseline',str(args.baseline),'--root',str(root/'history'),'--wake-prefix',str(args.prefix)],root/'history/receipt.json')
        assert history['status']=='passed' and history['native_sha256']==native_sha
        assert history['model_requests']==history['external_provider_requests']==0
        assert history['owned_processes_remaining']==[]
        report['checks'].update(history['checks'])
        report['scripted_provider_requests']+=history.get('scripted_provider_requests',0)
        remaining=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or proc.name==str(os.getpid()):continue
            try:
                if proc.stat().st_uid!=os.getuid():continue
                variables=dict(part.split(b'=',1) for part in (proc/'environ').read_bytes().split(b'\0') if b'=' in part)
                home=os.fsdecode(variables.get(b'CODEX_HOME',b''))
                if home and Path(home).is_relative_to(root):remaining.append(int(proc.name))
            except (OSError,ValueError):continue
        report['owned_processes_remaining']=remaining
        assert not remaining, 'owned native probe process survived teardown'
        report['status']='passed'
    except Exception as error:report['reason']=type(error).__name__+': '+str(error)
    (root/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
