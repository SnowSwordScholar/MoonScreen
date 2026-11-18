# MoonScreen 协议记录

本文记录 MoonScreen 使用的 Moonlight / Foundation Sunshine 控制面协议，以及为什么
“只调用 `/launch`、不建立 RTSP 视频流”就足以让 Sunshine 创建虚拟屏并关闭物理屏。

> 适用范围：Foundation Sunshine `v2026.705.121137.杂鱼`（`C:\Program Files\Sunshine`）。
> 上游 Sunshine 的接口大体相同，但“VDD 接管物理屏”和 `VddCapabilityVersion`
> 是 Foundation 的增强，且不同 Foundation 版本是否返回该字段并不一致，不能假定上游原版具备。

## 1. 端口与角色

| 端口 | 协议 | 用途 |
|---|---|---|
| 47989 | HTTP | 配对 `/pair`；未配对预检 `/serverinfo` |
| 47984 | HTTPS（mTLS） | 配对后的 `/serverinfo`、`/applist`、`/launch`、`/cancel` |
| 47990 | HTTPS | WebUI：PIN 页面、可选的 `/api/runtime/sessions` |
| 48010 | RTSP | Moonlight 视频/音频/控制数据面；本集成不使用 |

## 2. 客户端身份与配对

### 2.1 证书

- 客户端生成 2048-bit RSA 自签名证书（CN=`MoonScreen`，20 年有效期，SHA-256）。
- 私钥与证书保存在 HA config entry；配对成功后，Sunshine 会把它加入
  `sunshine_state.json` 的 `named_devices`。
- 服务端证书在配对第 1 阶段以 `plaincert` 返回，之后作为 HTTPS 的唯一信任锚。

### 2.2 四阶段（HTTP）

参数中的 `uniqueid` 是客户端 UUID；`clientname` / `devicename` 都是 `MoonScreen`。
所有 hex 均为小写、无分隔符。

**阶段 1：getservercert**

```text
GET http://<host>:47989/pair
  ?uniqueid=<uuid>
  &phrase=getservercert
  &salt=<16 字节随机数的 hex>
  &clientcert=<客户端 PEM 字节的 hex>
  &clientname=MoonScreen
  &devicename=MoonScreen
  &updateState=1
```

服务端会挂起这个请求，直到有人在 Sunshine WebUI 的 PIN 页面输入 4 位 PIN。
返回：

```xml
<root status_code="200">
  <paired>1</paired>
  <pairname>MoonScreen</pairname>
  <plaincert>2d2d2d2d2d424547494e...</plaincert>
</root>
```

`plaincert` 是 **PEM 字节的 hex**，不是 base64。

**阶段 2：clientchallenge**

```text
key = SHA-256(salt || pin)[:16]
clientchallenge = AES-128-ECB(key, random16)   # 无 padding
GET /pair?uniqueid=...&clientchallenge=<hex>
```

返回 `challengeresponse` = `AES-ECB(hash32 || serverChallenge16)`。
`hash32 = SHA-256(clientChallenge || serverCertSignature || serverSecret)`，
其中 `serverCertSignature` 是服务端 X.509 证书的原始 `signature` 字节。

**阶段 3：serverchallengeresp**

客户端生成 `clientSecret`（16 字节）：

```text
clientHash = SHA-256(serverChallenge || clientCertSignature || clientSecret)
serverchallengeresp = AES-128-ECB(key, clientHash)   # 无 padding
GET /pair?uniqueid=...&serverchallengeresp=<hex>
```

返回 `pairingsecret` = `serverSecret16 || RSA-SHA256(serverSecret)`（用服务端私钥签名）。

客户端校验：

1. 用服务端证书公钥验证 `pairingsecret` 的 RSA 签名；
2. `SHA-256(clientChallenge || serverCertSignature || serverSecret)` 必须等于阶段 2 的
   `hash32`（PIN 错误会在这里失败）。

**阶段 4：clientpairingsecret**

```text
clientpairingsecret = clientSecret16 || RSA-SHA256(clientSecret)
GET /pair?uniqueid=...&clientpairingsecret=<hex>
```

服务端验证 `SHA-256(serverChallenge || clientCertSignature || clientSecret)` 与
阶段 3 的 `clientHash` 一致，并用客户端证书验证签名；成功返回 `<paired>1</paired>`。

**阶段 5：HTTPS 确认**

```text
GET https://<host>:47984/pair?uniqueid=...&phrase=pairchallenge
```

