# Mid_transport_server

公网侧 Xray MT reverse 运行器。第一版只负责下载/校验固定 `mt-v26.3.27` 产物、生成公网侧 VLESS reverse 配置、用 `subprocess` 启停 `xray/xray.exe`，并提供仅本机可访问的 health/status。

## 运行

1. 复制示例配置：

```powershell
Copy-Item .\configs\mid-transport.example.yaml .\configs\mid-transport.yaml
```

2. 把 `portal.reverseCredentialId` 改成和 C# 端一致的 UUID。

3. 生成并检查 Xray 配置：

```powershell
python -m mid_transport_server.main --config .\configs\mid-transport.yaml --generate-config-only
```

4. 启动中转：

```powershell
python -m mid_transport_server.main --config .\configs\mid-transport.yaml
```

health/status 只监听 `127.0.0.1:18080`：

```text
GET /healthz
GET /status
```

`/healthz` 只表示 Xray 进程存活，不表示公网 reverse tunnel 已经可用。C# 内网侧 reverse mux 注册完成前，公网入口可能短暂出现 `non existing outTag`；`/status` 会暴露最近一次该类路由错误，便于判断是否还处于 reverse 注册前状态。

## 固定约束

- release tag 固定为 `mt-v26.3.27`。
- Linux 使用 `xray-mt-linux-amd64.tar.gz` 中的 `xray`。
- Windows 使用 `xray-mt-windows-amd64.zip` 中的 `xray.exe`。
- Python 不解析、不修改业务 payload。
- 不提供公网 Web 控制面板。
