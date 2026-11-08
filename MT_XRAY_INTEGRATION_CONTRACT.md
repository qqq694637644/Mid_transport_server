# MT Xray 集成共同约定

## 1. 目标

本文是 C# 服务端与 Python 中转服务端共享的集成契约。两端必须按同一份版本、产物、端口、tag、协议参数和失败策略实现，避免各自生成不兼容的 Xray 配置。

核心链路：

```text
公网访问者
  -> Python 中转服务端启动的公网侧 Xray
  -> VLESS reverse 隧道
  -> C# 端内嵌 Xray-core shared library
  -> C# 本机 PPv2Bridge
  -> C# 本机 HPSocket 内部端口
```

## 2. 固定 Xray-core 版本与 release 产物

固定版本：

```text
Xray-core fork: qqq694637644/Xray-core
source tag: v26.3.27
MT release tag: mt-v26.3.27
```

Release 地址：

```text
https://github.com/qqq694637644/Xray-core/releases/tag/mt-v26.3.27
```

Windows amd64 产物：

```text
xray-mt-windows-amd64.zip
xray-mt-windows-amd64.zip.sha256
```

包内文件：

```text
xray.exe
xray-mt-bridge.dll
xray-mt-bridge.h
README.md
SHA256SUMS.txt
```

Linux amd64 产物：

```text
xray-mt-linux-amd64.tar.gz
xray-mt-linux-amd64.tar.gz.sha256
```

包内文件：

```text
xray
libxray-mt-bridge.so
libxray-mt-bridge.h
README.md
SHA256SUMS.txt
```

## 3. 两端角色

Python 中转服务端：

```text
- 公网侧。
- 默认通过 subprocess 启动 xray/xray.exe。
- 负责下载、校验、解压、生成配置、启动、停止、健康检查和日志。
- 负责运行 VLESS reverse 公网侧配置。
- 不解析、不修改业务 payload。
- 不实现自研隧道协议。
```

C# 服务端：

```text
- 内网侧，可能没有公网。
- 默认加载 xray-mt-bridge.dll。
- 通过 P/Invoke 调用 XrayBridge* API。
- 主动连接 Python 中转服务端的公网 reverse 端口。
- 把 reverse 回流连接转发到本机 PPv2Bridge。
- PPv2Bridge 剥离 PROXY protocol v2 header 后转发给 HPSocket。
```

## 4. 默认端口与 tag

所有名称可配置，但两端必须一致。

```text
midHost                       = <MID_PUBLIC_HOST>
midReversePort                = 8443
midPublicMainPort             = 7000
csharpLocalPp2BridgeAddress   = 127.0.0.1
csharpLocalPp2BridgePort      = 17000
csharpLocalHpSocketAddress    = 127.0.0.1
csharpLocalHpSocketPort       = 17001
reverseCredentialId           = <MT_UUID>
reverseInboundTagOnCSharp     = mt-reverse-in
reverseOutboundTagOnMid       = mt-reverse-out
midReverseInboundTag          = mt-vless-reverse
midPublicMainInboundTag       = mt-public-main
csharpLocalPp2OutboundTag     = mt-local-ppv2
```

## 5. Xray shared library API

C# 端必须绑定这些 API：

```c
int XrayBridgeStart(const char* config_json_utf8);
int XrayBridgeStop(void);
int XrayBridgeIsRunning(void);
int XrayBridgeTestConfig(const char* config_json_utf8);
int XrayBridgeLastError(char* buffer, int buffer_len);
int XrayBridgeVersion(char* buffer, int buffer_len);
```

启动顺序必须包含配置测试：

```text
1. 读取/生成 Xray JSON。
2. 调用 XrayBridgeTestConfig。
3. TestConfig 返回成功后再调用 XrayBridgeStart。
4. Start 返回失败时调用 XrayBridgeLastError 并报错。
```

## 6. C# 端 VLESS reverse 配置模板

这是 C# 内网侧配置模板。所有 `<...>` 占位符必须由配置生成器替换。

```json
{
  "log": {
    "loglevel": "warning"
  },
  "routing": {
    "rules": [
      {
        "type": "field",
        "inboundTag": ["mt-reverse-in"],
        "outboundTag": "mt-local-ppv2"
      }
    ]
  },
  "outbounds": [
    {
      "tag": "mt-local-ppv2",
      "protocol": "freedom",
      "settings": {
        "redirect": "127.0.0.1:17000",
        "proxyProtocol": 2
      }
    },
    {
      "tag": "mt-connect-reverse",
      "protocol": "vless",
      "settings": {
        "address": "<MID_PUBLIC_HOST>",
        "port": 8443,
        "id": "<MT_UUID>",
        "encryption": "none",
        "reverse": {
          "tag": "mt-reverse-in"
        }
      },
      "streamSettings": {
        "network": "tcp",
        "security": "none"
      }
    }
  ]
}
```

第一版先使用 `tcp + security:none` 作为最小可验证模板。后续如启用 TLS/REALITY/WS/gRPC，必须同时更新本契约和两端配置生成器。

## 7. Python 中转侧 VLESS reverse 配置模板