使用客户端证书 + 固定的服务端证书做 mTLS；返回 `paired=1` 即完成。
Sunshine 的 HTTPS 监听器会对每个请求做客户端证书校验，未配对证书会 401。

### 2.3 关键细节

- AES-128-ECB **没有 PKCS#7 padding**；所有明文都是 16 的倍数。
- 哈希统一 SHA-256；RSA 统一 PKCS#1 v1.5 + SHA-256。
- PIN 只有 4 位数字；服务端有配对限流，错误次数过多会 429。
- 配对阶段走 HTTP，这是 Moonlight 的既有设计；请只在可信局域网内配对。

参考实现：

- `src/nvhttp/pairing.cpp`：`getservercert_checked`、`clientchallenge`、
  `serverchallengeresp`、`clientpairingsecret`。
- `src/crypto.cpp`：`gen_aes_key`、`hash`、`signature`、`sign256`、`verify256`。
- Moonlight-Qt `app/backend/nvpairingmanager.cpp`（客户端侧完全对应的实现）。

## 3. 控制面端点

### 3.1 `/serverinfo`

```text
GET https://<host>:47984/serverinfo?uniqueid=<uuid>
```

返回字段（本集成使用）：

| 字段 | 含义 |
|---|---|
| `uniqueid` | 主机唯一 ID；用于 HA config entry 的 unique_id |
| `hostname` | 主机名；用作设备名 |
| `appversion` / `SunshineVersion` | 版本 |
| `currentgame` | 当前应用 ID；`0` 表示没有应用 |
| `state` | `SUNSHINE_SERVER_BUSY` / `SUNSHINE_SERVER_FREE` |
| `PairStatus` | 是否已配对 |
| `VddCapabilityVersion` | 部分 Foundation 版本才返回；缺失表示“未知”，不等于不支持；显式为 0 才提示可能不支持 |
| `FsDisplayModes` | 主机报告的显示模式列表（可选） |

### 3.2 `/applist`

```xml
<root status_code="200">
  <App>
    <AppTitle>Desktop</AppTitle>
    <ID>25818427</ID>
  </App>
  ...
</root>
```

集成按 `desktop_app_name` 做大小写不敏感匹配，不硬编码 ID。
注意：这个版本的 ID 是哈希值（本机 `Desktop=25818427`、`Steam Big Picture=1104442234`、
`Xbox Game=1087677720`），不能假设是 1/2/3。

### 3.3 `/launch`

```text
GET https://<host>:47984/launch
  ?appid=<Desktop ID>
  &rikey=<32 hex 随机>
  &rikeyid=<随机 uint32>
  &localAudioPlayMode=0
  &mode=<width>x<height>x<fps>
  &uniqueid=<uuid>
  &clientname=MoonScreen
  &corever=1
  &useVdd=1
  &hdrMode=0
  &sops=0
  &gcmap=0
  &surroundAudioInfo=196610
  &continuousAudio=0
  &customScreenMode=-1
```

- `rikey` / `rikeyid` / `localAudioPlayMode` / `appid` 是服务端必填参数；
  `rikey` 仅用于不会建立的 RTSP 加密。
- `mode` 决定 VDD 的分辨率与刷新率。
- `useVdd=1` 明确要求虚拟屏；是否真正选用 VDD 还受主机显示配置影响。
- 成功返回 `<gamesession>1</gamesession>` 和 `sessionUrl0`。
- 400 `An app is already running on this host`：已有应用（包括 Desktop）在跑。
- 503 会带 `status_message`、`sunshine_error_code`、`sunshine_error_hint`，
  例如 `VDD_DRIVER_MISSING`、`VDD_DRIVER_UNAVAILABLE`、`DISPLAY_NOT_CONNECTED`。

### 3.4 `/cancel`

```text
GET https://<host>:47984/cancel
```

要求客户端证书；服务端调用 `stream::session::request_global_cancel()`，随后终止当前应用
并 `display_device::session_t::get().restore_state()`。返回 `<cancel>1</cancel>`。
清理是异步的，集成会轮询 `/serverinfo` 等 `currentgame` 归零。

**注意**：这是全局取消；如果此时有真实 Moonlight 串流，会一并结束。

### 3.5 可选：WebUI 会话列表

```text
GET https://<host>:47990/api/runtime/sessions
Authorization: Basic <base64(username:password)>
```

