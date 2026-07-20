# 中转服务器服务端实现计划

## 1. 背景与目标

`Mid_transport_server` 作为公网侧中转服务端，负责把公网访问者的 TCP 连接转发到已经建立隧道的下游节点。

本计划只描述中转服务器服务端本身，不绑定任何具体业务服务端、客户端实现、GUI 程序或内部业务协议。中转服务器只处理连接接入、隧道会话、路由绑定、鉴权、流量转发和观测，不解析业务 payload。

第一版目标：

```text
1. 对公网暴露一个或多个 TCP 入口端口。
2. 接受下游节点主动连入并建立持久隧道会话。
3. 将公网入口连接与可用下游隧道会话配对。
4. 透明转发双向字节流。
5. 记录公网访问者 source IP:port、入口 destination IP:port、routeId、sessionId、connectionId。
6. 默认安全，不成为无鉴权开放代理。
7. 支持最小可运维日志、指标和连接清理。
```

## 2. 范围边界

### 2.1 本次覆盖

```text
- 公网 TCP 入口监听。
- 隧道控制监听。
- 下游节点鉴权。
- 路由注册与端口绑定。
- 公网连接与隧道连接配对。
- 透明 TCP 字节流转发。
- 连接生命周期管理。
- 日志、指标、限流和错误处理。
- 服务端配置文件和部署方式。
```

### 2.2 本次不覆盖

```text
- 任意具体业务端程序的内部协议。
- 任意 GUI 或桌面端配置界面。
- 下游节点的具体实现代码。
- 业务 payload 解密、识别、修改或重封包。
- 数据库同步、文件传输、插件协议等业务层逻辑。
- 和其他仓库的强耦合调用。
```

中转服务器只把公网连接送入隧道，并把下游返回的数据送回公网连接。业务端如何处理收到的字节流，不属于本计划。

## 3. 核心架构

推荐第一版采用两个平面：

```text
公网访问平面 Public Ingress
  - 监听对外服务端口
  - 接受访问者 TCP 连接
  - 生成 connectionId
  - 记录 source/destination metadata

隧道控制平面 Tunnel Control
  - 监听下游节点控制连接
  - 鉴权并注册 agent/session
  - 管理 routeId -> agent/session 的映射
  - 为公网连接分配可用隧道
```

逻辑拓扑：

```text
公网访问者
  -> Mid_transport_server public listen port
  -> route table 匹配 routeId
  -> 已认证下游 session
  -> tunnel data channel
  -> 下游节点
```

中转服务器不关心下游节点背后的真实服务类型，只关心 route 是否在线、是否有容量、是否允许当前入口端口转发。

## 4. 基础概念

### 4.1 Agent

下游主动连入中转服务器的一端，代表一个可接收转发流量的节点。

字段建议：

```text
agentId
name
secretHash 或 publicKey
allowedRoutes
maxSessions
maxConnections
createdAt
lastSeenAt
enabled
```

### 4.2 Session

Agent 与中转服务器之间的一条已认证控制连接或复用连接。

字段建议：

```text
sessionId
agentId
remoteAddress
protocolVersion
authenticatedAt
lastHeartbeatAt
activeConnectionCount
maxConnectionCount
state
```

### 4.3 Route

公网入口到下游 agent 的转发规则。

字段建议：

```text
routeId
name
listenAddress
listenPort
agentId
enabled
maxConnections
idleTimeoutSeconds
connectTimeoutSeconds
allowSourceCidrs
```

### 4.4 Connection

一条公网访问者 TCP 连接与一条下游数据通道的配对。

字段建议：

```text
connectionId
routeId
sessionId
publicSourceAddress
publicSourcePort
publicDestinationAddress
publicDestinationPort
openedAt
closedAt
bytesFromPublic
bytesToPublic
closeReason
```

## 5. 协议选择

第一版建议采用简单、可调试的协议，不急于做复杂多路复用。

推荐方式：

```text
- 控制连接：TCP + TLS，JSON Lines 或 length-prefixed JSON frame。
- 数据连接：每条公网连接对应一条 agent data connection。
- 鉴权：agentId + token HMAC，或 mTLS。
- 心跳：控制连接定期 ping/pong。
```

不建议第一版直接做：

```text
- 自研复杂多路复用。
- UDP 转发。
- HTTP 层代理语义。
- payload 压缩或加密二次封装。
- 业务协议识别。
```

