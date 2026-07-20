# Python 中转服务器服务端实现计划

## 1. 定位

`Mid_transport_server` 第一版全部使用 Python 实现。

它不是一套新的隧道协议，也不是控制面板系统。它是公网侧 Xray reverse 运行器和部署管理器：

```text
Python Mid_transport_server
  -> 下载/校验固定版本 Xray-core MT release 产物
  -> 生成公网侧 VLESS reverse 配置
  -> 通过 subprocess 启动 xray/xray.exe
  -> 监控进程、日志、健康状态
  -> 停止或重启 xray
```

实际协议、认证、reverse、加密和 TCP 转发由 Xray 负责。Python 不解析、不修改、不理解业务 payload。

共享契约见：

```text
MT_XRAY_INTEGRATION_CONTRACT.md
```

## 2. 核心目标

第一版目标：

```text
1. 全部服务端管理逻辑用 Python 实现。
2. 默认使用 subprocess 管理 xray/xray.exe。
3. Linux 使用 xray-mt-linux-amd64.tar.gz 中的 xray。
4. Windows 使用 xray-mt-windows-amd64.zip 中的 xray.exe。
5. 按共享契约生成公网侧 VLESS reverse 配置。
6. 接收 C# 端主动建立的 reverse 连接。
7. 接收公网访问者主控入口连接。
8. 通过 Xray routing 把公网入口流量转入 reverse 连接。
9. 提供本机 health/status 接口。
10. 提供清晰的错误提示、日志、安装和升级/回滚策略。
```

## 3. 明确不做

第一版不做：

```text
- 不自研隧道协议。
- 不自研控制平面。
- 不自研数据通道。
- 不解析业务协议。
- 不修改 TCP payload。
- 不做公网 Web 控制面板。
- 不做用户管理系统。
- 不做动态开端口面板。
- 不默认使用 .dll/.so 嵌入 Xray。
- 不和 C# 代码耦合。
```

中转服务器只负责运行公网侧 Xray 和管理本地服务生命周期。

## 4. 是否需要控制面板

结论：**第一版不需要公网控制面板**。

原因：

```text
- 这个端只是轻量转发节点。
- Xray 已经处理协议、认证、reverse 和转发。
- 配置项数量有限，用 YAML/JSON 文件更简单可靠。
- 公网控制面板会引入鉴权、权限、攻击面和运维复杂度。
```

第一版只提供本机管理接口：

```text
GET 127.0.0.1:18080/healthz
GET 127.0.0.1:18080/status
POST 127.0.0.1:18080/stop       # 可选，仅本机
POST 127.0.0.1:18080/reload     # 可选，第一版可不实现
```

限制：

```text
- health/status 默认只监听 127.0.0.1。
- 不对公网开放管理接口。
- reload 第一版可以不做，配置修改后重启生效。
```

## 5. Xray 运行模式

### 5.1 默认模式：subprocess 启动 xray 可执行文件

Linux：

```text
./runtime/xray-mt/mt-v26.3.27/linux-amd64/xray run -config ./configs/xray.portal.json
```

Windows：

```text
.\runtime\xray-mt\mt-v26.3.27\windows-amd64\xray.exe run -config .\configs\xray.portal.json
```

优点：

```text
- 跨 Linux / Windows 最简单。
- Xray 崩溃不会直接杀掉 Python 进程。
- systemd、Windows Service、Docker 都更容易管理。
- stdout/stderr、退出码、重启策略清楚。
- 不需要 ctypes、ABI、Go runtime 嵌入。
```

### 5.2 可选模式：ctypes 加载 .so/.dll

仅作为未来选项，不是第一版默认路径。

可用文件：

```text
Windows: xray-mt-bridge.dll
Linux:   libxray-mt-bridge.so
```

只有明确需要“无 xray 子进程”时才考虑：

```text
Python ctypes -> XrayBridgeStart/TestConfig/Stop/LastError
```

第一版不实现该模式。

## 6. 固定 release 产物安装

固定 release：

```text
https://github.com/qqq694637644/Xray-core/releases/tag/mt-v26.3.27
```

Linux 下载：

```text
xray-mt-linux-amd64.tar.gz
xray-mt-linux-amd64.tar.gz.sha256
```

Windows 下载：

```text
xray-mt-windows-amd64.zip
xray-mt-windows-amd64.zip.sha256
```

安装步骤：

```text
1. 根据 platform.machine/platform.system 判断平台。
2. 下载对应 asset 和 .sha256。
3. 校验 archive SHA256。
4. 解压到 runtime/xray-mt/mt-v26.3.27/<platform>/。
5. 校验包内 SHA256SUMS.txt。
6. 确认 xray 或 xray.exe 存在。
7. 调用 xray version 或 xray run -test -config 进行可用性检查。
```

目录建议：

```text
runtime/
  xray-mt/
    mt-v26.3.27/
      linux-amd64/
        xray
        libxray-mt-bridge.so
        libxray-mt-bridge.h
        README.md
        SHA256SUMS.txt
      windows-amd64/
        xray.exe
        xray-mt-bridge.dll
        xray-mt-bridge.h
        README.md
        SHA256SUMS.txt
```

