#!/usr/bin/env python3
"""Opt-in #688 installed busy-turn overlap acceptance; synthetic owned recipient only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


GATE_PROGRAM = r"""import json,os,sys,time
from pathlib import Path
os.umask(0o077)
root=Path(sys.argv[1]);nonce=sys.argv[2]
pid=os.getpid();ticks=int(Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19])
end=time.monotonic()+120
info={'pid':pid,'start_ticks':ticks,'nonce':nonce,'deadline_monotonic':end}
tmp=root/('run-'+str(pid)+'.tmp');tmp.write_text(json.dumps(info));tmp.rename(root/('run-'+str(pid)+'.json'))
while time.monotonic()<end:
    if (root/'release').exists():
        print('CW688_GATE_RELEASED');sys.exit(0)
    time.sleep(.1)
print('CW688_GATE_TIMED_OUT');sys.exit(2)
"""


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-prefix', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    import codex_wake
    from codex_wake.native_protocol import native_request
    from codex_wake.native_clock import snapshot
    from codex_wake.recurring_schedules import ScheduleStore, poll_schedules, timestamp
    from codex_wake.session_permissions import PermissionStore, Principal
    from codex_wake.monitor import read_monitor_health
    from codex_wake.records import all_records
    from codex_wake.process import process_identity
    prefix = args.expected_prefix.resolve(strict=True)
    assert Path(sys.executable).absolute().parent == prefix/'bin'
    assert Path(codex_wake.__file__).resolve().is_relative_to(prefix)
    target = json.loads(args.target.read_text())
    assert target['ticket'] == 688 and target['disposable'] is True
    address = Path(target['tmux_socket']); directory = args.target.absolute().parent
    assert directory.resolve(strict=True) == directory and address.parent == directory
    assert directory.stat().st_uid == os.geteuid() and not directory.stat().st_mode & 0o077
    assert target['tmux_session'].startswith('cw688-')
    base = args.artifacts.absolute(); base.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = dict(os.environ, TMUX=str(address)+',0,0'); env.pop('PYTHONPATH', None)
    os.environ['TMUX'] = env['TMUX']
    for key in ('CODEX_THREAD_ID', 'CODEX_TURN_ID'):
        env.pop(key, None)
    principal = Principal('cw688-operator', 'operator')
    unit = 'cw688-'+base.name+'.service'
    roots, schedules = [], []
    monitor_units, stopped_units, gates = [], set(), []
    receipt = dict(ticket=685, state='running', target=target, prefix=str(prefix), cases=[], commands=[])

    def save(name, value):
        with (base/name).open('x') as f:
            json.dump(value, f, indent=2)

    def run(argv, check=True):
        r = subprocess.run([str(v) for v in argv], capture_output=True, text=True,
                           timeout=45, env=env, cwd=target['cwd'])
        receipt['commands'].append(dict(argv=[str(v) for v in argv], code=r.returncode,
                                        stdout=r.stdout, stderr=r.stderr))
        if check and r.returncode:
            raise RuntimeError('command failed: '+str(argv[:3]))
        return r

    def clock():
        value = snapshot()
        assert value['utc']['status'] == 'network' and value['utc']['upper']-value['utc']['lower'] < 5
        return value

    def wait(probe, label, seconds=180):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            value = probe()
            if value:
                return value
            time.sleep(.5)
        raise TimeoutError(label)

    def history():
        turns, cursor, seen, ids = [], None, set(), set()
        end = time.monotonic()+30
        for _ in range(8):
            remaining = end-time.monotonic(); assert remaining > 0
            page = native_request(target['endpoint'], target['executable'], 'thread/turns/list',
                dict(threadId=target['thread_id'], limit=8, sortDirection='asc', itemsView='full', cursor=cursor), remaining)
            for turn in page['data']:
                assert turn['id'] not in ids and turn['itemsView'] == 'full'
                ids.add(turn['id']); turns.append(turn)
            assert 'nextCursor' in page
            cursor = page['nextCursor']
            if cursor is None:
                return turns
            assert isinstance(cursor, str) and cursor and cursor not in seen
            seen.add(cursor)
        raise RuntimeError('owned history page budget')

    def inputs(turns):
        return [(turn, item) for turn in turns for item in turn['items'] if item['type'] == 'userMessage']

    def store(name):
        root = base/name; root.mkdir(mode=0o700); roots.append(root)
        actions = {a: dict(decision='allow', targets=[target['thread_id']])
                   for a in ('session.inspect', 'wake.background', 'wake.existing_tab')}
        policy = {'version': 1, 'global': {'default': 'deny'},
                  'sessions': {principal.subject: {'actions': actions}}}
        PermissionStore(root).configure(policy, principal, expected_revision=0)
        return ScheduleStore(root)

    def register(owner, label, start, interval, count, missed, overlap, prompt):
        request = dict(idempotency_key='cw688-'+base.name+'-'+label, thread_id=target['thread_id'],
            prompt=prompt, session_mode='background',
            cadence=dict(kind='interval', seconds=interval, start_at=iso(start)), end=dict(kind='count', count=count),
            missed=dict(max_lateness_seconds=240, **missed), overlap=overlap, delivery_window_seconds=240)
        r = owner.register(request, codex_path=target['executable'], endpoint=target['endpoint'], principal=principal)
        schedules.append((owner, r['id']))
        return r

    def anchors(value, start, interval, count):
        assert value['next_index'] == count and len(value['occurrences']) == count
        for i, item in enumerate(value['occurrences']):
            assert item['id'] == value['id']+':1:'+str(i)
            assert item['due_at'] == iso(start+interval*i)
            assert item['expires_at'] == iso(start+interval*i+240)

    try:
        receipt['native_before'] = process_identity(2082)
        initial = history(); assert len(inputs(initial)) == 1
        save('native-before.json', initial)
        gate_py = Path(target['cwd'])/'wait.py'
        gate_py.write_text(GATE_PROGRAM)
        baseline = 1
        for policy in ('skip', 'latest', 'queue'):
            case = Path(target['cwd'])/policy; case.mkdir(mode=0o700); gates.append(case)
            nonce = 'cw688-'+policy+'-'+str(time.monotonic_ns())
            owner = store(policy)
            unit = 'cw688-'+base.name+'-'+policy+'.service'; monitor_units.append(unit)
            run(['systemd-run', '--user', '--unit='+unit, '--property=RuntimeMaxSec=360',
                 '--property=KillMode=process', '--property=UMask=0077', '--working-directory='+target['cwd'],
                 '--setenv=TMUX='+env['TMUX'], '--setenv=PATH='+env['PATH'],
                 prefix/'bin/codex-waked', '--wake-root', owner.root, '--interval', '1'])
            wait(lambda: (read_monitor_health(owner.root) or {}).get('mode') == 'loop', 'monitor loop')
            start = clock()['utc']['upper']+20
            marker = 'CW688_'+policy.upper()+'_COMPLETED'
            command = '/usr/bin/python3 '+str(gate_py)+' '+str(case)+' '+nonce
            prompt = ('Run this exact command using exec_command, then wait for that command to finish '
                      'using write_stdin if necessary. Do not run any other command or modify any files. '
                      'The host will release the bounded gate; do not create the release file yourself. '
                      'After it exits successfully, reply exactly '+marker+'. Command: '+command)
            overlap = dict(policy=policy)
            if policy == 'queue': overlap['limit'] = 2
            admitted = register(owner, policy, start, 20, 4, dict(policy='latest'), overlap, prompt)
            assert admitted['armed']; save(policy+'-registration.json', admitted)
            entry = dict(name=policy, state='running', busy_observations=[]); receipt['cases'].append(entry)
            def gate_started():
                values = list(case.glob('run-*.json'))
                if not values: return None
                assert len(values) == 1
                record = json.loads(values[0].read_text()); assert record['nonce'] == nonce
                identity = process_identity(record['pid'])
                assert identity and identity['start_time_ticks'] == record['start_ticks']
                return record
            gate = wait(gate_started, 'actual native gate command', 100)
            assert clock()['utc']['upper'] < start+20, 'command did not start before later occurrences'
            entry['gate'] = gate
            observed = set()
            expected_busy = {'skip':['submitted','skipped','skipped','skipped'],
                             'latest':['submitted','coalesced','coalesced','queued'],
                             'queue':['submitted','skipped','queued','queued']}
            until = time.monotonic()+110
            while True:
                assert time.monotonic() < until, 'busy classification deadline'
                value = owner.read(admitted['id']); assert value['state'] != 'attention'
                data = history(); added = inputs(data)[baseline:]
                assert len(added) == 1, 'native input entered while original turn busy'
                turn, user = added[0]; assert turn['status'] == 'inProgress'
                assert process_identity(gate['pid'])['start_time_ticks'] == gate['start_ticks']
                tools = [i for i in turn['items'] if i['type'] not in ('userMessage','agentMessage','reasoning') and str(gate_py) in json.dumps(i)]
                command_argv = Path('/proc', str(gate['pid']), 'cmdline').read_bytes().split(b'\0')
                assert str(gate_py).encode() in command_argv and nonce.encode() in command_argv, 'live process is not the scoped gate command'
                for occurrence in value['occurrences'][1:]:
                    if occurrence['index'] not in observed:
                        observed.add(occurrence['index'])
                        entry['busy_observations'].append(dict(index=occurrence['index'], turn_id=turn['id'],
                            user_message_id=user['id'], native_status=turn['status'], command_pid=gate['pid'],
                            clock=clock(), state=occurrence['state'], tool_item_ids=[i['id'] for i in tools]))
                if [i['state'] for i in value['occurrences']] == expected_busy[policy]: break
                time.sleep(.5)
            assert observed == {1,2,3}
            anchors(value, start, 20, 4)
            assert [i['state'] for i in value['occurrences']] == expected_busy[policy]
            save(policy+'-busy.json', value); save(policy+'-native-busy.json', data)
            (case/'release').touch(exist_ok=False)
            expected_done = {'skip':['completed','skipped','skipped','skipped'],
                             'latest':['completed','coalesced','coalesced','completed'],
                             'queue':['completed','skipped','completed','completed']}
            def finished():
                v = owner.read(admitted['id']); assert v['state'] != 'attention', v.get('attention')
                return v if [i['state'] for i in v['occurrences']] == expected_done[policy] else None
            final = wait(finished, 'retained occurrences complete after gate release', 180)
            anchors(final, start, 20, 4); assert final['state'] == 'exhausted'
            data = history(); added = inputs(data)[baseline:]; count = {'skip':1,'latest':2,'queue':3}[policy]
            assert len(added) == count
            wakes = {w.record['id']:w.record for w in all_records(owner.root, include_archive=True)}
            entry['completed_turns'] = []
            for item in final['occurrences']:
                if item['state'] != 'completed':
                    assert not item.get('wake_id'); continue
                wake = wakes[item['wake_id']]; assert wake['attempts'] == 1
                matches = [(t, m) for t, m in added if wake['id'] in json.dumps(m['content'])
                           and wake['native_delivery']['submission_id'] in json.dumps(m['content'])]
                assert len(matches) == 1 and matches[0][0]['status'] == 'completed'
                assert [i['text'] for i in matches[0][0]['items'] if i['type'] == 'agentMessage'] == [marker]
                assert any(i['type'] == 'commandExecution' and str(gate_py) in i.get('command', '') and nonce in i.get('command', '') for i in matches[0][0]['items']), 'completed native command record missing'
                entry['completed_turns'].append(matches[0][0]['id'])
            ended = process_identity(gate['pid'])
            assert ended is None or ended['start_time_ticks'] != gate['start_ticks'], 'gate generation still exists after completion'
            save(policy+'-result.json', final); save(policy+'-native-completed.json', data)
            run(['systemctl','--user','stop',unit]); stopped_units.add(unit)
            owner.cancel(admitted['id'], 1, principal=principal)
            entry['state'] = 'passed'; entry['native_inputs'] = count; baseline += count
        receipt['state'] = 'passed'
    except BaseException as e:
        receipt.update(state='failed', failure=type(e).__name__+': '+str(e))
        raise
    finally:
        errors = []
        for owner, identifier in schedules:
            try: owner.cancel(identifier, owner.read(identifier)['revision'], principal=principal)
            except Exception as e: errors.append('cancel:'+str(e))
        for case in gates:
            (case/'release').touch(exist_ok=True)
        for monitor_unit in monitor_units:
            if monitor_unit not in stopped_units:
                try:
                    r = run(['systemctl','--user','stop',monitor_unit], check=False)
                    if r.returncode: errors.append('monitor stop unconfirmed:'+monitor_unit)
                except Exception as e: errors.append('monitor stop unknown:'+str(e))
        try:
            wait(lambda: all(t['status'] != 'inProgress' for t in history()), 'owned native turns settle', 30)
        except Exception as e:
            errors.append('native turn not settled:'+str(e))
            try:
                active = [t for t in history() if t['status'] == 'inProgress']
                assert len(active) == 1
                receipt['cleanup_interrupt_turn'] = active[0]['id']
                receipt['cleanup_interrupt_result'] = native_request(target['endpoint'], target['executable'],
                    'turn/interrupt', dict(threadId=target['thread_id'], turnId=active[0]['id']), 10)
                wait(lambda: all(t['status'] != 'inProgress' for t in history()), 'own interrupted turn settles', 15)
            except Exception as interrupt_error:
                errors.append('owned interrupt outcome unknown:'+str(interrupt_error))
        for root in roots:
            try: PermissionStore(root).configure(dict(version=1, **{'global':{'default':'deny'}}), principal, expected_revision=1)
            except Exception as e: errors.append('policy:'+str(e))
        try:
            info = address.lstat(); assert stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid()
            inode = (info.st_dev, info.st_ino)
            assert process_identity(target['server_pid']) == target['server_generation']
            assert run(['tmux', '-S', address, 'list-sessions', '-F', '#{session_name}']).stdout.splitlines() == [target['tmux_session']]
            run(['tmux', '-S', address, 'kill-server'])
            wait(lambda: process_identity(target['server_pid']) != target['server_generation']
                 and process_identity(target['tui_pid']) != target['tui_generation'], 'owned terminal generations gone', 20)
            if address.exists():
                probe = run(['tmux', '-S', address, 'list-sessions'], check=False)
                assert probe.returncode == 1 and ('no server running on '+str(address)) in probe.stderr
                fresh = address.lstat(); assert (fresh.st_dev, fresh.st_ino) == inode and fresh.st_uid == os.geteuid()
                assert directory.resolve(strict=True) == directory and not directory.stat().st_mode & 0o077
                address.unlink()
            native_request(target['endpoint'], target['executable'], 'thread/archive', dict(threadId=target['thread_id']), 10)
        except Exception as e: errors.append('terminal/archive:'+str(e))
        receipt['cleanup_errors'] = errors
        receipt['native_preserved'] = process_identity(2082) == receipt.get('native_before')
        if errors or not receipt['native_preserved']: receipt['state'] = 'failed'
        save('receipt.json', receipt)
        print(json.dumps(dict(state=receipt['state'], receipt=str(base/'receipt.json'))))


if __name__ == '__main__':
    main()