后续如需提升连接密度，可以在协议稳定后引入多路复用，例如 QUIC stream、yamux 类 stream，或 WebSocket stream。

## 6. 控制协议草案

### 6.1 Register

Agent 建立控制连接后，第一帧必须注册。

```json
{
  "type": "register",
  "version": 1,
  "agentId": "agent-a",
  "timestamp": 1790000000,
  "nonce": "random",
  "signature": "hmac-or-signature",
  "capabilities": {
    "maxConnections": 200,
    "protocols": ["tcp"]
  }
}
```

服务端返回：

```json
{
  "type": "register_result",
  "ok": true,
  "sessionId": "sess-...",
  "heartbeatIntervalSeconds": 15,
  "routes": ["route-main"]
}
```

### 6.2 Heartbeat

```json
{
  "type": "ping",
  "sessionId": "sess-...",
  "timestamp": 1790000015
}
```

```json
{
  "type": "pong",
  "sessionId": "sess-...",
  "timestamp": 1790000015
}
```

### 6.3 OpenConnection

当公网入口收到新连接后，服务端向 agent 发起连接打开请求。

```json
{
  "type": "open_connection",
  "connectionId": "conn-...",
  "routeId": "route-main",
  "sourceAddress": "8.8.8.8",
  "sourcePort": 45678,
  "destinationAddress": "1.2.3.4",
  "destinationPort": 7000
}
```

这些 metadata 只描述公网侧连接事实。下游节点是否使用这些 metadata，由下游节点自行决定，中转服务器不依赖具体业务端行为。

### 6.4 OpenConnectionResult

```json
{
  "type": "open_connection_result",
  "connectionId": "conn-...",
  "ok": true,
  "dataToken": "one-time-token"
}
```

如果失败：

```json
{
  "type": "open_connection_result",
  "connectionId": "conn-...",
  "ok": false,
  "error": "capacity_exceeded"
}
```

### 6.5 CloseConnection

```json
{
  "type": "close_connection",
  "connectionId": "conn-...",
  "reason": "public_closed"
}
```

## 7. 数据通道草案

第一版建议每条公网连接使用一条独立数据连接，避免多路复用带来的队头阻塞、流控和半关闭复杂度。

数据通道建立流程：

```text
1. 公网入口接收新 TCP 连接。
2. 服务端生成 connectionId。
3. 服务端通过控制连接发送 open_connection。
4. Agent 返回 ok 和一次性 dataToken。
5. Agent 主动连接服务端 data listener，并发送 dataToken。
6. 服务端校验 dataToken，把 public socket 和 data socket 绑定。
7. 双向 CopyLoop 透明转发。
8. 任一侧关闭时，关闭另一侧并发送 close_connection。
```

数据连接握手帧示例：

```json
{
  "type": "data_bind",
  "connectionId": "conn-...",
  "dataToken": "one-time-token"
}
```

要求：

```text
- dataToken 必须短期有效，例如 10 秒。
- dataToken 一次性使用。
- data_bind 未通过认证前不转发任何公网数据。
- public socket 可短暂暂停读取，等待 data channel 建立，避免内存堆积。
```

## 8. 服务端组件

建议模块划分：

```text
cmd/server
internal/config
internal/auth
internal/control
internal/ingress
internal/router
internal/session
internal/dataplane
internal/metrics
internal/logging
```

职责：

```text
config      - 读取 YAML/JSON 配置并校验端口冲突。
auth        - agent 鉴权、token 校验、签名校验。
control     - 控制连接监听、register、heartbeat、open/close 消息。
ingress     - 公网 TCP 入口监听和 connectionId 生成。
router      - routeId/listenPort 到 agent/session 的匹配。
session     - agent session 生命周期、心跳超时、容量统计。
dataplane   - data listener、dataToken、socket 绑定和 CopyLoop。
metrics     - 连接数、流量、错误码、延迟统计。
logging     - 结构化日志输出。
```

## 9. 配置文件

示例：

