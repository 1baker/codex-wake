"""Bounded derived tab observations owned by one persistent host monitor.

Default tick1s; exact background health>=60s and eligible visible errors>=5s.
Retained metadata feeds and the shared cache avoid per-cycle inventory children.
Unsupported backends and explicit one-shot refresh use bounded isolated probes.
Observation generates no input/model calls or layout effects; separately enabled
formatting, organization and routing owners consume the same derived snapshot.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

from .json_decode import decode_json
from .managed_inventory import InventoryError
from .process import process_identity

DEFAULTS = dict(interval=1.0, probe_timeout=1.5, stale_after=20.0, cycle_timeout=10.0,
                concurrency=1, max_workspaces=64, max_snapshot_bytes=1048576,
                activity=True, health=True, errors=True, health_interval=60., error_interval=5.)
OPERATIONS = frozenset('tabs.monitor.'+verb for verb in ('start','status','refresh','stop'))
MAX_STATE = DEFAULTS['max_snapshot_bytes']
_OWNED_CHILDREN = {}


def _identity(pid):
    if type(pid) is not int or pid<=0:return None
    value = process_identity(pid)
    if value is None:
        return None
    try:
        if Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[0] == 'Z':
            return None
    except OSError:
        return None
    return dict(pid=pid,start_ticks=value['start_time_ticks'],boot_id=value.get('boot_id'))


def _read(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise InventoryError('monitor_state_unavailable','Monitor state must be private and user-owned.')
        with os.fdopen(os.dup(fd),'rb') as stream:
            raw=stream.read(MAX_STATE+1)
        if len(raw)>MAX_STATE:
            raise InventoryError('monitor_state_unavailable','Monitor state exceeds its bound.')
        return decode_json(raw)
    finally:
        os.close(fd)


def _publication_interval(settings):
    return min(10.,settings['stale_after']/2)


def _stable_time_observation():
    from .native_clock import configuration, snapshot
    # Absence of configured Stable Time is uncertainty, never permission to
    # acquire plain NTP or use the guest wall clock for freshness.
    return snapshot() if configuration() else {}


def _counter_observation(provider):
    from .native_intents import valid_counter
    try:
        value = provider()
        if (value.get('reason') in ('authenticated_utc', 'authenticated_counter_only')
                and valid_counter(value.get('counter'))):
            return dict(value['counter'])
    except Exception:
        pass
    return None


def _counter_age(origin, current):
    from .native_intents import valid_counter
    if not (valid_counter(origin) and valid_counter(current)
            and origin['epoch'] == current['epoch']
            and origin['frequency'] == current['frequency']
            and current['counter'] >= origin['counter']):
        return None
    from decimal import Decimal
    rate = max(origin['rate_ppm'], current['rate_ppm'])
    age = (Decimal(current['counter'] - origin['counter'] + 1) * 1000000
           / (Decimal(origin['frequency']) * (1000000 - rate)))
    return math.nextafter(float(age), math.inf)


def _save(path,value):
    raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
    _save_bytes(path,raw)


def _save_bytes(path,raw):
    if len(raw)>MAX_STATE:
        raise InventoryError('monitor_capacity','Derived monitor snapshot exceeds1MiB; reduce selected workspaces.')
    fd,name=tempfile.mkstemp(prefix='.monitor-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


@contextmanager
def _lock(path):
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise InventoryError('monitor_state_unavailable','Monitor lock must be private.')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise InventoryError('monitor_busy','Another owner is operating the selected monitor.') from None
        yield
    finally:
        os.close(fd)


class TabMonitor:
    ARGUMENTS = {'tabs.monitor.start':{'interval','probe_timeout','stale_after','cycle_timeout',
                    'activity','health','errors','health_interval','error_interval'},
                 'tabs.monitor.refresh':set(),'tabs.monitor.status':set(),'tabs.monitor.stop':{'timeout'}}

    def __init__(self,root,*,clock=None,monotonic=time.monotonic,clock_provider=None):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=self.root.stat()
        if info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise InventoryError('monitor_state_unavailable','Use a private same-user controller root.')
        self.directory=self.root/'tab-monitor'
        self.directory.mkdir(mode=0o700,exist_ok=True)
        info=self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise InventoryError('monitor_state_unavailable','Monitor directory must be private and canonical.')
        self.clock=clock if clock is not None else time.time
        self.clock_provider=(clock_provider if clock_provider is not None else
                             _stable_time_observation if clock is None else None)
        self.monotonic=monotonic
        self._published_revision=None
        self._published_at=-float('inf')

    def execute(self,operation,arguments):
        if operation not in self.ARGUMENTS:
            raise InventoryError('unsupported_operation','Unsupported tab monitor operation.')
        if not isinstance(arguments,dict) or set(arguments)-self.ARGUMENTS[operation]:
            raise InventoryError('invalid_argument','Unsupported tab monitor arguments.')
        if operation=='tabs.monitor.status':return self.status()
        if operation=='tabs.monitor.refresh':return self.refresh()
        with _lock(self.directory/'control.lock'):
            if operation=='tabs.monitor.start':return self.start(arguments)
            return self.stop(arguments.get('timeout',5))

    def _settings(self,arguments=None):
        result=dict(DEFAULTS)
        saved=_read(self.directory/'settings.json')
        if saved:result.update(saved)
        result.update(arguments or {})
        bounds={'interval':(.2,300),'probe_timeout':(.1,5),'stale_after':(.2,600),'cycle_timeout':(.5,30)}
        for key,(low,high) in bounds.items():
            value=result[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
                raise InventoryError('invalid_argument',key+' is outside the monitor bounds.')
        for key, low in (('health_interval',60),('error_interval',5)):
            value=result[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=3600:
                raise InventoryError('invalid_argument',key+' is outside the monitor bounds.')
        for key in ('activity','health','errors'):
            if type(result[key]) is not bool:
                raise InventoryError('invalid_argument',key+' must be boolean.')
        if result['stale_after']<result['interval']:
            raise InventoryError('invalid_argument','stale_after must cover at least one monitor interval.')
        return result

    def _running(self):
        record=_read(self.directory/'owner.json')
        if not record or record.get('state')!='running':return record,False
        expected=record.get('process')
        running=bool(isinstance(expected,dict) and _identity(expected.get('pid',0))==expected)
        if running:
            try:
                command=Path('/proc',str(expected['pid']),'cmdline').read_bytes().decode().split('\0')
                running=('codex_wake.tab_monitor' in command and '--serve' in command
                         and command[command.index('--serve')+1]==str(self.root))
            except (OSError,ValueError,IndexError,UnicodeError):running=False
        return record,running

    def status(self):
        settings=self._settings()
        record,running=self._running()
        snapshot=_read(self.directory/'snapshot.json')
        now=self.clock()
        if snapshot:
            if running and snapshot.get('monitor_generation')==record.get('generation') and record.get('observer'):
                snapshot['observer']=record['observer']
            age=(_counter_age(snapshot.get('clock_counter'), _counter_observation(self.clock_provider))
                 if self.clock_provider is not None else now-snapshot['observed_at'])
            fresh=age is not None and 0<=age<=settings['stale_after'] and (snapshot.get('origin')=='manual' or (running and snapshot.get('monitor_generation')==record.get('generation')))
            snapshot['freshness']='fresh' if fresh else 'stale'
            snapshot['age_seconds']=max(0,age) if age is not None else None
            snapshot['freshness_basis']=('stable_time_counter' if age is not None else 'clock_continuity_unavailable') if self.clock_provider is not None else 'injected_clock'
            if not fresh:
                for key in ('projection_revision','evidence_revision','projection_valid_until'):
                    snapshot.pop(key,None)
            for row in snapshot.get('resources',[]):
                row_age=age if self.clock_provider is not None else now-row.get('monitor_observed_at',0)
                row['monitor_freshness']='fresh' if fresh and row_age is not None and 0<=row_age<=settings['stale_after'] and not row.get('monitor_unavailable') else 'stale'
                if row['monitor_freshness']=='stale':
                    for key in ('projection_revision','evidence_revision','projection_valid_until'):
                        snapshot.pop(key,None);row.pop(key,None)
                    def mark(value):
                        if isinstance(value,dict):
                            if {'value','status','source','freshness'}<=value.keys() and value.get('status')=='observed':
                                value.update(status='stale',freshness='stale')
                                value['source_available']=False
                            if value.get('fresh') is True:value['fresh']=False
                            for item in value.values():mark(item)
                        elif isinstance(value,list):
                            for item in value:mark(item)
                    mark(row.get('traits',{}))
        return dict(monitor=dict(status='running' if running else 'stopped' if record and record.get('state')=='stopped'
                                  else 'lost' if record else 'inactive',
                                  process=record.get('process') if record else None,
                                  generation=record.get('generation') if record else None,settings=settings,
                                  last_error=record.get('last_error') if record else None,
                                  last_policy_operation=record.get('last_policy_operation') if record else None,
                                  last_formatting=record.get('last_formatting') if record else None,
                                  last_routing=record.get('last_routing') if record else None,
                                  observer=snapshot.get('observer') if snapshot else None,
                                  capabilities=record.get('capabilities',[]) if record else []),
                    snapshot=snapshot,application_effects=False)

    def _control_status(self, **flags):
        """Keep mutation acknowledgements below the retained-operation bound.

        Inventory and potentially large per-workspace diagnostics remain in the
        separate status/refresh reads, never the journaled start/stop result.
        """
        value=self.status()
        monitor=value['monitor']
        fields=('status','process','generation','settings','last_error','capabilities')
        return dict(monitor={key:monitor[key] for key in fields},
                    application_effects=False,**flags)

    def start(self,arguments):
        record,running=self._running()
        settings=self._settings(arguments)
        if running:
            if arguments and any(self._settings()[key]!=value for key,value in arguments.items()):
                raise InventoryError('monitor_running','Stop the current monitor before changing its settings.')
            return self._control_status(already_running=True)
        _save(self.directory/'settings.json',settings)
        env=dict(os.environ)
        for key in ('CODEX_THREAD_ID','CODEX_TURN_ID','CODEX_SESSION_ID'):
            env.pop(key,None)
        child=subprocess.Popen([sys.executable,'-m','codex_wake.tab_monitor','--serve',str(self.root)],
                               stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                               env=env,start_new_session=True)
        _OWNED_CHILDREN[str(self.root)]=child
        until=time.monotonic()+3
        while time.monotonic()<until:
            record,running=self._running()
            if running:
                return self._control_status(already_running=False)
            if child.poll() is not None:
                raise InventoryError('monitor_start_failed','Monitor exited before publishing a verified owner.')
            time.sleep(.02)
        # This is our unreaped child, not a PID inferred from a stale record.
        child.terminate()
        try:child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=1)
        raise InventoryError('monitor_start_failed','Monitor did not publish ownership before its deadline.')

    def stop(self,timeout):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not .1<=timeout<=10:
            raise InventoryError('invalid_argument','Stop timeout must be0.1..10seconds.')
        record,running=self._running()
        if not running:
            child=_OWNED_CHILDREN.pop(str(self.root),None)
            if child is not None:
                try:child.wait(timeout=.5)
                except subprocess.TimeoutExpired:_OWNED_CHILDREN[str(self.root)]=child
            return self._control_status(already_stopped=True)
        expected=record['process']
        if _identity(expected['pid'])!=expected:
            return self._control_status(already_stopped=True)
        os.kill(expected['pid'],signal.SIGTERM)
        until=time.monotonic()+timeout
        while time.monotonic()<until and _identity(expected['pid'])==expected:
            time.sleep(.02)
        result=self._control_status()
        if result['monitor']['status']!='running':
            child=_OWNED_CHILDREN.pop(str(self.root),None)
            if child is not None:
                try:child.wait(timeout=.5)
                except subprocess.TimeoutExpired:_OWNED_CHILDREN[str(self.root)]=child
        result['stop_requested']=True
        return result

    def _probe(self,workspace,timeout):
        args=[sys.executable,'-m','codex_wake.tab_monitor','--probe',str(self.root),'--budget',str(timeout)]
        if workspace is not None:args+=['--workspace',workspace]
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            out,err=child.communicate(timeout=timeout+.1)
            if len(out)>MAX_STATE or len(err)>32768:
                return dict(status='unavailable',reason='probe_output_bound')
            if child.returncode:
                return dict(status='unavailable',reason='probe_failed')
            value=json.loads(out)
            return value if isinstance(value,dict) else dict(status='unavailable',reason='invalid_probe')
        except subprocess.TimeoutExpired:
            # Owned child process group contains only this read-only probe and
            # its finite transport clients, never the existing tmux/agent server.
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL)
            child.communicate(timeout=1)
            return dict(status='unavailable',reason='probe_deadline')
        except ValueError:
            return dict(status='unavailable',reason='invalid_probe')

    def refresh(self,*,origin='manual',deadline=None):
        settings=self._settings()
        with _lock(self.directory/'refresh.lock'):
            counter = _counter_observation(self.clock_provider) if self.clock_provider is not None else None
            deadline=deadline or time.monotonic()+settings['cycle_timeout']
            previous=_read(self.directory/'snapshot.json') or {}
            known=self._probe(None,min(settings['probe_timeout'],max(.1,deadline-time.monotonic())))
            names=known.get('workspaces',[])[:settings['max_workspaces']]
            old=previous.get('resources',[])
            cursor=previous.get('cursor',0)%len(names) if names else 0
            order=names[cursor:]+names[:cursor]
            resources=[];unavailable=[];attempted=0
            if len(known.get('workspaces',[]))>settings['max_workspaces']:
                unavailable.append(dict(status='unavailable',reason='workspace_capacity'))
            for name in order:
                remaining=deadline-time.monotonic()
                if remaining>.1:
                    result=self._probe(name,min(settings['probe_timeout'],remaining));attempted+=1
                else:result=dict(status='unavailable',reason='cycle_deadline')
                if result.get('status')=='completed':
                    for row in result.get('result',{}).get('resources',[]):
                        resources.append(dict(row,monitor_observed_at=self.clock(),monitor_unavailable=False))
                    unavailable.extend(result.get('result',{}).get('unavailable',[]))
                else:
                    unavailable.append(dict(workspace=name,status='unavailable',reason=result.get('reason','probe_unavailable')))
                    resources.extend(dict(row,monitor_unavailable=True) for row in old if row.get('target',{}).get('workspace')==name)
            if known.get('status')!='completed':
                resources=[dict(row,monitor_unavailable=True) for row in old]
                unavailable.append(dict(status='unavailable',reason=known.get('reason','discovery_unavailable')))
            owner_record,_=self._running()
            snapshot=dict(schema_version=1,observed_at=self.clock(),origin=origin,resources=resources,
                          clock_counter=counter,
                          observed_at_time_basis='guest_wall_display_only' if self.clock_provider is not None else 'injected_clock',
                          monitor_generation=owner_record.get('generation') if origin=='daemon' and owner_record else None,
                          unavailable=unavailable,workspaces=names,cursor=(cursor+attempted)%len(names) if names else 0,
                          discovery=known.get('discovery'),
                          status='partial' if unavailable else 'complete' if names else 'not_found')
            _save(self.directory/'snapshot.json',snapshot)
        return self.status()

    def _policy_tick(self,record):
        from .tab_organization_policy import TabOrganizationPolicy
        state=TabOrganizationPolicy(self.root,workspaces={}).execute('tabs.policy.status',{})['policy']
        if state['state']!='enabled':return
        from .tab_commands import operator_execute
        from .controller_tabs import controller_tabs_from_root
        owner=controller_tabs_from_root(self.root)
        key='monitor-'+record['generation']+'-'+str(state['revision'])
        value=operator_execute('tabs.policy.tick',{},self.root,owner=owner,request_id=key)
        operation=value['result']['operation']
        record['last_policy_operation']=dict(operation_id=operation['operation_id'],execution=operation['execution'],
                                              policy_revision=state['revision'])

    def _routing_tick(self,snapshot,deadline,*,resources_loader=None):
        # Reuse the service-owned bounded observations; never create another monitor.
        from .terminal_routing import TerminalRouting
        from .controller_tabs import controller_tabs_from_root
        from .shortcut_store import read as routing_read
        try:state=routing_read(self.root/'terminal-routing'/'routing.json')
        except FileNotFoundError:state=None
        if not state or not (state.get('pending') or any(r['enabled'] for r in state.get('rules',{}).values())):
            return dict(status='inactive',outcomes=[])
        if time.monotonic()>=deadline:return dict(status='partial',reason='cycle_deadline')
        owner=controller_tabs_from_root(self.root)
        if not owner.host_managed:return dict(status='partial',reason='host_inventory_required')
        if resources_loader is not None:resources_loader()
        if not isinstance(snapshot.get('resources'),list):
            raise InventoryError('observation_unavailable','Routing requires observed resource rows.')
        return TerminalRouting(self.root,tabs=owner).tick(snapshot,deadline=deadline)

    def publish_observation(self, snapshot, record, *, resources_loader=None, resources_serializer=None, settings=None):
        """Persist changed evidence immediately, or a bounded liveness heartbeat.

        Only trusted producer revisions admit the quiet fast path. Legacy callers
        without a revision retain unconditional publication. Small diagnostics go
        to the owner heartbeat so status remains current between large writes.

        resources_serializer is an internal trusted producer seam: it returns a
        strict stdlib-encoded JSON array of complete retained resource rows. Only
        the service-owned observer supplies it; portable command input must never
        supply encoded JSON. Metadata remains strictly encoded here, while rows
        are neither materialized nor parsed or encoded a second time.
        """
        diagnostics=dict(snapshot.get('observer') or {})
        fields=('source_id','source_kind','workspace','state','reason','epoch','sequence',
                'owned_pid','backlog','pending_commands','buffered_bytes','startup_seconds')
        sources=diagnostics.get('sources',[])
        diagnostics['sources']=[{key:source[key] for key in fields if key in source}
                                for source in sources[:64]]
        diagnostics['source_count']=len(sources)
        diagnostics['sources_truncated']=len(sources)>64
        diagnostics['unknown_reasons']=diagnostics.get('unknown_reasons',[])[:32]
        if len(json.dumps(diagnostics,separators=(',',':')).encode())>32768:
            diagnostics['sources']=[];diagnostics['sources_truncated']=True
            diagnostics['unknown_reasons']=['observer_diagnostics_capacity']
        record['observer']=diagnostics
        revision=(snapshot.get('projection_revision'),snapshot.get('evidence_revision'))
        qualified=all(isinstance(value,str) and 0<len(value)<=128 for value in revision)
        settings=self._settings() if settings is None else settings
        heartbeat=_publication_interval(settings)
        now=self.monotonic()
        publish=(not qualified or revision!=self._published_revision or now-self._published_at>=heartbeat)
        if publish:
            if resources_serializer is not None:
                metadata={key:value for key,value in snapshot.items() if key!='resources'}
                encoded=json.dumps(metadata,allow_nan=False,separators=(',',':'))
                rows=resources_serializer()
                separator=',' if metadata else ''
                _save_bytes(self.directory/'snapshot.json',
                    (encoded[:-1]+separator+'"resources":'+rows+'}').encode())
            else:
                if resources_loader is not None:resources_loader()
                if not isinstance(snapshot.get('resources'),list):
                    raise InventoryError('observation_unavailable','Metadata-only frames cannot be persisted as inventory.')
                _save(self.directory/'snapshot.json',snapshot)
            self._published_revision=revision if qualified else None
            self._published_at=now
        record['last_snapshot_published_at']=self.clock() if publish else record.get('last_snapshot_published_at')
        return publish

    def serve(self):
        stop=threading.Event()
        signal.signal(signal.SIGTERM,lambda signum,frame:stop.set())
        signal.signal(signal.SIGINT,lambda signum,frame:stop.set())
        with _lock(self.directory/'owner.lock'):
            record=dict(schema_version=1,state='running',generation=uuid4().hex,process=_identity(os.getpid()),started_at=self.clock(),
                        capabilities=['tab-formatting-v1','tab-routing-v1','tab-observer-events-v1'])
            _save(self.directory/'owner.json',record)
            from .tab_observer import TabObserver
            settings=self._settings()
            observer=TabObserver(self.root,settings=settings,fallback_probe=self._probe)
            try:
                while not stop.is_set():
                    started=time.monotonic()
                    try:
                        settings=self._settings()
                        cycle_deadline=started+settings['cycle_timeout']
                        counter = _counter_observation(self.clock_provider) if self.clock_provider is not None else None
                        snapshot=observer.tick(deadline=started+settings['cycle_timeout']*.65,materialize=False)
                        def ensure_resources():
                            if 'resources' not in snapshot:
                                snapshot['resources']=observer.materialize_resources(snapshot['observed_at'])
                            return snapshot['resources']
                        snapshot.update(origin='daemon',monitor_generation=record['generation'],
                                        clock_counter=counter, observed_at_time_basis='guest_wall_display_only')
                        self.publish_observation(snapshot,record,resources_loader=ensure_resources,
                            resources_serializer=lambda:observer.serialize_resources(snapshot['observed_at']),settings=settings)
                        observed=dict(snapshot=snapshot)
                        from .tab_format_monitor import refresh_formatting
                        record['last_formatting']=refresh_formatting(self.root,observed.get('snapshot') or {},
                            tabs=observer.owner,deadline=cycle_deadline,resources_loader=ensure_resources)
                        self._policy_tick(record)
                        routed=self._routing_tick(observed.get('snapshot') or {},cycle_deadline,resources_loader=ensure_resources)
                        record['last_routing']=dict(status=routed.get('status','completed'),outcomes=len(routed.get('outcomes',[])),pending=len(routed.get('pending',[])))
                        record.pop('last_error',None)
                    except (InventoryError,OSError,ValueError) as error:
                        record['last_error']=getattr(error,'code','observation_unavailable')
                    record['last_cycle_at']=self.clock()
                    _save(self.directory/'owner.json',record)
                    delay=settings['interval']-(time.monotonic()-started)
                    if math.isfinite(self._published_at):
                        delay=min(delay,self._published_at+_publication_interval(settings)-self.monotonic())
                    stop.wait(max(.05,delay))
            finally:
                observer.close()
                record.update(state='stopped',stopped_at=self.clock())
                _save(self.directory/'owner.json',record)


class _ProbeDeadline(BaseException):
    pass


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--serve',type=Path)
    mode.add_argument('--probe',type=Path)
    parser.add_argument('--workspace')
    parser.add_argument('--budget',type=float,default=1.5)
    args=parser.parse_args(argv)
    if args.serve:
        TabMonitor(args.serve).serve();return 0
    def expire(signum,frame):raise _ProbeDeadline()
    signal.signal(signal.SIGALRM,expire)
    signal.setitimer(signal.ITIMER_REAL,max(.05,min(5,args.budget)))
    try:
        from .controller_tabs import controller_tabs_from_root,ControllerTabs
        owner=controller_tabs_from_root(args.probe)
        if args.workspace is None:
            result=dict(status='completed',workspaces=sorted(owner.workspaces)[:65],
                        discovery=getattr(owner,'discovery_diagnostics',[])[:32])
        elif args.workspace not in owner.workspaces:
            result=dict(status='unavailable',reason='workspace_disappeared')
        else:
            scoped=ControllerTabs(args.probe,workspaces={args.workspace:owner.workspaces[args.workspace]},host=owner.host,environment=owner.environment)
            result=dict(status='completed',result=scoped.execute('tabs.list',{}))
        raw=json.dumps(result)
        if len(raw.encode())>MAX_STATE:return 2
        print(raw);return 0
    except _ProbeDeadline:
        print(json.dumps(dict(status='unavailable',reason='probe_deadline')));return 0
    except (InventoryError,OSError,ValueError):
        print(json.dumps(dict(status='unavailable',reason='probe_unavailable')));return 0
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)


if __name__=='__main__':
    raise SystemExit(main())
