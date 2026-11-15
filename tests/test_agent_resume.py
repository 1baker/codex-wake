"""Resume keeps exact identity and never repeats an ambiguous launch."""
from pathlib import Path
import tempfile
import unittest
from codex_wake.agent_resume import AgentResume
from codex_wake.managed_inventory import ManagedInventory, Observation
from codex_wake.session_permissions import PermissionStore, Principal

THREAD='01a123a8-5782-7d43-a214-55b293bbd65f'
NOW=1800000000

def observation(root, process=1, state='ready'):
    return Observation('codex','codex:fixture',THREAD,str(root),state,NOW,'native_metadata',
        dict(pid=process,start_ticks=process,boot_id='boot') if process else None,
        [dict(pane_id='%'+str(process))] if process else [],{'inspect':'supported'})

class Runtime:
    def __init__(self, root):
        self.root=root; self.current=observation(root,0,'unavailable'); self.launches=0; self.lost=False
    def identity(self, record, profile):
        return dict(runtime='codex',namespace='codex:fixture',conversation_id=THREAD,root=str(self.root))
    def binding(self, record, profile):return self.current
    def launch(self, record, profile, guard, name):
        guard();self.launches+=1;self.current=observation(self.root,2)
        if self.lost:raise OSError('lost response')

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.inv=ManagedInventory(self.root,now=lambda:NOW)
        self.agent=self.inv.enroll(observation(self.root))['agent'];self.runtime=Runtime(self.root)
        PermissionStore(self.root,now=lambda:NOW).configure({'version':1},Principal('op','operator'),expected_revision=0)
        self.config={'version':1,'profiles':{'saved':{'cwd':str(self.root),'app_server':'unix:///fixture',
            'codex_path':'/bin/true','tmux_session':'work','timeout':1}},'callers':{THREAD:['saved']}}
        self.args=dict(managed_agent_id=self.agent['managed_agent_id'],profile='saved',intent='one',expires_at='2027-01-16T09:00:00+00:00')
    def owner(self):return AgentResume(self.root,self.config,runtime=self.runtime,now=lambda:NOW)
    def test_last_confirmed_record_resumes_same_agent_and_preserves_pending_files(self):
        pending=self.root/'pending-work';pending.write_bytes(b'unknown effect; original allowance 17')
        result=self.owner().resume(self.args,Principal(THREAD))
        self.assertEqual(result['status'],'resumed');self.assertEqual(result['managed_agent_id'],self.agent['managed_agent_id'])
        self.assertEqual(self.inv.inspect(self.agent['managed_agent_id'])['agent']['process']['pid'],2)
        self.assertEqual(pending.read_bytes(),b'unknown effect; original allowance 17')
        self.assertEqual(self.owner().resume(self.args,Principal(THREAD))['status'],'resumed')
        self.assertEqual(self.runtime.launches,1)

    def test_lost_launch_is_reconciled_without_another_launch(self):
        self.runtime.lost=True
        self.assertEqual(self.owner().resume(self.args,Principal(THREAD))['status'],'uncertain')
        self.assertEqual(self.owner().resume(self.args,Principal(THREAD))['status'],'resumed')
        self.assertEqual(self.runtime.launches,1)

    def test_operator_recovery_uses_real_principal_and_common_recovery_permission(self):
        from codex_wake.agent_resume import ResumeError
        with self.assertRaises(ResumeError):self.owner().resume(self.args,Principal('op','operator'))
        self.config['recovery_callers']={'op':[self.agent['managed_agent_id']]}
        store=PermissionStore(self.root)
        store.configure({'version':1,'global':{'actions':{'resume.recover':'allow'}}},Principal('op','operator'),expected_revision=1)
        self.assertEqual(self.owner().resume(self.args,Principal('op','operator'))['status'],'resumed')

    def test_unqualified_existing_attachment_and_suppression_never_launch(self):
        self.runtime.current=Observation('codex','codex:fixture',THREAD,str(self.root),'unavailable',NOW,
            'native_metadata',None,[dict(pane_id='%stale')],{'inspect':'supported'})
        self.assertEqual(self.owner().resume(self.args,Principal(THREAD))['reason'],'resume_existing_attachment_unqualified')
        self.assertEqual(self.runtime.launches,0)
        self.inv.set_enrollment(self.agent['managed_agent_id'],enabled=False)
        from codex_wake.agent_resume import ResumeError
        with self.assertRaises(ResumeError):self.owner().resume(self.args,Principal(THREAD))

class WholeContainerResumeTests(unittest.TestCase):
    def test_missing_owned_explicit_terminal_has_complete_empty_inventory(self):
        from codex_wake.sessions import tmux_inventory
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(tmux_inventory(str(Path(directory)/'owned.sock'), 1), [])

    def test_saved_launcher_recreates_explicit_missing_container_with_same_thread(self):
        from codex_wake.agent_resume import SavedRuntime
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def terminal(args, *command):
                args.effect_guard()
                calls.append(command)
                return '@0\t%0'
            runtime = SavedRuntime(terminal=terminal)
            profile = dict(cwd=directory, app_server='unix:///native.sock', codex_path='/bin/true',
                           tmux_socket=str(Path(directory)/'owned.sock'), tmux_session='owned', timeout=1)
            runtime.launch(dict(root=directory, conversation_id=THREAD), profile, lambda: None, 'restore')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], 'new-session')
            self.assertIn(THREAD, calls[0][-1])
            self.assertIn('owned', calls[0])

    def test_missing_socket_under_symlink_directory_is_not_qualified_absence(self):
        from codex_wake.sessions import tmux_inventory
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'real').mkdir(mode=0o700)
            (root/'alias').symlink_to(root/'real', target_is_directory=True)
            with self.assertRaises(Exception):
                tmux_inventory(str(root/'alias'/'owned.sock'), 1)
