# MoonScreen（月光屏）

在 Home Assistant 里用一个 **电脑屏幕** 开关控制 Foundation Sunshine 的虚拟屏：

- **关闭开关** → Sunshine 启动 `Desktop`，创建客户端分辨率/刷新率的 Zako VDD，物理屏熄灭。
- **打开开关** → Sunshine 退出当前应用，销毁 VDD，恢复物理屏。

集成只使用 Moonlight 的 HTTPS 控制面（`/pair`、`/launch`、`/cancel`、`/serverinfo`、`/applist`），
不建立 RTSP、视频、音频或输入通道，HA 侧几乎没有 CPU/带宽开销。

## 功能

- `switch.电脑屏幕`：开 = 物理屏正常，关 = VDD 接管、物理屏熄灭。
- 状态跟随 Sunshine 的 `currentgame`；真实 Moonlight 连接/退出 Desktop 时也会同步。
- 点击开关后立即刷新，并每秒刷新直到状态确认，不会等下一个轮询周期。
- 虚拟屏分辨率、刷新率、Desktop 应用名、轮询间隔均可配置。
- 可选 WebUI 凭据：读取活动串流列表；开启保护后，检测到真实串流时拒绝开屏。
- 一次 PIN 配对，客户端证书与私钥保存在 HA config entry 中；后续请求使用 mTLS +
  服务端证书固定。

## 工作原理

```text
HA MoonScreen ──HTTP 47989 /pair（仅首次）──▶ Sunshine
              ──HTTPS 47984 mTLS────────────▶ /launch?appid=<Desktop ID>&mode=WxHxFPS&useVdd=1
                                                ├─ 创建 Zako VDD（客户端分辨率）
                                                ├─ 切换显示拓扑，物理屏 INACTIVE
                                                └─ 启动 Desktop（无视频流）
              ──HTTPS 47984 mTLS────────────▶ /cancel
                                                ├─ 终止 Desktop
                                                └─ 销毁 VDD，恢复显示设置
              ──HTTPS 47984 mTLS────────────▶ /serverinfo  → currentgame / state
```

Sunshine 在 `/launch` 阶段就完成 VDD 创建和显示拓扑切换，早于 RTSP 串流。本集成利用这一点，
只发控制请求，不建立 RTSP/ENET 会话。协议细节见 [docs/protocol.md](docs/protocol.md)。

## 环境要求

1. Windows 10 22H2 / Windows 11，已安装 **Foundation Sunshine**（上游原版可以试，但
   “虚拟屏 + 物理屏熄灭”依赖 Foundation 的 Zako VDD 与显示组合功能）。
2. 已安装 **Zako Display Driver**，并在 Sunshine 的显示设置里选择
   “基地虚拟显示器 / 远程时停用物理屏”之类的组合。集成不会修改这部分配置。
3. Sunshine 的 WebUI 已能打开并登录，PIN 页面可用（`https://<主机>:47990/pin`）。
4. `apps.json` 里有名为 `Desktop` 的应用；不同 Foundation 版本的 ID 可能是哈希值，
   集成按名称匹配，不硬编码 ID。
5. Home Assistant **2025.1 或更新版本**；HA 与 Windows 主机在同一局域网，
   `47989/tcp`、`47984/tcp`（以及可选的 `47990/tcp`）可达。
6. 主机防火墙允许上述端口（Sunshine 安装器一般会自动加规则）。

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角 ⋮ → **自定义存储库**。
2. 填 `https://github.com/SnowSwordScholar/MoonScreen`，类别选“集成”，添加。
3. 搜索 **MoonScreen**，下载。
4. **重启 Home Assistant**。
5. **设置 → 设备与服务 → 添加集成 → MoonScreen**。

### 手动安装

