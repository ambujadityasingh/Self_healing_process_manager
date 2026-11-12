import sys
from process_manager.manager import ProcessManager
from process_manager.dashboard import create_app

def test_dashboard_api(tmp_path):
    m=ProcessManager(db_path=tmp_path/'db.sqlite',enforce=False)
    pid=m.launch([sys.executable,'-c','import time; time.sleep(4)'],'test')
    response=create_app(m).test_client().get('/api/state')
    assert response.status_code==200 and response.json['processes'][0]['pid']==pid
    assert 'activity' in response.json
    m.targets[pid]['proc'].terminate();m.targets[pid]['proc'].wait(timeout=3)
