import threading, time, json, urllib.request, sys
URL = 'http://127.0.0.1:%s/v1/images/generations' % sys.argv[1]

def bench(n, conc):
    lat = []; cnt = [0]; lock = threading.Lock(); lock2 = threading.Lock()
    def worker():
        while True:
            with lock:
                if cnt[0] >= n: return
                cnt[0] += 1
            t = time.perf_counter()
            ok = False
            try:
                r = urllib.request.urlopen(urllib.request.Request(URL,
                    data=json.dumps({'prompt': 'p'}).encode(),
                    headers={'Content-Type': 'application/json'}), timeout=30)
                r.read(); ok = (r.status == 200)
            except Exception:
                pass
            with lock2:
                lat.append(time.perf_counter() - t)
                if not ok: lat.append(('ERR',))
    ths = [threading.Thread(target=worker) for _ in range(conc)]
    t0 = time.perf_counter(); [t.start() for t in ths]; [t.join() for t in ths]
    el = time.perf_counter() - t0
    good = sorted(x for x in lat if not isinstance(x, tuple))
    errs = len(lat) - len(good)
    p = lambda q: good[min(int(q * len(good)), len(good)-1)] * 1000
    print(f'{n} req / {conc} conc: rps={n/el:.1f}  p50={p(.5):.1f}ms  p99={p(.99):.1f}ms  errs={errs}')

bench(200, 10)
bench(200, 60)
e = 0
for _ in range(20):
    r = urllib.request.urlopen(urllib.request.Request(URL, data=b'{"prompt":""}',
        headers={'Content-Type': 'application/json'}))
    if r.status == 400: e += 1
print(f'error-path: {e}/20 -> 400')
print('health:', urllib.request.urlopen(URL.rsplit('/v1', 1)[0] + '/health').read().decode())