这是公网中转侧配置模板。公网访问者连接 `midPublicMainPort`，C# 端主动连接 `midReversePort`。

```json
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "tag": "mt-vless-reverse",
      "listen": "0.0.0.0",
      "port": 8443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "<MT_UUID>",
            "email": "csharp-main",
            "reverse": {
              "tag": "mt-reverse-out"
            }
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "none"
      }
    },
    {
      "tag": "mt-public-main",
      "listen": "0.0.0.0",
      "port": 7000,
      "protocol": "dokodemo-door",
      "settings": {
        "address": "mt.reverse.local",
        "port": 1,
        "network": "tcp"
      }
    }
  ],
  "routing": {
    "rules": [
      {
        "type": "field",
        "inboundTag": ["mt-public-main"],
        "outboundTag": "mt-reverse-out"
      }
    ]
  },
  "outbounds": [
    {
      "tag": "direct",
      "protocol": "freedom"
    }
  ]
}
```

说明：

```text
- mt-vless-reverse 接收 C# 端主动建立的 reverse 连接。
- mt-public-main 接收公网访问者的原始 TCP 连接。
- routing 把 mt-public-main 流量送到 mt-reverse-out。
- mt-reverse-out 来自 VLESS inbound client 的 reverse.tag。
- dokodemo-door 的 address/port 只是业务流进入 reverse 的目标占位；C# 端 freedom redirect 会把流量落到本机 PPv2Bridge。
```

## 8. PROXY protocol v2 约定

C# 端 `mt-local-ppv2` 必须设置：

```json
{
  "protocol": "freedom",
  "settings": {
    "redirect": "127.0.0.1:17000",
    "proxyProtocol": 2
  }
}
```

Xray-core v26.3.27 源码支持点：

```text
infra/conf/freedom.go        -> 解析 settings.proxyProtocol，允许 1 或 2。
proxy/freedom/freedom.go     -> proxyProtocol > 0 时写入 PROXY protocol header。
infra/conf/vless.go          -> VLESS inbound/outbound 支持 reverse.tag。
proxy/vless/outbound.go      -> outbound reverse 会创建并维护 reverse worker。
app/reverse/*                -> legacy reverse bridge/portal 组件仍存在。
```

重要细节：

```text
- PROXY protocol source 应来自 Xray inbound metadata，也就是公网访问者来源。
- PROXY protocol destination 在 freedom redirect 场景下是实际 backend 连接地址，通常是 127.0.0.1:17000。
- 因此 C# 端不要把 PPv2 destination 当成公网入口端口。
- 公网入口端口应由 mt-public-main route 配置记录，例如 7000。
```

## 9. 失败策略

第一版不做自动回退直连。任何关键失败都必须明确报错并停止启动本模式。

C# 端失败策略：

```text
- xray-mt-bridge.dll 缺失：报错，Reverse/PPv2 模式启动失败。
- xray-mt-bridge.dll 版本不符：报错，Reverse/PPv2 模式启动失败。
- SHA256 校验失败：报错，拒绝加载。
- XrayBridgeTestConfig 失败：读取 XrayBridgeLastError，报错，停止启动。
- PPv2Bridge 启动失败：报错，停止启动 Xray。
- HPSocket 内部端口启动失败：报错，停止启动 PPv2Bridge/Xray。
- XrayBridgeStart 失败：读取 XrayBridgeLastError，停止 PPv2Bridge 和内部 HPSocket。
- reverse 长时间连不上中转服务器：报错提示连接失败，不自动回退直连。
```

中转端失败策略：

```text
- release asset 下载失败：报错。
- sha256 校验失败：报错并删除损坏文件。
- xray/xray.exe 不存在：报错。
- xray config test 失败：报错，不启动。
- 端口被占用：报错。
- xray 进程异常退出：按配置重启或报错退出，但不得静默忽略。
```

安全要求：

```text
- 不自动回退直连，避免意外把 HPSocket 暴露到公网。
- 直连模式只能由用户显式配置启用。
- 失败提示必须包含失败阶段、错误码/LastError、配置文件路径和建议检查项。
```

## 10. 端到端验收

最小验收矩阵：

```text
1. Python 中转运行在 Linux，C# 运行在 Windows。
2. Python 中转运行在 Windows，C# 运行在 Windows。
3. C# 机器无公网，只能主动连出。
4. C# 端 XrayBridgeTestConfig 成功。
5. C# 端 XrayBridgeStart 成功并主动连接中转。
6. 公网访问者连接中转 mtPublicMainPort。
7. 流量通过 VLESS reverse 回到 C# 端。
8. C# 端 PPv2Bridge 收到 PROXY protocol v2 header。
9. PPv2 source 是公网访问者 IP:port。
10. HPSocket 收到原始业务包，不包含 PPv2 header。
11. OnClose 后 Registry 清理。
12. 中转 xray 重启后 C# 端能重新建立 reverse 连接，或给出明确错误。
```

第 9 条是必须验收项。源码支持 `proxyProtocol` 和 `reverse`，但集成仍必须用端到端测试确认真实 source metadata 沿 reverse 链路传递符合预期。
