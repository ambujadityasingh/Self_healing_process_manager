import sys, time
from process_manager.manager import ProcessManager

def test_managed_process_launch_and_sample(tmp_path):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=False)
    pid=m.launch([sys.executable,'-c','import time; time.sleep(5)'],'test')
    sample=m.sample(pid)
    assert sample['pid']==pid and sample['status'] in ('running','sleeping')
    m.targets[pid]['proc'].terminate(); m.targets[pid]['proc'].wait(timeout=3)

def test_external_process_cannot_be_terminated(tmp_path):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=True)
    pid=m.launch([sys.executable,'-c','import time; time.sleep(5)'])
    m.targets[pid]['managed']=False; m.targets[pid]['allow_actions']=False
    assert not m._act(pid,1,'terminate')
    assert m.targets[pid]['proc'].is_running()
    m.targets[pid]['proc'].terminate();m.targets[pid]['proc'].wait(timeout=3)

def test_failed_throttle_escalates_and_terminates(tmp_path):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=True)
    pid=m.launch([sys.executable,'-c','import time; time.sleep(8)'],'selected-test-process')
    iid=m.store.incident(pid,'cpu_unused','critical','sustained unused CPU')
    assert m._act(pid,iid,'throttle')
    action_id=m.last_action_id
    m.pending[pid]={'incident_id':iid,'actions':('throttle','terminate'),'next_index':1,'action_id':action_id,'action':'throttle','verify_at':time.time()-1,'anomaly':'cpu_unused'}
    sample={'cpu_percent':99,'memory_mb':5,'crashed':False,'user_idle_seconds':120,'foreground':False,'activity_supported':True}
    proc=m.targets[pid]['proc']
    m._advance_pending(pid,sample,time.time())
    assert not proc.is_running()
    assert pid not in m.targets
    actions=m.store.rows('actions')
    assert any(a['action']=='throttle' and a['outcome']=='failed' for a in actions)
    assert any(a['action']=='terminate' and a['outcome']=='terminated' for a in actions)

def test_external_process_requires_explicit_opt_in(tmp_path):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=True)
    pid=m.launch([sys.executable,'-c','import time; time.sleep(5)'],'external')
    m.targets[pid]['managed']=False; m.targets[pid]['allow_actions']=False
    assert not m._act(pid,1,'terminate')
    assert m.targets[pid]['proc'].is_running()
    m.targets[pid]['proc'].terminate();m.targets[pid]['proc'].wait(timeout=3)

def test_opt_in_scanner_discovers_current_user_processes(tmp_path,monkeypatch):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=False,auto_scan_user=True,auto_kill_user=True)
    child=m._spawn([sys.executable,'-c','import time; time.sleep(5)'])
    try:
        import psutil
        monkeypatch.setattr('process_manager.manager.psutil.process_iter',lambda attrs: iter([psutil.Process(child.pid)]))
        assert child.pid in m.discover_user_processes()
        assert m.targets[child.pid]['allow_actions'] is True
    finally:
        child.terminate(); child.wait(timeout=3)


def test_intentional_termination_is_not_restarted_on_next_tick(tmp_path):
    from process_manager.user_activity import Activity
    class ActiveDesktop:
        def snapshot(self): return Activity(0,999999,True,'test')
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=True,activity_provider=ActiveDesktop())
    pid=m.launch([sys.executable,'-c','import time; time.sleep(8)'],'must-stay-stopped')
    proc=m.targets[pid]['proc']
    assert m._act(pid,7,'terminate')
    assert pid not in m.targets
    m.tick()
    assert not proc.is_running()
    assert [row['action'] for row in m.store.rows('actions')]==['terminate']

def test_external_high_cpu_is_logged_without_actions_when_user_active(tmp_path):
    from process_manager.user_activity import Activity
    class ActiveDesktop:
        def snapshot(self): return Activity(0,999999,True,'test')
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=True,activity_provider=ActiveDesktop())
    child=m._spawn([sys.executable,'-c','import time; time.sleep(8)'])
    pid=child.pid
    try:
        m.add_pid(pid,allow_actions=True)
        m.targets[pid]['managed']=False
        m.cpu_history[pid].extend([99,99,99,99])
        m.sample=lambda observed_pid, activity=None: {'pid':observed_pid,'name':'external-test','cpu_percent':99,'memory_mb':5,'status':'running','crashed':False,'foreground':False,'user_idle_seconds':0,'activity_supported':True}
        m.tick()
        assert m.store.rows('incidents')[0]['pid']==pid
        assert 'not foreground' not in m.store.rows('incidents')[0]['detail']
        assert m.store.rows('decisions')[0]['action']=='none'
        assert m.store.rows('actions')==[]
        assert child.poll() is None
    finally:
        child.terminate(); child.wait(timeout=3)
