from dataclasses import dataclass

@dataclass(frozen=True)
class Finding:
    anomaly: str
    severity: str
    value: float | None = None
    detail: str = ""

class Policy:
    ACTIONS = {"warning": ("throttle",), "critical": ("throttle", "restart", "terminate")}
    def __init__(self, config): self.config=config
    def classify(self, sample, memory_history=(), cpu_history=()):
        c=self.config["monitor"]; out=[]
        cpu=sample.get("cpu_percent",0) or 0; mem=sample.get("memory_mb",0) or 0
        sustained=len(cpu_history)>=c.get('cpu_sustain_samples',1) and all(x>=c['cpu_warning'] for x in cpu_history[-c.get('cpu_sustain_samples',1):])
        unused=bool(sample.get('user_idle_seconds') is not None and sample.get('user_idle_seconds',0)>=c.get('unused_user_idle_seconds',60) and sample.get('foreground') is False and sample.get('activity_supported'))
        if cpu>=c['cpu_warning'] and sustained:
            critical=cpu>=c['cpu_critical']
            if unused and critical:
                out.append(Finding('cpu_unused','critical',cpu,'Sustained critical CPU while user is idle and this process is not foreground'))
            else:
                sev='critical' if critical else 'warning'
                reason='CPU above critical threshold' if critical else 'CPU above warning threshold'
                if not unused: reason += '; termination eligibility not established'
                out.append(Finding('cpu',sev,cpu,reason))
        if mem>=c['memory_critical_mb']: out.append(Finding('memory','critical',mem,'Memory above critical threshold'))
        elif mem>=c['memory_warning_mb']: out.append(Finding('memory','warning',mem,'Memory above warning threshold'))
        if len(memory_history)>=3 and mem-memory_history[0]>=c['memory_growth_warning_mb']:
            out.append(Finding('memory_growth','warning',mem-memory_history[0],'Memory is growing'))
        if sample.get('hung'): out.append(Finding('hang','critical',detail='Responsiveness heartbeat timed out'))
        if sample.get('crashed'): out.append(Finding('crash','critical',detail='Managed process exited unexpectedly'))
        return out
    def actions_for(self,severity): return tuple(self.config['policy'].get(severity,self.ACTIONS.get(severity,())))
