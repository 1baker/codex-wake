"""Persistent named terminal sessions, separate from native container liveness."""
import hashlib
import json
import os
import subprocess
from pathlib import Path, PureWindowsPath
import time
import uuid

from .managed_inventory import InventoryError
from .shortcut_store import read, write, locked


def _name(value):
    if not isinstance(value,str) or not value.strip() or len(value.encode())>128 or any(ord(c)<32 or c in ':.' for c in value):
        raise InventoryError('invalid_argument','Use a nonempty session name without control characters, dots or colons.')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


class TerminalSessions:
    READS=frozenset(('tabs.session.list','tabs.session.show'))
    def __init__(self,root,*,tabs,deadline=None):
        self.root=Path(root);self.tabs=tabs;self.deadline=deadline;self.directory=self.root/'terminal-sessions';self.path=self.directory/'registry.json'
        self._restore_bindings()

    def _timeout(self,seconds):
        remaining=seconds if self.deadline is None else min(seconds,self.deadline-time.monotonic())
        if remaining<=0:raise InventoryError('cycle_deadline','Terminal management cycle deadline elapsed.')
        return remaining

    def _deadline(self,seconds):
        return time.monotonic()+self._timeout(seconds)

    def _restore_bindings(self):
        from .controller_tab_adapters import TmuxAttachmentTransport
        for record in self.state()['sessions'].values():
            if record.get('backend')=='psmux' and record.get('native_key') and not record.get('deleted'):
                from .terminal_session_psmux import restore
                restore(self,record)
            if record.get('deleted') or record.get('backend') not in ('tmux','byobu') or not record.get('native_session_id'):continue
            try:
                transport=TmuxAttachmentTransport(record['server'],record['native_session_id'])
                snap=transport.snapshot(self._deadline(2))
                key=_digest({k:snap.get(k) for k in ('server','session_id','socket_identity','bridge_generation')})
                if key!=record.get('native_key'):continue
                existing=next((name for name,cfg in self.tabs.workspaces.items()
                    if cfg['kind'] in ('tmux','byobu')
                    and str(cfg.get('socket_path') or getattr(cfg['transport'],'socket',''))==record['server']
                    and (cfg.get('session_id') or getattr(cfg['transport'],'session',None))==record['native_session_id']),None)
                if existing is not None:continue
                self.tabs.workspaces[record['id']]=dict(kind=record['backend'],label=record['name'],socket_path=record['server'],session_id=record['native_session_id'],transport=transport)
            except (OSError,ValueError,subprocess.SubprocessError):continue

    def state(self):
        try:return read(self.path)
        except FileNotFoundError:return dict(version=1,sessions={})

    def save(self,state):
        write(self.path,state)

    def target(self):
        return dict(host=self.tabs.host,environment=self.tabs.environment,workspace='@terminal-sessions',presentation='terminal',generation=_digest(dict(sessions=self.state(),rules=self.routing_rules())))

    def routing_rules(self):
        try:return read(self.root/'terminal-routing'/'routing.json').get('rules',{})
        except FileNotFoundError:return {}

    def inventory(self,state=None):
        state=state or self.state();live={};aliases={};by_native={v.get('native_key'):v for v in state['sessions'].values() if not v.get('deleted') and v.get('native_key')}
        for workspace,cfg in list(self.tabs.workspaces.items())[:64]:
            try:snap=cfg['transport'].snapshot(self._deadline(2))
            except (OSError,ValueError,subprocess.SubprocessError):continue
            native_key=_digest({k:snap.get(k) for k in ('server','session_id','socket_identity','bridge_generation')})
            saved=by_native.get(native_key);sid=saved['id'] if saved else 'native-'+native_key[:24]
            label=cfg.get('label') or snap.get('session_name') or workspace
            record=dict(saved or {},id=sid,name=label if not saved else saved['name'],backend=cfg['kind'],server=(snap.get('server_identity',{}).get('namespace') if cfg['kind']=='psmux' else str(cfg.get('socket_path') or snap.get('server'))),native_key=native_key,workspace=workspace,state='running',tab_count=len(snap['windows']),snapshot=snap,labels=(saved or {}).get('labels',[]),defaults=(saved or {}).get('defaults',{}),description=(saved or {}).get('description',''),managed=bool(saved))
            aliases.setdefault(sid,[]).append(workspace)
            if sid not in live:live[sid]=record
        result=[]
        for sid,saved in state['sessions'].items():
            if saved.get('deleted'):continue
            fallback=dict(saved,state='empty',tab_count=0,workspace=None,snapshot=None,managed=True)
            if saved.get('opening'):
                fallback.update(state='unavailable',tab_count=None)
            elif sid not in live and saved.get('native_session_id'):
                try:
                    if saved['backend']=='psmux':
                        from .terminal_session_psmux import presence
                        if presence(self,saved)!='absent':fallback.update(state='unavailable',tab_count=None)
                        result.append(live.pop(sid,fallback));continue
                    check=subprocess.run(['tmux','-S',saved['server'],'has-session','-t',saved['native_session_id']],capture_output=True,timeout=self._timeout(2))
                    if check.returncode!=1:fallback.update(state='unavailable',tab_count=None)
                except (OSError,subprocess.SubprocessError):fallback.update(state='unavailable',tab_count=None)
            result.append(live.pop(sid,fallback))
        result.extend(live.values())
        from .terminal_session_summary import summarize
        return summarize(self.root,sorted(result,key=lambda v:(v['name'],v['server'],v['id'])),aliases,self.tabs)

    def resolve(self,selector,*,state=None,server=None):
        from .terminal_session_contract import split_selector
        selector,server=split_selector(selector,server)
        records=self.inventory(state)
        matches=[v for v in records if (v['id']==selector or v['name']==selector or v.get('workspace')==selector) and (server is None or v['server']==server)]
        if len(matches)!=1:
            error=InventoryError('ambiguous_target' if matches else 'target_not_found','Select a unique terminal session name or ID; list sessions for candidates.')
            error.candidates=[{k:v[k] for k in ('id','name','server','backend')} for v in matches];raise error
        return matches[0]

    def _settings(self,changes,*,backend=None):
        if not isinstance(changes,dict) or set(changes)-{'name','description','labels','defaults','formatting'}:
            raise InventoryError('invalid_argument','Unknown session setting.')
        if 'name' in changes:_name(changes['name'])
        if 'description' in changes and (not isinstance(changes['description'],str) or len(changes['description'])>2048):raise InventoryError('invalid_argument','Bounded description required.')
        if 'labels' in changes and (not isinstance(changes['labels'],list) or len(changes['labels'])>64 or any(not isinstance(v,str) or not v or len(v)>128 for v in changes['labels'])):raise InventoryError('invalid_argument','Bounded labels required.')
        if 'defaults' in changes:
            v=changes['defaults']
            if not isinstance(v,dict) or set(v)-{'cwd','profile','argv'}:raise InventoryError('invalid_argument','Defaults accept cwd, profile and argv.')
            if 'cwd' in v:
                cwd=v['cwd']
                valid=isinstance(cwd,str) and 0<len(cwd)<=4096 and not any(ord(c)<32 for c in cwd)
                if valid:valid=PureWindowsPath(cwd).is_absolute() if backend=='psmux' else Path(cwd).is_absolute() and Path(cwd).is_dir()
                if not valid:raise InventoryError('invalid_argument','Absolute default directory required; existence is checked on the native host.')
            if 'profile' in v and 'argv' in v:raise InventoryError('invalid_argument','Choose a launch profile or a command argv.')
            if 'profile' in v and (not isinstance(v['profile'],str) or not v['profile'] or len(v['profile'])>128):raise InventoryError('invalid_argument','Profile selector required.')
            if backend=='psmux' and 'argv' in v:raise InventoryError('unsupported_target','Generic argv defaults are not qualified for native psmux; no launch was applied.')
            if 'argv' in v and (not isinstance(v['argv'],list) or not 1<=len(v['argv'])<=64 or any(not isinstance(x,str) or '\0' in x or len(x)>4096 for x in v['argv'])):raise InventoryError('invalid_argument','Bounded command argv required.')
        if 'formatting' in changes:
            from .tab_format_policy import validate_policy
            validate_policy(changes['formatting'])
        return changes

    def creation_selection(self,args,*,records=None,ensure=False):
        """Resolve creation/ensure once for both authority and native execution."""
        records=self.inventory() if records is None else records
        name=_name(args.get('name'));backend=args.get('backend','tmux')
        if backend not in ('tmux','byobu','psmux'):raise InventoryError('invalid_argument','Unsupported terminal backend.')
        server=args.get('server')
        eligible=[v for v in records if (v['backend']=='psmux' if backend=='psmux' else v['backend'] in ('tmux','byobu'))]
        servers=sorted({v['server'] for v in eligible})
        named=[v for v in eligible if v['name']==name]
        context=os.environ.get('TMUX','').split(',',1)[0]
        if server is None and ensure and len(named)==1:server=named[0]['server']
        if server is None and context in servers:server=context
        if server is None and len(servers)==1:server=servers[0]
        if server is None and len(servers)>1:
            error=InventoryError('ambiguous_target','Select a terminal server with --server; multiple servers are available.')
            error.candidates=[dict(server=value,backend=backend) for value in servers];raise error
        if backend=='psmux' and not server:raise InventoryError('unsupported_target','Select an explicit host-configured psmux namespace.')
        server=server or str(self.directory/'tmux.sock')
        existing=[v for v in records if v['name']==name and v['server']==server]
        if len(existing)>1:
            error=InventoryError('ambiguous_target','Several identities share this name; inspect sessions before reuse.')
            error.candidates=[{k:v[k] for k in ('id','name','server','backend','state')} for v in existing];raise error
        return dict(name=name,backend=backend,server=server,existing=existing)

    def execute(self,operation,args,*,container_only=False):
        if operation=='tabs.session.delete':
            from .terminal_session_delete import TerminalSessionDelete
            return TerminalSessionDelete(self).execute(args)
        verb=operation.rsplit('.',1)[1]
        allowed={'session','server','name','backend','start','changes','defaults','expected_target','_request'}
        if not isinstance(args,dict) or set(args)-allowed:raise InventoryError('invalid_argument','Unsupported session arguments.')
        if operation in self.READS:
            state=self.state()
            if verb=='list':return dict(sessions=self.inventory(state),target=self.target())
            return dict(session=self.resolve(args.get('session'),server=args.get('server'),state=state),target=self.target())
        with locked(self.directory):
            if args.get('expected_target') is not None and args['expected_target']!=self.target():raise InventoryError('stale_target','Session registry changed; inspect again.')
            state=self.state();records=self.inventory(state)
            reused=False
            if verb in ('create','ensure'):
                selected=self.creation_selection(args,records=records,ensure=verb=='ensure')
                name,backend,server,existing=(selected[k] for k in ('name','backend','server','existing'))
                if existing and verb=='create':raise InventoryError('name_conflict','Session name already exists on this terminal server.')
                defaults=self._settings({'defaults':args.get('defaults',{})},backend=backend)['defaults']
                if existing:
                    observed=existing[0];record={k:v for k,v in observed.items() if k not in ('snapshot','workspace','state','tab_count','managed','health_summary','activity_summary','error_summary')};reused=True
                else:record=dict(id='session-'+uuid.uuid4().hex,name=name,backend=backend,server=server,labels=[],defaults=defaults,description='',created_at=time.time())
                state['sessions'][record['id']]=record;self.save(state)
            else:
                observed=self.resolve(args.get('session'),server=args.get('server'),state=state)
                record={k:v for k,v in observed.items() if k not in ('snapshot','workspace','state','tab_count','managed','health_summary','activity_summary','error_summary')}
                state['sessions'][record['id']]=record
                if verb=='update':
                    changes=self._settings(args.get('changes'),backend=record['backend'])
                    if any(v['id']!=record['id'] and v['server']==record['server'] and v['name']==changes.get('name',record['name']) for v in records):raise InventoryError('name_conflict','Session name already exists.')
                    if 'name' in changes and observed['state']=='running':
                        updated=self.native(observed,'rename',name=changes['name'])
                        if record['backend']=='psmux':record.update({k:updated[k] for k in ('native_key','native_session_id','psmux_bridge_command')})
                    if 'formatting' in changes and observed['state']=='running':
                        from .tab_formatting import TabFormatting
                        TabFormatting(self.root,tabs=self.tabs).execute('tabs.format.configure',dict(workspace=observed['workspace'],policy=changes['formatting']))
                    record.update(changes)
                elif verb=='delete':
                    if observed['state']=='unavailable' or observed['tab_count']:raise InventoryError('session_not_empty','Choose explicit drain or terminate for a populated session.')
                    record.update(deleted=True,deleted_at=time.time());self.save(state)
                    return dict(status='deleted',session=record)
                elif verb!='open':raise InventoryError('unsupported_operation','Unsupported terminal session operation.')
                self.save(state)
            if verb=='open' or args.get('start',verb=='ensure'):
                self.open(record,container_only=container_only)
                state=self.state();record=state['sessions'][record['id']]
            return dict(status='created' if verb=='create' else 'ensured' if verb=='ensure' else 'updated' if verb=='update' else 'opened',session=self.resolve(record['id']),reused=reused)

    def native(self,record,verb,**kwargs):
        if record['backend']=='psmux':
            from .terminal_session_psmux import native
            return native(self,record,verb,**kwargs)
        cfg=self.tabs.workspaces[record['workspace']];transport=cfg['transport'];deadline=self._deadline(10)
        if verb=='rename':
            transport.command(deadline,'rename-session','-t',transport.session,kwargs['name'])
            cfg['label']=kwargs['name']
        else:raise InventoryError('unsupported_operation','Unsupported native session action.')

    def open(self,record,*,container_only=False):
        current=self.resolve(record['id'])
        if current['state']=='running':
            if not container_only and current.get('profile_seed',{}).get('status') in ('pending','held','uncertain'):
                raise InventoryError('uncertain_effect','Prior profile seed is retained for inspection; no launch was replayed.')
            return current
        if record['backend']=='psmux':
            from .terminal_session_psmux import native
            return native(self,record,'open')
        from .controller_tab_adapters import TmuxAttachmentTransport
        server=Path(record['server'])
        known={str(c.get('socket_path')) for c in self.tabs.workspaces.values() if c['kind'] in ('tmux','byobu')}
        if str(server) not in known and server!=self.directory/'tmux.sock':raise InventoryError('unsupported_target','Select a discovered terminal server or the private session server.')
        profile=None if container_only else record.get('defaults',{}).get('profile')
        profile_owner=self.tabs.profile_owner() if profile else None
        if profile_owner is not None:profile_owner.selection(profile)  # Fail before creating any native container.
        if record.get('opening'):
            raise InventoryError('uncertain_effect','A prior native session launch needs reconciliation; no launch was replayed.')
        record['opening']=True
        state=self.state();state['sessions'][record['id']]=record;self.save(state)
        # Launch argv is an explicit new-tab default, never applied to existing work.
        import subprocess
        defaults=record.get('defaults',{})
        command=['tmux','-S',str(server),'new-session','-d','-s',record['name'],'-P','-F','#{session_id}']
        if defaults.get('cwd'):command+=['-c',defaults['cwd']]
        command+=['--',*(['/bin/sh'] if container_only or profile else defaults.get('argv',['/bin/sh']))]
        result=subprocess.run(command,capture_output=True,text=True,timeout=self._timeout(10))
        if result.returncode:raise InventoryError('session_start_failed',result.stderr[:500])
        session=result.stdout.strip();workspace=record['id']
        cfg=dict(kind=record['backend'],label=record['name'],socket_path=str(server),session_id=session,transport=TmuxAttachmentTransport(str(server),session))
        self.tabs.workspaces[workspace]=cfg
        snap=cfg['transport'].snapshot(self._deadline(5))
        record.pop('opening',None)
        record['native_session_id']=session
        record['native_key']=_digest({k:snap.get(k) for k in ('server','session_id','socket_identity','bridge_generation')})
        state=self.state();state['sessions'][record['id']]=record;self.save(state)
        if profile_owner is not None:
            bootstrap=snap['windows'][0]
            record['profile_seed']=dict(status='pending');state=self.state();state['sessions'][record['id']]=record;self.save(state)
            def guard():
                now=self.resolve(record['id'])
                if now['state']!='running' or now.get('native_key')!=record['native_key']:
                    raise InventoryError('stale_target','New profile session identity changed before launch.')
            seeded=profile_owner.create(profile,transport=cfg['transport'],name=record['name'],cwd=defaults.get('cwd',str(Path.home())),deadline=self._deadline(10),guard=guard)
            record['profile_seed']=seeded;state=self.state();state['sessions'][record['id']]=record;self.save(state)
            if seeded['status']!='applied':raise InventoryError('uncertain_effect','Profile seed was not verified; inspect session profile_seed before recovery.')
            live=cfg['transport'].snapshot(self._deadline(5))
            slot=next((w for w in live['windows'] if w['window_id']==bootstrap['window_id']),None)
            if slot is None or slot['panes']!=bootstrap['panes']:
                raise InventoryError('uncertain_effect','Bootstrap changed; it was preserved for inspection.')
            cfg['transport'].command(self._deadline(5),'kill-window','-t',bootstrap['window_id'])
        if record.get('formatting'):
            from .tab_formatting import TabFormatting
            TabFormatting(self.root,tabs=self.tabs).execute('tabs.format.configure',dict(workspace=workspace,policy=record['formatting']))
        return self.resolve(record['id'])
