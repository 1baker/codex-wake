"""Session discovery reports cached per-tab traits without probing again."""
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from codex_wake.controller_tabs import ControllerTabs
from codex_wake.tab_organization import digest
from codex_wake.tab_monitor import TabMonitor
from codex_wake.terminal_session_cli import render


class SummaryTests(unittest.TestCase):
    def test_listing_uses_fresh_cached_traits_and_renders_both_summaries(self):
        counter = [1000]
        def clock_provider():
            return dict(utc=None, reason='authenticated_counter_only', counter=dict(
                epoch='3c93a3d4-445d-4403-8a40-77fa9162dee6',
                counter=counter[0], frequency=1000, rate_ppm=0))
        class Transport:
            def snapshot(self, deadline):
                return dict(server='/fixture', session_id='$0', socket_identity='birth', bridge_generation=None,
                            windows=[dict(window_id='@1',panes=[dict(pane_id='%1',pid=42)]),
                                     dict(window_id='@2',panes=[dict(pane_id='%2',pid=43)])])
        with tempfile.TemporaryDirectory() as d, patch.dict(
                os.environ, CODEX_WAKE_STABLE_TIME_CONFIG='/host-clock.json'), patch(
                'codex_wake.native_clock.snapshot', side_effect=clock_provider):
            root=Path(d);transport=Transport()
            tabs=ControllerTabs(root,host='test',environment='fixture',workspaces={
                'enrolled':dict(kind='tmux',label='development',socket_path='/fixture',transport=transport)})
            monitor=TabMonitor(root,clock=lambda:100,clock_provider=clock_provider)
            def probe(workspace, timeout):
                if workspace is None:return dict(status='completed',workspaces=['enrolled'])
                rows=[]
                for window,activity,health,error in zip(transport.snapshot(0)['windows'],['running','idle'],['responsive','unknown'],['absent','present']):
                    trait=lambda value:dict(value=value,status='observed',freshness='fresh',source='fixture')
                    rows.append(dict(target=dict(host='test',environment='fixture',workspace='enrolled',presentation='tmux',generation=digest(transport.snapshot(0))),window=window,
                                     traits=dict(traits=dict(activity=trait(activity),health=trait(health),error=trait(error)))))
                return dict(status='completed',result=dict(resources=rows,unavailable=[]))
            with patch.object(monitor,'_probe',side_effect=probe):monitor.refresh()
            with patch.object(TabMonitor,'_probe',side_effect=AssertionError('listing must not probe')):
                result=tabs.execute('tabs.session.list',{})
            row=result['sessions'][0]
            self.assertEqual(row['health_summary']['counts'],{'responsive':1,'unknown':1})
            self.assertEqual(row['activity_summary']['counts'],{'running':1,'idle':1})
            self.assertEqual(row['error_summary']['counts'],{'absent':1,'present':1})
            output=render(result)
            self.assertIn('responsive=1',output)
            self.assertIn('running=1',output)
            self.assertIn('present=1',output)

            # Same cache becomes unknown after expiry, without a refresh or probe.
            counter[0] = 22000
            with patch.object(TabMonitor,'_probe',side_effect=AssertionError('no refresh')):
                stale=tabs.execute('tabs.session.list',{})['sessions'][0]
            for name in ('health','activity','error'):
                self.assertEqual(stale[name+'_summary']['counts'],{'unknown':2})
                self.assertEqual(stale[name+'_summary']['freshness'],'stale')
            # An enrolled name alone cannot bind a cache row to a replacement container.
            transport.snapshot=lambda deadline:dict(server='/replacement',session_id='$0',socket_identity='new',bridge_generation=None,
                windows=[dict(window_id='@1',panes=[dict(pane_id='%1',pid=42)])])
            counter[0] = 1000
            replacement=tabs.execute('tabs.session.list',{})['sessions'][0]
            self.assertEqual(replacement['health_summary']['counts'],{'unknown':1})

    def test_unobserved_empty_listing_does_not_create_monitor_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            tabs=ControllerTabs(root,host='test',environment='fixture',workspaces={})
            tabs.execute('tabs.session.create',{'name':'saved'})
            row=tabs.execute('tabs.session.list',{})['sessions'][0]
            self.assertEqual(row['health_summary'],dict(counts={},tab_count=0,freshness='empty',stale_tabs=0))
            self.assertFalse((root/'tab-monitor').exists())
