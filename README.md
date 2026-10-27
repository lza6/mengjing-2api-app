# mengjing-2api-app — AI梦境画画师 APK 协议逆向 + OpenAI 兼容 2API 网关

逆向 Android 应用 **AI梦境画画师**（`com.fnm.huahuashi` v2.0.1）的 AI 文生图协议，
提取出完整的后端调用链，实现 OpenAI 兼容的本地网关（免费号池 + 自动扩容 + 余额探测）。

> ⚠️ 仅供安全研究与协议学习。所有请求由自己的账号发起，请勿滥用第三方服务。

## 逆向结论（全貌）

```
App (com.fnm.huahuashi)
   │  Apache HttpClient multipart/form-data
   ▼
huahuashi.durl.info  (作者中转服务器, Struts action 路由, Java/Tomcat)
   │  服务端会话 = JSESSIONID cookie  ← 关键! 无 cookie 一律 st:-1
   ▼
阿里云 DashScope  通义千问 qwen_image3  (文生图, 1328x1328, ~50s/张)
```

### 会话机制（静态分析最难发现的一点）

服务端用 `JSESSIONID` cookie 维持登录态。App 的 `DefaultHttpClient` 自动保持
cookie，所以静态反编译时看不到任何 token 传递——所有端点在无 cookie 时都返回
`{"st":"-1"}`，极易误判为"接口已关闭"或"有风控"。

### 完整调用链（全部实测打通）

| # | 端点 (POST, multipart) | 参数 | 返回 |
|---|---|---|---|
| 1 | `/yh!tempUser.action` | qudao, vcode, androidid, imei, mac, oaid, jixing | `{st:1, id, mima}` **无验证注册** |
| 2 | `/yh!dlUser.action` | id, mm, qudao, vcode, jixing, oaid | `{st:1}` + `Set-Cookie: JSESSIONID` |
| 3 | `/ctext!isweigui.action` | textinfo | `{st:1, weigui:false}` 内容合规 |
| 4 | `/qwenpic!zhizuo.action` | miaoshu, chicun(1\*1/9\*16/16\*9), fengge | `{st:1, taskid}` |
| 5 | `/qwenpic!jieguo.action` | taskid (轮询 ~1.2s, 最多 60 次) | st:2 处理中 → `{st:1, picurl}` |

`picurl` 是阿里云 OSS 签名 URL（24 小时有效）。

### 免费额度体系（破解版源码还原）

- `FnmUsers.isNeedPay()` 硬编码 `return false`（破解版去掉了付费墙）
- 每账号 5 次免费（本地 `SharedPreferences freecishu` 计数，服务端也有额度）
- 注册无任何验证（androidid/oaid 都是客户端自报）→ **无限注册 = 无限额度**

### 远程开关矩阵 `/ppos123/201/ppinfo_qq.txt`（gb2312）

| 开关 | 值 | 语义 |
|---|---|---|
| mustLogin | 0 | 无需登录 |
| noPay | 1 | 免支付 |
| noCheckProxy | 0 | 不查代理（抓包友好）|
| freeTest | 1 | 免费试玩 |
| pollinations.ai | 1 | 备用上游开关 |

### 其他通道（还原未全走通，协议已提取）

- `POST /dmh!aliDmh.action` — 照片转动漫（fge=anime/3d/handdrawn/artstyle + AliOSS imgurl）
- `POST /bdtoken!bdToken.action` — 返回 RSA(block-type-1) 加密的百度云凭证，
  App 用硬编码公钥 `Cipher.init(DECRYPT_MODE, publicKey)` 反向解出
  `{bd_appid, bd_key, bd_secret}` → 百度 `selfie_anime` 人像动漫化
- `POST /alitoken!aliToken.action` — 阿里凭证（同构）

### 预设风格 `/preText.txt`（远程可变）

`名称===提示词后缀` 格式，如 `绝美壁纸===古装少女，月亮夜晚，祥云…`。
本网关 `/v1/styles` 实时拉取。

## 2API 网关用法

```bash
pip 无需第三方依赖 (纯标准库)
python demo_server.py --port 8790
```

### 端点

| 端点 | 说明 |
|---|---|
| `POST /v1/images/generations` | OpenAI 兼容：`{"prompt": "...", "size": "1024x1024\|768x1344\|1344x768"}` |
| `GET /v1/pool` | 号池状态与余额（`?probe=true` 做真实余额校验，每号消耗 1 次）|
| `GET /v1/styles` | 实时预设风格 |
| `GET /health` | 服务状态 + 号池统计 |
| `GET /` | 中文 demo 网页 |

### 号池机制

- 每账号 5 次免费额度，额度尽自动淘汰并注册新号（重试 3 次）
- 会话 30 分钟自动保鲜（`dlUser` 重登录，不消耗注册）
- 生成失败（额度尽）自动换号重试
- `device_pool.json` 持久化，重启不丢号

```bash
# 生成
curl -X POST http://127.0.0.1:8790/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"一只可爱的白色小猫，动漫风格"}'

# 查看号池余额
curl http://127.0.0.1:8790/v1/pool
curl "http://127.0.0.1:8790/v1/pool?probe=true"   # 真实校验
```

## 实测记录（2026-10-27）

| 测试 | 结果 |
|---|---|
| 真实生成 #1 白猫 1328×1328 | ✅ 47s |
| 真实生成 #2 cyberpunk 城市 | ✅ 52s |
| 真实生成 #3 雪原巨狼 | ✅ 53.6s |
| 额度扣减 5→3 (used=2) | ✅ |
| 空 prompt 错误路径 | ✅ 20/20 → 400 |
| mock 压测 200req×10/60 并发 | 0 错误 |

## 关键反编译源文件

| 文件 | 内容 |
|---|---|
| `d/e/a/o0/a.java` | HttpUtil — multipart 请求 + st:-1 自动重登录 |
| `d/e/a/p0/c.java` | qwenpic 任务客户端（合规→提交→轮询状态机）|
| `d/e/a/p0/f.java` / `m.java` | 文生图 UI + 免费次数门 |
| `d/e/a/o0/c.java` | 远程配置/开关矩阵/风格列表加载 |
| `com/fnm/huahuashi/fnm_sysutil/FnmMyApp.java` | RSA block-type-1 凭证解密 |
| `com/fnm/huahuashi/fnm_work_activity/Fnm_PhotoAiExeActivity_RadiosBase.java` | 百度 selfie_anime 链路 |
| `com/fnm/huahuashi/fnm_entity/FnmUsers.java` | `isNeedPay()=false` 破解点 |

## 环境与坑

- APK：百度加固（baiduprotect）+ `libSignatureKiller.so` 二次打包破解版
- jadx 1.5.6 反编译，assets 的 `.da` 文件是明文 HTML 隐私协议（非密文）
- 服务端 TLS 1.3 正常但部分中间件对非常见客户端断连 —— 用 raw socket/http.client 而非 curl
- 响应是 chunked + JSON 混排，需正则提取 `{...}`

## License

MIT