升级/回滚：

```text
- 不覆盖旧版本目录。
- 新版本下载到新目录。
- 校验通过后切换 current 指针或配置项。
- 启动失败时切回上一版本。
```

## 7. 公网侧职责

Python 中转服务端是公网侧，负责运行 Xray portal/public-side 配置。

职责：

```text
1. 监听 C# 端主动连接的 VLESS reverse 端口，例如 8443。
2. 监听公网访问者主控入口端口，例如 7000。
3. 在 Xray 配置中把 C# reverse client 的 reverse.tag 设置为 mt-reverse-out。
4. 在 Xray routing 中把 mt-public-main 流量转给 mt-reverse-out。
5. 记录 xray 进程状态、端口状态、启动失败原因和退出码。
```

不做：

```text
- 不知道 C# 内部 HPSocket 端口。
- 不知道 C# PPv2Bridge 实现细节。
- 不解析业务协议。
```

## 8. Xray portal 配置生成

Python 根据共享契约生成 `configs/xray.portal.json`。

默认模板必须与 `MT_XRAY_INTEGRATION_CONTRACT.md` 保持一致：

```text
inbound mt-vless-reverse: 0.0.0.0:8443, protocol=vless, client.reverse.tag=mt-reverse-out
inbound mt-public-main:   0.0.0.0:7000, protocol=dokodemo-door
routing: mt-public-main -> mt-reverse-out
```

第一版使用：

```text
network = tcp
security = none
```

后续如果启用 TLS/REALITY/WS/gRPC，必须同时更新：

```text
- MT_XRAY_INTEGRATION_CONTRACT.md
- Python 配置生成器
- C# 配置生成器
```

## 9. Python 项目结构

建议目录：

```text
mid_transport_server/
  __init__.py
  main.py
  config.py
  release_assets.py
  xray_config.py
  xray_process.py
  health_server.py
  logging_config.py
  platform_service.py
  errors.py
configs/
  mid-transport.example.yaml
  xray.portal.example.json
runtime/
  .gitkeep
logs/
  .gitkeep
README.md
MID_TRANSPORT_SERVER_IMPLEMENTATION_PLAN.md
MT_XRAY_INTEGRATION_CONTRACT.md
```

模块职责：

```text
config.py          - 读取/校验 YAML 配置。
release_assets.py  - 下载、sha256 校验、解压、版本目录管理。
xray_config.py     - 生成 Xray portal JSON。
xray_process.py    - subprocess 启动/停止/重启 xray。
health_server.py   - 本机 health/status HTTP。
platform_service.py - Linux systemd / Windows Service 辅助。
```

## 10. Python 配置文件

`configs/mid-transport.example.yaml`：

```yaml
xray:
  releaseTag: "mt-v26.3.27"
  installRoot: "./runtime/xray-mt"
  autoDownload: true
  restartOnExit: true
  restartDelaySeconds: 3

portal:
  reverseListenAddress: "0.0.0.0"
  reverseListenPort: 8443
  publicListenAddress: "0.0.0.0"
  publicMainPort: 7000
  reverseCredentialId: "<MT_UUID>"
  reverseOutboundTag: "mt-reverse-out"
  reverseInboundTag: "mt-vless-reverse"
  publicMainInboundTag: "mt-public-main"

health:
  enabled: true
  listenAddress: "127.0.0.1"
  listenPort: 18080

logging:
  level: "info"
  file: "./logs/mid-transport-server.log"
```

配置校验：

```text
- reverseListenPort 和 publicMainPort 不能冲突。
- 端口必须在 1..65535。
- reverseCredentialId 必须是有效 UUID。
- health.listenAddress 默认必须是 127.0.0.1。
- releaseTag 第一版必须是 mt-v26.3.27。
```

## 11. 启动流程

```text
1. 读取 mid-transport YAML。
2. 校验配置。
3. 确认平台 Linux/Windows amd64。
4. 下载/校验/解压 Xray MT release asset。
5. 生成 configs/xray.portal.generated.json。
6. 执行 xray run -test -config configs/xray.portal.generated.json。
7. 测试通过后 subprocess 启动 xray。
8. 启动本机 health/status server。
9. 记录 xray PID、配置路径、监听端口。
```

任何关键失败都直接报错，不静默跳过。

## 12. 停止流程

Linux：

```text
1. 收到 SIGTERM/SIGINT。
2. 向 xray 子进程发送 terminate。
3. 等待 graceful timeout。
4. 超时后 kill。
5. 写入退出日志。
```

Windows：

```text
1. 控制台 Ctrl+C 或 Service stop。
2. 调用 subprocess terminate。
3. 等待 graceful timeout。
4. 超时后 kill。
5. 写入退出日志。
```

## 13. Linux 部署

推荐 systemd：

```text
/etc/mid-transport-server/config.yaml
/opt/mid-transport-server/
/opt/mid-transport-server/runtime/
/var/log/mid-transport-server/
```