```yaml
server:
  controlListen: "0.0.0.0:9000"
  dataListen: "0.0.0.0:9001"
  logLevel: "info"
  shutdownTimeoutSeconds: 10

security:
  authMode: "hmac"
  tokenFile: "config/agents.yaml"
  requireTls: true
  tlsCertFile: "config/server.crt"
  tlsKeyFile: "config/server.key"

agents:
  - agentId: "agent-a"
    enabled: true
    secretRef: "agent-a-secret"
    allowedRoutes: ["route-main"]
    maxSessions: 2
    maxConnections: 200

routes:
  - routeId: "route-main"
    enabled: true
    listenAddress: "0.0.0.0"
    listenPort: 7000
    agentId: "agent-a"
    maxConnections: 200
    idleTimeoutSeconds: 300
    connectTimeoutSeconds: 10
    allowSourceCidrs: ["0.0.0.0/0"]
```

配置校验要求：

```text
- controlListen、dataListen、route listenPort 不能冲突。
- route.agentId 必须存在且 enabled。
- agent.allowedRoutes 必须包含对应 routeId。
- listenPort 必须在 1..65535。
- maxConnections 必须有限制。
- requireTls 默认为 true。
```

## 10. 路由选择策略

第一版一个 route 绑定一个 agent。

如果同一 agent 有多个 session：

```text
- 优先选择 activeConnectionCount 最低的 session。
- 跳过心跳超时 session。
- 跳过超过 maxConnectionCount 的 session。
```

后续可扩展：

```text
- 一个 route 多个 agent 负载均衡。
- 权重调度。
- 主备切换。
- 灰度路由。
```

## 11. 连接生命周期

### 11.1 Public connection

```text
accepted
  -> route matched
  -> session selected
  -> open_connection sent
  -> data channel bound
  -> forwarding
  -> closing
  -> closed
```

失败处理：

```text
- route 不存在：直接关闭。
- route disabled：直接关闭。
- agent offline：直接关闭并记录 no_session。
- agent 容量满：直接关闭并记录 capacity_exceeded。
- data channel 超时：关闭 public socket。
```

### 11.2 Session

```text
connected
  -> registered
  -> active
  -> heartbeat missed
  -> draining
  -> closed
```

Session 关闭时：

```text
- 标记 session unavailable。
- 关闭或迁移其绑定的 active connections。
- 删除 pending dataToken。
- 写入 summary 日志。
```

## 12. 转发实现要求

CopyLoop 要求：

```text
- 双向转发使用独立 goroutine 或等价异步任务。
- 任一方向 EOF 或错误，关闭整个 connection。
- 支持半关闭时可以先简单全关闭，后续再优化。
- 每条连接统计 bytesFromPublic / bytesToPublic。
- idleTimeout 到期后关闭。
- 单连接内存使用有上限。
```

Buffer 建议：

```text
- 32KB 或 64KB buffer。
- 使用 buffer pool 降低 GC 压力。
- 不缓存完整 payload。
```

## 13. 安全要求

默认安全策略：

```text
1. 控制连接必须鉴权。
2. 生产环境 requireTls 默认 true。
3. agent secret 不写入日志。
4. dataToken 一次性、短 TTL、不可复用。
5. route 必须显式绑定 agent，不能自动开放所有端口。
6. 每个 route、agent、session 都有连接数上限。
7. 支持 allowSourceCidrs 限制公网访问者来源。
8. 控制消息大小有限制，避免内存攻击。
9. 心跳超时必须清理 session。
10. 不能把本服务变成无鉴权开放代理。
```

## 14. 日志与指标

结构化日志字段：

```text
ts
level
event
routeId
agentId
sessionId
connectionId
sourceAddress
sourcePort
destinationAddress
destinationPort
bytesFromPublic
bytesToPublic
reason
error
```

关键事件：

```text
server_start
route_listen_start
agent_register_success
agent_register_failed
session_heartbeat_timeout
public_connection_accepted
open_connection_sent
data_channel_bound
connection_closed
route_capacity_exceeded
server_shutdown
```

最小指标：

```text
active_sessions
active_connections
connections_total
connections_failed_total
bytes_from_public_total
bytes_to_public_total
open_connection_latency_ms
session_heartbeat_missed_total
```

## 15. 管理接口

第一版可以不提供 HTTP 管理 API，只通过日志和配置文件运维。

如果增加管理接口，建议只监听本机或内网，并提供：

```text
GET /healthz
GET /readyz
GET /metrics
GET /routes
GET /sessions
```

管理接口不得提供无鉴权的动态开端口能力。

## 16. 部署方式

第一版部署形态：

