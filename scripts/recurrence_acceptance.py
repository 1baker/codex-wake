#!/usr/bin/env python3
"""Opt-in #685 installed recurrence acceptance; synthetic owned recipient only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


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
    assert target['ticket'] == 685 and target['disposable'] is True
    address = Path(target['tmux_socket']); directory = args.target.absolute().parent
    assert directory.resolve(strict=True) == directory and address.parent == directory
    assert directory.stat().st_uid == os.geteuid() and not directory.stat().st_mode & 0o077
    assert target['tmux_session'].startswith('cw685-')
    base = args.artifacts.absolute(); base.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = dict(os.environ, TMUX=str(address)+',0,0'); env.pop('PYTHONPATH', None)
    os.environ['TMUX'] = env['TMUX']
    for key in ('CODEX_THREAD_ID', 'CODEX_TURN_ID'):
        env.pop(key, None)
    principal = Principal('cw685-operator', 'operator')
    unit = 'cw685-'+base.name+'.service'
    roots, schedules = [], []
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

    def register(owner, label, start, interval, count, missed, overlap):
        request = dict(idempotency_key='cw685-'+base.name+'-'+label, thread_id=target['thread_id'],
            prompt='Reply exactly CW685_CADENCE_COMPLETED. Do not use tools.', session_mode='background',
            cadence=dict(kind='interval', seconds=interval, start_at=iso(start)), end=dict(kind='count', count=count),
            missed=dict(max_lateness_seconds=180, **missed), overlap=overlap, delivery_window_seconds=180)
        r = owner.register(request, codex_path=target['executable'], endpoint=target['endpoint'], principal=principal)
        schedules.append((owner, r['id']))
        return r

    def anchors(value, start, interval, count):
        assert value['next_index'] == count and len(value['occurrences']) == count
        for i, item in enumerate(value['occurrences']):
            assert item['id'] == value['id']+':1:'+str(i)
            assert item['due_at'] == iso(start+interval*i)
            assert item['expires_at'] == iso(start+interval*i+180)

    try:
        receipt['native_before'] = process_identity(2082)
        initial = history(); assert len(inputs(initial)) == 1
        save('native-before.json', initial)
        owner = store('cadence')
        run(['systemd-run', '--user', '--unit='+unit, '--property=RuntimeMaxSec=480',
             '--property=KillMode=process', '--property=UMask=0077', '--working-directory='+target['cwd'],
             '--setenv=TMUX='+env['TMUX'], '--setenv=PATH='+env['PATH'],
             prefix/'bin/codex-waked', '--wake-root', owner.root, '--interval', '1'])
        wait(lambda: (read_monitor_health(owner.root) or {}).get('mode') == 'loop', 'monitor loop')
        start = clock()['utc']['upper']+15
        admitted = register(owner, 'cadence', start, 30, 3, dict(policy='latest'), dict(policy='skip'))
        assert admitted['armed']; save('cadence-registration.json', admitted)
        def finished():
            value = owner.read(admitted['id'])
            assert value['state'] != 'attention', value.get('attention')
            return value if len(value['occurrences']) == 3 and all(x['state'] == 'completed' for x in value['occurrences']) else None
        final = wait(finished, 'three actual completed occurrences', 240)
        anchors(final, start, 30, 3); assert final['state'] == 'exhausted'
        data = history(); added = inputs(data)[1:]; assert len(added) == 3
        wakes = {w.record['id']:w.record for w in all_records(owner.root, include_archive=True)}
        for item in final['occurrences']:
            wake = wakes[item['wake_id']]; assert wake['attempts'] == 1
            matches = [(turn, msg) for turn, msg in added if wake['id'] in json.dumps(msg['content'])
                       and wake['native_delivery']['submission_id'] in json.dumps(msg['content'])]
            assert len(matches) == 1 and matches[0][0]['status'] == 'completed'
            assert [i['text'] for i in matches[0][0]['items'] if i['type'] == 'agentMessage'] == ['CW685_CADENCE_COMPLETED']
        save('cadence-result.json', final); save('native-cadence.json', data)
        receipt['cases'].append(dict(name='repeated-cadence', state='passed', occurrence_ids=[x['id'] for x in final['occurrences']]))
        run(['systemctl', '--user', 'stop', unit])
        owner.cancel(admitted['id'], 1, principal=principal)
        # Independent missed cases: no scheduler polls between registration and all four due slots.
        start = clock()['utc']['upper']+20
        missed_cases = []
        for policy in ('skip', 'latest', 'catch_up'):
            o = store('missed-'+policy); missed = dict(policy=policy)
            if policy == 'catch_up': missed['limit'] = 2
            registered = register(o, 'missed-'+policy, start, 4, 4, missed, dict(policy='queue', limit=2))
            assert not registered['armed']
            missed_cases.append((o, registered['id'], policy))
        wait(lambda: clock()['utc']['lower'] > start+13, 'actual missed polling interval', 60)
        expected = {'skip':['skipped']*4, 'latest':['coalesced']*3+['pending'], 'catch_up':['skipped']*2+['pending','queued']}
        for o, identifier, policy in missed_cases:
            poll_schedules(o.root, clock()); value = o.read(identifier); anchors(value, start, 4, 4)
            assert [i['state'] for i in value['occurrences']] == expected[policy]
            save('missed-'+policy+'.json', value)
            receipt['cases'].append(dict(name='missed-'+policy, state='passed'))
            o.cancel(identifier, 1, principal=principal)
        # Ordinary same-generation polling creates an actual pending wake, then bounded overlap.
        start = clock()['utc']['upper']+20; overlap_cases = []
        for policy in ('skip', 'latest', 'queue'):
            o = store('overlap-'+policy); overlap = dict(policy=policy)
            if policy == 'queue': overlap['limit'] = 2
            r = register(o, 'overlap-'+policy, start, 4, 4, dict(policy='latest'), overlap)
            overlap_cases.append((o, r['id'], policy))
        until = time.monotonic()+70
        while clock()['utc']['lower'] < start+13:
            assert time.monotonic() < until
            c = clock()
            for o, _, _ in overlap_cases: poll_schedules(o.root, c)
            time.sleep(.25)
        expected = {'skip':['pending']+['skipped']*3, 'latest':['pending','coalesced','coalesced','queued'], 'queue':['pending','skipped','queued','queued']}
        for o, identifier, policy in overlap_cases:
            poll_schedules(o.root, clock()); value = o.read(identifier); anchors(value, start, 4, 4)
            assert [i['state'] for i in value['occurrences']] == expected[policy]
            assert len(all_records(o.root, include_archive=True)) == 1
            save('overlap-'+policy+'.json', value)
            receipt['cases'].append(dict(name='overlap-'+policy, state='passed'))
            o.cancel(identifier, 1, principal=principal)
        assert len(inputs(history())) == 4, 'classification cases dispatched native input'
        for o, identifier in schedules:
            code = 'from codex_wake.recurring_schedules import ScheduleStore; import sys; v=ScheduleStore(sys.argv[1]).read(sys.argv[2]); assert v["state"]=="cancelled"'
            run([prefix/'bin/python', '-c', code, o.root, identifier])
        receipt['state'] = 'passed'
    except BaseException as e:
        receipt.update(state='failed', failure=type(e).__name__+': '+str(e))
        raise
    finally:
        errors = []
        for owner, identifier in schedules:
            try: owner.cancel(identifier, owner.read(identifier)['revision'], principal=principal)
            except Exception as e: errors.append('cancel:'+str(e))
        r = run(['systemctl', '--user', 'stop', unit], check=False)
        if r.returncode: errors.append('monitor stop unconfirmed')
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
