"""Small OS-specific inspection/control helpers. Unsupported controls fail explicitly."""
import os, signal
import psutil

def proc_inspect(pid):
    """Linux /proc details when present; returns an empty mapping elsewhere."""
    if not sys_linux(): return {}
    result={}
    try:
        for line in open(f'/proc/{pid}/status'):
            if line.startswith(('State:','VmRSS:','VmSize:','Threads:')):
                key,value=line.split(':',1); result[key.lower()]=value.strip()
    except (OSError, ProcessLookupError): pass
    return result

def sys_linux(): return os.name=='posix' and os.path.isdir('/proc/self')

def throttle(proc, suspend=True):
    """Lower scheduling priority and briefly yield via platform suspend/resume."""
    try: proc.nice(min(19,proc.nice()+5))
    except (psutil.AccessDenied,OSError): pass
    if suspend:
        if os.name=='nt' and not hasattr(proc,'suspend'):
            raise OSError('suspend/resume is unavailable')
        proc.suspend()
        try: proc.resume()
        except Exception:
            # Never leave a managed target suspended if resume itself fails.
            raise

def terminate(proc, grace_seconds=3):
    proc.terminate()
    try: proc.wait(timeout=grace_seconds)
    except psutil.TimeoutExpired: proc.kill()
