from process_manager.user_activity import combine_idle_measurements

def test_recent_input_from_either_source_prevents_idle_classification():
    idle,supported=combine_idle_measurements(68.0,0.4)
    assert supported and idle==0.4

def test_missing_activity_source_fails_closed():
    idle,supported=combine_idle_measurements(68.0,None)
    assert idle is None and not supported

def test_both_idle_sources_must_exceed_threshold():
    idle,supported=combine_idle_measurements(68.0,65.0)
    assert supported and idle==65.0
