"""Durable reversible ownership of tab decoration, independent of backend."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time

from .managed_inventory import InventoryError
from .json_decode import decode_json
from .tab_organization import digest, TmuxTransport

READS=frozenset(('tabs.format.status','tabs.format.inspect','tabs.format.override-inspect'))
VERBS=('status','inspect','enable','pause','resume','rollback','reenable','reset','configure')
from .tab_format_policy import DEFAULT_POLICY, effective_policy, validate_policy


class TabFormatting:
    def __init__(self, root, *, tabs):
        self.root=Path(root)/'tab-formatting';self.tabs=tabs
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.root/'state.json'

    @contextmanager
    def locked(self,deadline=None):
        import fcntl
        fd=os.open(self.root/'lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            deadline=deadline or time.monotonic()+10
            while True:
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:
                        raise InventoryError('formatting_busy','Formatting owner lock deadline exhausted.')
                    time.sleep(.01)
            yield
        finally:os.close(fd)

    def read(self):
        if not self.path.exists():return dict(schema_version=1,policy=dict(DEFAULT_POLICY),workspaces={})
        value=decode_json(self.path.read_text())
        if value.get('schema_version')!=1:raise InventoryError('configuration_unavailable','Unsupported formatting state.')
        value['policy']=dict(DEFAULT_POLICY,**value.get('policy',{}))
        value.setdefault('workspace_policies',{})
        return value

    def save(self,value):
        fd,name=tempfile.mkstemp(dir=self.root,prefix='.state-')
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(json.dumps(value,allow_nan=False,separators=(',',':')));stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)

    def identity(self,snapshot):
        return digest({k:snapshot.get(k) for k in ('server','session_id','socket_identity','bridge_generation')})

    @staticmethod
    def presentation_target(inspected):
        # Titles are live display metadata, not namespace or process custody.
        snapshot=inspected['snapshot']
        stable=dict(snapshot,windows=[dict(window,panes=[
            {key:value for key,value in pane.items() if key!='pane_title'}
            for pane in window['panes']]) for window in snapshot['windows']])
        return dict(inspected['target'],generation=digest(stable))

    def target(self,scope='workspace',workspace=None):
        if scope=='global':
            return dict(host=self.tabs.host,environment=self.tabs.environment,
                        workspace='*',presentation='formatting',generation=digest(self.read()['policy']))
        if scope!='workspace':raise InventoryError('invalid_argument','scope must be global or workspace.')
        if workspace is None and len(self.tabs.workspaces)==1:workspace=next(iter(self.tabs.workspaces))
        from .tab_lifecycle import TabLifecycle
        inspected=TabLifecycle(self.tabs.root,workspaces=self.tabs.workspaces,
            host=self.tabs.host,environment=self.tabs.environment).inspect(workspace)
        return self.presentation_target(inspected)

    def configure(self,state,policy,*,workspace=None):
        values=validate_policy(policy)
        if workspace is None:
            state['policy'].update(values);result=dict(state['policy'])
        else:
            state.setdefault('workspace_policies',{}).setdefault(workspace,{}).update(values)
            result=effective_policy(state,workspace)
        self.save(state)
        return dict(status='configured',policy=result,scope='global' if workspace is None else 'workspace')

    def new_record(self,state,name,identity,*,enabled):
        active_conflict=any(other!=name and value.get('identity')==identity for other,value in state['workspaces'].items())
        retired_conflict=any(other!=name and identity in records for other,records in state.get('retired_workspaces',{}).items())
        if active_conflict or retired_conflict:
            raise InventoryError('formatting_custody_conflict','Another workspace alias owns this namespace baseline; use that workspace.')
        record=dict(identity=identity,enabled=enabled,paused=False,windows={})
        state['workspaces'][name]=record
        return record

    def replace_namespace(self,state,name,identity,*,enabled=False):
        """Retain originals before explicit or opted-in namespace rollover."""
        record=state['workspaces'][name]
        retired=state.setdefault('retired_workspaces',{}).setdefault(name,{})
        previous=retired.get(identity)
        self.new_record(state,name,identity,enabled=enabled)  # checks alias custody
        retired[record['identity']]=record
        record=previous or state['workspaces'][name]
        state['workspaces'][name]=record
        retired.pop(identity,None)
        self.save(state)
        return record

    def execute(self,operation,arguments):
        result=self._execute(operation,arguments)
        if (operation in ('tabs.format.enable','tabs.format.resume','tabs.format.reenable')
                and result.get('status')=='applied' and getattr(self.tabs,'host_managed',False)):
            result=self.ensure_monitor(result)
        return result

    def ensure_monitor(self,result):
        """Enable continuous projection only for the trusted persisted host owner.

        Injected owners have no persisted discovery contract. The existing monitor
        is shared; this method never replaces it, adjusts its policy or returns
        another workspace's observation snapshot.
        """
        from .tab_monitor import TabMonitor
        result=dict(result)
        try:
            started=TabMonitor(self.tabs.root).execute('tabs.monitor.start',{})
            monitor=started['monitor']
            capable='tab-formatting-v1' in monitor.get('capabilities',[])
            interval=monitor['settings']['interval']
            result['monitor']=dict(status=monitor['status'],interval=interval,
                already_running=started.get('already_running',False),formatting_capability=capable)
            if monitor['status']!='running':
                raise InventoryError('monitor_start_failed','Formatting monitor is not running.')
            if not capable:
                raise InventoryError('monitor_formatting_unqualified','Existing monitor lacks a qualified formatting capability; no restart was attempted.')
            if interval>20:
                raise InventoryError('monitor_interval_exceeds_freshness','Existing monitor interval exceeds the formatting freshness budget; settings were preserved.')
        except Exception as error:
            result['status']='partial'
            result.setdefault('failures',[]).append(dict(code=getattr(error,'code','monitor_start_failed')))
            result.setdefault('monitor',dict(status='unavailable',interval=None,formatting_capability=False))
        return result

    @staticmethod
    def override_key(snapshot, window):
        namespace = (snapshot.get('server'), snapshot.get('socket_identity') or snapshot.get('bridge_generation'))
        return digest(dict(namespace=namespace, window=window))

    def linked_targets(self, lifecycle, selected, snapshot, target, deadline):
        sessions = set(selected.get('linked_sessions', ()))
        if snapshot['session_id'] not in sessions:
            raise InventoryError('unsupported_target', 'Linked tab memberships are unavailable.')
        missing = sessions - {snapshot['session_id']}
        if not missing:
            return []
        targets = []
        for workspace in self.tabs.workspaces:
            if workspace == target['workspace']:
                continue
            try:
                candidate = lifecycle.inspect(workspace, window_ids=[selected['window_id']], deadline=deadline)
            except (OSError, ValueError):
                continue
            other = candidate['snapshot']
            if self.override_key(other, selected['window_id']) != self.override_key(snapshot, selected['window_id']):
                continue
            session_id = other['session_id']
            if session_id not in missing or not any(row['window_id'] == selected['window_id']
                                                    for row in other['windows']):
                continue
            targets.append(self.presentation_target(candidate))
            missing.remove(session_id)
            if not missing:
                return targets
        raise InventoryError('unsupported_target', 'Every linked appearance must belong to an enrolled session.')

    def override(self, verb, arguments, *, authorize_linked=None):
        from .tab_format_policy import validate_style_override
        from .tab_format_transport import WINDOW_OPTIONS
        from .tab_lifecycle import TabLifecycle

        allowed = {'workspace', 'window', 'expected_target'}
        if verb == 'override-set':
            allowed.add('style')
        if not isinstance(arguments, dict) or set(arguments) - allowed:
            raise InventoryError('invalid_argument', 'Unsupported formatting override arguments.')
        style = validate_style_override(arguments.get('style')) if verb == 'override-set' else None
        workspace = arguments.get('workspace')
        if workspace is None and len(self.tabs.workspaces) == 1:
            workspace = next(iter(self.tabs.workspaces))
        if workspace not in self.tabs.workspaces:
            raise InventoryError('ambiguous_target', 'Select one owned workspace.')
        transport = self.tabs.workspaces[workspace]['transport']
        if not hasattr(transport, 'formatting'):
            raise InventoryError('unsupported_target', 'Backend formatting is unavailable.')
        deadline = time.monotonic() + 10
        lifecycle = TabLifecycle(self.tabs.root, workspaces=self.tabs.workspaces,
                                host=self.tabs.host, environment=self.tabs.environment)
        with self.locked(deadline):
            inspected = lifecycle.inspect(workspace, deadline=deadline)
            target = self.presentation_target(inspected)
            snapshot = inspected['snapshot']
            window = arguments.get('window')
            selected = next((row for row in snapshot['windows'] if row['window_id'] == window), None)
            if selected is None:
                raise InventoryError('stale_target', 'Exact tab was not found.')
            if verb != 'override-inspect' and arguments.get('expected_target') != target:
                raise InventoryError('stale_target', 'Presentation changed before formatting.')
            state = self.read()
            overrides = state.setdefault('tab_overrides', {})
            key = self.override_key(snapshot, window)
            saved = overrides.get(key)
            options = transport.formatting('read', dict(window=window), deadline)
            if verb != 'override-inspect':
                fresh = lifecycle.inspect(workspace, deadline=deadline)
                current = next((row for row in fresh['snapshot']['windows'] if row['window_id'] == window), None)
                if (current is None or self.presentation_target(fresh) != target
                        or current.get('linked_appearances') != selected.get('linked_appearances')):
                    raise InventoryError('stale_target', 'Tab identity or linked appearances changed before formatting.')
                if current.get('linked'):
                    appearances = self.linked_targets(lifecycle, current, fresh['snapshot'], target, deadline)
                    if appearances:
                        if authorize_linked is None:
                            raise InventoryError('insufficient_scope', 'Linked tab style requires control of every appearance.')
                        authorize_linked(appearances)
            if verb == 'override-set':
                native_style = ','.join([f"fg={style['foreground']}", f"bg={style['background']}", *style['attributes']])
                values = dict(zip(WINDOW_OPTIONS, (' #W ', ' #W ', native_style, native_style)))
                original = saved['original'] if saved else options
                overrides[key] = dict(style=style, original=original)
                self.save(state)
                options = transport.formatting('write', dict(window=window, values=values), deadline)
                if any(options[name]['value'] != value for name, value in values.items()):
                    raise InventoryError('formatting_mismatch', 'Tab formatting override did not match readback.')
                saved = overrides[key]
            elif verb == 'override-clear' and saved:
                values = {name: row['value'] if row['explicit'] else None
                          for name, row in saved['original'].items()}
                options = transport.formatting('write', dict(window=window, values=values), deadline)
                if any(options[name]['value'] != value for name, value in values.items()):
                    raise InventoryError('restoration_mismatch', 'Tab style restoration did not match readback.')
                del overrides[key]
                self.save(state)
                saved = None
            return dict(status='inspection' if verb == 'override-inspect' else 'applied',
                        target=target, window=window, override=saved['style'] if saved else None,
                        options=options)

    def _execute(self,operation,arguments):
        verb=operation.removeprefix('tabs.format.')
        if verb in ('override-set', 'override-inspect', 'override-clear'):
            return self.override(verb, arguments)
        if verb not in VERBS or not isinstance(arguments,dict) or set(arguments)-{'scope','workspace','policy','expected_target','preset'}:
            raise InventoryError('invalid_argument','Unsupported formatting arguments.')
        if 'preset' in arguments:
            if verb != 'configure':raise InventoryError('invalid_argument','Preset selection requires configure.')
            arguments=dict(arguments)
            policy=dict(arguments.get('policy',{}))
            if 'preset' in policy and policy['preset']!=arguments['preset']:
                raise InventoryError('invalid_argument','Conflicting preset selections.')
            policy['preset']=arguments['preset'];arguments['policy']=policy
        scope=arguments.get('scope','workspace')
        if scope not in ('global','workspace'):raise InventoryError('invalid_argument','scope must be global or workspace.')
        if scope=='global':
            if arguments.get('workspace') is not None or verb not in ('configure','status','inspect'):
                raise InventoryError('invalid_argument','Global display scope supports configure/status/inspect without workspace.')
            with self.locked():
                state=self.read();target=self.target('global')
                if arguments.get('expected_target') is not None and arguments['expected_target']!=target:
                    raise InventoryError('stale_target','Global display policy changed.')
                if verb=='configure':return dict(self.configure(state,arguments.get('policy',{})),target=target)
                return dict(status='inspection',scope='global',target=target,policy=state['policy'])
        name=arguments.get('workspace')
        if name is None and len(self.tabs.workspaces)==1:name=next(iter(self.tabs.workspaces))
        if name not in self.tabs.workspaces:raise InventoryError('ambiguous_target','Select one owned workspace.')
        # Preferences can be disabled before terminal availability or custody.
        if verb=='configure':
            with self.locked():
                supplied=arguments.get('expected_target')
                if supplied is not None and supplied!=self.target(workspace=name):
                    raise InventoryError('stale_target','Policy pin does not identify the selected current workspace.')
                return self.configure(self.read(),arguments.get('policy',{}),workspace=name)
        config=self.tabs.workspaces[name];transport=config['transport'];deadline=time.monotonic()+10
        if not hasattr(transport,'formatting'):raise InventoryError('unsupported_target','Backend formatting is unavailable.')
        from .tab_lifecycle import TabLifecycle
        inspected=TabLifecycle(self.tabs.root,workspaces=self.tabs.workspaces,host=self.tabs.host,environment=self.tabs.environment).inspect(name,deadline=deadline)
        snapshot=inspected['snapshot'];expected=self.presentation_target(inspected)
        if arguments.get('expected_target') is not None and arguments['expected_target']!=expected:
            raise InventoryError('stale_target','Presentation changed before formatting.')
        with self.locked(deadline):
            state=self.read();record=state['workspaces'].get(name)
            identity=self.identity(snapshot)
            namespace_changed=bool(record and record['identity']!=identity)
            if namespace_changed and verb not in ('enable','status','inspect'):
                raise InventoryError('stale_target','Formatting baseline belongs to a different namespace; use enable to capture the current namespace while preserving it.')
            if verb in ('status','inspect'):
                from .tab_format_rendering import capabilities
                return dict(status='stale_target' if namespace_changed else 'inspection',
                    namespace_matches=not namespace_changed,target=expected,policy=effective_policy(state,name),record=record,
                    capabilities=capabilities(config['kind'],identity=config.get('formatting_identity')),
                    available_presets=['slate','dusk','graphite','legacy'],
                    windows=[dict(window=w['window_id'],options=transport.formatting('read',dict(window=w['window_id']),deadline)) for w in snapshot['windows']])
            if namespace_changed:
                record=self.replace_namespace(state,name,identity)
            if record is None:
                if verb in ('rollback','reenable','resume'):
                    raise InventoryError('baseline_missing','No saved original formatting baseline; use enable first.')
                record=self.new_record(state,name,identity,enabled=False)
            if verb in ('pause','rollback','reset'):
                record.update(enabled=False,paused=verb=='pause');self.save(state)
                if verb=='pause':return dict(status='paused',target=expected)
                failures=[]
                live={w['window_id']:w for w in snapshot['windows']}
                for window,saved in record['windows'].items():
                    override = state.get('tab_overrides', {}).get(self.override_key(snapshot, window))
                    if override is not None:
                        # Clearing the override later must resume the restored
                        # baseline, even though this tab remains manually styled.
                        override['original'] = saved['original']
                        saved['restored'] = True
                        continue
                    if window not in live:
                        failures.append(dict(window=window,code='window_missing'));continue
                    if live[window].get('linked'):
                        failures.append(dict(window=window,code='linked_window'));continue
                    try:
                        wanted={k:v['value'] if v['explicit'] else None for k,v in saved['original'].items()}
                        actual=transport.formatting('write',dict(window=window,values=wanted),deadline)
                        if any(actual[k]['explicit']!=saved['original'][k]['explicit'] or actual[k]['value']!=saved['original'][k]['value'] for k in wanted):
                            raise InventoryError('restoration_mismatch','Restoration readback differs from saved original.')
                        saved['restored']=True
                    except Exception as error:failures.append(dict(window=window,code=getattr(error,'code','restoration_failed')))
                if 'session_original' in record:
                    try:
                        wanted={k:v['value'] if v['explicit'] else None for k,v in record['session_original'].items()}
                        actual=transport.formatting('write-session',dict(values=wanted),deadline)
                        if any(actual[k]['explicit']!=v['explicit'] or actual[k]['value']!=v['value'] for k,v in record['session_original'].items()):
                            raise InventoryError('restoration_mismatch','Session restoration differs from saved original.')
                        record['session_restored']=True
                    except Exception as error:failures.append(dict(code=getattr(error,'code','session_restoration_failed')))
                if verb=='reset':state.setdefault('workspace_policies',{}).pop(name,None)
                self.save(state)
                try:transport.formatting('refresh',{},deadline)
                except Exception as error:failures.append(dict(code=getattr(error,'code','refresh_failed')))
                return dict(status='partial' if failures else 'reset' if verb=='reset' else 'rolled_back',failures=failures,target=expected)
            workspace_policy=state.get('workspace_policies',{}).get(name,{})
            if verb in ('enable','reenable') and state['policy']['enabled'] and workspace_policy.get('enabled') is False:
                workspace_policy['enabled']=True
                self.save(state)
            policy=effective_policy(state,name)
            if not policy['enabled']:
                import shlex
                global_disabled=not state['policy']['enabled']
                return dict(status='disabled',target=expected,policy=policy,
                    reason='global_policy_disabled' if global_disabled else 'workspace_policy_disabled',
                    message='Formatting was not applied: the '+('global' if global_disabled else 'workspace')+' formatting policy is disabled.',
                    next_action=('codex-wake tabs format configure --scope global --policy \'{"enabled":true}\''
                                 if global_disabled else 'codex-wake tabs format enable --workspace '+shlex.quote(name)))
            if verb=='resume':
                record.pop('pause_reason',None)
                for saved in record['windows'].values():
                    saved.pop('paused',None);saved.pop('pause_reason',None)
            elif record.get('pause_reason')=='manual_session_style':
                return dict(status='paused',target=expected,reason='manual_session_style')
            record.update(enabled=True,paused=False);self.save(state)
            # Explicit enable uses public observations. Automatic refresh passes
            # its already bounded snapshot directly to the same apply path.
            rows=self.tabs.execute('tabs.list',{})['resources']
            resources={r['window']['window_id']:r for r in rows if r['target']['workspace']==name}
            failures=self.apply(state,record,snapshot,resources,transport,deadline,policy=policy,resume_manual=verb=='resume')
            return dict(status='partial' if failures else 'applied',target=expected,failures=failures)

    def session_plan(self,state,record,transport,deadline,*,resume_manual=False,current=None):
        """Read custody before window effects; prepare a deferred clock renewal."""
        if current is None:current=transport.formatting('read-session',{},deadline)
        if 'session_original' not in record:
            record['session_original']=current
            self.save(state)
        if not resume_manual and not record.get('session_restored') and record.get('session_last_applied'):
            if any(current[k]['value']!=v for k,v in record['session_last_applied'].items()):
                record['paused']=True;record['pause_reason']='manual_session_style';self.save(state)
                raise InventoryError('manual_override','Managed session style changed.')
        effective=record['session_original']['status-interval']['effective']
        interval=float(effective)
        interval=str(int(interval)) if 0<interval<=5 else '5'
        clock=current['@wake-format-clock']['value']
        try:remaining=int(clock)-time.time()
        except (TypeError,ValueError):remaining=0
        lease=clock if 15<=remaining<=20 and not record.get('session_restored') else str(int(time.time()+20))
        values={'status-interval':interval,'@wake-format-clock':lease}
        updates={k:v for k,v in values.items() if record.get('session_last_applied',{}).get(k)!=v or record.get('session_restored')}
        return current,values,updates

    @staticmethod
    def commit_session(record,transport,deadline,plan):
        current,values,updates=plan
        actual=transport.formatting('write-session',dict(values=updates),deadline) if updates else current
        if any(actual[k]['value']!=v for k,v in values.items()):
            raise InventoryError('formatting_mismatch','Session formatting readback differs from policy.')
        record['session_last_applied']=values
        record['session_restored']=False

    def renew_session(self,state,record,transport,deadline,*,resume_manual=False):
        """Renew an unchanged qualified source after checking session custody."""
        try:
            self.commit_session(record,transport,deadline,self.session_plan(
                state,record,transport,deadline,resume_manual=resume_manual))
            return []
        except Exception as error:
            return [dict(code=getattr(error,'code','session_formatting_failed'))]

    def apply(self,state,record,snapshot,resources,transport,deadline,*,policy=None,resume_manual=False,trust_unchanged=False,trusted_revisions=False):
        """Apply one snapshot under the owner lock, saving originals first."""
        from .tab_format_projection import project
        from .tab_format_expiry import expiring_options
        from .tab_format_monitor import semantic_revision
        failures=[]
        policy=policy or state['policy']
        policy_revision=digest(policy)
        windows=snapshot['windows'][:128]
        record['current_windows']=snapshot.get('all_window_ids',[window['window_id'] for window in windows])
        if len(snapshot['windows'])>128:failures.append(dict(code='formatting_window_capacity'))
        eligible=[]
        for window in windows:
            wid=window['window_id']
            if self.override_key(snapshot, wid) in state.get('tab_overrides', {}):
                continue
            if window.get('linked'):
                failures.append(dict(window=wid,code='linked_window'));continue
            if not resume_manual and record['windows'].get(wid,{}).get('paused'):
                failures.append(dict(window=wid,code='manual_override'));continue
            eligible.append(window)
        # A trusted monitor sample may reuse a settled projection between audits.
        # Any changed projection is still read and custody-checked before writing.
        prepared={}
        if trust_unchanged:
            dirty=[]
            for window in eligible:
                wid=window['window_id'];saved=record['windows'].get(wid,{})
                resource=resources.get(wid,dict(window=window))
                revision=semantic_revision(resource,trusted=trusted_revisions and not resource.get('monitor_unavailable'))
                reusable=(revision is not None and saved.get('projection_revision')==revision
                    and saved.get('projection_policy')==policy_revision and saved.get('panes')==window.get('panes')
                    and saved.get('projection') and saved.get('last_applied') and not saved.get('restored'))
                if reusable and saved.get('evidence_revision')==resource.get('evidence_revision'):
                    rendered=dict(saved['projection'],options=saved['last_applied'])
                    options=saved['last_applied']
                else:
                    rendered=project(resource,dict(policy,_source_lease=True),now=time.time())
                    options=expiring_options(rendered['options'],observed_at=time.time(),shared_lease=True,
                                             fallback_styles=rendered['fallback_styles'])
                prepared[wid]=(rendered,options,revision,resource.get('evidence_revision'))
                if (not saved.get('restored') and saved.get('last_applied')==options
                        and time.time()-saved.get('last_audited_at',0)<60):
                    saved['projection']={k:v for k,v in rendered.items() if k!='options'}
                    saved.update(projection_revision=revision,projection_policy=policy_revision,
                                 evidence_revision=resource.get('evidence_revision'))
                else:dirty.append(window)
            eligible=dirty
        try:
            combined=getattr(transport,'formatting_read_session_windows',None)
            if eligible and 'session_original' in record and callable(combined):
                current,observed=combined([w['window_id'] for w in eligible],deadline)
                if not isinstance(observed,list) or len(observed)!=len(eligible):
                    raise InventoryError('formatting_mismatch','Native batch readback count differs.')
                session=self.session_plan(state,record,transport,deadline,resume_manual=resume_manual,current=current)
                reads=[dict(error=value['error'].get('code','formatting_failed')) if isinstance(value,dict) and 'error' in value else dict(result=value) for value in observed]
            else:
                session=self.session_plan(state,record,transport,deadline,resume_manual=resume_manual)
                reads=self.batch(transport,[dict(action='read',window=w['window_id']) for w in eligible],deadline)
        except Exception as error:return [dict(code=getattr(error,'code','session_formatting_failed'))]
        pending=[]
        new_originals=False
        for window,read in zip(eligible,reads):
            wid=window['window_id']
            if 'error' in read:
                failures.append(dict(window=wid,code=read['error']));continue
            try:
                current=read['result']
                if wid not in record['windows']:
                    record['windows'][wid]=dict(original=current,last_applied=None,restored=False)
                    new_originals=True
                saved=record['windows'][wid]
                saved['last_audited_at']=time.time()
                saved['panes']=window.get('panes',[])
                last=saved.get('last_applied')
                changed=(last and not saved.get('restored') and any(
                    not current[k]['explicit'] or current[k]['value']!=v or current[k]['effective']!=v
                    or current[k].get('parent')!=saved.get('parent_at_apply',{}).get(k,current[k].get('parent'))
                    for k,v in last.items()))
                if not resume_manual and changed:
                    saved.update(paused=True,pause_reason='manual_style')
                    failures.append(dict(window=wid,code='manual_override'));continue
                if resume_manual:saved.pop('paused',None);saved.pop('pause_reason',None)
                saved['parent_at_apply']={k:v.get('parent') for k,v in current.items()}
                resource=resources.get(wid,{})
                if wid in prepared:
                    rendered,options,revision,evidence=prepared[wid]
                else:
                    rendered=project(resource,dict(policy,_source_lease=True),now=time.time())
                    stamp=resource.get('monitor_observed_at',time.time())
                    options=expiring_options(rendered['options'],observed_at=stamp,render_mode=policy.get('render_mode','full'),show_stale=False,shared_lease=True,fallback_styles=rendered['fallback_styles'])
                    revision=semantic_revision(resource,trusted=trusted_revisions and not resource.get('monitor_unavailable'))
                    evidence=resource.get('evidence_revision')
                # One shared publisher lease changes independently of window options.
                # Unchanged projections do not trigger native window writes.
                if all(current[k]['value']==v for k,v in options.items()):
                    saved['projection']={k:v for k,v in rendered.items() if k!='options'}
                    saved.update(projection_revision=revision,projection_policy=policy_revision,evidence_revision=evidence)
                    continue
                pending.append((wid,options,rendered,revision,evidence))
            except Exception as error:failures.append(dict(window=wid,code=getattr(error,'code','formatting_failed')))
        # Existing baselines are already durable. Persist new originals before
        # a window effect; settled refreshes need only the final checkpoint.
        if pending and new_originals:self.save(state)
        writes=self.batch(transport,[dict(action='write',window=wid,values=options) for wid,options,_,_,_ in pending],deadline)
        for (wid,options,rendered,revision,evidence),write in zip(pending,writes):
            if 'error' in write:
                failures.append(dict(window=wid,code=write['error']));continue
            actual=write['result']
            if any(actual[k]['value']!=v for k,v in options.items()):
                failures.append(dict(window=wid,code='formatting_mismatch'));continue
            record['windows'][wid].update(last_applied=options,restored=False,
                projection_revision=revision,projection_policy=policy_revision,evidence_revision=evidence,
                projection={k:v for k,v in rendered.items() if k!='options'})
        # A failed changed window may still display an old dynamic cue. Do not
        # extend that cue's shared lease unless its new projection was verified.
        lease_safe=True
        for failure in failures:
            wid=failure.get('window')
            if wid is None:lease_safe=False;break
            saved=record['windows'].get(wid,{})
            if saved.get('last_applied') and (wid not in prepared or prepared[wid][1]!=saved['last_applied']):
                lease_safe=False;break
        if lease_safe:
            try:self.commit_session(record,transport,deadline,session)
            except Exception as error:failures.append(dict(code=getattr(error,'code','session_formatting_failed')))
        self.save(state)
        try:
            # Native set-option already schedules redraw for attached clients.
            # Keep explicit refresh for CLI and non-tmux host adapters.
            if pending and not (trust_unchanged and isinstance(transport,TmuxTransport)):
                transport.formatting('refresh',{},deadline)
        except Exception as error:failures.append(dict(code=getattr(error,'code','refresh_failed')))
        return failures

    @staticmethod
    def batch(transport,requests,deadline):
        """Bounded finite batches avoid a host bridge startup per window."""
        if not requests:return []
        if hasattr(transport,'formatting_batch'):
            try:
                results=transport.formatting_batch(requests,deadline)
                if not isinstance(results,list) or len(results)!=len(requests):
                    raise InventoryError('formatting_mismatch','Native batch readback count differs.')
                return [dict(error=value['error'].get('code','formatting_failed')) if isinstance(value,dict) and 'error' in value else dict(result=value) for value in results]
            except Exception as error:
                return [dict(error=getattr(error,'code','formatting_batch_failed')) for _ in requests]
        results=[]
        for request in requests:
            args={k:v for k,v in request.items() if k!='action'}
            try:results.append(dict(result=transport.formatting(request['action'],args,deadline)))
            except Exception as error:results.append(dict(error=getattr(error,'code','formatting_failed')))
        return results

    def renew_unchanged(self,snapshot,previous,*,deadline):
        """Renew settled daemon projections without rescanning physical windows.

        The caller has matched the exact trusted whole-source revision, transport
        configuration and state-file identity. Native session custody is still
        checked; socket replacement or a due window audit forces full qualification.
        """
        import copy
        import stat
        from .tab_format_monitor import semantic_revision
        from .tab_format_projection import project
        from .tab_format_expiry import expiring_options
        grouped={}
        for resource in snapshot.get('resources',[]):
            grouped.setdefault(resource.get('target',{}).get('workspace'),{})[resource['window']['window_id']]=resource
        with self.locked(deadline):
            state=self.read()
            if not state['policy'].get('enabled',True):return dict(status='disabled',workspaces=[])
            plans=[]
            for outcome in previous.get('workspaces',[]):
                if outcome.get('status')!='applied':continue
                name=outcome['workspace'];record=state['workspaces'].get(name)
                config=self.tabs.workspaces.get(name,{})
                policy=effective_policy(state,name)
                if (not record or not record.get('enabled') or record.get('paused') or not policy['enabled']
                        or config.get('kind') not in ('tmux','byobu') or 'session_original' not in record):return None
                transport=config['transport']
                try:
                    info=Path(transport.socket).lstat()
                    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.geteuid()
                            or [info.st_dev,info.st_ino]!=transport.socket_identity):return None
                except (OSError,AttributeError):return None
                rows=grouped.get(name,{})
                if set(rows)!=set(record.get('current_windows',[])):return None
                policy_revision=digest(policy)
                for wid,resource in rows.items():
                    saved=record['windows'].get(wid,{})
                    revision=semantic_revision(resource,trusted=not resource.get('monitor_unavailable'))
                    if (revision is None or saved.get('projection_revision')!=revision
                            or saved.get('projection_policy')!=policy_revision or saved.get('restored')
                            or saved.get('paused') or not saved.get('last_applied')
                            or saved.get('panes')!=resource.get('window',{}).get('panes')
                            or time.time()-saved.get('last_audited_at',0)>=60):return None
                    if saved.get('evidence_revision')!=resource.get('evidence_revision'):
                        rendered=project(resource,dict(policy,_source_lease=True),now=time.time())
                        options=expiring_options(rendered['options'],observed_at=time.time(),shared_lease=True,
                                                 fallback_styles=rendered['fallback_styles'])
                        if options!=saved['last_applied']:return None
                        saved.update(projection={k:v for k,v in rendered.items() if k!='options'},
                                     evidence_revision=resource.get('evidence_revision'))
                plans.append((outcome,record,transport))
            result=copy.deepcopy(previous)
            for outcome,record,transport in plans:
                failures=self.renew_session(state,record,transport,deadline)
                if failures:
                    result['status']='partial'
                    for row in result['workspaces']:
                        if row.get('workspace')==outcome['workspace']:row.update(status='partial',failures=failures)
            if plans:self.save(state)
            return result

    def refresh(self,snapshot,*,deadline=None,trusted_revisions=False):
        """Project a trusted monitor/event snapshot without repeating probes.

        Unavailable retained observations clear dynamic cues immediately while
        preserving static type/name and redacted inspect evidence.
        """
        deadline=deadline or time.monotonic()+10
        resources=snapshot.get('resources',[])
        grouped={}
        for resource in resources:
            name=resource.get('target',{}).get('workspace')
            if name in self.tabs.workspaces:
                if resource.get('monitor_unavailable'):
                    import copy
                    resource=copy.deepcopy(resource)
                    observed=resource.get('traits',{})
                    for traits in [observed.get('traits',{}),*[p.get('traits',{}) for p in observed.get('panes',[])]]:
                        for key in ('activity','health','error'):
                            if isinstance(traits.get(key),dict):traits[key]['source_available']=False
                grouped.setdefault(name,{})[resource['window']['window_id']]=resource
        results=[dict(workspace=value.get('workspace'),status='unavailable',code=value.get('reason',value.get('code','observation_unavailable'))) for value in snapshot.get('unavailable',[])[:64]]
        with self.locked(deadline):
            state=self.read()
            if not state['policy'].get('enabled',True):return dict(status='disabled',workspaces=[])
            for name,rows in grouped.items():
                if time.monotonic()>=deadline:
                    results.append(dict(workspace=name,status='unavailable',code='formatting_deadline'));continue
                record=state['workspaces'].get(name)
                policy=effective_policy(state,name)
                if not policy['enabled']:
                    results.append(dict(workspace=name,status='disabled'));continue
                if record and (not record.get('enabled') or record.get('paused')):
                    results.append(dict(workspace=name,status='paused' if record.get('paused') else 'disabled'));continue
                config=self.tabs.workspaces[name];transport=config['transport']
                try:
                    from .tab_lifecycle import TabLifecycle
                    from .tab_format_monitor import semantic_revision
                    lifecycle=TabLifecycle(self.tabs.root,workspaces=self.tabs.workspaces,host=self.tabs.host,environment=self.tabs.environment)
                    selected=None
                    if trusted_revisions and record:
                        policy_revision=digest(policy)
                        selected=set(record.get('current_windows',[]))-set(rows)
                        for wid,resource in rows.items():
                            saved=record['windows'].get(wid,{})
                            revision=semantic_revision(resource,trusted=not resource.get('monitor_unavailable'))
                            if (revision is None or saved.get('projection_revision')!=revision
                                    or saved.get('projection_policy')!=policy_revision or saved.get('restored')
                                    or saved.get('paused') or not saved.get('last_applied')
                                    or saved.get('panes')!=resource.get('window',{}).get('panes')
                                    or time.time()-saved.get('last_audited_at',0)>=60):selected.add(wid)
                    for attempt in range(2):
                        physical=lifecycle.inspect(name,deadline=deadline,window_ids=selected)['snapshot']
                        extra=set()
                        if selected is not None:
                            for window in physical['windows']:
                                wid=window['window_id']
                                if wid in selected:continue
                                saved=record['windows'].get(wid,{}).get('panes',[])
                                panes=window.get('panes',[])
                                if (len(saved)!=len(panes) or any(
                                        {k:v for k,v in old.items() if k!='process_generation'}!=pane
                                        for old,pane in zip(saved,panes))):
                                    extra.add(wid);continue
                                for old,pane in zip(saved,panes):pane['process_generation']=old.get('process_generation')
                        if not extra:break
                        selected.update(extra)
                    else:raise InventoryError('stale_target','Physical panes changed during bounded formatting inspection.')
                    identity=self.identity(physical)
                    if record and identity!=record['identity']:
                        if not policy['recover_namespace'] or not any(not row.get('monitor_unavailable') for row in rows.values()):
                            raise InventoryError('stale_target','Formatting namespace changed; baseline preserved.')
                        record=self.replace_namespace(state,name,identity,enabled=True)
                        if not record.get('enabled') or record.get('paused'):
                            results.append(dict(workspace=name,status='paused' if record.get('paused') else 'disabled'));continue
                    if record is None:
                        record=self.new_record(state,name,identity,enabled=True);self.save(state)
                    # Clear old dynamic cues for missing samples before renewing a
                    # shared lease for other windows. Keep static metadata only
                    # while the saved exact pane identity is still represented.
                    for window in physical['windows']:
                        wid=window['window_id']
                        saved=record['windows'].get(wid,{})
                        if wid in rows:
                            if rows[wid].get('window',{}).get('panes')!=window.get('panes'):
                                rows[wid]=dict(window=window,traits={},monitor_unavailable=True,target=dict(presentation=config.get('kind')))
                            continue
                        if not saved:continue
                        panes=[]
                        if saved.get('panes')==window.get('panes'):
                            for pane in saved.get('projection',{}).get('details',{}).get('panes',[]):
                                traits=dict(pane.get('dimensions',{}),**pane.get('attention',{}))
                                for key in ('activity','health','error'):
                                    if isinstance(traits.get(key),dict):traits[key]=dict(traits[key],source_available=False)
                                panes.append(dict(pane_id=pane.get('pane_id'),traits=traits))
                        rows[wid]=dict(window=window,traits=dict(panes=panes),monitor_unavailable=True,target=dict(presentation=config.get('kind')))
                    # Never project onto a newly discovered or replaced window
                    # that was not represented in the trusted bounded sample.
                    physical=dict(physical,all_window_ids=[w['window_id'] for w in physical['windows']],windows=[w for w in physical['windows'] if w['window_id'] in rows
                        and w['panes']==rows[w['window_id']]['window']['panes']])
                    failures=self.apply(state,record,physical,rows,transport,deadline,policy=policy,trust_unchanged=True,trusted_revisions=trusted_revisions)
                    results.append(dict(workspace=name,status='partial' if failures else 'applied',failures=failures))
                except Exception as error:
                    results.append(dict(workspace=name,status='unavailable',code=getattr(error,'code','formatting_unavailable')))
        return dict(status='partial' if any(r['status'] in ('partial','unavailable') for r in results) else 'completed',workspaces=results)
