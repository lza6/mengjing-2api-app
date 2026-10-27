#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI梦境画画师 (com.fnm.huahuashi) 真实链路 2API 网关 — OpenAI 兼容
协议来源: jadx 反编译 d/e/a/o0/a.java (HttpUtil) + d/e/a/p0/c.java (qwenpic 任务) + FnmMyApp.java

=== 协议全貌 (已实测打通, 真实出图) ===
上游: 阿里 DashScope 通义千问文生图 (qwen_image3), 经 app 作者中转服务器
Host: huahuashi.durl.info (116.62.14.47, Java/Struts 风格 action 路由)
会话: JSESSIONID cookie (关键! DefaultHttpClient 自动保持; 无 cookie 一律 st:-1)

链路:
  1. POST /yh!tempUser.action  (qudao,vcode,androidid,imei,mac,oaid,jixing)
     -> {st:1, id, mima, nicheng}              # 无验证注册临时账号
  2. POST /yh!dlUser.action     (id,mm,qudao,vcode,jixing,oaid)
     -> {st:1} + Set-Cookie: JSESSIONID        # 登录建会话
  3. POST /ctext!isweigui.action (textinfo)    # 内容合规
     -> {st:1, weigui:false}
  4. POST /qwenpic!zhizuo.action (miaoshu,chicun,fengge)  # 需会话 cookie
     -> {st:1, taskid}                          # chicun: 1*1 / 9*16 / 16*9
  5. POST /qwenpic!jieguo.action (taskid) 轮询  # 1s 间隔, 最多 50 次
     -> st:2 process | st:1 + picurl (阿里 OSS 签名 URL, 24h 有效)
  备用通道: /dmh!aliDmh.action (fge=anime/3d/handdrawn/artstyle + imgurl, 照片转动漫)
  凭证通道: /bdtoken!bdToken.action -> RSA 加密的百度云凭证 (需会话)
  远程开关: /ppos123/201/ppinfo_qq.txt (gb2312, 10 个功能开关)