systemd 要求：

```text
- WorkingDirectory 指向程序目录。
- ExecStart 使用 Python 入口。
- Restart=on-failure 可选。
- SIGTERM 能触发优雅停止 xray。
- stdout/stderr 进入 journald 或日志文件。
```

Docker 可作为后续增强，不是第一版必须。

## 14. Windows 部署

第一版支持控制台运行：

```text
python -m mid_transport_server.main --config .\configs\mid-transport.yaml
```

后续可选 Windows Service：

```text
- 使用 NSSM 或 Python service wrapper。
- service stop 时停止 xray.exe。
- 可配置 CREATE_NO_WINDOW，避免弹出 xray.exe 控制台窗口。
- 日志写入 logs/ 或 Windows Event Log。
```

第一版不要求必须实现 Windows Service，但必须保证 Windows 控制台模式可用。

## 15. 健康检查

本机接口：

```text
GET /healthz
GET /status
```

`/healthz` 示例：

```json
{
  "ok": true,
  "xrayRunning": true,
  "pid": 12345,
  "releaseTag": "mt-v26.3.27"
}
```

`/status` 示例：

```json
{
  "platform": "linux-amd64",
  "xrayExecutable": "./runtime/xray-mt/mt-v26.3.27/linux-amd64/xray",
  "xrayConfig": "./configs/xray.portal.generated.json",
  "reverseListen": "0.0.0.0:8443",
  "publicMainListen": "0.0.0.0:7000",
  "restartOnExit": true,
  "lastExitCode": null,
  "lastError": null
}
```

只监听 `127.0.0.1`。

## 16. 日志

最小日志事件：

```text
config_loaded
asset_download_start
asset_download_success
asset_sha256_failed
asset_installed
xray_config_generated
xray_config_test_start
xray_config_test_success
xray_config_test_failed
xray_start
xray_exit
xray_restart
xray_stop
health_server_start
```

禁止记录：

```text
- reverseCredentialId 完整值。
- 私钥、token、证书内容。
- 业务 payload。
```

## 17. 失败策略

```text
asset 下载失败：报错。
sha256 校验失败：报错并删除损坏文件。
xray/xray.exe 不存在：报错。
xray config test 失败：报错，不启动。
端口冲突：报错。
xray 子进程启动失败：报错。
xray 异常退出：按 restartOnExit 决定重启或退出，但必须记录清楚。
```

不做自动协议降级，不改业务端配置。

## 18. 测试计划

### 18.1 单元/配置测试

```text
- YAML 配置解析。
- UUID 校验。
- 端口冲突校验。
- 平台判断。
- release asset URL 选择。
- sha256 文件解析。
- Xray portal JSON 生成。
```

### 18.2 进程管理测试

```text
- xray run -test 成功才启动。
- xray run -test 失败时不启动。
- stop 能结束 xray 子进程。
- xray 异常退出时按 restartOnExit 重启或退出。
```

### 18.3 跨平台 smoke test

```text
- Linux amd64：下载 xray-mt-linux-amd64.tar.gz，启动 xray。
- Windows amd64：下载 xray-mt-windows-amd64.zip，启动 xray.exe。
- health/status 返回正确。
```

### 18.4 端到端测试

```text
1. Python 中转服务端启动公网侧 Xray。
2. C# 端启动内嵌 Xray reverse。
3. C# 端无公网，只能主动连出。
4. 公网访问者连接中转 publicMainPort。
5. 流量通过 reverse 回到 C# 端。
6. C# PPv2Bridge 收到 PPv2 header。
7. PPv2 source 是公网访问者 IP:port。
8. HPSocket 收到原业务包。
```

## 19. 分阶段实现

```text
Phase 1：共享契约和 Python 计划确认。
Phase 2：Python 配置读取/校验。
Phase 3：release asset 下载、sha256 校验和解压。
Phase 4：Xray portal JSON 生成和 xray run -test。
Phase 5：subprocess 启停和日志。
Phase 6：本机 health/status。
Phase 7：Linux systemd 和 Windows 控制台部署文档。
Phase 8：端到端联调。
```

## 20. 最小验收标准

```text
1. Python 服务能在 Linux amd64 启动 xray。
2. Python 服务能在 Windows amd64 启动 xray.exe。
3. 能下载并校验 mt-v26.3.27 release 产物。
4. 能生成符合共享契约的 VLESS reverse 公网侧配置。
5. xray run -test 通过后才启动。
6. 公网 8443 接收 C# reverse 连接。
7. 公网 7000 接收访问者主控连接。
8. routing 能把 7000 流量送入 reverse 隧道。
9. health/status 只监听 127.0.0.1。
10. 不提供公网控制面板。
```

## 21. 总结

Python 中转服务端第一版应该保持很薄：

```text
Python 负责安装、配置、启动、停止、监控 Xray。
Xray 负责协议、认证、reverse、加密和转发。
业务 payload 只作为 TCP 字节流经过，不被 Python 服务理解或修改。
```
