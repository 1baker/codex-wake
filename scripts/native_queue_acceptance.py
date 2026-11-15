#!/usr/bin/env python3
"""Opt-in #694 direct native busy queue proof; no native expiry promise."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from uuid import uuid4

from native_busy_overlap_acceptance import GATE_PROGRAM


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-live',action='store_true',required=True)
    p.add_argument('--target',type=Path,required=True)
    p.add_argument('--artifacts',type=Path,required=True)
    p.add_argument('--expected-prefix',type=Path,required=True)
    args=p.parse_args();os.umask(0o077)
    import codex_wake
    from codex_wake.native_protocol import native_request
    from codex_wake.native_clock import snapshot
    from codex_wake.process import process_identity
    from codex_wake.codex_runtime import CodexRuntimeAdapter
    prefix=args.expected_prefix.resolve(strict=True)
    assert Path(sys.executable).absolute().parent==prefix/'bin' and Path(codex_wake.__file__).resolve().is_relative_to(prefix)
    target=json.loads(args.target.read_text());assert target['ticket']==694 and target['disposable'] is True
    directory=args.target.absolute().parent;address=Path(target['tmux_socket'])
    assert directory.resolve(strict=True)==directory and directory.stat().st_uid==os.geteuid() and not directory.stat().st_mode & 0o077
    assert address.parent==directory and target['tmux_session'].startswith('cw694-')
    base=args.artifacts.absolute();base.mkdir(mode=0o700,parents=True,exist_ok=False)
    cwd=Path(target['cwd']);case=cwd/'gate';case.mkdir(mode=0o700)
    gate_py=cwd/'wait.py';gate_py.write_text(GATE_PROGRAM.replace('CW688','CW694'))
    receipt={'ticket':694,'state':'running','target':target,'prefix':str(prefix),'operations':[],
             'expiry_boundary':'native schema has no declared deadline field; host deadline only'}
    owned={};queue_safe=False
    def save(name,value):
        with (base/name).open('x') as f:json.dump(value,f,indent=2)
    def checkpoint():
        tmp=base/'operations.tmp';tmp.write_text(json.dumps(receipt,indent=2));tmp.replace(base/'operations-current.json')
    def rpc(method,params,write=False):
        assert params.get('threadId')==target['thread_id']
        operation=None
        if write:
            operation=dict(index=len(receipt['operations']),method=method,params=params,state='prepared')
            receipt['operations'].append(operation);checkpoint()
        try:
            answer=native_request(target['endpoint'],target['executable'],method,params,15)
            if operation is not None:operation.update(state='observed',response=answer);checkpoint()
            return answer
        except Exception as e:
            if operation is not None:operation.update(state='unknown',error=type(e).__name__);checkpoint()
            raise
    def clock():
        c=snapshot();assert c['utc']['status']=='network' and c['utc']['upper']-c['utc']['lower']<5;return c
    def wait(probe,label,seconds=60):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            v=probe()
            if v:return v
            time.sleep(.5)
        raise TimeoutError(label)
    def history():
        r=rpc('thread/turns/list',dict(threadId=target['thread_id'],limit=16,sortDirection='asc',itemsView='full'))
        assert r['nextCursor'] is None and len({t['id'] for t in r['data']})==len(r['data'])
        assert all(t['itemsView']=='full' for t in r['data']);return r['data']
    def inputs(h):return [(t,i) for t in h for i in t['items'] if i['type']=='userMessage']
    def queued():
        r=rpc('thread/queue/list',dict(threadId=target['thread_id'],limit=100));assert r['nextCursor'] is None
        assert len({i['id'] for i in r['data']})==len(r['data']);return r['data']
    def delete(item):
        r=rpc('thread/queue/delete',dict(threadId=target['thread_id'],queuedSubmissionId=item['id']),write=True)
        assert r['deleted'] is True
        assert not any(i['id']==item['id'] for i in queued())
    def busy():
        h=history();u=inputs(h)
        if len(u)<2:return None
        assert len(u)==2 and u[-1][0]['status']=='inProgress'
        files=list(case.glob('run-*.json'))
        if not files:return None
        assert len(files)==1;gate=json.loads(files[0].read_text());identity=process_identity(gate['pid'])
        assert identity and identity['start_time_ticks']==gate['start_ticks'] and gate['nonce']==nonce
        argv=Path('/proc',str(gate['pid']),'cmdline').read_bytes().split(b'\0')
        assert str(gate_py).encode() in argv and nonce.encode() in argv
        return dict(turn_id=u[-1][0]['id'],user_message_id=u[-1][1]['id'],gate=gate,clock=clock())
    nonce='cw694-'+uuid4().hex
    try:
        receipt['native_before']=process_identity(2082)
        metadata=rpc('thread/read',dict(threadId=target['thread_id'],includeTurns=False))['thread']
        assert metadata['id']==target['thread_id'] and metadata['cwd']==target['cwd']
        before=history();assert len(inputs(before))==1 and not queued();save('native-before.json',before)
        def forbidden(*a,**k):raise AssertionError('unqualified busy policy attempted native I/O')
        adapter=CodexRuntimeAdapter(read_thread=forbidden,request=forbidden,run=forbidden,project_failure=forbidden,busy_policy='queue')
        recipient=adapter.resolve(dict(transport='native',thread_id=target['thread_id'],endpoint=target['endpoint'],codex_cmd=target['executable']))
        refused=adapter.submit(recipient,'unqualified busy policy proof')
        assert refused.state=='not_sent' and refused.pre_io is True and refused.reason=='busy_policy_unsupported'
        receipt['wake_refusal']=asdict(refused)
        command='/usr/bin/python3 '+str(gate_py)+' '+str(case)+' '+nonce
        block_prompt=('Run this exact command once with exec_command and wait for it to finish using write_stdin if needed. '
            'Do not run other commands or create the release file; the host will release this bounded gate. '
            'After success reply exactly CW694_BLOCK_COMPLETED. Command: '+command)
        started=rpc('turn/start',dict(threadId=target['thread_id'],input=[dict(type='text',text=block_prompt)]),write=True)
        receipt['block_start']=started;witness=wait(busy,'real native blocker command');receipt['busy_before_add']=witness
        for name in ('cancel','deadline','control'):
            client=str(uuid4());text='Reply exactly CW694_'+name.upper()+'_COMPLETED. Do not use tools.'
            owned[client]={'name':name,'client':client,'text':text};checkpoint()
            answer=rpc('thread/queue/add',dict(threadId=target['thread_id'],clientUserMessageId=client,input=[dict(type='text',text=text)]),write=True)
            item=answer['queuedSubmission'];assert item['clientUserMessageId']==client and [i['text'] for i in item['input']]==[text]
            owned[client]['item']=item;receipt['owned_entries']=owned;checkpoint();busy()
        q=queued();assert {i['clientUserMessageId'] for i in q}==set(owned);save('queue-all.json',q)
        byname={v['name']:v for v in owned.values()}
        delete(byname['cancel']['item']);receipt['cancel_before_idle']='confirmed_deleted_and_absent'
        deadline=clock()['utc']['upper']+10;receipt['host_only_deadline']=deadline;checkpoint()
        wait(lambda: clock()['utc']['lower']>deadline,'host deadline crossing',30)
        receipt['busy_after_host_deadline']=busy();q=queued();assert any(i['id']==byname['deadline']['item']['id'] for i in q)
        save('queue-after-host-deadline.json',q)
        receipt['native_expiry']='not_qualified: no deadline communicated to native; item retained past host-only deadline'
        delete(byname['deadline']['item']);q=queued();assert len(q)==1 and q[0]['id']==byname['control']['item']['id']
        queue_safe=True;receipt['before_release']=busy();save('queue-before-release.json',q)
        (case/'release').touch(exist_ok=False)
        def completed():
            h=history();u=inputs(h)
            assert not any(v['text'] in json.dumps(i['content']) for v in (byname['cancel'],byname['deadline']) for _,i in u)
            assert len(u)<=3
            if len(u)!=3 or any(t['status']!='completed' for t,_ in u):return None
            return h
        after=wait(completed,'control dequeue and completion',90);u=inputs(after);control_turn,control_msg=u[-1]
        assert [i['text'] for i in control_msg['content']]==[byname['control']['text']]
        assert control_msg.get('clientId')==byname['control']['client'] or control_msg['id']==byname['control']['client']
        assert [i['text'] for i in control_turn['items'] if i['type']=='agentMessage' and i.get('phase')=='final_answer']==['CW694_CONTROL_COMPLETED']
        block_turn=u[1][0];assert block_turn['id']==witness['turn_id']
        assert [i['text'] for i in block_turn['items'] if i['type']=='agentMessage' and i.get('phase')=='final_answer']==['CW694_BLOCK_COMPLETED']
        assert any(i['type']=='commandExecution' and nonce in i.get('command','') for i in block_turn['items'])
        assert not queued();save('native-completed.json',after)
        receipt['control_result']=dict(turn_id=control_turn['id'],user_message_id=control_msg['id'],client_id=byname['control']['client'],native_inputs_after_setup=2)
        receipt['state']='passed_with_native_expiry_unqualified'
    except BaseException as e:
        receipt.update(state='failed',failure=type(e).__name__+': '+str(e));raise
    finally:
        errors=[]
        try:
            q=queued()
            for item in q:
                client=item['clientUserMessageId']
                if client in owned:
                    assert [i['text'] for i in item['input']]==[owned[client]['text']]
                    delete(item)
                else:raise AssertionError('unowned queue input; no deletion authority')
            assert not queued();queue_safe=True
        except Exception as e:errors.append('queue cleanup unknown:'+str(e));queue_safe=False
        if queue_safe:(case/'release').touch(exist_ok=True)
        try:
            wait(lambda: all(t['status']!='inProgress' for t in history()),'owned native settles',30)
        except Exception as e:
            errors.append('native not settled:'+str(e))
            try:
                active=[t for t in history() if t['status']=='inProgress'];assert len(active)==1
                rpc('turn/interrupt',dict(threadId=target['thread_id'],turnId=active[0]['id']),write=True)
                wait(lambda: all(t['status']!='inProgress' for t in history()),'owned interrupt settles',15)
            except Exception as error:errors.append('own interrupt unknown:'+str(error))
        try:
            assert directory.resolve(strict=True)==directory and not directory.stat().st_mode & 0o077
            info=address.lstat();assert stat.S_ISSOCK(info.st_mode) and info.st_uid==os.geteuid();inode=(info.st_dev,info.st_ino)
            assert process_identity(target['server_pid'])==target['server_generation']
            sessions=subprocess.check_output(['tmux','-S',str(address),'list-sessions','-F','#{session_name}'],text=True).splitlines();assert sessions==[target['tmux_session']]
            subprocess.run(['tmux','-S',str(address),'kill-server'],check=True,timeout=15)
            wait(lambda: process_identity(target['server_pid'])!=target['server_generation'] and process_identity(target['tui_pid'])!=target['tui_generation'],'owned terminal gone',20)
            if address.exists():
                r=subprocess.run(['tmux','-S',str(address),'list-sessions'],capture_output=True,text=True,timeout=10)
                assert r.returncode==1 and ('no server running on '+str(address)) in r.stderr
                now=address.lstat();assert (now.st_dev,now.st_ino)==inode and now.st_uid==os.geteuid();address.unlink()
            rpc('thread/archive',dict(threadId=target['thread_id']),write=True)
        except Exception as e:errors.append('terminal/archive unknown:'+str(e))
        receipt['cleanup_errors']=errors;receipt['native_preserved']=process_identity(2082)==receipt.get('native_before')
        if errors or not receipt['native_preserved']:receipt['state']='failed'
        checkpoint();save('receipt.json',receipt);print(json.dumps(dict(state=receipt['state'],receipt=str(base/'receipt.json'))))


if __name__=='__main__':main()
