#!/usr/bin/env python3
"""Run one already configured disposable upgrade through its public job seam.

Host preparation owns private configuration and all effect authorization. This
launcher neither provisions accounts nor substitutes executors. Each phase runs
in a fresh controller context; terminal evidence is retained before completion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from codex_profiles.upgrades import _atomic
from codex_wake.operation_commands import local_actor
from codex_wake.upgrade_jobs import TERMINAL, UpgradeJobs


def run(root, recipe, evidence):
    root=Path(root).resolve(strict=True)
    evidence=Path(evidence).resolve()
    evidence.mkdir(mode=0o700,parents=True,exist_ok=False)
    config_path=root/'upgrade-bot.json'
    config=json.loads(config_path.read_text())
    target=config['target']
    if target.get('environment')!='test':
        raise ValueError('explicit disposable test target required')
    receipt=dict(schema_version=1,started_at=time.time(),root=str(root),recipe=recipe,
        configuration_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),phases=[])
    def call(verb,**arguments):
        actor=local_actor(root)
        value=UpgradeJobs(root).execute(actor,'upgrades.'+verb,
            dict(expected_target=target,**arguments),authorize=lambda:local_actor(root))
        receipt['phases'].append(dict(operation=verb,at=time.time(),result=value))
        _atomic(evidence/'checkpoint.json',receipt)
        return value['result']
    try:
        call('enable')
        job=call('start',recipe=recipe)['job']
        receipt['job_id']=job['id']
        # There are exactly three public phases: repair/build, qualify, promote.
        # A held job is evidence, never an invitation to replenish its budget.
        for unused in range(3):
            if job['state'] in TERMINAL:break
            job=call('advance',job_id=job['id'])['job']
        job=call('show',job_id=job['id'])['job']
        receipt.update(status=job['state'],reason=job.get('reason'),job=job,
            exit_code=0 if job['state']=='succeeded' else 1)
    except BaseException as error:
        receipt.update(status='launcher_failed',reason=type(error).__name__+': '+str(error),exit_code=1)
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
    finally:
        receipt['finished_at']=time.time()
        _atomic(evidence/'completion.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--recipe',required=True)
    parser.add_argument('--evidence',required=True,type=Path)
    args=parser.parse_args()
    receipt=run(args.root,args.recipe,args.evidence)
    print(json.dumps({k:receipt.get(k) for k in ('status','reason','job_id','exit_code')}))
    return receipt['exit_code']


if __name__=='__main__':raise SystemExit(main())
