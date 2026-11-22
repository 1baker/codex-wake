"""Portable OAuth caller, deliberately independent of native execution owners.

The Windows CLI can call an enrolled controller over API or OAuth MCP. Native
Windows state/locking and native TUI health are not qualified by this client.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler,Request,build_opener

OPERATIONS=frozenset(('tabs.list', 'tabs.show', 'tabs.preview', 'tabs.apply', 'tabs.undo', 'tabs.capture', 'tabs.input', 'inventory.list', 'inventory.resolve', 'accounts.list', 'accounts.resolve', 'configuration.explain', 'builds.list', 'builds.launch', 'builds.stage', 'builds.select', 'builds.rollback', 'hosts.list', 'hosts.resolve', 'hosts.route', 'history.search', 'history.read', 'history.resume', 'operations.send', 'operations.result', 'operations.wait', 'operations.stream', 'operations.cancel', 'operations.rebind', 'migration.preview', 'migration.apply', 'migration.rollback', 'flows.propose', 'flows.publish', 'flows.definition', 'flows.start', 'flows.inspect', 'flows.advance', 'flows.reconcile', 'flows.cancel', 'health.observe', 'notices.list', 'notices.publish', 'notices.reconcile', 'recovery.list', 'recovery.show', 'recovery.configure', 'recovery.enable', 'recovery.disable', 'recovery.check', 'recovery.tick', 'recovery.apply', 'recovery.reconcile', 'sessions.capabilities', 'sessions.create', 'sessions.prompt', 'sessions.wait', 'sessions.cancel', 'sessions.checkpoint', 'sessions.fork'))


# Pinned published MCP aliases; no owner imports on Windows.
MCP_TOOLS={'accounts.list': 'wake_controller_accounts', 'accounts.resolve': 'wake_controller_account_resolve', 'builds.launch': 'wake_builds_launch', 'builds.list': 'wake_builds_list', 'builds.rollback': 'wake_builds_rollback', 'builds.select': 'wake_builds_select', 'builds.stage': 'wake_builds_stage', 'configuration.explain': 'wake_controller_configuration', 'flows.advance': 'wake_flows_advance', 'flows.cancel': 'wake_flows_cancel', 'flows.definition': 'wake_flows_definition', 'flows.inspect': 'wake_flows_inspect', 'flows.propose': 'wake_flows_propose', 'flows.publish': 'wake_flows_publish', 'flows.reconcile': 'wake_flows_reconcile', 'flows.start': 'wake_flows_start', 'health.observe': 'wake_controller_health', 'history.read': 'wake_controller_history_read', 'history.resume': 'wake_controller_history_resume', 'history.search': 'wake_controller_history_search', 'hosts.list': 'wake_hosts_list', 'hosts.resolve': 'wake_hosts_resolve', 'hosts.route': 'wake_hosts_route', 'inventory.list': 'wake_controller_list', 'inventory.resolve': 'wake_controller_resolve', 'migration.apply': 'wake_controller_migration_apply', 'migration.preview': 'wake_controller_migration_preview', 'migration.rollback': 'wake_controller_migration_rollback', 'notices.list': 'wake_controller_notices_list', 'notices.publish': 'wake_controller_notices_publish', 'notices.reconcile': 'wake_controller_notices_reconcile', 'operations.cancel': 'wake_operations_cancel', 'operations.rebind': 'wake_operations_rebind', 'operations.result': 'wake_operations_result', 'operations.send': 'wake_operations_send', 'operations.stream': 'wake_operations_stream', 'operations.wait': 'wake_operations_wait', 'recovery.apply': 'wake_controller_recovery_apply', 'recovery.check': 'wake_controller_recovery_check', 'recovery.configure': 'wake_controller_recovery_configure', 'recovery.disable': 'wake_controller_recovery_disable', 'recovery.enable': 'wake_controller_recovery_enable', 'recovery.list': 'wake_controller_recovery_list', 'recovery.reconcile': 'wake_controller_recovery_reconcile', 'recovery.show': 'wake_controller_recovery_show', 'recovery.tick': 'wake_controller_recovery_tick', 'sessions.cancel': 'wake_flow_sessions_cancel', 'sessions.capabilities': 'wake_flow_sessions_capabilities', 'sessions.checkpoint': 'wake_flow_sessions_checkpoint', 'sessions.create': 'wake_flow_sessions_create', 'sessions.fork': 'wake_flow_sessions_fork', 'sessions.prompt': 'wake_flow_sessions_prompt', 'sessions.wait': 'wake_flow_sessions_wait', 'tabs.apply': 'wake_tabs_apply', 'tabs.capture': 'wake_tabs_capture', 'tabs.input': 'wake_tabs_input', 'tabs.list': 'wake_tabs_list', 'tabs.preview': 'wake_tabs_preview', 'tabs.show': 'wake_tabs_show', 'tabs.undo': 'wake_tabs_undo'}
from .upgrade_commands import tool_specs as _upgrade_specs
OPERATIONS = OPERATIONS | frozenset(spec[1] for spec in _upgrade_specs().values())
MCP_TOOLS.update({spec[1]: name for name, spec in _upgrade_specs().items()})

OPERATIONS=OPERATIONS|frozenset(['grok.capabilities', 'grok.create', 'grok.load', 'grok.prompt', 'grok.wait', 'grok.cancel', 'grok.health', 'grok.checkpoint', 'grok.fork'])
MCP_TOOLS.update({"grok."+verb:"wake_controller_grok_"+verb for verb in ('capabilities', 'create', 'load', 'prompt', 'wait', 'cancel', 'health', 'checkpoint', 'fork')})


OPERATIONS = OPERATIONS | frozenset('daemons.' + verb for verb in ('list', 'status', 'start', 'restart', 'update', 'stop'))
MCP_TOOLS.update({'daemons.' + verb: 'wake_daemons_' + verb for verb in ('list', 'status', 'start', 'restart', 'update', 'stop')})


OPERATIONS = OPERATIONS | frozenset(('accounts.init', 'accounts.create', 'history.import'))
MCP_TOOLS.update({'accounts.init': 'wake_controller_account_init', 'accounts.create': 'wake_controller_account_create', 'history.import': 'wake_controller_history_import'})


OPERATIONS = OPERATIONS | frozenset(('accounts.status',))
MCP_TOOLS['accounts.status'] = 'wake_controller_account_status'


from .command_contract import public_tools
for _tool, (_operation, _schema) in public_tools().items():
    MCP_TOOLS[_operation] = _tool
OPERATIONS = OPERATIONS | frozenset(MCP_TOOLS)

# Native Grok account controls use the existing exact-target OAuth contract.
MCP_TOOLS.update({'grok_auth.status': 'wake_grok_auth_status', 'grok_auth.revoke': 'wake_grok_auth_revoke'})
OPERATIONS = OPERATIONS | frozenset(MCP_TOOLS)
# Generated pure metadata keeps portable clients independent of host owners.
from .unified_public import PUBLIC_MCP_TOOLS
OPERATIONS = OPERATIONS | frozenset(PUBLIC_MCP_TOOLS)
MCP_TOOLS.update({key:value for key,value in PUBLIC_MCP_TOOLS.items() if key not in MCP_TOOLS})

class ClientError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def private_token(path):
    path=Path(path)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or getattr(info,'st_file_attributes',0)&1024:
        raise ClientError('token_file_not_private','OAuth token must be a private regular file')
    if os.name=='nt':
        from .controller_client_windows import check_private_file
        check_private_file(path)
    elif info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise ClientError('token_file_not_private','OAuth token file must be owned and private')
    with path.open(encoding='utf-8') as stream:value=stream.read(16385)
    value=value.strip()
    if not value or len(value)>16384 or any(ord(c)<=32 or ord(c)==127 for c in value):
        raise ClientError('invalid_token_file','bounded opaque OAuth token required')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def invoke(endpoint,token_file,operation,arguments,*,transport='api'):
    url=urlsplit(endpoint)
    if (len(endpoint)>4096 or any(ord(c)<=32 or ord(c)==127 for c in endpoint) or url.username or url.password or
        url.query or url.fragment or not url.netloc or (url.scheme!='https' and not(url.scheme=='http' and url.hostname in ('127.0.0.1','::1','localhost')))):
        raise ClientError('invalid_endpoint','canonical HTTPS endpoint required except loopback fixtures')
    if operation not in OPERATIONS or not isinstance(arguments,dict):
        raise ClientError('unsupported_operation','registered operation and JSON object arguments required')
    if transport not in ('api','mcp'):raise ClientError('unsupported_transport','API or OAuth MCP transport required')
    token=private_token(token_file)
    body=dict(operation=operation,arguments=arguments)
    if transport=='mcp':body=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name=MCP_TOOLS[operation],arguments=arguments))
    data=json.dumps(body).encode()
    if len(data)>1048576:raise ClientError('request_limit','request exceeds bounded capacity')
    request=Request(endpoint.rstrip('/')+('/operations' if transport=='api' else '/mcp'),data=data,
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    failed=False
    try:response=build_opener(NoRedirect).open(request,timeout=35)
    except HTTPError as error:response=error;failed=True
    try:
        with response:raw=response.read(4194305)
        if len(raw)>4194304:raise ClientError('response_limit','response exceeds bounded capacity')
        value=json.loads(raw)
    except ClientError:raise
    except (ValueError,UnicodeError):raise ClientError('invalid_response','controller response was not a bounded JSON envelope') from None
    if not isinstance(value,dict):raise ClientError('invalid_response','controller operation envelope required')
    if transport=='mcp' and not failed:
        if value.get('error'):raise ClientError('remote_mcp_error','controller MCP operation failed')
        result=value.get('result',{})
        value=result.get('structuredContent')
        if not isinstance(value,dict):raise ClientError('invalid_response','controller MCP envelope unavailable')
        failed=result.get('isError',False)
    if not isinstance(value,dict):raise ClientError('invalid_response','controller operation envelope required')
    return value,failed or value.get('status')=='failed'


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv not in ([],['-h'],['--help']) and argv[:2]!=['controller','remote']:
        print(json.dumps(dict(schema_version=1,status='failed',error=dict(code='unsupported_native_windows_owner',
            message='This portable client supports controller remote API/OAuth MCP calls. Native Windows Wake execution owners are not qualified.'))))
        return 2
    parser=argparse.ArgumentParser(prog='codex-wake',description='Portable controller caller; native Windows execution owners are not qualified.')
    controller=parser.add_subparsers(dest='command',required=True).add_parser('controller')
    remote=controller.add_subparsers(dest='verb',required=True).add_parser('remote')
    remote.add_argument('--endpoint',required=True);remote.add_argument('--token-file',type=Path,required=True)
    remote.add_argument('--transport',choices=('api','mcp'),default='api')
    remote.add_argument('operation',choices=sorted(OPERATIONS));remote.add_argument('--arguments',type=json.loads,default={})
    args=parser.parse_args(argv)
    return execute_cli(args)


def execute_cli(args):
    """Shared bounded caller behavior for portable and full native CLI parsers."""
    try:
        value,failed=invoke(args.endpoint,args.token_file,args.operation,args.arguments,transport=args.transport)
        print(json.dumps(value,sort_keys=True))
        if failed:return 2
        if args.operation.startswith('tabs.'):
            from .tab_result import exit_status
            return exit_status(value)
        return 0
    except (ClientError,OSError,URLError,ValueError):
        error=sys.exception()
        code=error.code if isinstance(error,ClientError) else 'controller_unavailable'
        message=str(error) if isinstance(error,ClientError) else 'controller request or private token unavailable'
        print(json.dumps(dict(schema_version=1,operation=args.operation,status='failed',error=dict(code=code,message=message)),sort_keys=True))
        return 2


if __name__=='__main__':raise SystemExit(main())
