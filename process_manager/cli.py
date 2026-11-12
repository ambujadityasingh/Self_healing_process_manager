import argparse, threading
from .manager import ProcessManager
from .dashboard import create_app

def main():
    p=argparse.ArgumentParser(description='Self-Healing Process Manager')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('dashboard',help='monitor a safe CPU demo and serve the dashboard')
    run=sub.add_parser('run',help='launch and manage a command'); run.add_argument('command',nargs=argparse.REMAINDER)
    watch=sub.add_parser('watch',help='observe selected PID or, with opt-in, all processes owned by this account'); watch.add_argument('pid',type=int,nargs='?'); watch.add_argument('--all-user-processes',action='store_true',help='discover processes owned by this account (observation only unless --auto-kill is added)'); watch.add_argument('--auto-kill',action='store_true',help='authorize automatic recovery/termination after CPU and idle checks')
    p.add_argument('--config',default='config/policy.yaml'); p.add_argument('--db',default='data/manager.sqlite3'); p.add_argument('--port',type=int,default=5050,help='local dashboard port (default: 5050)'); p.add_argument('--no-enforce',action='store_true')
    a=p.parse_args()
    if a.cmd=='watch' and (bool(a.pid)==bool(a.all_user_processes)): p.error('watch requires exactly one PID or --all-user-processes')
    m=ProcessManager(a.config,a.db,not a.no_enforce,auto_scan_user=(a.cmd=='watch' and a.all_user_processes),auto_kill_user=(a.cmd=='watch' and a.all_user_processes and a.auto_kill))
    if a.cmd=='run':
        if not a.command: p.error('provide command after --')
        pid=m.launch(a.command); print(f'Managing PID {pid}')
    elif a.cmd=='watch':
        if a.all_user_processes:
            if a.auto_kill: print('Scanning this account with guarded auto-kill: sustained critical CPU, verified idle time, and non-foreground status are required.')
            else: print('Scanning this account in observation-only mode; no processes will be changed.')
            m.discover_user_processes()
            if m.discovery_error: print(f'Process discovery is unavailable: {m.discovery_error}. Try watching one PID explicitly instead.')
        else:
            if a.auto_kill: print(f'Auto-kill enabled for PID {a.pid} only; it requires sustained critical CPU, verified user-idle time, and a non-foreground process.')
            m.add_pid(a.pid,allow_actions=a.auto_kill)
    else:
        import sys
        pid=m.launch([sys.executable,'demos/workload.py','cpu'],'safe-cpu-demo')
        print(f'Started bounded CPU demonstration as PID {pid}. It may be recovered or stopped after verified user inactivity.')
    threading.Thread(target=m.run,daemon=True).start()
    print(f'Dashboard: http://127.0.0.1:{a.port} (Ctrl+C to stop)')
    create_app(m).run(host='127.0.0.1',port=a.port,debug=False)
if __name__=='__main__': main()
