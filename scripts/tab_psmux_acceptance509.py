#!/usr/bin/env python3
"""Owned Windows psmux and actual PowerShell acceptance for the finite bridge.

Run with the exact installed prefix's Python. Caller supplies a private output
root and existing native Windows Python path; only a new unique psmux namespace
is created or stopped. No provider, production tabs, or credentials are used.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from codex_wake.controller_tab_adapters import ConfiguredBridge, PsmuxAttachmentTransport
from codex_wake import tab_psmux_bridge


POWERSHELL = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'


def qualify_public(state,source,holding,windows_python):
    from codex_wake.controller_tabs import controller_tabs_from_root
    from codex_wake.controller_operations import ControllerOperations
    from codex_wake.controller_auth import OAuthAuthority
    from codex_wake.controller_http import ControllerHTTPServer
    from codex_wake.managed_inventory import ManagedInventory
    from codex_wake.mcp_server import CommandRunner
    import threading
    from urllib.request import Request,urlopen
    root=state/'public';root.mkdir(mode=0o700)
    config=dict(schema_version=1,workspaces={name:dict(kind='psmux',bridge_command=transport.bridge.command,
            bridge_generation=transport.generation,evidence_scope='disposable_fixture',privacy='safe')
            for name,transport in [('source',source),('holding',holding)]})
    path=root/'controller-tabs.json';path.write_text(json.dumps(config));path.chmod(0o600)
    executable=str(Path(sys.executable).parent/'codex-wake')
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    def cli(*args):
        p=subprocess.run([executable,'--wake-root',str(root),'tabs',*args,'--json'],capture_output=True,text=True,timeout=25,env=env)
        assert p.returncode==0,(p.stdout,p.stderr)
        return json.loads(p.stdout)
    listing=cli('list')
    assert all(p['platform']=='windows' for r in listing['resources'] for p in r['traits']['panes'])
    created=cli('create','--workspace','source','--name','public-509','--position','first')['result']['operation']
    assert created['execution']=='completed',created
    wid=created['result']['window']['window_id']
    target=next(r['target'] for r in cli('list')['resources'] if r['target']['workspace']=='source')
    payload=dict(workspace='source',expected_target=target,window=wid,name='public-renamed-509')
    payload['_request']=dict(operation_id='public-rename',idempotency_key='public-rename',correlation_id='public-rename',binding='fixture',target=target)
    renamed,failed=CommandRunner(wake_root=root).call('wake_tabs_rename',payload)
    assert not failed and renamed['result']['operation']['execution']=='completed',renamed
    before = source.snapshot(time.monotonic() + 15)
    assert sorted(before['windows'], key=lambda window: window['index'])[0]['window_id'] == wid
    expected_focus = next(window['window_id'] for window in before['windows'] if window['focused'])
    target = next(r['target'] for r in cli('list')['resources'] if r['target']['workspace']=='source')
    move = dict(workspace='source', destination='source', window=wid, position='last',
                expected_target=target, expected_destination=target,
                _request=dict(operation_id='public-order', idempotency_key='public-order',
                              correlation_id='public-order', binding='fixture', target=target))
    moved, failed = CommandRunner(wake_root=root).call('wake_tabs_move', move)
    assert not failed and moved['result']['operation']['execution'] == 'completed', moved
    after = source.snapshot(time.monotonic() + 15)
    assert sorted(after['windows'], key=lambda window: window['index'])[-1]['window_id'] == wid
    assert next(window['window_id'] for window in after['windows'] if window['focused']) == expected_focus
    owner=controller_tabs_from_root(root)
    authority=OAuthAuthority(root/'auth.sqlite',issuer='http://127.0.0.1',resource='http://127.0.0.1/controller')
    client=authority.register(dict(redirect_uris=['http://127.0.0.1/callback']))
    verifier='v'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    scope={k:v for k,v in target.items() if k!='generation'}
    code=authority.authorize(subject='fixture',principal_kind='owner',client_id=client['client_id'],redirect_uri='http://127.0.0.1/callback',resource=authority.resource,scopes=['observe','control'],targets=[scope],code_challenge=challenge)
    access=authority.token(dict(grant_type='authorization_code',client_id=client['client_id'],code=code,code_verifier=verifier,redirect_uri='http://127.0.0.1/callback',resource=authority.resource))['access_token']
    service=ControllerOperations(ManagedInventory(root),host=owner.host,environment=owner.environment,tabs=owner)
    server=ControllerHTTPServer(('127.0.0.1',0),authority,service)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    destroy_submitted = False
    try:
        target=next(r['target'] for r in cli('list')['resources'] if r['target']['workspace']=='source')
        focus=dict(workspace='source',window=wid,expected_target=target,
                   _request=dict(operation_id='public-focus',idempotency_key='public-focus',correlation_id='public-focus',binding='fixture',target=target))
        body=json.dumps(dict(operation='tabs.focus',arguments=focus)).encode()
        request=Request('http://127.0.0.1:'+str(server.server_address[1])+'/operations',data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+access})
        with urlopen(request,timeout=25) as response:value=json.load(response)
        assert value['result']['operation']['execution']=='completed',value
        command="$ErrorActionPreference='Stop'; $r=[Console]::In.ReadToEnd() | ConvertFrom-Json; & wsl.exe --distribution $r.distro --user $r.user --exec $r.exe --wake-root $r.root tabs list --json; if ($LASTEXITCODE -ne 0) {exit $LASTEXITCODE}"
        encoded=base64.b64encode(command.encode('utf-16-le')).decode()
        import pwd
        native_root=subprocess.check_output(['wslpath','-w',str(root)],text=True).strip()
        parts=native_root.split('\\')
        distro=os.environ.get('WSL_DISTRO_NAME') or (parts[3] if len(parts)>3 and parts[2].lower() in ('wsl.localhost','wsl$') else None)
        assert distro,'The selected fixture must identify its owning WSL distribution.'
        payload=dict(distro=distro,user=pwd.getpwuid(os.getuid()).pw_name,exe=executable,root=str(root))
        result=subprocess.run([POWERSHELL,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],input=json.dumps(payload),capture_output=True,text=True,timeout=30)
        assert result.returncode==0,(result.stdout,result.stderr)
        assert json.loads(result.stdout.lstrip('\ufeff'))['resources']
        # Native PowerShell HTTP and OAuth MCP callers reach the same WSL
        # authority; credential arrives only over the private process stdin.
        command="$ErrorActionPreference='Stop'; $r=[Console]::In.ReadToEnd() | ConvertFrom-Json; $h=@{Authorization=('Bearer '+$r.token)}; $api=@{operation='tabs.list';arguments=@{}} | ConvertTo-Json -Compress; $a=Invoke-RestMethod -TimeoutSec 15 -Method Post -Uri ($r.base+'/operations') -Headers $h -ContentType 'application/json' -Body $api; $m=@{jsonrpc='2.0';id=1;method='tools/call';params=@{name='wake_tabs_list';arguments=@{}}} | ConvertTo-Json -Depth 10 -Compress; $b=Invoke-RestMethod -TimeoutSec 15 -Method Post -Uri ($r.base+'/mcp') -Headers $h -ContentType 'application/json' -Body $m; @{api=$a;mcp=$b} | ConvertTo-Json -Depth 100 -Compress"
        encoded=base64.b64encode(command.encode('utf-16-le')).decode()
        result=subprocess.run([POWERSHELL,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
            input=json.dumps(dict(token=access,base='http://127.0.0.1:'+str(server.server_address[1]))),capture_output=True,text=True,timeout=40)
        assert result.returncode==0,(result.returncode,result.stderr)
        values=json.loads(result.stdout.lstrip('\ufeff'))
        assert values['api']['result']['resources']
        assert values['mcp']['result']['structuredContent']['result']['resources']

        target = next(r['target'] for r in cli('list')['resources'] if r['target']['workspace'] == 'source')
        payload = dict(workspace='source', window=wid, expected_target=target)
        def intent(request_id):
            return dict(operation_id=request_id, idempotency_key=request_id, correlation_id=request_id,
                        binding='fixture', target=target)

        preview, failed = CommandRunner(wake_root=root).call('wake_tabs_destroy',
            dict(payload, preview=True, _request=intent('destroy-preview')))
        operation = preview['result']['operation']
        assert not failed and operation['execution'] == 'completed', preview
        impact = operation['result']
        assert impact['affected_sessions'] and impact['pane_ids'], impact
        cli_preview = cli('destroy', '--workspace', 'source', '--window', wid, '--dry-run')
        assert cli_preview['result']['operation']['result']['confirmation'] == impact['confirmation']
        unlink, _ = CommandRunner(wake_root=root).call('wake_tabs_unlink',
            dict(payload, _request=intent('native-unlink-unsupported')))
        declined = unlink['result']['operation']
        assert declined['phase'] == 'terminal' and declined['result']['status'] == 'unsupported', unlink
        assert declined['result']['reason'] == 'unsupported_target', unlink
        body = json.dumps(dict(operation='tabs.destroy', arguments=dict(payload,
            confirmation=impact['confirmation'], _request=intent('destroy-exact-native')))).encode()
        request = Request('http://127.0.0.1:' + str(server.server_address[1]) + '/operations',
                          data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + access})
        destroy_submitted = True
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
        assert result['result']['operation']['execution'] == 'completed', result
        assert not any(window['window_id'] == wid for window in source.snapshot(time.monotonic() + 15)['windows'])
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        if not destroy_submitted:
            cli('close','--workspace','source','--window',wid,'--force')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--windows-python', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.state.mkdir(mode=0o700, parents=True, exist_ok=False)
    namespace = 'wake509-' + uuid.uuid4().hex[:12]
    bridge_path = Path(tab_psmux_bridge.__file__).resolve()
    native_bridge = subprocess.check_output(['wslpath', '-w', str(bridge_path)], text=True).strip()
    helper = args.state / 'native_fixture.py'
    helper.write_text('''import json,os,subprocess,sys\nfrom pathlib import Path\np=str(Path(os.environ['LOCALAPPDATA'])/'Microsoft/WinGet/Links/psmux.exe')\na=sys.argv[1]\nnamespace=sys.argv[2]\nif a=='start':\n for session in ('source','holding'):\n  subprocess.run([p,'-L',namespace,'new-session','-d','-s',session,'-n',session+'-anchor','--','cmd.exe','/d','/k'],capture_output=True,check=True,timeout=5)\n print('started')\nelif a=='error':\n subprocess.run([p,'-L',namespace,'send-keys','-t',sys.argv[3],'-l','echo Error: fixture-current-visible-error'],capture_output=True,check=True,timeout=5)\n subprocess.run([p,'-L',namespace,'send-keys','-t',sys.argv[3],'Enter'],capture_output=True,check=True,timeout=5)\n print('marked')\nelif a=='census':\n r=subprocess.run([p,'-L',namespace,'list-sessions','-F','#{session_id}'],capture_output=True,text=True,timeout=5)\n print(json.dumps({'returncode':r.returncode,'sessions':r.stdout.splitlines()}))\nelif a=='stop':\n r=subprocess.run([p,'-L',namespace,'kill-server'],capture_output=True,timeout=5)\n print('stopped',r.returncode)\n''')
    native_helper = subprocess.check_output(['wslpath', '-w', str(helper)], text=True).strip()
    python = args.windows_python
    owned = False
    checks = []
    started = time.monotonic()
    def native(*values):
        return subprocess.check_output([python, native_helper, *values], text=True, timeout=15).strip()
    def invoke(owner, action, arguments):
        return owner.lifecycle(action, arguments, time.monotonic() + 15)
    try:
        native('start', namespace)
        owned = True
        base = [python, native_bridge, '--namespace', namespace, '--session', 'source']
        description = json.loads(subprocess.check_output(base + ['--describe'], text=True, timeout=15))
        identity = description['identity']
        fixed = ['--server-pid', str(identity['pid']), '--server-birth', str(identity['creation_filetime'])]
        bridge = ConfiguredBridge(base + fixed)
        source = PsmuxAttachmentTransport(bridge, generation=description['generation'])
        holding_base = [python, native_bridge, '--namespace', namespace, '--session', 'holding']
        holding_description = json.loads(subprocess.check_output(holding_base + ['--describe'], text=True, timeout=15))
        holding_identity = holding_description['identity']
        holding_command = holding_base + ['--server-pid', str(holding_identity['pid']), '--server-birth', str(holding_identity['creation_filetime'])]
        holding = PsmuxAttachmentTransport(ConfiguredBridge(holding_command), generation=holding_description['generation'])
        initial = source.snapshot(time.monotonic() + 15)
        assert initial['server_identity'] == identity
        assert all(pane['platform'] == 'windows' and pane['windows_creation_filetime'] > 0
                   and pane['windows_processes'] for window in initial['windows'] for pane in window['panes'])
        assert not source.same_server(holding)
        assert identity['pid'] != holding_identity['pid']
        source_session = initial['session_id']
        holding_session = holding.snapshot(time.monotonic() + 15)['session_id']
        assert len(bridge('discover', {}, time.monotonic() + 15)['result']['sessions']) == 2
        checks.append('pinned-native-process-and-session-discovery')
        created = invoke(source, 'create', dict(name='managed-509'))
        wid = created['window_id']
        original = next(w for w in created['snapshot']['windows'] if w['window_id'] == wid)
        renamed = invoke(source, 'rename', dict(window=wid, name='renamed-509'))
        assert next(w for w in renamed['snapshot']['windows'] if w['window_id'] == wid)['name'] == 'renamed-509'
        focused = invoke(source, 'focus', dict(window=wid))
        assert next(w for w in focused['snapshot']['windows'] if w['window_id'] == wid)['focused']
        native('error', namespace, 'source:' + str(original['index']) + '.' + str(original['panes'][0]['pane_index']))
        screen = source.visible_screen(original['panes'][0]['pane_id'], time.monotonic() + 15)
        assert 'fixture-current-visible-error' in screen
        checks.append('create-rename-focus-current-visible-screen')
        from codex_wake.managed_inventory import InventoryError
        try:
            invoke(source, 'park', dict(window=wid, destination_session=holding_session))
            raise AssertionError('native unsupported cross-session move was accepted')
        except InventoryError as error:
            assert error.code == 'unsupported_target'
        preserved = source.snapshot(time.monotonic() + 15)
        assert next(w for w in preserved['windows'] if w['window_id'] == wid)['panes'] == original['panes']
        checks.append('cross-session-movement-explicitly-unsupported-source-preserved')
        # Actual native PowerShell invokes the same finite bridge; no profile or
        # per-process PowerShell census, one bounded process with private stdin.
        command = '''$ErrorActionPreference='Stop'; $r=[Console]::In.ReadToEnd() | ConvertFrom-Json; $body='{"action":"snapshot","arguments":{}}'; $body | & $r.python $r.bridge --namespace $r.namespace --session source --server-pid $r.pid --server-birth $r.birth; if ($LASTEXITCODE -ne 0) {exit $LASTEXITCODE}'''
        encoded = base64.b64encode(command.encode('utf-16-le')).decode()
        payload = json.dumps(dict(python=python.replace('/mnt/c/', 'C:/') if python.startswith('/mnt/c/') else python,
            bridge=native_bridge, namespace=namespace, pid=identity['pid'], birth=str(identity['creation_filetime'])))
        # Convert executable paths with wslpath rather than relying on slash mapping.
        native_python = subprocess.check_output(['wslpath', '-w', python], text=True).strip()
        value = json.loads(payload); value['python'] = native_python
        reply = subprocess.run([POWERSHELL, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            input=json.dumps(value), text=True, capture_output=True, timeout=20, check=True)
        observed = json.loads(reply.stdout.lstrip('\ufeff'))
        assert observed['generation'] == description['generation']
        checks.append('actual-powershell-native-bridge-client')
        unsupported = bridge('lifecycle', dict(action='execute', argv=['never']), time.monotonic() + 15)
        assert unsupported['error']['code'] == 'unsupported_operation'
        wrong = base + ['--server-pid', str(identity['pid']), '--server-birth', str(identity['creation_filetime'] + 1)]
        stale = subprocess.run(wrong, input='{"action":"snapshot","arguments":{}}', text=True, capture_output=True, timeout=15)
        assert json.loads(stale.stdout)['error']['code'] == 'stale_target'
        checks.append('unsupported-action-and-replaced-process-generation-refused')
        assert qualify_public(args.state,source,holding,python)
        checks.append('installed-wake-cli-http-native-mcp-and-actual-powershell')
        checks.append('installed-confirmed-destroy-and-explicit-native-unlink-refusal')
        closed = invoke(source, 'close', dict(window=wid))
        assert not any(w['window_id'] == wid for w in closed['snapshot']['windows'])
        native('stop', namespace)
        owned = False
        census = json.loads(native('census', namespace))
        assert not census['sessions'], census
        missing = subprocess.run(base + fixed, input='{"action":"snapshot","arguments":{}}', text=True, capture_output=True, timeout=15)
        assert json.loads(missing.stdout).get('error')
        checks.append('owned-namespace-cleanup-and-unavailable-result')
        receipt = dict(status='passed', checks=checks, namespace=namespace,
            identity=identity, bridge_sha256=hashlib.sha256(bridge_path.read_bytes()).hexdigest(),
            bridge_module=str(bridge_path), python=sys.version.split()[0], windows_python=python,
            elapsed_seconds=round(time.monotonic() - started, 3), provider_calls=0,
            native_windows_owner=False, actual_powershell=True, final_owned_namespace=census,
            boundary='Actual native presentation/finite transport; installed public CLI/API/nativeMCP lifecycle and actual PowerShell qualified; native Windows execution owner unsupported.')
        args.output.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(dict(status='passed', checks=len(checks), receipt=str(args.output))))
    except Exception as error:
        args.output.write_text(json.dumps(dict(status='failed', namespace=namespace, checks=checks,
            error_type=type(error).__name__, message=str(error), provider_calls=0), indent=2) + '\n')
        raise
    finally:
        if owned:
            native('stop', namespace)


if __name__ == '__main__':
    main()
