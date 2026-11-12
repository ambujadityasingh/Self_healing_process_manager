from process_manager.policy import Policy
import yaml

def policy(): return Policy(yaml.safe_load(open('config/policy.yaml')))

def test_cpu_requires_sustained_samples():
    p=policy(); sample={'cpu_percent':99,'memory_mb':5,'user_idle_seconds':120,'foreground':False,'activity_supported':True}
    assert p.classify(sample,cpu_history=[99,99,99,99])==[]
    findings=p.classify(sample,cpu_history=[99]*5)
    assert len(findings)==1 and findings[0].anomaly=='cpu_unused' and findings[0].severity=='critical'

def test_high_cpu_is_not_unused_while_foreground_or_active():
    p=policy(); history=[99]*5
    for sample in ({'cpu_percent':99,'memory_mb':5,'user_idle_seconds':120,'foreground':True,'activity_supported':True},{'cpu_percent':99,'memory_mb':5,'user_idle_seconds':5,'foreground':False,'activity_supported':True},{'cpu_percent':99,'memory_mb':5,'user_idle_seconds':None,'foreground':None,'activity_supported':False}):
        assert p.classify(sample,cpu_history=history)[0].anomaly=='cpu'

def test_memory_growth_and_hang():
    findings=policy().classify({'cpu_percent':0,'memory_mb':150,'hung':True},[10,20,30])
    assert {f.anomaly for f in findings}=={'memory_growth','hang'}

def test_policy_actions_are_configurable():
    p=policy(); assert p.actions_for('critical')==('throttle','restart','terminate')
    p.config['policy']['warning']=['throttle','restart']; assert p.actions_for('warning')==('throttle','restart')
