#!/usr/bin/env python3
"""Opt-in #681 acceptance using one actual, privately prepared native recipient.

Run with the qualified installed package's Python after coordinator readiness.
The target manifest selects only an already saved, uniquely attached disposable
thread. No daemon, provider session, or schedule is created by --help.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-prefix', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    # Imports intentionally follow argument parsing so preparation is effect-free.
    import codex_wake
    from codex_wake.process import process_identity
    from codex_wake.sessions import observe
    from codex_wake.native_protocol import native_request
    from codex_wake.recurring_schedules import ScheduleStore
    from codex_wake.session_permissions import PermissionStore, Principal
    from codex_wake.records import find_record
    from codex_wake.monitor import read_monitor_health
    from codex_wake.native_clock import snapshot

    prefix = args.expected_prefix.resolve(strict=True)
    assert Path(sys.executable).absolute().parent == prefix/'bin', 'Use exact installed Python'
    assert Path(codex_wake.__file__).resolve().is_relative_to(prefix), 'Source shadowing forbidden'
    owned = json.loads(args.target.read_text())
    assert owned['ticket']==681 and owned['disposable'] is True, 'Explicit owned target required'
    thread, endpoint = owned['thread_id'], owned['endpoint']
    socket = Path(owned['tmux_socket']).absolute()
    cwd = Path(owned['cwd']).resolve(strict=True)
    native = Path(owned['executable']).resolve(strict=True)
    session = owned['tmux_session']
    assert socket.is_absolute() and socket.name != 'default' and session.startswith('cw681-')
    target_directory = args.target.absolute().parent
    assert target_directory == target_directory.resolve(strict=True), 'Private target directory must not traverse symlinks'
    target_info = target_directory.stat()
    assert target_info.st_uid==os.geteuid() and not target_info.st_mode & 0o077, 'Private owned target directory required'
    assert socket.parent==target_directory, 'Socket must be inside dedicated private target directory'
    base = args.artifacts.absolute()
    base.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = base/'wake'; root.mkdir(mode=0o700)
    unit = 'cw681-monitor-'+base.name+'.service'
    env = dict(os.environ, TMUX=str(socket)+',0,0')
    env.pop('PYTHONPATH', None)
    # API registration observes this process environment, while CLI/service
    # children receive the identical explicit private socket.
    os.environ['TMUX'] = env['TMUX']
    for key in ('CODEX_THREAD_ID', 'CODEX_TURN_ID'):
        env.pop(key, None)
    receipt = dict(ticket=681, status='running', package=str(Path(codex_wake.__file__).resolve()),
                   python=sys.executable, started_at=stamp(time.time()), target=owned,
                   wake_root=str(root), monitor_unit=unit, scenarios=[], commands=[],
                   memory_disposition='forbidden', memory_reason='No memory write authority')
    operator = Principal('cw681-operator', 'operator')
    schedules = ScheduleStore(root)
    enrolled = None
    pending = []

    def save(name, value):
        path = base/name
        with path.open('x') as output:
            json.dump(value, output, indent=2)
        return str(path)

    def run(argv, *, check=True):
        result = subprocess.run([str(x) for x in argv], env=env, cwd=cwd,
                                capture_output=True, text=True, timeout=45)
        receipt['commands'].append(dict(argv=[str(x) for x in argv], code=result.returncode,
                                       stdout=result.stdout, stderr=result.stderr))
        if check and result.returncode:
            raise RuntimeError('Command failed: '+str(argv[0:3]))
        return result

    server_custody = None

    def kill_owned_server():
        nonlocal server_custody
        # Revalidate physical custody immediately before every destructive command.
        assert socket.parent==target_directory and target_directory.resolve(strict=True)==target_directory
        info=target_directory.stat()
        assert info.st_uid==os.geteuid() and not info.st_mode & 0o077
        try: info=socket.lstat()
        except FileNotFoundError: return
        assert not socket.is_symlink() and stat.S_ISSOCK(info.st_mode) and info.st_uid==os.geteuid()
        assert socket.resolve(strict=True)==socket
        inode=(info.st_dev, info.st_ino, info.st_uid)
        listed=run(['tmux', '-S', socket, 'list-sessions', '-F', '#{session_name}'], check=False)
        if listed.returncode==0:
            assert listed.stdout.splitlines()==[session], 'Private server contains undeclared sessions'
            server_pid=int(run(['tmux', '-S', socket, 'display-message', '-p', '#{pid}']).stdout.strip())
            generation=process_identity(server_pid)
            assert generation, 'Exact owned tmux server generation required'
            attachment=row()['attachments']
            assert len(attachment)==1
            tui_pid=attachment[0]['client_pid']; tui_generation=process_identity(tui_pid)
            assert tui_generation, 'Exact owned TUI generation required'
            server_custody=dict(inode=inode, pid=server_pid, generation=generation,
                                tui_pid=tui_pid, tui_generation=tui_generation)
            receipt.setdefault('server_removals', []).append(server_custody.copy())
            run(['tmux', '-S', socket, 'kill-server'])
        else:
            assert server_custody is not None, 'Dead socket lacks prior exact server custody'
        custody=server_custody
        assert custody['inode']==inode, 'Socket inode changed since owned kill'
        wait_for(lambda: process_identity(custody['pid'])!=custody['generation']
                 and process_identity(custody['tui_pid'])!=custody['tui_generation'],
                 'exact owned server and TUI generations gone', 20)
        if not socket.exists(): return
        # tmux can leave its physical socket inode after a successful kill-server.
        # Remove only that captured inode, after a specific cannot-connect result.
        dead=run(['tmux', '-S', socket, 'list-sessions', '-F', '#{session_name}'], check=False)
        assert dead.returncode==1 and not dead.stdout and dead.stderr.strip() in (
            'no server running on '+str(socket),
            'error connecting to '+str(socket)+' (Connection refused)'), 'Server absence unproven'
        info=target_directory.stat()
        assert target_directory.resolve(strict=True)==target_directory and info.st_uid==os.geteuid() and not info.st_mode & 0o077
        stale=socket.lstat()
        assert stat.S_ISSOCK(stale.st_mode) and not socket.is_symlink()
        assert (stale.st_dev, stale.st_ino, stale.st_uid)==custody['inode']
        assert process_identity(custody['pid'])!=custody['generation']
        assert process_identity(custody['tui_pid'])!=custody['tui_generation']
        socket.unlink()
        receipt['server_removals'][-1]['original_stale_inode_removed']=True

    def cli(*argv):
        return json.loads(run([prefix/'bin/codex-wake', '--wake-root', root, *argv]).stdout)

    def wait_for(probe, label, seconds=60):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            value = probe()
            if value:
                return value
            time.sleep(.5)
        raise TimeoutError(label)

    def row():
        observed = observe(endpoint=endpoint, socket_path=str(socket), timeout=15)
        selected = [r for r in observed.get('sessions', []) if r.get('thread_id')==thread]
        assert observed['complete'] and len(selected)==1, observed
        return selected[0]

    def history():
        deadline = time.monotonic()+30
        metadata = native_request(endpoint, str(native), 'thread/read',
                                  dict(threadId=thread, includeTurns=False), 10)['thread']
        assert metadata['id']==thread and metadata['cwd']==str(cwd)
        turns, ids, cursors, cursor = [], set(), set(), None
        for unused in range(8):
            remaining = deadline-time.monotonic()
            assert remaining>0, 'Native history absolute deadline'
            params=dict(threadId=thread, limit=8, sortDirection='asc', itemsView='full', cursor=cursor)
            page=native_request(endpoint, str(native), 'thread/turns/list', params, remaining)
            assert isinstance(page.get('data'), list), page
            for turn in page['data']:
                assert turn['id'] not in ids and turn.get('itemsView')=='full', 'Incomplete or duplicate native turn'
                ids.add(turn['id']); turns.append(turn)
            assert 'nextCursor' in page, 'Missing native pagination completeness marker'
            cursor=page['nextCursor']
            if cursor is None:
                return dict(metadata, turns=turns)
            assert isinstance(cursor, str) and cursor and cursor not in cursors
            cursors.add(cursor)
        raise RuntimeError('Native history page budget exceeded')

    def start_monitor():
        prior = (read_monitor_health(root) or {}).get('reader_generation')
        run(['systemd-run', '--user', '--unit='+unit, '--property=RuntimeMaxSec=1200',
             '--property=Restart=no', '--property=KillMode=process', '--property=UMask=0077', '--working-directory='+str(cwd),
             '--setenv=TMUX='+env['TMUX'], '--setenv=PATH='+env['PATH'],
             prefix/'bin/codex-waked', '--wake-root', root, '--interval', '1'])
        def fresh_monitor():
            health = read_monitor_health(root) or {}
            return (health.get('mode')=='loop' and health.get('reader_generation')!=prior
                    and process_identity(health.get('pid', 0)) is not None)
        wait_for(fresh_monitor, 'fresh live monitor generation')
        health = read_monitor_health(root)
        check = cli('monitor', 'check', '--name', unit, '--json')
        save('monitor-'+str(len(receipt['commands']))+'.json', dict(health=health, check=check))
        return health

    try:
        receipt['native_daemon_before'] = process_identity(2082)
        assert receipt['native_daemon_before'], 'Required existing native daemon missing'
        initial = row()
        assert initial['binding_status']=='metadata_matched' and len(initial['attachments'])==1
        assert initial['cwd']==str(cwd) and initial['attachments'][0]['socket']==str(socket)
        assert Path('/proc/'+str(initial['attachments'][0]['client_pid'])+'/exe').resolve()==native
        before_history = history()
        inputs = lambda data: [(turn, item) for turn in data.get('turns', []) for item in turn.get('items', []) if item.get('type')=='userMessage']
        assert len(inputs(before_history))==1, 'Exactly one real saved setup input required'
        save('native-before.json', before_history)
        allowed = {action:dict(decision='allow', targets=[thread]) for action in
                   ('session.inspect', 'resume.recover', 'wake.existing_tab', 'wake.new_tab')}
        receipt['isolated_policy'] = PermissionStore(root).configure(dict(version=1, **{'global':{'default':'deny'},
            'sessions':{operator.subject:{'actions':allowed}}}), operator, expected_revision=0)
        enrolled = cli('agents', 'enroll', '--operator', '--conversation-id', thread,
                       '--app-server', endpoint, '--tmux-socket', str(socket), '--json')['agent']['managed_agent_id']
        profiles = base/'profiles.json'
        save('profiles.json', dict(version=1, profiles={'cw681':dict(cwd=str(cwd), app_server=endpoint,
            codex_path=str(native), tmux_session=session, tmux_socket=str(socket), timeout=30)},
            callers={operator.subject:['cw681']}, recovery_callers={operator.subject:[enrolled]}))
        (root/'wake-live-restore.json').write_text(json.dumps(dict(version=1, bindings={thread:dict(
            profiles=str(profiles), managed_agent_id=enrolled, profile='cw681')})))
        (root/'controller-tabs.json').write_text(json.dumps(dict(schema_version=1, workspaces={
            'cw681':dict(kind='byobu', socket_path=str(socket), session_id=initial['attachments'][0]['session_id'])})))
        start_monitor()
        for number, scenario in enumerate(('complete-container-loss', 'owned-monitor-restart'), 1):
            entry = dict(scenario=scenario); receipt['scenarios'].append(entry)
            attached = row(); old = attached['attachments'][0]
            clock = snapshot()
            assert clock['utc']['status']=='network', clock
            assert clock['utc']['upper']-clock['utc']['lower']<5, clock
            due = clock['utc']['upper']+75
            marker = 'CW681_'+str(number)+'_COMPLETED'
            request = dict(idempotency_key='cw681-'+base.name+'-'+str(number), thread_id=thread,
                prompt='Reply exactly '+marker+'. Do not use tools.', session_mode='reopen_live',
                cadence=dict(kind='interval', seconds=30, start_at=stamp(due)), end=dict(kind='count', count=1),
                missed=dict(policy='latest', max_lateness_seconds=180), overlap=dict(policy='skip'), delivery_window_seconds=180)
            registered = schedules.register(request, codex_path=str(native), endpoint=endpoint, principal=operator)
            pending.append(registered['id']); entry['registration']=registered
            assert registered['armed']
            assert registered['target']['tmux_socket']==str(socket)
            assert registered['target']['session_origin']['pid']==old['client_pid']
            original = dict(target=registered['target'], request=registered['request'], next_due_at=registered['next_due_at'])
            baseline = history(); count = len(inputs(baseline))
            if number==1:
                kill_owned_server()
                wait_for(lambda: not socket.exists() and process_identity(old['client_pid']) is None, 'whole owned container and TUI gone')
                entry['whole_loss']=dict(socket_absent=not socket.exists(), old_generation_absent=process_identity(old['client_pid']) is None)
            else:
                recipient_generation=process_identity(old['client_pid'])
                assert recipient_generation, 'Restored TUI must be live before monitor-only restart'
                entry['recipient_before_monitor_restart']=recipient_generation
                entry['monitor_before']=read_monitor_health(root)
                run(['systemctl', '--user', 'stop', unit])
                run(['systemctl', '--user', 'reset-failed', unit], check=False)
                entry['monitor_after']=start_monitor()
                assert entry['monitor_before']['reader_generation'] != entry['monitor_after']['reader_generation']
                entry['recipient_after_monitor_restart']=process_identity(old['client_pid'])
                assert entry['recipient_after_monitor_restart']==recipient_generation, 'Monitor-only restart killed recipient'
            assert snapshot()['utc']['upper']<due, 'Disruption must finish before due'
            saved = schedules.read(registered['id'])
            assert all(saved[key]==value for key, value in original.items()), 'Original intent changed'
            entry['intent_after_disruption']=dict(target=saved['target'], request=saved['request'], next_due_at=saved['next_due_at'])
            def completed():
                shown=schedules.read(registered['id']); entry['schedule_after']=shown
                if shown.get('state')=='attention':
                    raise RuntimeError('Schedule attention; preserve original journals')
                if len(shown.get('occurrences', []))!=1:
                    return None
                occurrence=shown['occurrences'][0]
                assert occurrence['due_at']==stamp(due) and occurrence['expires_at']==stamp(due+180)
                if not occurrence.get('wake_id'):
                    return None
                wake=find_record(root, occurrence['wake_id']).record; entry['wake']=wake
                # Uncertain while firing is the normal durable before-I/O fence.
                # Observe this same intent only; neither this probe nor cleanup retries it.
                if wake.get('status') in ('failed', 'expired', 'cancelled', 'archived'):
                    raise RuntimeError('Terminal wake outcome; preserve original journals')
                data=history()
                fresh=inputs(data)[count:]
                assert len(fresh)<=1, 'Duplicate native input'
                if len(fresh)!=1 or fresh[0][0].get('status')!='completed':
                    return None
                text='\n'.join(c.get('text','') for c in fresh[0][1].get('content', []))
                assert wake['id'] in text and wake['native_delivery']['submission_id'] in text
                answers=[i for i in fresh[0][0]['items'] if i.get('type')=='agentMessage']
                assert len(answers)==1 and answers[0]['text'].strip()==marker
                assert wake['attempts']==1
                if wake.get('native_delivery', {}).get('state')!='accepted':
                    return None
                save('native-after-'+str(number)+'.json', data)
                return dict(turn_id=fresh[0][0]['id'], user_message_id=fresh[0][1]['id'], reply=marker)
            entry['result']=wait_for(completed, scenario, 300)
            restored=row(); entry['restored']=restored
            assert restored['binding_status']=='metadata_matched' and len(restored['attachments'])==1
            after=restored['attachments'][0]
            assert restored['cwd']==str(cwd) and after['socket']==str(socket) and after['session_name']==session
            assert Path('/proc/'+str(after['client_pid'])+'/exe').resolve()==native
            if number==1:
                assert after['client_pid']!=old['client_pid']
            schedules.cancel(registered['id'], 1, principal=operator)
        receipt['status']='passed'
    except BaseException as error:
        receipt.update(status='failed', failure_type=type(error).__name__, failure=str(error))
        raise
    finally:
        cleanup=[]
        for identifier in pending:
            try: schedules.cancel(identifier, schedules.read(identifier)['revision'], principal=operator)
            except Exception as error: cleanup.append(dict(schedule=identifier, error=str(error)))
        try:
            stopped=run(['systemctl', '--user', 'stop', unit], check=False)
            if stopped.returncode: cleanup.append(dict(monitor_stop='unconfirmed', code=stopped.returncode))
        except Exception as error: cleanup.append(dict(monitor_stop='unknown', error=str(error)))
        try: kill_owned_server()
        except Exception as error: cleanup.append(dict(socket_cleanup='unknown', error=str(error)))
        if enrolled:
            try: receipt['unenrollment']=cli('agents', 'unenroll', '--operator', '--managed-agent-id', enrolled, '--json')
            except Exception as error: cleanup.append(dict(enrollment= str(error)))
        # Revoke isolated authority while retaining every immutable launch/delivery journal.
        try:
            policy=PermissionStore(root)
            if policy.active(): receipt['authority_cleanup']=policy.configure(dict(version=1, **{'global':{'default':'deny'}}), operator, expected_revision=1)
        except Exception as error: cleanup.append(dict(policy=str(error)))
        try:
            native_request(endpoint, str(native), 'thread/archive', dict(threadId=thread), 20)
            receipt['disposable_thread']='archived'
        except Exception as error: cleanup.append(dict(archive=str(error)))
        receipt['cleanup_errors']=cleanup
        receipt['native_daemon_after']=process_identity(2082)
        receipt['native_daemon_preserved']=receipt.get('native_daemon_before')==receipt['native_daemon_after']
        receipt['private_socket_absent']=not socket.exists()
        if cleanup or not receipt['native_daemon_preserved'] or not receipt['private_socket_absent']:
            receipt['status']='failed'
        receipt['finished_at']=stamp(time.time())
        save('receipt.json', receipt)
        print(json.dumps(dict(status=receipt['status'], receipt=str(base/'receipt.json'))))


if __name__=='__main__':
    main()