免费号池: 每账号日限次, 耗尽即注册新号 (uuid androidid/oaid)
"""
import http.client, ssl, sys, json, re, time, uuid, threading, argparse, html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ARG = argparse.ArgumentParser()
ARG.add_argument('--port', type=int, default=8788)
ARGS = ARG.parse_args()

CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HOST = 'huahuashi.durl.info'
UA = 'Apache-HttpClient/4.5 (Java/1.8)'
BOUNDARY = '----JavaFormBoundary7MA4'

STATE = {'requests': 0, 'success': 0, 'errors': 0, 'registrations': 0, 'start': time.time()}
LOCK = threading.Lock()
POOL_LOCK = threading.Lock()
POOL = []  # [{id, mm, cookie, ts, used, credits, inflight}]
POOL_FILE = 'device_pool.json'
FREE_PER_ACCOUNT = 5  # app 本地免费次数 (m.java: freecishu cs>=5)

# ---- 并发号池参数 (面向几百并发) ----
TARGET_POOL = 16        # 目标常驻可用号 (16 号 × 5 次 = 80 发弹匣)
MIN_POOL = 8            # 低于此数立即触发补号
MAX_POOL = 40           # 硬上限 (防注册失控)
REG_MIN_INTERVAL = 3.0  # 相邻两次注册最小间隔 (秒) — 避免注册风暴触发风控
REFILL_INTERVAL = 5.0   # 补号线程巡检周期

def _save_pool():
    try:
        json.dump(POOL, open(POOL_FILE, 'w'))
    except Exception:
        pass

def _load_pool():
    global POOL
    try:
        POOL = json.load(open(POOL_FILE))
        for a in POOL:
            a.setdefault('used', 0)
            a.setdefault('credits', FREE_PER_ACCOUNT)
    except Exception:
        POOL = []

def post_form(path, parts, cookie=None):
    """复刻 app 的 Apache MultipartEntity + cookie 会话"""
    body = b''
    for k, v in parts:
        body += f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += f'--{BOUNDARY}--\r\n'.encode()
    conn = http.client.HTTPSConnection(HOST, context=CTX, timeout=90)
    hdr = {'Content-Type': f'multipart/form-data; boundary={BOUNDARY}', 'User-Agent': UA}
    if cookie: hdr['Cookie'] = cookie
    conn.request('POST', path, body=body, headers=hdr)
    r = conn.getresponse()
    setc = r.getheader('Set-Cookie')
    data = r.read().decode('utf-8', errors='replace')
    conn.close()
    jar = cookie or ''
    if setc and not cookie:
        kv = setc.split(';')[0].strip()
        if '=' in kv: jar = kv
    m = re.search(r'\{.*\}', data, re.S)
    return (json.loads(m.group(0)) if m else {'st': '-9', 'raw': data[:200]}), jar

def _register():
    jixing = 'Google sdk_gphone64_x86_64 api33'
    j, _ = post_form('/yh!tempUser.action', [
        ('qudao', 'qq'), ('vcode', '201'), ('androidid', uuid.uuid4().hex[:16]),
        ('imei', ''), ('mac', ''), ('oaid', str(uuid.uuid4())), ('jixing', jixing)])
    if str(j.get('st')) != '1' or not j.get('id'):
        raise RuntimeError(f'tempUser fail: {j}')
    j2, jar = post_form('/yh!dlUser.action', [
        ('id', str(j['id'])), ('mm', j['mima']), ('qudao', 'qq'), ('vcode', '201'),
        ('jixing', jixing), ('oaid', str(uuid.uuid4()))])
    if str(j2.get('st')) != '1':
        raise RuntimeError(f'dlUser fail: {j2}')
    with LOCK:
        STATE['registrations'] += 1
    return {'id': str(j['id']), 'mm': j['mima'], 'cookie': jar, 'ts': time.time(),
            'used': 0, 'credits': FREE_PER_ACCOUNT, 'inflight': 0}

def _relogin(acct):
    """会话过期时用已有账号重新登录 (不消耗注册次数)"""
    j2, jar = post_form('/yh!dlUser.action', [
        ('id', acct['id']), ('mm', acct['mm']), ('qudao', 'qq'), ('vcode', '201'),
        ('jixing', 'Google sdk_gphone64_x86_64 api33'), ('oaid', str(uuid.uuid4()))])
    if str(j2.get('st')) == '1':
        acct['cookie'] = jar
        acct['ts'] = time.time()
        return True
    return False

def _probe_credit(acct):
    """余额探测: 用 1 字符 prompt 提交一次, 从 st 判断该号是否还有免费次数.
    st:1=有额度(拿到taskid, 浪费1次) st:-1=会话失效 st:其他=额度尽/被拒.
    注意: 探测本身消耗 1 次免费额度, 仅在池里没有可用号时才做."""
    try:
        j, _ = post_form('/qwenpic!zhizuo.action',
                         [('miaoshu', 'a'), ('chicun', '1*1'), ('fengge', '')], acct['cookie'])
    except Exception:
        return -1
    st = str(j.get('st'))
    if st == '1':
        acct['used'] = acct.get('used', 0) + 1
        acct['credits'] = max(0, FREE_PER_ACCOUNT - acct['used'])
        return 1  # 有额度
    return 0       # 额度尽/被拒

# ---- 并发取号: 信号量 + 账号 inflight 计数 ----
# 每个号同时只跑 1 个生成任务 (同 cookie 并发任务会互相顶掉会话),
# 池子足够大时 16 号并行 ≈ 上游真实吞吐上限 (~50s/张).
ACCT_SEM = {}  # id -> threading.Semaphore

def _sem(acct):
    s = ACCT_SEM.get(acct['id'])
    if not s:
        s = threading.Semaphore(1)
        ACCT_SEM[acct['id']] = s
    return s

def _try_acquire(acct, wait=False):
    """尝试独占该账号 (非阻塞). wait=True 时阻塞等待."""
    ok = (_sem(acct).acquire() if wait else _sem(acct).acquire(blocking=False))
    if ok:
        acct['inflight'] = acct.get('inflight', 0) + 1
    return ok

def _release(acct):
    try:
        acct['inflight'] = max(0, acct.get('inflight', 1) - 1)
        _sem(acct).release()
    except ValueError:
        pass

def get_account(wait=False):
    """从池取可用号: 优先取空闲号(非阻塞), 全忙时:
    - wait=True: 轮询等待最早释放的号
    - wait=False: 交给补号线程扩容, 自旋短等
    额度尽 (credits<=0) 的号被淘汰 (补号线程负责清理和注册补充)."""
    deadline = time.time() + (120 if wait else 25)
    while time.time() < deadline:
        with POOL_LOCK:
            now = time.time()
            candidates = [a for a in POOL if a.get('credits', 0) > 0]
            # 会话保鲜: 超过 25 分钟的重登录 (每号只做一次, 由取到号的线程做)
            for a in candidates:
                if now - a.get('ts', 0) > 1500:
                    a['stale'] = True
        for a in candidates:
            if a.get('stale'):
                if _relogin(a):
                    a['ts'] = time.time()
                    a.pop('stale', None)
                else:
                    a['credits'] = 0
                    a.pop('stale', None)
                    continue
            if _try_acquire(a, wait=False):
                return a
        if wait:
            time.sleep(0.3)
        else:
            time.sleep(0.5)
    raise RuntimeError('no available account in pool (timeout)')

def _refill_loop():
    """后台补号线程: 让池子始终保有 TARGET_POOL 个可用号.
    - 低于 MIN_POOL: 立即补 (受注册限速约束)
    - 低于 TARGET_POOL: 缓慢补
    - 清理额度尽的号 (保留记录用于统计, 标记 dead 不再取用)
    - 注册失败指数退避"""
    global POOL
    backoff = REG_MIN_INTERVAL
    while True:
        try:
            time.sleep(REFILL_INTERVAL)
            with POOL_LOCK:
                alive = [a for a in POOL if a.get('credits', 0) > 0]
                need_min = len(alive) < MIN_POOL
                need_soft = len(alive) < TARGET_POOL
                # 清理死号出池 (保留在 dead_accounts 统计里)
                dead = [a for a in POOL if a.get('credits', 0) <= 0 and a.get('inflight', 0) == 0]
                for d in dead:
                    POOL.remove(d)
                if dead:
                    _save_pool()
            if not (need_min or need_soft):
                backoff = REG_MIN_INTERVAL
                continue
            # 注册限速: 单飞 + 最小间隔
            with REG_LOCK:
                with POOL_LOCK:
                    if len(POOL) >= MAX_POOL:
                        continue
                try:
                    acct = _register()
                    backoff = REG_MIN_INTERVAL
                except Exception:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                with POOL_LOCK:
                    POOL.append(acct)
                    _save_pool()
        except Exception as e:
            try:
                sys.stderr.write(f'[refill] {e}\n')
            except Exception:
                pass

REG_LOCK = threading.Lock()

def start_refill():
    threading.Thread(target=_refill_loop, daemon=True).start()

def generate(prompt, chicun='1*1'):
    """完整生成链路: 合规 -> 提交 -> 轮询.
    号池模式: 独占账号(同号单飞) -> 生成 -> 释放; 失败按原因处理额度."""
    last_err = None
    for attempt in range(3):
        acct = get_account(wait=True)
        try:
            j, _ = post_form('/ctext!isweigui.action', [('textinfo', prompt)], acct['cookie'])
            if str(j.get('st')) == '-1':  # 会话过期 -> 重新登录
                if _relogin(acct):
                    j, _ = post_form('/ctext!isweigui.action', [('textinfo', prompt)], acct['cookie'])
                else:
                    acct['credits'] = 0
                    continue
            if str(j.get('st')) == '1' and j.get('weigui'):
                raise RuntimeError('内容违规 (weigui=true)')
            if str(j.get('st')) != '1':
                raise RuntimeError(f'isweigui fail: {j}')
            j2, _ = post_form('/qwenpic!zhizuo.action',
                              [('miaoshu', prompt), ('chicun', chicun), ('fengge', '')], acct['cookie'])
            if str(j2.get('st')) != '1':
                # 该号额度尽/被拒 -> 扣光淘汰, 换号重试
                acct['credits'] = 0
                last_err = f'zhizuo fail: {j2}'
                continue
            # 提交成功 = 消耗 1 次
            with POOL_LOCK:
                acct['used'] = acct.get('used', 0) + 1
                acct['credits'] = max(0, FREE_PER_ACCOUNT - acct['used'])
                acct['ts'] = time.time()
                _save_pool()
            tid = j2['taskid']
            ok = False
            for _ in range(60):
                time.sleep(1.2)
                j3, _ = post_form('/qwenpic!jieguo.action', [('taskid', tid)], acct['cookie'])
                st = str(j3.get('st'))
                if st == '1':
                    return j3['picurl'], tid
                if st != '2':
                    last_err = f'jieguo fail: {j3}'
                    break
            else:
                last_err = 'jieguo timeout'
            break  # 提交成功但结果失败: 不换号 (任务可能还在跑)
        finally:
            _release(acct)
    raise RuntimeError(f'生成失败: {last_err}')

CHICUN_MAP = {'1024x1024': '1*1', '1*1': '1*1', '768x1344': '9*16', '9*16': '9*16',
              '1344x768': '16*9', '16*9': '16*9'}

class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/health':
            with LOCK: s = dict(STATE)
            with POOL_LOCK:
                s['pool_size'] = len(POOL)
                s['pool_alive'] = sum(1 for a in POOL if a.get('credits', 0) > 0)
                s['pool_idle'] = sum(1 for a in POOL if a.get('credits', 0) > 0 and a.get('inflight', 0) == 0)
                s['pool_total_credits'] = sum(max(0, a.get('credits', 0)) for a in POOL)
                s['target_pool'] = TARGET_POOL
                s['accounts'] = [{'id': a['id'], 'credits': max(0, a.get('credits', 0)),
                                  'used': a.get('used', 0),
                                  'busy': a.get('inflight', 0) > 0} for a in POOL[:24]]
            s['uptime_s'] = round(time.time() - s.pop('start'), 1)
            return self._json(200, {'status': 'ok', 'upstream': 'qwen_image3 via huahuashi.durl.info', **s})
        if u.path == '/v1/pool':
            """号池状态 + 余额探测 (probe=true 时对每个可用号做真实余额校验, 消耗 1 次/号)"""
            qs = parse_qs(u.query)
            with POOL_LOCK:
                accounts = [{'id': a['id'], 'credits': max(0, a.get('credits', 0)),
                             'used': a.get('used', 0),
                             'busy': a.get('inflight', 0) > 0,
                             'age_min': round((time.time()-a.get('ts',0))/60, 1)}
                            for a in POOL]
                summary = {'pool_size': len(POOL),
                           'alive': sum(1 for a in POOL if a.get('credits', 0) > 0),
                           'idle': sum(1 for a in POOL if a.get('credits', 0) > 0 and a.get('inflight', 0) == 0),
                           'total_credits': sum(max(0, a.get('credits', 0)) for a in POOL),
                           'target_pool': TARGET_POOL, 'min_pool': MIN_POOL,
                           'free_per_account': FREE_PER_ACCOUNT,
                           'auto_expand': True,
                           'accounts': accounts}
            if qs.get('probe', ['false'])[0] == 'true':
                with POOL_LOCK:
                    targets = [a for a in POOL if a.get('credits', 0) > 0]
                for a in targets:
                    r = _probe_credit(a)
                    a['last_probe'] = r
                with POOL_LOCK: _save_pool()
            with POOL_LOCK:
                return self._json(200, summary)
        if u.path == '/v1/styles':
            """app 预设风格 (preText.txt 远程可变; 此为静态还原 + 在线刷新)"""
            try:
                conn = http.client.HTTPSConnection(HOST, context=CTX, timeout=15)
                conn.request('GET', '/preText.txt', headers={'User-Agent': UA})
                d = conn.getresponse().read().decode('utf-8', errors='replace'); conn.close()
                styles = [l.strip() for l in d.splitlines() if '===' in l]
            except Exception:
                styles = []
            if not styles:
                styles = ['绝美壁纸===绝美壁纸，古装少女，月亮夜晚，祥云，古典纹样，月光柔美，花瓣飘落',
                          '长发少女===手绘头像，厚涂，长发少女，美少女，精致面容，二次元',
                          '人物立绘===凤凰，高清，3d，人物立绘，cg感，古风，唯美',
                          '巨狼===巨狼，飘雪，蓝色大片烟雾，毛发细致，高清，3d',
                          '独角兽===独角兽，眼神带光，平静的湖面，超细节，超高清']
            parsed = [{'name': s.split('===')[0], 'prompt_suffix': s.split('===', 1)[1]} for s in styles]
            return self._json(200, {'styles': parsed,
                                    'usage': '把 prompt_suffix 拼接到你的描述后面, 或直接用 name 作为 style 参数'})
        if u.path == '/':
            b = DEMO_HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n)
        with LOCK: STATE['requests'] += 1
        try:
            if u.path == '/v1/images/generations':
                req = json.loads(raw or b'{}')
                prompt = (req.get('prompt') or '').strip()
                if not prompt:
                    with LOCK: STATE['errors'] += 1
                    return self._json(400, {'error': {'message': 'prompt is required',
                                                      'type': 'invalid_request_error'}})
                size = (req.get('size') or '1024x1024')
                chicun = CHICUN_MAP.get(size, '1*1')
                t0 = time.time()
                picurl, tid = generate(prompt, chicun)
                with LOCK: STATE['success'] += 1
                return self._json(200, {
                    'created': int(time.time()),
                    'data': [{'url': picurl, 'b64_json': None}],
                    'task_id': tid, 'elapsed_s': round(time.time() - t0, 1),
                    'upstream': 'qwen_image3 (dashscope)'})
            return self._json(404, {'error': 'not found'})
        except Exception as e:
            with LOCK: STATE['errors'] += 1
            return self._json(502, {'error': {'message': str(e)}})

DEMO_HTML = '''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>AI梦境画画师 · 真实 2API</title>
<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px;background:#0f1220;color:#e7e9f5}
h1{color:#8ab4ff}textarea,select,button{font-size:15px;border-radius:8px;padding:10px;margin:6px 0}
textarea{width:100%;height:80px;background:#1a1f36;color:#fff;border:1px solid #334;box-sizing:border-box}
select{background:#1a1f36;color:#fff;border:1px solid #334}
button{background:#3b6ef5;color:#fff;border:0;padding:10px 26px;cursor:pointer}
pre{background:#12162b;padding:14px;border-radius:10px;overflow:auto;white-space:pre-wrap}
img{max-width:100%;border-radius:10px;margin-top:10px}.m{color:#8ab4ff}</style></head><body>
<h1>🎨 AI梦境画画师 — 真实文生图 2API</h1>
<p class="m">上游: 通义千问 qwen_image3 (经 huahuashi.durl.info) · 免费号池 · 已实测出图</p>
<label>描述</label><textarea id="p">一只可爱的白色小猫，动漫风格</textarea><br>
<label>尺寸</label><select id="sz"><option>1024x1024</option><option>768x1344</option><option>1344x768</option></select>
<button onclick="go()">生成 (POST /v1/images/generations)</button>
<pre id="out">等待请求…</pre><div id="pic"></div>
<script>
async function go(){
 const out=document.getElementById('out'), pic=document.getElementById('pic');
 pic.innerHTML='<p>生成中… (约 30 秒)</p>'; out.textContent='';
 const r=await fetch('/v1/images/generations',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({prompt:document.getElementById('p').value, size:document.getElementById('sz').value})});
 const j=await r.json(); out.textContent='HTTP '+r.status+'\\n'+JSON.stringify(j,null,2);
 if(j.data&&j.data[0]&&j.data[0].url) pic.innerHTML='<img src="'+j.data[0].url+'">';
}
</script></body></html>'''

if __name__ == '__main__':
    _load_pool()
    for a in POOL:
        a.setdefault('inflight', 0)
    start_refill()
    print(f'AI梦境画画师 真实 2API listening on :{ARGS.port} (pool={len(POOL)}, target={TARGET_POOL})')
    ThreadingHTTPServer(('127.0.0.1', ARGS.port), H).serve_forever()
