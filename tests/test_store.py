from process_manager.store import Store

def test_event_pipeline_persists(tmp_path):
    s=Store(tmp_path/'test.db'); s.add_sample(1,'demo',3,4,'running'); i=s.incident(1,'cpu','warning','high'); s.decision(1,i,'throttle','warning'); s.action(1,i,'throttle','succeeded','nice')
    assert len(s.rows('samples'))==len(s.rows('incidents'))==len(s.rows('decisions'))==len(s.rows('actions'))==1
