"""Best-effort desktop activity checks. Unknown activity is treated as active."""
from __future__ import annotations
import ctypes
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Activity:
    idle_seconds: float | None
    foreground_pid: int | None
    supported: bool
    source: str
    def as_dict(self): return asdict(self)

def combine_idle_measurements(*readings):
    """Treat the desktop as idle only when every independent source agrees."""
    if not readings or any(value is None for value in readings): return None, False
    values=[max(0.0,float(value)) for value in readings]
    return min(values), True

class UserActivityProvider:
    def __init__(self): self._cached=None; self._cached_at=0.0
    def snapshot(self):
        if self._cached is not None and time.monotonic()-self._cached_at < 1.0: return self._cached
        try: value=self._windows() if os.name=='nt' else self._mac() if __import__('sys').platform=='darwin' else self._linux()
        except Exception: value=Activity(None,None,False,'unavailable')
        self._cached=value; self._cached_at=time.monotonic(); return value
    def _mac(self):
        idle_hid=None; idle_quartz=None; front=None
        try:
            r=subprocess.run(['ioreg','-c','IOHIDSystem','-d','4'],capture_output=True,text=True,timeout=1,check=True)
            m=re.search(r'"HIDIdleTime"\s*=\s*(\d+)',r.stdout)
            if m: idle_hid=int(m.group(1))/1_000_000_000
        except Exception: pass
        try:
            coregraphics=ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
            seconds_since=coregraphics.CGEventSourceSecondsSinceLastEventType
            seconds_since.argtypes=[ctypes.c_int32,ctypes.c_uint32]
            seconds_since.restype=ctypes.c_double
            # Combined session state + any input event (keyboard, mouse, or tablet).
            idle_quartz=float(seconds_since(0,0xFFFFFFFF))
            if idle_quartz<0: idle_quartz=None
        except Exception: pass
        try:
            script='tell application "System Events" to get unix id of first application process whose frontmost is true'
            r=subprocess.run(['osascript','-e',script],capture_output=True,text=True,timeout=1,check=True)
            front=int(r.stdout.strip())
        except Exception: pass
        idle,supported=combine_idle_measurements(idle_hid,idle_quartz)
        source='macOS Quartz + IOHIDSystem + System Events' if supported and front is not None else 'macOS activity or foreground app could not be verified'
        return Activity(idle,front,supported and front is not None,source)
    def _linux(self):
        idle=None; front=None; source='Linux desktop utilities'
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            try:
                r=subprocess.run(['xprintidle'],capture_output=True,text=True,timeout=.5,check=True); idle=int(r.stdout.strip())/1000
            except Exception: pass
            try:
                wid=subprocess.run(['xdotool','getwindowfocus'],capture_output=True,text=True,timeout=.5,check=True).stdout.strip()
                front=int(subprocess.run(['xdotool','getwindowpid',wid],capture_output=True,text=True,timeout=.5,check=True).stdout.strip())
            except Exception: pass
        supported=idle is not None and front is not None
        return Activity(idle,front,supported,source if supported else 'unsupported Linux desktop/session or foreground app unknown')
    def _windows(self):
        class LASTINPUTINFO(ctypes.Structure): _fields_=[('cbSize',ctypes.c_uint),('dwTime',ctypes.c_uint)]
        info=LASTINPUTINFO(); info.cbSize=ctypes.sizeof(info)
        user32=ctypes.windll.user32
        if not user32.GetLastInputInfo(ctypes.byref(info)): return Activity(None,None,False,'Windows input API unavailable')
        elapsed=((ctypes.windll.kernel32.GetTickCount64() & 0xFFFFFFFF)-info.dwTime & 0xFFFFFFFF)/1000
        hwnd=user32.GetForegroundWindow(); pid=ctypes.c_ulong(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        return Activity(max(0,elapsed),pid.value or None,bool(pid.value),'Windows input or foreground app unavailable')