从 [Releases](https://github.com/SnowSwordScholar/MoonScreen/releases) 下载
`moonscreen.zip`，解压到 HA 的 `/config`，确认得到
`/config/custom_components/moonscreen/`；或直接把仓库里的
`custom_components/moonscreen` 复制到该目录。重启 HA 后添加集成。

HAOS 可以用 Samba 共享或 “SSH & Web Terminal” 插件。

### 从源码打包

```powershell
python tools/build_zip.py
```

把 `dist/moonscreen.zip` 解压到 `/config`，重启 HA。

## 配置

第一次添加集成时填写：

| 字段 | 默认值 | 说明 |
|---|---|---|
| 主机地址 | — | Windows 主机的局域网 IP 或主机名（不要填 `localhost`，除非 HA 和 Sunshine 在同一台机器） |
| HTTPS / GameStream 端口 | 47984 | Sunshine 的 `/launch`、`/cancel`、`/serverinfo` |
| HTTP 端口 | 47989 | 配对用 `/pair`；也用于预检 `/serverinfo` |
| Sunshine WebUI 端口 | 47990 | PIN 页面和可选的会话列表 API |
| Desktop 应用名称 | `Desktop` | 在 `/applist` 中按名称匹配；大小写不敏感 |
| 虚拟屏宽度 / 高度 | 1920 × 1080 | 关闭屏幕时 VDD 的分辨率 |
| 刷新率（FPS） | 60 | VDD 的刷新率 |
| 状态轮询间隔 | 15 秒 | 5–120 秒；动作后另有 1 秒级快速刷新 |
| WebUI 用户名/密码 | 空 | 可选。填写后可读取活动串流列表，并启用“保护正在串流的会话” |
| 保护正在串流的会话 | 关 | 打开后，如果检测到真实 Moonlight 串流，`打开屏幕` 会被拒绝而不是掐断串流 |

提交后 HA 会生成一个 4 位 PIN。在 Sunshine WebUI 的 **PIN** 页面输入这个 PIN
（设备名会显示为 `MoonScreen`），回到 HA 勾选确认并提交。首次配对成功后，客户端证书
会保存在 HA 的 config entry 里。

**如果 PIN 页面没有看到请求**：等 2–5 秒刷新；配对请求会在 HA 提交后约 1 秒到达主机。
如果仍然没有，检查主机地址/端口是否填反（47989 是 HTTP，47984 是 HTTPS）。

### 修改选项

集成条目 → **配置**：默认分辨率、FPS、Desktop 应用名称、轮询间隔、WebUI 用户名/密码、
是否保护正在串流的会话。主机地址、端口和客户端证书不能在选项里改；换主机请删除条目重新添加。

## 实体与状态

实体：`switch.电脑屏幕`，显示名 **电脑屏幕**。集成图标在
`custom_components/moonscreen/brand/`（256×256 icon、512×256 logo）。

| 状态 | 含义 |
|---|---|
| **开** | 主机上没有应用在运行，物理屏处于正常状态 |
| **关** | Sunshine 有应用在运行（通常是 `Desktop`），VDD 已接管，物理屏熄灭 |
| **不可用** | HA 连不上主机，或配对失效 / 找不到 Desktop 应用 |

附加属性：`app_id`、`app_name`、`server_version`、`vdd_capability_version`、
`desktop_app_id`、`resolution`、`last_launch_at`、`last_cancel_at`、`active_sessions`、
`active_clients`、`web_api_ok`。

状态按“主机是否有应用在运行”判断，不直接读取物理显示器的电源状态。

## 行为说明

- **关闭开关**：先读 `/serverinfo`。Desktop 已在跑 → 幂等成功；别的应用在跑 → 抛错，不会误杀；
  否则 `GET /launch`，参数 `appid`、`mode=WxHxFPS`、`useVdd=1` 等。
- **打开开关**：`GET /cancel`。这是**全局**取消：如果此时有真实 Moonlight 串流，会结束它。
  需要保护时，填写 WebUI 凭据并打开“保护正在串流的会话”。
- **动作后的刷新**：`/launch` 或 `/cancel` 返回后立即刷新，之后每秒刷新一次，直到
  `currentgame` 变成预期值（关屏最多 15 秒、开屏最多 20 秒）。
- **平时轮询**：每 15 秒（可改）读一次 `/serverinfo`。
- **真实 Moonlight**：连接 Desktop 时开关变关；退出时 Sunshine 自动 cancel 并恢复显示，开关变开。
- **HA 重启**：证书、私钥、分辨率都在 config entry 里；启动后恢复轮询，不会重复 launch。
- **Sunshine 重启**：`currentgame` 归零，开关显示开；如果 VDD 残留导致物理屏仍黑，
  需要在主机侧恢复。

## 安全

- PIN 只用于派生 AES 密钥；配对使用 Moonlight 的四阶段协议。
- 后续控制请求全部使用 **mTLS**：客户端证书 + 固定服务端证书。服务端证书变化会触发重新配对。
- 客户端私钥、WebUI 密码保存在 HA config entry 中；诊断信息会脱敏，不写入日志。
- 不建立视频/音频/输入通道，不读取屏幕内容。
- 配对阶段走局域网明文 HTTP（Moonlight 协议如此）；请勿在不可信网络上配对。
- WebUI 凭据是可选的；不填也能正常开关。

## 已知限制

- 只支持 Windows + Foundation Sunshine + Zako VDD 的“虚拟屏接管物理屏”路径；
  上游原版 Sunshine 没有 VDD 时，`/launch` 只会启动应用，不会熄物理屏。
- 状态按“是否有应用在运行”判断，不直接读取物理显示器电源状态；本地面板启动的应用
  也可能让开关显示“关”。
- 不实现 RTSP 数据面；如果宿主在 RTSP 票据超时后清理 VDD，需要按
  [docs/protocol.md](docs/protocol.md) 的退路补一个最小控制面。
- 一个 config entry 对应一台主机；多台主机就添加多个条目。
- 打开开关会结束当前应用（包括真实串流）；这是需求定义的语义，保护选项可选。

## 排障

| 现象 | 处理 |
|---|---|
| 添加集成提示无法连接 | 确认 HA 能访问 `http://<主机>:47989/serverinfo`；检查防火墙、端口、IP；不要填 `https://` 前缀（会被自动去掉） |
| PIN 页面没有请求 | 等 2–5 秒刷新；确认 HA 已提交“用户”步骤且日志没有 `pairing` 错误；确认 WebUI 端口是 47990 |
| 提示 PIN 错误 | HA 会生成新 PIN 并重新发起配对；重新在 WebUI 输入新 PIN |
| 配对成功但 HTTPS 校验失败 | 见 HA 日志；通常是 Sunshine 证书被重建或 Python 无法把自签证书当信任锚，请附完整错误反馈 |
| `VDD_DRIVER_MISSING` / `VDD_DRIVER_UNAVAILABLE` | 在 Foundation GUI 里安装/修复 ZakoVDD，重启 Windows 后重试 |
| 关闭开关后物理屏不灭 | 确认 Sunshine 显示设置选了“仅基地虚拟屏/远程时停用物理屏”；确认 Desktop 应用存在；看 Sunshine 日志的 `创建虚拟显示器` / `INACTIVE` |
| 打开开关后屏不亮 | 看 Sunshine 日志 `销毁虚拟显示器完成` / `显示设备配置已恢复`；可能是 VDD 残留，重启 Sunshine 服务或在 GUI 里恢复显示 |
| 点击后状态不刷新 | 确认安装的代码包含动作后快速刷新；看 HA 日志有没有 `moonscreen` 报错 |
| 实体显示不可用 | 看 HA 日志的 `MoonScreen`；主机离线、配对失效或找不到 Desktop 应用都会这样 |
| 真实串流被打开开关掐断 | 这是 `/cancel` 的语义；填写 WebUI 凭据并打开“保护正在串流的会话” |
| 配对 429 | Sunshine 对配对请求做了限流；等 `Retry-After` 指示的时间再试 |

日志：HA 的 **设置 → 系统 → 日志** 搜索 `moonscreen`；主机侧
`C:\Program Files\Sunshine\config\sunshine.log`。

## 开发与测试

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m compileall -q custom_components tests tools
```

真实主机验证会熄屏并新增一个配对客户端，执行前请确认主机空闲：

```powershell
.\.venv\Scripts\python.exe tools\live_check.py --host 192.168.1.100 --dry-run
.\.venv\Scripts\python.exe tools\live_check.py --host 192.168.1.100 --yes
```

`--host` 填 Windows 主机的局域网 IP；在主机本机上可以用 `127.0.0.1`。第一次运行会配对一次，
并把测试客户端证书保存到 `tools/.live-check/credentials.json`（已加入 `.gitignore`，含私钥，
不要提交）；之后再运行会复用该证书，`--force-pair` 可换新证书。

## 许可

GNU General Public License v3.0，见 [LICENSE](LICENSE)。

## 参考

- [AlkaidLab/foundation-sunshine](https://github.com/AlkaidLab/foundation-sunshine)：
  `src/nvhttp.cpp`、`src/nvhttp/pairing.cpp`、`src/crypto.cpp`、`src/nvhttp_stream_start.cpp`
- [moonlight-qt `nvpairingmanager.cpp`](https://github.com/moonlight-stream/moonlight-qt/blob/master/app/backend/nvpairingmanager.cpp)
- [Wolf HTTP pairing 文档](https://games-on-whales.github.io/wolf/stable/protocols/http-pairing.html)
