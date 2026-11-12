import getpass, os, subprocess, threading, time
from collections import defaultdict, deque
from pathlib import Path
import psutil, yaml
from .policy import Policy
from .store import Store
from .os_control import proc_inspect, throttle, terminate
from .user_activity import UserActivityProvider

class ProcessManager:
    def __init__(self,config_path='config/policy.yaml',db_path='data/manager.sqlite3',enforce=True,activity_provider=None,auto_scan_user=False,auto_kill_user=False):
        self.config=yaml.safe_load(Path(config_path).read_text()); self.policy=Policy(self.config); self.store=Store(db_path); self.enforce=enforce
        self.targets={}; self.history=defaultdict(lambda:deque(maxlen=max(3,self.config['monitor']['history_window'])))
        self.cpu_history=defaultdict(lambda:deque(maxlen=max(3,self.config['monitor'].get('cpu_sustain_samples',5))))
        self.last_action=defaultdict(float); self.restarts=defaultdict(int); self.heartbeats={}; self.pending={}; self.stop_event=threading.Event()
        self.activity_provider=activity_provider or UserActivityProvider(); self.last_action_id=None; self.replacements={}; self.auto_scan_user=auto_scan_user; self.discovery_error=None; self.auto_kill_user=auto_kill_user
    def add_pid(self,pid,managed=False,command=None,name=None,allow_actions=False):
        proc=psutil.Process(int(pid)); self.targets[proc.pid]={'name':name or proc.name(),'managed':managed,'command':command,'proc':proc,'allow_actions':allow_actions}
        try: proc.cpu_percent(None)
        except psutil.Error: pass
        return proc.pid
    def discover_user_processes(self):
        """Enroll current-account processes for observation; caller explicitly enables auto-scan."""
        ancestors={os.getpid()}; current=os.getpid()
        try:
            while current>1:
                parent_pid=psutil.Process(current).ppid()
                if not parent_pid or parent_pid in ancestors: break
                ancestors.add(parent_pid); current=parent_pid
        except psutil.Error: pass
        added=[]
        try: processes=list(psutil.process_iter(['pid','name','username'])); self.discovery_error=None
        except (psutil.Error,PermissionError) as exc: self.discovery_error=str(exc); return added
        for proc in processes:
            pid=proc.pid
            if pid in ancestors or pid in self.targets: continue
            try:
                username=(getattr(proc,'info',{}).get('username') or '').lower()
                if username:
                    if username != getpass.getuser().lower(): continue
                elif hasattr(os,'getuid'):
                    if proc.uids().real != os.getuid(): continue
                else: continue
                self.add_pid(pid,allow_actions=self.auto_kill_user); added.append(pid)
            except (psutil.Error,PermissionError): continue
        return added
    def _spawn(self,command):
        limits=self.config.get('resource_limits',{}); preexec_fn=None
        if os.name=='posix' and any(limits.get(k) for k in ('cpu_seconds','memory_mb')):
            def apply_limits():
                import resource
                if limits.get('cpu_seconds'):
                    value=int(limits['cpu_seconds']); resource.setrlimit(resource.RLIMIT_CPU,(value,value))
                if limits.get('memory_mb'):
                    value=int(limits['memory_mb'])*1024*1024; resource.setrlimit(resource.RLIMIT_AS,(value,value))
            preexec_fn=apply_limits
        return subprocess.Popen(command,start_new_session=(os.name!='nt'),preexec_fn=preexec_fn)
    def launch(self,command,name=None):
        if isinstance(command,str): raise ValueError('Pass command as an argument list; shell launch is disabled')
        child=self._spawn(command); self.add_pid(child.pid,True,list(command),name,True); return child.pid
    def register_heartbeat(self,pid,timeout_seconds=None):
        self.heartbeats[pid]={'at':time.time(),'timeout':timeout_seconds or self.config['monitor']['hang_seconds']}
    def heartbeat(self,pid):
        if pid not in self.heartbeats: raise KeyError(f'No heartbeat registered for PID {pid}')
        self.heartbeats[pid]['at']=time.time()
    def sample(self,pid,activity=None):
        target=self.targets[pid]; proc=target['proc']; activity=activity or self.activity_provider.snapshot()
        try:
            cpu=proc.cpu_percent(None); mem=proc.memory_info().rss/1048576; status=proc.status()
            hb=self.heartbeats.get(pid); hung=bool(hb and time.time()-hb['at']>hb['timeout'])
            foreground=(activity.foreground_pid==pid) if activity.foreground_pid is not None else None
            crashed=bool(target['managed'] and (status==psutil.STATUS_ZOMBIE or not proc.is_running()))
            result={'pid':pid,'name':target['name'],'cpu_percent':cpu,'memory_mb':mem,'status':status,'hung':hung,'crashed':crashed,'os_details':proc_inspect(pid),
                    'user_idle_seconds':activity.idle_seconds,'foreground':foreground,'activity_supported':bool(activity.supported and activity.foreground_pid is not None),'activity_source':activity.source}
        except (psutil.NoSuchProcess,psutil.ZombieProcess):
            result={'pid':pid,'name':target['name'],'cpu_percent':0,'memory_mb':0,'status':'exited','hung':False,'crashed':bool(target['managed']),'os_details':{},'user_idle_seconds':activity.idle_seconds,'foreground':None,'activity_supported':False,'activity_source':activity.source}
        self.store.add_sample(pid,result['name'],result['cpu_percent'],result['memory_mb'],result['status'],result['user_idle_seconds'],result['foreground'],result['activity_supported']); return result
    def _act(self,pid,iid,action):
        t=self.targets[pid]; proc=t['proc']; ok=False; detail=''; self.replacements.pop(pid,None)
        try:
            if action=='throttle':
                if not self.enforce: detail='enforcement disabled'
                elif not (t['managed'] or t['allow_actions']): detail='external process is observation-only; opt in with --auto-kill'
                elif not proc.is_running() or proc.status()==psutil.STATUS_ZOMBIE: detail='process has already exited'
                else:
                    throttle(proc,suspend=(os.name!='nt')); detail='priority lowered; brief suspend/resume applied where supported'; ok=True
            elif action=='restart':
                if not t['managed'] or not t['command']: detail='restart is available only for a process launched by this manager'
                elif self.restarts[pid]>=self.config['policy'].get('restart_limit',2): detail='restart limit reached'
                elif not self.enforce: detail='enforcement disabled'
                else:
                    try: terminate(proc,grace_seconds=2)
                    except psutil.NoSuchProcess: pass
                    self.restarts[pid]+=1; new=self._spawn(t['command']); newpid=new.pid
                    self.targets[newpid]={**t,'proc':psutil.Process(newpid)}; self.history[newpid]=self.history.pop(pid,deque(maxlen=5)); self.cpu_history[newpid]=self.cpu_history.pop(pid,deque(maxlen=5)); self.targets.pop(pid,None)
                    self.replacements[pid]=newpid; detail=f'restarted as pid {newpid}'; ok=True
            elif action=='terminate':
                protected={str(x).lower() for x in self.config['policy'].get('protected_process_names',[])}
                if t['name'].lower() in protected: detail='protected process name; termination blocked'
                elif not (t['managed'] or t['allow_actions']): detail='termination not authorized for this process'
                elif not self.enforce: detail='enforcement disabled'
                else: terminate(proc,grace_seconds=3); detail='process terminated'; ok=True
        except (psutil.Error,OSError,subprocess.SubprocessError) as e: detail=str(e)
        self.last_action_id=self.store.action(pid,iid,action,'succeeded' if ok else 'failed',detail,'pending' if ok and action!='terminate' else ('terminated' if ok else 'failed'))
        if ok and action=='terminate':
            # An intentional stop is final; do not treat it as a crash and restart it next tick.
            self.targets.pop(pid,None); self.history.pop(pid,None); self.cpu_history.pop(pid,None); self.heartbeats.pop(pid,None); self.pending.pop(pid,None)
        return ok
    def _begin_escalation(self,pid,iid,actions,sample,now,anomaly):
        index=0
        while index<len(actions):
            action=actions[index]; self.store.decision(pid,iid,action,'Try the next action only if this action fails to restore CPU below the recovery threshold.')
            if self._act(pid,iid,action):
                if action=='terminate': return
                newpid=self.replacements.get(pid,pid)
                self.pending[newpid]={'incident_id':iid,'actions':actions,'next_index':index+1,'action_id':self.last_action_id,'action':action,'anomaly':anomaly,'verify_at':now+self.config['monitor'].get('recovery_window_seconds',3)}
                return
            index+=1
    def _advance_pending(self,pid,sample,now):
        p=self.pending.get(pid)
        if not p or now<p['verify_at']: return bool(p)
        anomaly=p['anomaly']
        if anomaly=='cpu_unused' and (sample.get('user_idle_seconds') is None or sample.get('foreground') is None or sample.get('foreground') or sample.get('user_idle_seconds',0)<self.config['monitor'].get('unused_user_idle_seconds',60)):
            self.store.action_outcome(p['action_id'],'cancelled','User became active or desktop activity could not be verified; escalation stopped.')
            self.pending.pop(pid,None); return False
        c=self.config['monitor']
        if anomaly in ('cpu','cpu_unused'):
            recovered=not sample.get('crashed') and sample.get('cpu_percent',0)<c.get('cpu_recovery_percent',60)
            metric=f"CPU is {sample.get('cpu_percent',0):.1f}%"
        elif anomaly=='memory':
            recovered=not sample.get('crashed') and sample.get('memory_mb',0)<c['memory_warning_mb']; metric=f"memory is {sample.get('memory_mb',0):.1f} MB"
        elif anomaly=='memory_growth':
            h=list(self.history[pid]); recovered=len(h)>=3 and h[-1]-h[0]<c['memory_growth_warning_mb']; metric='memory growth is below its configured threshold' if recovered else 'memory is still growing'
        elif anomaly=='hang': recovered=not sample.get('hung'); metric='heartbeat recovered' if recovered else 'heartbeat is still overdue'
        else: recovered=not sample.get('crashed'); metric='process is running' if recovered else 'process is still exited'
        if recovered:
            self.store.action_outcome(p['action_id'],'recovered',f"{metric} after {p['action']}.")
            self.pending.pop(pid,None); return True
        self.store.action_outcome(p['action_id'],'failed',f"{metric} after {p['action']}.")
        self.pending.pop(pid,None)
        self._begin_escalation(pid,p['incident_id'],p['actions'][p['next_index']:],sample,now,anomaly)
        return True
    def tick(self):
        events=[]; now=time.time(); activity=self.activity_provider.snapshot()
        if self.auto_scan_user: self.discover_user_processes()
        for pid in list(self.targets):
            if pid not in self.targets: continue
            sample=self.sample(pid,activity); self.history[pid].append(sample['memory_mb']); self.cpu_history[pid].append(sample['cpu_percent'])
            if self._advance_pending(pid,sample,now): continue
            findings=self.policy.classify(sample,list(self.history[pid]),list(self.cpu_history[pid]))
            for f in findings:
                events.append({'pid':pid,'anomaly':f.anomaly,'severity':f.severity,'detail':f.detail})
                if now-self.last_action[pid]<self.config['monitor']['recovery_cooldown_seconds']: continue
                self.last_action[pid]=now; iid=self.store.incident(pid,f.anomaly,f.severity,f.detail)
                # Record observed problems for external processes too, but only
                # permit automatic controls for verified unused high CPU.
                if not self.targets[pid]['managed'] and f.anomaly!='cpu_unused':
                    self.store.decision(pid,iid,'none','Observed only: automatic action requires sustained critical CPU while desktop inactivity and non-foreground status are verified.')
                    break
                actions=self.policy.actions_for(f.severity)
                if f.anomaly=='cpu':
                    eligible=(sample.get('activity_supported') and sample.get('foreground') is False and sample.get('user_idle_seconds',0)>=self.config['monitor'].get('unused_user_idle_seconds',60))
                    actions=('throttle',) if eligible else ()
                if not self.targets[pid]['managed'] and f.anomaly=='cpu_unused': actions=tuple(a for a in actions if a!='restart')
                self._begin_escalation(pid,iid,actions,sample,now,f.anomaly)
                break
        return events
    def run(self):
        while not self.stop_event.is_set(): self.tick(); self.stop_event.wait(self.config['monitor']['interval_seconds'])
    def stop(self): self.stop_event.set()
