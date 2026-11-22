#!/usr/bin/env python3
"""Installed CLI/stdio/OAuth acceptance; disposable state, no source path injection."""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request,urlopen


def result(value):
    """Unwrap the documented CLI/API/common-operation envelopes."""
    while isinstance(value,dict) and 'result' in value:
        value=value['result']
        if isinstance(value,dict) and 'operation' in value and isinstance(value['operation'],dict):value=value['operation']
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--windows-python')
    parser.add_argument('--psmux',action='store_true',help='Use an owned native psmux workspace instead of tmux.')
    parser.add_argument('--wheel',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    if args.psmux and not args.windows_python:parser.error('--psmux requires --windows-python')
    import codex_wake
    package=Path(codex_wake.__file__).resolve().parent;prefix=Path(sys.prefix).resolve()
    assert package.is_relative_to(prefix),(package,prefix)
    assert not os.environ.get('PYTHONPATH'),'Unset PYTHONPATH for installed acceptance'
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    cli=str(prefix/'bin/codex-wake');checks=[];windows={};server=None
    with tempfile.TemporaryDirectory(prefix='wake-format524-') as directory:
        root=Path(directory)/'wake';root.mkdir(mode=0o700);sock=str(Path(directory)/'tmux.sock')
        def tmux(*argv,check=True):return subprocess.run(['tmux','-S',sock,*argv],text=True,capture_output=True,check=check,timeout=5).stdout
        native=NativePsmuxFixture(args.windows_python) if args.psmux else None
        if native:tmux=native.command
        tmux('new-session','-d','-s','installed','-n','original','exec sleep 120')
        before=tmux('show-options','-w','-t','@0');before_session=tmux('show-options','-t','$0');before_pane=tmux('list-panes','-F','#{pane_id}:#{pane_pid}')
        config=root/'controller-tabs.json';config.write_text(json.dumps(dict(schema_version=1,workspaces=dict(work=native.configuration() if native else dict(kind='tmux',socket_path=sock,session_id='$0')))));config.chmod(0o600)
        def command(*argv,expected=0):
            if argv and argv[0] == 'tabs' and '--json' not in argv:
                argv = (*argv, '--json')
            p=subprocess.run([cli,'--wake-root',str(root),*argv],env=env,cwd=directory,text=True,capture_output=True,timeout=30)
            assert p.returncode==expected,(p.returncode,p.stdout,p.stderr)
            return json.loads(p.stdout)
        def continuity():
            return [(r['window']['window_id'],r['window']['name'],[(p['pane_id'],p['pid'],p.get('windows_creation_filetime') or p.get('process_generation')) for p in r['window']['panes']]) for r in command('tabs','list')['resources']]
        before_identity=continuity()
        def target():return command('tabs','format','status','--workspace','work')['target']
        def request(verb,extra=None):
            pin=target();identifier='format524-'+uuid.uuid4().hex
            return dict(workspace='work',expected_target=pin,_request=dict(operation_id=identifier,idempotency_key=identifier,correlation_id=identifier,binding='installed-fixture',target=pin),**(extra or {}))
        def restored():
            assert tmux('show-options','-w','-t','@0')==before
            assert tmux('show-options','-t','$0')==before_session
            assert tmux('list-panes','-F','#{pane_id}:#{pane_pid}')==before_pane
        try:
            for verb in ('enable','rollback','reenable','rollback'):
                value=command('tabs','format',verb,'--workspace','work')
                assert result(value)['status']==('rolled_back' if verb=='rollback' else 'applied'),value
            restored();checks.append('installed-wsl-cli-repeated-exact-rollback-reenable')
            # Completion/help come from this installed parser, without user setup.
            help_text=subprocess.check_output([cli,'tabs','format','--help'],env=env,text=True)
            assert 'rollback' in help_text and 'reenable' in help_text
            from codex_wake.completion import candidates
            choices=candidates(['tabs','format',''],2)
            assert {'rollback','reenable','configure','inspect'}<=set(choices),choices
            for shell in ('bash','zsh'):
                text=subprocess.check_output([cli,'completion',shell],env=env,text=True);assert 'codex-wake' in text
            checks.append('installed-parser-help-bash-zsh-completion')
            async def stdio():
                from mcp import ClientSession,StdioServerParameters
                from mcp.client.stdio import stdio_client
                parameters=StdioServerParameters(command=str(prefix/'bin/codex-wake-mcp'),args=['--wake-root',str(root)],env=env)
                async with stdio_client(parameters) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        tools={t.name for t in (await session.list_tools()).tools}
                        assert {'wake_tabs_format_enable','wake_tabs_format_rollback','wake_tabs_format_reenable'}<=tools
                        for verb in ('reenable','rollback'):
                            called=await session.call_tool('wake_tabs_format_'+verb,request(verb))
                            assert not called.is_error,called
                            value=json.loads(called.content[0].text)
                            assert result(value)['status']==('rolled_back' if verb=='rollback' else 'applied'),value
                        policy_before=command('tabs','format','status','--workspace','work')['policy']
                        invalid=await session.call_tool('wake_tabs_format_configure',request('configure',dict(policy={'render_mode':'invalid'})))
                        rejected=json.loads(invalid.content[0].text)
                        assert rejected['result']['operation']['reason']=='invalid_argument',rejected
                        assert command('tabs','format','status','--workspace','work')['policy']==policy_before
                restored()
            asyncio.run(stdio());checks.append('real-installed-stdio-mcp-client-init-list-call-and-invalid-policy')
            port_socket=socket.socket();port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1];port_socket.close()
            endpoint='http://127.0.0.1:'+str(port);resource=endpoint+'/controller'
            command('controller','auth-configure','--issuer',endpoint,'--resource',resource,'--owner','synthetic-format-owner')
            server=subprocess.Popen([cli,'--wake-root',str(root),'controller','serve','--port',str(port)],env=env,cwd=directory,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            def http(path,body=None,token=None):
                data=json.dumps(body).encode() if body is not None else None
                headers={'Content-Type':'application/json'}
                if token:headers['Authorization']='Bearer '+token
                try:
                    with urlopen(Request(endpoint+path,data=data,headers=headers),timeout=15) as response:return response.status,json.loads(response.read() or b'{}')
                except HTTPError as error:return error.code,json.loads(error.read() or b'{}')
            until=time.monotonic()+5
            while True:
                try:
                    if http('/.well-known/oauth-authorization-server')[0]==200:break
                except OSError:pass
                assert time.monotonic()<until,'listener unavailable';time.sleep(.02)
            assert http('/operations',dict(operation='tabs.format.status',arguments={'workspace':'work'}))[0]==401
            client=http('/register',dict(redirect_uris=['http://127.0.0.1:45000/callback'],client_name='format524'))[1]
            verifier='x'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            pin=target();scope={k:v for k,v in pin.items() if k!='generation'}
            code=command('controller','authorize-client','--client-id',client['client_id'],'--redirect-uri',client['redirect_uris'][0],'--subject','synthetic-format-service','--principal-kind','service','--scope','control','--scope','observe','--targets',json.dumps([scope]),'--code-challenge',challenge)['code']
            status,tokens=http('/token',dict(grant_type='authorization_code',client_id=client['client_id'],redirect_uri=client['redirect_uris'][0],code=code,code_verifier=verifier,resource=resource))
            assert status==200,tokens;token=tokens['access_token']
            for transport in ('api','mcp'):
                for verb in ('reenable','rollback'):
                    payload=request(verb)
                    if transport=='api':status,value=http('/operations',dict(operation='tabs.format.'+verb,arguments=payload),token)
                    else:
                        status,value=http('/mcp',dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='wake_tabs_format_'+verb,arguments=payload)),token)
                        value=value['result']['structuredContent']
                    assert status==200 and result(value)['status']==('rolled_back' if verb=='rollback' else 'applied'),value
                restored()
            policy_before=command('tabs','format','status','--workspace','work')['policy']
            for transport in ('api','mcp'):
                payload=request('configure',dict(policy={'render_mode':'invalid'}))
                if transport=='api':status,value=http('/operations',dict(operation='tabs.format.configure',arguments=payload),token)
                else:
                    status,value=http('/mcp',dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name='wake_tabs_format_configure',arguments=payload)),token)
                    value=value['result']['structuredContent']
                assert status==200 and value['result']['operation']['reason']=='invalid_argument',value
                assert command('tabs','format','status','--workspace','work')['policy']==policy_before
            checks.append('authenticated-http-api-and-oauth-mcp-exact-format-controls-and-error-reasons')
            window=before_identity[0][0]
            style=dict(foreground='yellow',background='blue',attributes=['bold','underscore'])
            applied=command('tabs','format','override-set','--workspace','work',
                            '--window',window,'--style',json.dumps(style))
            assert result(applied)['override']==style,applied
            reenabled=command('tabs','format','reenable','--workspace','work')
            assert result(reenabled)['status']=='applied',reenabled
            status,value=http('/operations',dict(operation='tabs.format.override-inspect',
                arguments=dict(workspace='work',window=window)),token)
            assert status==200 and result(value)['override']==style,value
            assert result(value)['options']['window-status-style']['effective']=='fg=yellow,bg=blue,bold,underscore',value
            payload=request('override-clear',dict(window=window))
            status,value=http('/mcp',dict(jsonrpc='2.0',id=3,method='tools/call',
                params=dict(name='wake_tabs_format_override_clear',arguments=payload)),token)
            cleared=value['result']['structuredContent']
            assert status==200 and result(cleared)['override'] is None,value
            assert result(command('tabs','format','rollback','--workspace','work'))['status']=='rolled_back'
            restored()
            checks.append('installed-cli-api-mcp-tab-override-survives-automatic-style')
            if args.windows_python:
                windows=qualify_windows(args.windows_python,args.wheel,endpoint,token,request,window)
                restored();checks.append('actual-native-powershell-installed-cli-api-and-mcp-controls')
            assert continuity()==before_identity,'Native pane/process birth identity changed.'
            # All loaded Wake modules must come from the isolated immutable prefix.
            loaded={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if name.startswith('codex_wake') and getattr(module,'__file__',None)}
            assert all(Path(path).is_relative_to(prefix) for path in loaded.values()),loaded
            report=dict(status='PASS',python=sys.executable,prefix=str(prefix),package=str(package),loaded_modules=loaded,
                checks=checks,windows=windows,provider_calls=0,production_touched=False,owned_monitor_started=command('tabs','monitor-status')['monitor']['status']=='running',
                backend='psmux' if native else 'tmux',native_identity=native.identity if native else None,native_pane_process_preserved=True,native_pane_births_preserved=True,exact_originals_restored=True)
        finally:
            if server:
                server.terminate();server.wait(timeout=5)
                if server.stderr:server.stderr.close()
            # Public enable may own the single fixture monitor; rollback does not stop it.
            try:stopped=result(command('tabs','monitor-stop'))['monitor']['status']
            finally:
                tmux('kill-server',check=False)
                if native:native.close()
    report['owned_monitor_final_status']=stopped
    report['owned_listener_terminated']=server is None or server.poll() is not None
    report['owned_namespace_removed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status='PASS',checks=len(checks),receipt=str(args.output))))


class NativePsmuxFixture:
    """One disposable native namespace; shared public acceptance stays unchanged."""
    def __init__(self,python):
        from codex_wake import tab_psmux_bridge
        self.python=python;self.namespace='wake524-'+uuid.uuid4().hex[:12]
        self.directory=Path('/mnt/c/Users/ecoch/AppData/Local/codex-wake-test')/self.namespace
        self.directory.mkdir(parents=True,exist_ok=False)
        self.helper=self.directory/'fixture.py'
        self.helper.write_text("import json,os,subprocess,sys\nfrom pathlib import Path\np=Path(os.environ['LOCALAPPDATA'])/'Microsoft/WinGet/Links/psmux.exe'\nr=subprocess.run([str(p),'-L',sys.argv[1],*sys.argv[2:]],text=True,capture_output=True,timeout=8)\nprint(json.dumps(dict(rc=r.returncode,out=r.stdout,err=r.stderr)))\n")
        self.bridge=self.directory/'bridge.py';shutil.copyfile(tab_psmux_bridge.__file__,self.bridge)
        self.window=None

    def winpath(self,path):return subprocess.check_output(['wslpath','-w',str(path)],text=True).strip()

    def raw(self,*args):
        return json.loads(subprocess.check_output([self.python,self.winpath(self.helper),self.namespace,*args],text=True,timeout=12))

    def command(self,*args,check=True):
        args=[self.window if arg=='@0' and self.window else 'installed' if arg=='$0' else arg for arg in args]
        if args[0]=='new-session':args=args[:-1]+['--','cmd.exe','/d','/k']
        value=self.raw(*args)
        if check:assert value['rc']==0,value
        if args[0]=='new-session':self.window=self.raw('list-windows','-t','installed','-F','#{window_id}')['out'].splitlines()[0]
        return value['out']

    def configuration(self):
        base=[self.python,self.winpath(self.bridge),'--namespace',self.namespace,'--session','installed']
        description=json.loads(subprocess.check_output(base+['--describe'],text=True,timeout=15))
        identity=description['identity']
        self.identity=identity
        fixed=base+['--server-pid',str(identity['pid']),'--server-birth',str(identity['creation_filetime'])]
        return dict(kind='psmux',bridge_command=fixed,bridge_generation=description['generation'],formatting_identity=identity)

    def close(self):
        census=self.raw('list-sessions','-F','#{session_id}')
        assert not census['out'].strip(),census
        shutil.rmtree(self.directory)


def qualify_windows(python,wheel,endpoint,token,request,window):
    """Install into a private Windows fixture prefix; PowerShell calls real CLI."""
    helper=r'''
import json,os,subprocess,sys,uuid,zipfile,hashlib
from pathlib import Path
r=json.loads(sys.stdin.read());root=Path(os.environ['LOCALAPPDATA'])/'codex-wake-test'/('format524-'+uuid.uuid4().hex);root.mkdir(parents=True)
prefix=root/'venv';subprocess.run([sys.executable,'-m','venv',str(prefix)],check=True,capture_output=True,timeout=45)
py=prefix/'Scripts/python.exe';subprocess.run([str(py),'-m','pip','install','--no-deps',r['wheel']],check=True,capture_output=True,timeout=45)
token=root/'caller.token';token.write_text(r['token'])
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
sid=subprocess.check_output([str(ps),'-NoProfile','-NonInteractive','-Command','[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True,timeout=10).strip()
subprocess.run(['icacls',str(token),'/inheritance:r','/grant:r','*'+sid+':(F)','*S-1-5-18:(F)','*S-1-5-32-544:(F)'],check=True,capture_output=True,timeout=10)
package=subprocess.check_output([str(py),'-c','import codex_wake;print(codex_wake.__file__)'],text=True,timeout=10).strip()
with zipfile.ZipFile(r['wheel']) as z:
 members=[name for name in z.namelist() if name.endswith('.py')]
 for name in members:assert (prefix/'Lib/site-packages'/name).read_bytes()==z.read(name),name
print(json.dumps(dict(prefix=str(prefix),cli=str(prefix/'Scripts/codex-wake.exe'),python=str(py),token=str(token),package=package,python_members_verified=len(members),wheel_sha256=hashlib.sha256(Path(r['wheel']).read_bytes()).hexdigest())))
'''
    native_wheel=subprocess.check_output(['wslpath','-w',str(wheel.resolve())],text=True).strip()
    installed=subprocess.run([python,'-c',helper],input=json.dumps(dict(wheel=native_wheel,token=token)),text=True,capture_output=True,timeout=100,check=True)
    installed=json.loads(installed.stdout)
    powershell='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
    script=r'''$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$r=[Console]::In.ReadToEnd()|ConvertFrom-Json;& $r.cli controller remote --endpoint $r.endpoint --token-file $r.token --transport $r.transport $r.operation --arguments ($r.arguments.Replace('"','\"'));if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}'''
    encoded=base64.b64encode(script.encode('utf-16-le')).decode();calls=[]
    try:
        for transport in ('api','mcp'):
            for verb in ('reenable','rollback'):
                payload=dict(installed,endpoint=endpoint,transport=transport,operation='tabs.format.'+verb,arguments=json.dumps(request(verb)))
                process=subprocess.run([powershell,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],input=json.dumps(payload),text=True,capture_output=True,timeout=30)
                assert process.returncode==0,(process.returncode,process.stdout,process.stderr)
                value=json.loads(process.stdout.lstrip('\ufeff'));assert result(value)['status']==('rolled_back' if verb=='rollback' else 'applied'),value
                calls.append(dict(transport=transport,verb=verb,status=result(value)['status']))
        style=dict(foreground='yellow',background='blue',attributes=['bold'])
        for transport,verb,arguments,expected in (
                ('api','override-set',request('override-set',dict(window=window,style=style)),style),
                ('mcp','override-inspect',dict(workspace='work',window=window),style),
                ('mcp','override-clear',request('override-clear',dict(window=window)),None)):
            payload=dict(installed,endpoint=endpoint,transport=transport,operation='tabs.format.'+verb,
                         arguments=json.dumps(arguments))
            process=subprocess.run([powershell,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                                   input=json.dumps(payload),text=True,capture_output=True,timeout=30)
            assert process.returncode==0,(process.returncode,process.stdout,process.stderr)
            observed=result(json.loads(process.stdout.lstrip('\ufeff')))
            assert observed['override']==expected,observed
            calls.append(dict(transport=transport,verb=verb,status=observed['status']))
        for transport in ('api','mcp'):
            payload=dict(installed,endpoint=endpoint,transport=transport,operation='tabs.format.configure',arguments=json.dumps(request('configure',dict(policy={'render_mode':'invalid'}))))
            process=subprocess.run([powershell,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],input=json.dumps(payload),text=True,capture_output=True,timeout=30)
            value=json.loads(process.stdout.lstrip('\ufeff'))
            assert value['result']['operation']['reason']=='invalid_argument',value
            calls.append(dict(transport=transport,verb='configure-invalid',phase=value['result']['operation']['phase'],reason='invalid_argument',exit_code=process.returncode,expected_local_exit_code=3))
            assert process.returncode==3,(process.returncode,value)
    finally:
        # Remove only the ephemeral fixture token, retaining the candidate prefix for review.
        cleanup='import json,sys;from pathlib import Path;Path(json.loads(sys.stdin.read())).unlink()'
        subprocess.run([python,'-c',cleanup],input=json.dumps(installed['token']),text=True,capture_output=True,timeout=10,check=True)
    installed.pop('token');installed['calls']=calls;installed['token_removed']=True
    return installed


if __name__=='__main__':main()
