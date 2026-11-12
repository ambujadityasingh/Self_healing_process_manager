"""Safe local demo workloads. Never targets other processes."""
import sys,time
mode=sys.argv[1] if len(sys.argv)>1 else 'idle'
if mode=='cpu':
    end=time.time()+90
    while time.time()<end:
        x=0
        for i in range(200000): x+=i*i
elif mode=='memory':
    blocks=[]
    for _ in range(30): blocks.append(bytearray(4*1024*1024)); time.sleep(1)
elif mode=='crash': time.sleep(3); raise SystemExit(2)
else:
    while True: time.sleep(1)