```text
Mid_transport_server binary
config/server.yaml
config/agents.yaml
logs/
```

系统要求：

```text
- 具备公网 IP 或公网端口映射。
- 防火墙放行 route listenPort、controlListen、dataListen。
- TLS 证书和 agent secret 通过配置挂载。
- systemd / Windows Service / 容器部署任选其一，第一版优先 systemd 或容器。
```

启动顺序：

```text
1. 读取配置。
2. 校验端口、agent、route。
3. 启动 control listener。
4. 启动 data listener。
5. 启动 route public listeners。
6. 等待 agent 注册。
```

关闭顺序：

```text
1. 停止接受新的 public connections。
2. 停止接受新的 data channels。
3. 通知 agent draining。
4. 等待 active connections 在 shutdownTimeout 内结束。
5. 强制关闭剩余连接。
6. 写入 shutdown summary。
```

## 17. 测试计划

### 17.1 配置校验测试

```text
- 端口冲突。
- route 引用不存在 agent。
- disabled agent。
- 非法端口。
- maxConnections 为 0 或负数。
- TLS 配置缺失。
```

### 17.2 鉴权测试

```text
- 正确 token 注册成功。
- 错误 token 注册失败。
- 过期 timestamp 注册失败。
- 重放 nonce 注册失败。
- disabled agent 注册失败。
```

### 17.3 路由测试

```text
- public connection 命中 route。
- route disabled 时拒绝连接。
- agent offline 时拒绝连接。
- session 容量满时拒绝连接。
- 多 session 时选择连接数较少的 session。
```

### 17.4 数据转发 smoke test

```text
公网测试客户端 -> public listener -> fake agent -> echo server
```

验证：

```text
- 双向字节一致。
- 大包能持续转发。
- 连接关闭后资源释放。
- bytesFromPublic / bytesToPublic 正确。
```

### 17.5 稳定性测试

```text
- agent 控制连接断开时清理 session。
- data channel 未按时绑定时清理 public connection。
- public 端突然断开。
- agent 端突然断开。
- idleTimeout 自动关闭。
```

## 18. 分阶段实现建议

### Phase 1：文档与协议确认

确认服务端职责、route/session/connection 模型、控制协议和数据通道流程。

### Phase 2：配置与日志骨架

实现配置读取、校验、结构化日志、基础启动退出。

### Phase 3：控制平面

实现 control listener、agent register、heartbeat、session manager。

### Phase 4：公网入口与路由

实现 route public listener、route matching、session selection。

### Phase 5：数据通道

实现 data listener、dataToken、data_bind、public socket 与 data socket 绑定。

### Phase 6：转发与清理

实现双向 CopyLoop、超时、关闭传播、连接统计。

### Phase 7：安全加固

实现 TLS、HMAC/mTLS、nonce 防重放、连接数限制、source CIDR 限制。

### Phase 8：可观测性与部署

实现 healthz、metrics、systemd/container 部署文档和 smoke test。

## 19. 最小验收标准

第一版可接受的验收标准：

```text
1. 服务端能读取配置并启动 control/data/public 三类 listener。
2. agent 使用正确凭据能注册 session。
3. agent 心跳超时后 session 被清理。
4. public connection 能根据 route 绑定到在线 session。
5. data channel 使用一次性 dataToken 绑定 connection。
6. 双向 TCP 字节流透明转发。
7. public source/destination metadata 被记录并发送给 agent。
8. route/agent/session 连接数限制生效。
9. 关闭连接后 connection/session 计数正确回收。
10. 日志能定位 routeId、agentId、sessionId、connectionId 和 close reason。
```

## 20. 不建议第一版实现的内容

```text
- 多路复用。
- UDP。
- HTTP 代理模式。
- 动态公网端口自动开关。
- 无鉴权 agent 自注册。
- payload 压缩。
- payload 加密二次封装。
- 业务协议解析。
- 与任意具体业务端仓库耦合。
```

## 21. 总结

中转服务器服务端第一版应保持简单、透明、可运维：

```text
公网入口负责接收连接。
控制平面负责认证 agent 和维护 session。
路由表负责把入口端口绑定到 agent。
数据通道负责透明转发字节流。
日志和指标负责可观测性。
```

它不解析业务协议，也不依赖任何具体业务端实现。这样可以先把中转服务端能力稳定下来，再让不同下游节点按自己的方式接入。