返回 JSON：`success`、`total_sessions`、`sessions[]`（`client_name`、`state`、
`app_name`、`width`、`height`、`fps` 等）。仅用于实体的诊断属性与可选的
“保护正在串流的会话”；不填凭据时集成完全跳过。

## 4. 为什么不用 RTSP

`src/nvhttp.cpp` 的 `launch()`：

1. 校验 `rikey`、`appid` 等参数；
2. 若没有活动 session，调用
   `stream_start::prepare_display_and_probe_encoders(...)`；
3. 该函数调用 `display_device::session_t::get().configure_display(...)`，
   Foundation 在这里创建/复用 Zako VDD、切换显示拓扑（物理屏 `INACTIVE`）；
4. 然后 `proc::proc.execute(appid, launch_session)` 启动 Desktop；
5. 注册 RTSP launch ticket，返回 `gamesession=1`；
6. 成功后 `need_to_restore_display_state = false`。

`src/rtsp.cpp` 中 launch ticket 只在 `config::stream.ping_timeout`（默认约 10 秒）后
`prune()`，**只清票据，不停止应用、不恢复显示**。因此：

- `/launch` 已足够触发 VDD 与熄屏；
- 不连 RTSP 时，Desktop（无 `cmd`，`auto-detach=true`）保持“运行”状态；
- `/cancel` 才会终止应用并恢复显示。

日志实证（`sunshine.log`）：

```text
02:53:50 Launch request from IP: ...
02:53:50 VDD live mode list updated via SETMODES: 32 modes; requested 2202x1179@120Hz
02:53:50 创建虚拟显示器...
02:53:51 成功配置VDD设备...
02:53:55 Executing [Desktop]
...
22:49:51 Cancel request from IP: ...
22:49:51 非常驻模式，销毁VDD
22:49:52 销毁虚拟显示器完成 (IOCTL)
22:49:57 正在恢复显示设备设置 (原因: 串流结束)
22:49:57 显示设备配置已恢复
```

以及会话期间：

```text
DEVICE ID: {32118662-...}  FRIENDLY NAME: ASLHDMI      DEVICE STATE: INACTIVE
DEVICE ID: {3574df70-...}  FRIENDLY NAME: \\.\DISPLAY1 DEVICE STATE: INACTIVE
DEVICE ID: {12cdbd4d-...}  FRIENDLY NAME: Zako HDR     DEVICE STATE: PRIMARY
```

## 5. 仍未实机验证的点

- **已实测**：在真实主机 `550W` 上用 `tools/live_check.py` 完成了 PIN 配对，拿到了
  `/serverinfo` 与 `/applist`（Desktop ID `25818427`），并确认 HTTPS mTLS 可用。
- **未实测**：第一次尝试 `/launch` 时主机上正有真实 Moonlight 串流（小米平板），
  Sunshine 返回 400 “An app is already running on this host”；脚本没有强行 `/cancel`，
  因此没有改动主机状态，也没有验证“无 RTSP 时 VDD 持续存在”。

源码与日志都指向“无 RTSP 也能保持 VDD”，但还需要在没有真实串流时跑一次
“launch → 等 60 秒 → 查状态 → cancel”。这是 `tools/live_check.py` 的核心目的。

如果实机发现票据过期会清理 VDD/应用，按以下顺序兜底：

1. 在 `ping_timeout` 之前调用 `/resume` 续期（可能重复做显示配置，代价较高）；
2. 实现最小 RTSP 控制面握手（OPTIONS / DESCRIBE / SETUP / ANNOUNCE / PLAY），
   保持控制连接但不读视频；
3. 改用 WebUI 的 `/api/tray/action`（`vdd_create` / `vdd_destroy`）。它不按客户端
   分辨率创建、且带确认/冷却状态，只作为最后兜底。

## 6. 兼容性

- `VddCapabilityVersion` 只有部分 Foundation 版本返回（本机 `v2026.705.121137.杂鱼` 的
  HTTP `/serverinfo` 就没有这个字段，但 VDD 功能正常）；**缺失只能当未知**，不能据此判断不支持。
  显式返回 0 时，集成会在配对表单里提示“关闭屏幕可能不会生效”。
- 上游 Sunshine 没有 Zako VDD 时，`/launch` 仍可启动应用，但“关闭物理屏”不会发生。
- 本集成不修改 Sunshine 的显示配置；主机侧必须选择“仅虚拟屏/停用物理屏”的组合。
- 协议错误/401 会触发 HA 的重新配对流程；服务端证书变更也会如此。
