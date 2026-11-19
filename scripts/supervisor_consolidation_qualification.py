#!/usr/bin/env python3
"""Disposable public-command qualification; never polls working wake roots.

Run with an immutable installation using --prefix. --source-root explicitly
selects source qualification and is never reported as installed-wheel evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time


def wait_for(check, description, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise RuntimeError('timed out: ' + description)


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        return {'pid': pid, 'ppid': int(fields[1]), 'birth': fields[19], 'state': fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def children(pid):
    values = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            value = identity(int(path.name))
            if value and value['ppid'] == pid:
                values.append(value)
                values.extend(children(value['pid']))
    return values


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Pilot:
    def __init__(self, python, base, env):
        self.python, self.base, self.env = python, base, env
        self.commands, self.processes, self.observed = [], [], {}
        self.registry, self.state = base/'registry', base/'state/supervisor'

    def command(self, *args, expected=0):
        command = [self.python, '-m', 'codex_wake.entrypoint', *map(str, args)]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.commands.append({'argv': command, 'exit_code': result.returncode})
        if result.returncode != expected:
            raise RuntimeError(f'CLI exit {result.returncode}, expected {expected}: ' + result.stderr[-1500:])
        return result.stdout

    def enroll(self, root_id, root, interval=0.2, disabled=False, codex=None):
        options = ['supervisor', 'enroll', '--registry-dir', self.registry, '--state-dir', self.state,
                   '--root-id', root_id, '--wake-root', root, '--repo-root', self.base,
                   '--poll-interval', interval]
        if disabled:
            options.append('--disabled')
        if codex:
            options += ['--codex-path', codex]
        self.command(*options)

    def start(self, *args):
        log = (self.base/f'process-{len(self.processes)}.log').open('w')
        process = subprocess.Popen([self.python, '-m', *map(str, args)], env=self.env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append((process, log))
        value = identity(process.pid)
        if value:
            self.observed[process.pid] = value
        return process

    def observe(self):
        for process, _ in self.processes:
            if process.poll() is not None:
                continue
            for value in children(process.pid):
                self.observed[value['pid']] = value

    def stop(self, process, hard=False):
        self.observe()
        if process.poll() is None:
            process.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)

    def cleanup(self):
        for process, log in self.processes:
            self.stop(process)
            log.close()
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            live = [identity(pid) for pid, old in self.observed.items()
                    if identity(pid) and identity(pid)['birth'] == old['birth']
                    and identity(pid)['state'] != 'Z']
            if not live:
                return []
            time.sleep(0.02)
        # Only immutable identities created by this pilot are eligible for cleanup.
        for value in live:
            now = identity(value['pid'])
            if now and now['birth'] == value['birth']:
                os.kill(value['pid'], signal.SIGKILL)
        return [identity(value['pid']) for value in live
                if identity(value['pid']) and identity(value['pid'])['state'] != 'Z']

    def supervisor(self):
        return self.start('codex_wake.entrypoint', 'supervisor', 'run',
            '--registry-dir', self.registry, '--state-dir', self.state,
            '--interval', '0.05', '--max-workers', '2', '--poll-timeout', '1.5', '--no-dispatch')

    def health(self, root):
        self.observe()
        for path in (self.state.parent/'monitors').glob('*.json'):
            value = read_json(path)
            if value and value.get('wake_root') == str(root.resolve()):
                return value
        return None


def seed(python, root, env, count=1):
    code = '''import sys
from datetime import UTC, datetime
from pathlib import Path
from codex_wake.records import build_record,write_record
root=Path(sys.argv[1])
for index in range(int(sys.argv[2])):
 record=build_record(predicate={'type':'not_before','due_at':'2099-01-01T00:00:00Z'},
  prompt='Synthetic consolidation qualification',cwd=root.parent,now=datetime(2026,1,1,tzinfo=UTC),
  target={'transport':'tmux','tmux_socket':'/tmp/synthetic-unconnected','pane':'%1'})
 record['id']='wake_synthetic_'+str(index)
 write_record(root,record)
'''
    subprocess.run([python, '-c', code, str(root), str(count)], env=env, check=True, timeout=10)


def rss_kib(pid):
    try:
        return int(next(line.split()[1] for line in Path(f'/proc/{pid}/status').read_text().splitlines()
                        if line.startswith('VmRSS:')))
    except (OSError, StopIteration, ValueError):
        return 0


def benchmark(mode, base):
    from codex_wake.daemon import poll_once
    from codex_wake.supervisor import build_supervisor_config, enroll_root, supervisor_poll_once
    if mode == 'dedicated-root':
        for _ in range(3):
            poll_once(base, dispatch=False)
            time.sleep(0.02)
        return
    roots = [base/f'root-{index}' for index in range(6)]
    config = build_supervisor_config(registry_dir=base/'registry', state_dir=base/'state/supervisor',
                                    interval=0.02, validate_executable=False)
    for index, root in enumerate(roots):
        enroll_root(wake_root=root, registry_dir=config.registry_dir, root_id=f'root-{index}')
    cpu_start, started = time.process_time(), time.monotonic()
    peak_aggregate_rss = rss_kib(os.getpid())
    runtime_process_count = 1
    if mode == 'dedicated':
        processes = [subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                       '--benchmark-mode', 'dedicated-root', '--benchmark-root', str(root)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for root in roots]
        peak_aggregate_rss = 0
        runtime_process_count = 6
        while any(p.poll() is None for p in processes):
            peak_aggregate_rss = max(peak_aggregate_rss, sum(rss_kib(p.pid) for p in processes))
            time.sleep(0.005)
        for process in processes:
            _, error = process.communicate(timeout=2)
            if process.returncode:
                raise RuntimeError('dedicated benchmark failed: '+error.decode()[-800:])
        polls = 18
    elif mode == 'serial':
        for _ in range(3):
            supervisor_poll_once(config, dispatch=False)
        polls = 18
    else:
        from codex_wake.supervisor_scheduler import SupervisorScheduler
        from dataclasses import replace
        config = replace(config, max_workers=2)
        with SupervisorScheduler(config, dispatch=False) as scheduler:
            results = []
            counts = {f'root-{index}': 0 for index in range(6)}
            end = time.monotonic()+12
            while not all(value == 3 for value in counts.values()) and time.monotonic() < end:
                batch = scheduler.tick()
                results.extend(batch)
                for result in batch:
                    root_id = result['root_id']
                    counts[root_id] += 1
                    if counts[root_id] == 3:
                        index = int(root_id.split('-')[-1])
                        enroll_root(wake_root=roots[index], registry_dir=config.registry_dir,
                                    root_id=root_id, enabled=False)
                descendants = [int(pid) for pid in Path(
                    f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split()]
                runtime_process_count = max(runtime_process_count, 1 + len(descendants))
                peak_aggregate_rss = max(peak_aggregate_rss, rss_kib(os.getpid()) +
                                         sum(rss_kib(pid) for pid in descendants))
                time.sleep(scheduler.wait_seconds())
            if len(results) != 18 or not all(value == 3 for value in counts.values()):
                raise RuntimeError('benchmark did not complete exactly three polls per root')
            polls = len(results)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    print(json.dumps({'mode': mode, 'polls': polls, 'wall_seconds': time.monotonic()-started,
      'cpu_seconds': time.process_time()-cpu_start+usage.ru_utime+usage.ru_stime,
      'observed_peak_aggregate_rss_kib': peak_aggregate_rss,
      'runtime_process_count': runtime_process_count,
      'max_self_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      'max_child_rss_kib': usage.ru_maxrss,
      'rss_scope': '5ms/50ms sampled process RSS sum; shared pages counted repeatedly; excludes dedicated harness; not PSS or cgroup memory'}))


def qualify(args):
    python = str(Path(args.python or Path(args.prefix)/'bin/python').absolute())
    receipt = {'status': 'running', 'checks': {}, 'qualification_kind':
               'source' if args.source_root else 'installed', 'python': python,
               'commands': [], 'limitations': ['Synthetic v1 backlog only; native/provider delivery is not exercised.',
                 'Separate Linux test-user/native daemon upgrade gate is not replaced by this monitor qualification.',
                 'Working-host service migration has not been performed.']}
    started = time.monotonic()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    pilot = None
    try:
        with tempfile.TemporaryDirectory(prefix='codex-wake-p218-pilot-') as temporary:
            base = Path(temporary)
            env = dict(os.environ, XDG_CONFIG_HOME=str(base/'config'), XDG_STATE_HOME=str(base/'xdg-state'),
                       CODEX_WAKE_STABLE_TIME_CONFIG='')
            env.pop('PYTHONPATH', None)
            if args.source_root:
                env['PYTHONPATH'] = str(Path(args.source_root).resolve()/'src')
            package = subprocess.check_output([python, '-c',
                "import json,hashlib,importlib.metadata;from pathlib import Path;import codex_wake.supervisor as m;p=Path(m.__file__);print(json.dumps({'version':importlib.metadata.version('codex-wake'),'module':str(p),'supervisor_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))"],env=env,text=True,timeout=10)
            receipt['package'] = json.loads(package)
            receipt['script_sha256'] = digest(Path(__file__))
            pilot = Pilot(python, base, env)
            root = base/'ordinary'; seed(python, root, env)
            record = root/'pending/wake_synthetic_0.json'; original = digest(record)
            fake = base/'codex-synthetic'; fake.write_text('#!/bin/sh\nexit 0\n'); fake.chmod(0o700)
            pilot.enroll('ordinary', root, disabled=True, codex=fake)
            before = read_json(pilot.registry/'ordinary.json')
            dedicated = pilot.start('codex_wake.daemon','--wake-root',root,'--interval','0.2','--no-dispatch')
            wait_for(lambda: read_json(root/'locks/monitor.lock'), 'dedicated owner')
            contention = subprocess.check_output([python,'-m','codex_wake.daemon','--wake-root',str(root),
                                                '--once','--no-dispatch'],env=env,text=True,timeout=5)
            assert 'skipped=monitor_owned' in contention
            receipt['checks']['exclusive_dedicated_owner'] = True
            pilot.stop(dedicated)
            pilot.enroll('ordinary', root, codex=fake)
            after = read_json(pilot.registry/'ordinary.json')
            assert before['dispatch'] == after['dispatch'] and before['poll_interval'] == after['poll_interval']
            supervisor = pilot.supervisor()
            health = wait_for(lambda: pilot.health(root), 'migrated root health')
            assert health['source'] == 'supervisor' and digest(record) == original
            receipt['checks']['migration_preserved_pending_cadence_dispatch'] = True
            # A malformed synthetic root-local dispatch configuration must not
            # abort unrelated roots or the coordinator's polling pass.
            error_root = base/'error-root'
            pilot.enroll('error-root', error_root)
            error_entry = read_json(pilot.registry/'error-root.json')
            error_entry['dispatch'] = ['deliberately-invalid-synthetic-config']
            (pilot.registry/'error-root.json').write_text(json.dumps(error_entry))
            wait_for(lambda: (pilot.health(error_root) or {}).get('last_error'), 'root-local setup error')
            assert supervisor.poll() is None and pilot.health(root)
            receipt['checks']['root_setup_error_isolated'] = True
            pilot.enroll('error-root', error_root, disabled=True)
            pilot.stop(supervisor)
            supervisor = pilot.supervisor()
            wait_for(lambda: pilot.health(root), 'restart health')
            assert digest(record) == original
            receipt['checks']['clean_restart_preserved_pending_intent'] = True
            pilot.stop(supervisor)
            blocked = base/'blocked'; (blocked/'pending').mkdir(parents=True)
            os.mkfifo(blocked/'pending/wake_blocked.json')
            pilot.enroll('blocked',blocked)
            supervisor = pilot.supervisor()
            hold_path = blocked/'monitor-reconciliation.json'
            hold = wait_for(lambda: (pilot.observe(), read_json(hold_path))[1], 'blocked root hold')
            assert pilot.health(root) and supervisor.poll() is None
            receipt['checks']['blocked_root_isolated_and_held'] = True
            token = hold['token']
            pilot.stop(supervisor)
            supervisor = pilot.supervisor()
            wait_for(lambda: pilot.health(root), 'unrelated root after held restart')
            assert read_json(hold_path)['token'] == token
            skip = subprocess.check_output([python,'-m','codex_wake.daemon','--wake-root',str(blocked),
                                           '--once','--no-dispatch'],env=env,text=True,timeout=5)
            assert 'skipped=reconciliation_required' in skip
            receipt['checks']['restart_retained_uncertain_hold'] = True
            pilot.stop(supervisor)
            (blocked/'pending/wake_blocked.json').unlink()
            pilot.command('supervisor','reconcile','--registry-dir',pilot.registry,'--state-dir',pilot.state,
                          '--root-id','blocked','--expected-token',token,'--acknowledge-uncertain-effects')
            assert not hold_path.exists()
            receipt['checks']['exact_reconciliation_released_hold'] = True
            # Rollback changes monitoring configuration, never wake record contents.
            pilot.enroll('ordinary',root,disabled=True,codex=fake)
            dedicated = pilot.start('codex_wake.daemon','--wake-root',root,'--interval','0.2','--no-dispatch')
            wait_for(lambda: read_json(root/'locks/monitor.lock').get('pid') == dedicated.pid,
                     'rollback dedicated owner')
            assert digest(record) == original
            receipt['checks']['rollback_restored_dedicated_owner'] = True
            pilot.stop(dedicated)
            # Deliberately kill only this disposable coordinator while a root is
            # blocked, then prove its admission journal becomes a durable hold.
            pilot.enroll('blocked', blocked, disabled=True)
            crash_root = base/'crash-root'; (crash_root/'pending').mkdir(parents=True)
            os.mkfifo(crash_root/'pending/wake_blocked.json')
            pilot.enroll('crash-root', crash_root)
            supervisor = pilot.supervisor()
            wait_for(lambda: (pilot.observe(), read_json(crash_root/'locks/monitor.lock'))[1],
                     'crash fixture polling owner')
            pilot.stop(supervisor, hard=True)
            supervisor = pilot.supervisor()
            crash_hold = wait_for(lambda: (pilot.observe(), read_json(crash_root/'monitor-reconciliation.json'))[1],
                                  'abandoned poll recovered to hold')
            assert crash_hold['reason'] == 'coordinator_restarted_with_inflight_poll'
            receipt['checks']['abrupt_coordinator_restart_held_abandoned_poll'] = True
            pilot.stop(supervisor)
            (crash_root/'pending/wake_blocked.json').unlink()
            pilot.command('supervisor','reconcile','--registry-dir',pilot.registry,'--state-dir',pilot.state,
                          '--root-id','crash-root','--expected-token',crash_hold['token'],
                          '--acknowledge-uncertain-effects')
            receipt['commands'] = pilot.commands
            receipt['final_owned_processes'] = pilot.cleanup()
            assert receipt['final_owned_processes'] == []
            benchmarks = []
            for mode in ('serial','dedicated','isolated'):
                bench_base = base/('benchmark-'+mode)
                selected = args.baseline_python if mode in ('serial','dedicated') and args.baseline_python else python
                bench_env = dict(env)
                if selected != python:
                    bench_env.pop('PYTHONPATH',None)
                for index in range(6):
                    seed(selected,bench_base/f'root-{index}',bench_env,count=40)
                run = subprocess.run([selected,str(Path(__file__).resolve()),'--benchmark-mode',mode,
                    '--benchmark-root',str(bench_base)],env=bench_env,capture_output=True,text=True,timeout=20)
                if run.returncode:
                    raise RuntimeError('benchmark failed: '+run.stderr[-1200:])
                value = json.loads(run.stdout); value['python'] = selected
                benchmarks.append(value)
            receipt['economics'] = {'workload': '6 roots x 40 synthetic future v1 wakes; 18 completed polls',
                'baseline_kind': 'old installed release serial' if args.baseline_python else 'same-package serial reference',
                'measurements': benchmarks, 'interpretation':
                'Process isolation adds IPC/journaling/startup cost; compare numbers before rollout. These figures do not establish lower steady-state production CPU.'}
            receipt['status'] = 'passed'
    except Exception as error:
        import traceback
        receipt['status'] = 'failed'; receipt['error'] = f'{type(error).__name__}: {error}'
        receipt['failure_traceback'] = traceback.format_exc()
        if pilot:
            receipt['commands'] = pilot.commands
            receipt['final_owned_processes'] = pilot.cleanup()
    receipt['elapsed_seconds'] = time.monotonic()-started
    output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':receipt['status'],'receipt':str(output),'elapsed_seconds':receipt['elapsed_seconds']}))
    return 0 if receipt['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path)
    parser.add_argument('--python')
    parser.add_argument('--baseline-python')
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--benchmark-mode',choices=('serial','dedicated','dedicated-root','isolated'))
    parser.add_argument('--benchmark-root',type=Path)
    args = parser.parse_args()
    if args.benchmark_mode:
        benchmark(args.benchmark_mode,args.benchmark_root)
        return 0
    if not args.output or not (args.python or args.prefix):
        parser.error('--output and --python or --prefix are required')
    return qualify(args)


if __name__ == '__main__':
    raise SystemExit(main())
