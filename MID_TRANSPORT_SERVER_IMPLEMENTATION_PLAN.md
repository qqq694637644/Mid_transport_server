# 中转服务器服务端实现计划

## 1. 定位

`Mid_transport_server` 不是一套新的隧道协议，也不是控制平面系统。

它只是一个部署在中转服务器上的轻量转发节点：

```text
入口 TCP 流量
  -> 中转服务器
  -> Xray 协议链路
  -> 目标方向
```

Xray 已经负责连接建立、协议握手、加密、认证、传输和转发能力。中转服务器服务端不要重复实现这些能力，也不要另起一套调度或控制协议。

本仓库第一版只需要把“中转节点如何启动、如何配置、如何转发、如何观察状态”规划清楚。

## 2. 核心目标

第一版目标：

```text
1. 在中转服务器上提供一个可部署的转发服务。
2. 使用固定版本的 Xray-core 作为实际隧道/代理内核。
3. 按配置监听入口端口。
4. 按配置把流量转发到指定出口。
5. 不解析、不修改、不理解业务 payload。
6. 不实现自定义控制协议。
7. 不和任何具体业务端代码耦合。
8. 提供最小日志、配置校验、启动停止和连通性验证。
```

## 3. 本次不做什么

明确不做：

```text
- 不自研隧道协议。
- 不设计独立控制平面。
- 不设计额外数据通道。
- 不做动态调度系统。
- 不解析业务协议。
- 不修改 TCP payload。
- 不感知数据库同步、文件传输、插件消息等业务。
- 不和任意具体业务服务端绑定。
```

中转服务器只处理转发链路本身。业务端内部怎么处理收到的字节流，和中转服务器无关。

## 4. 推荐架构

第一版推荐直接把中转服务器做成 Xray-core 的部署封装。

```text
Mid_transport_server
  ├─ 读取配置
  ├─ 校验端口和目标地址
  ├─ 生成或加载 Xray 配置
  ├─ 启动 Xray-core
  ├─ 监控 Xray 进程/实例状态
  └─ 输出日志和健康状态
```

实际转发由 Xray 完成：

```text
公网入口
  -> Xray inbound
  -> Xray outbound
  -> 下一跳 / 目标地址
```

如果第一版不想写太多代码，也可以先把本仓库定位为：

```text
- Xray 配置模板
- 启停脚本
- 部署文档
- 连通性测试脚本
```

等部署流程稳定后，再封装成守护进程或服务。

## 5. 运行模式

### 5.1 外部 xray 可执行文件模式

中转服务器上可以直接运行固定版本的 `xray` 可执行文件。

优点：

```text
- 最简单。
- 和 Xray 官方运行方式一致。
- 崩溃隔离好。
- 易于 systemd / Docker 管理。
```

中转服务程序只负责：

```text
- 检查 xray 文件是否存在。
- 检查配置是否存在。
- 启动/停止 xray。
- 记录 stdout/stderr。
- 失败时退出或重启。
```

### 5.2 仅配置仓库模式

如果不需要额外服务程序，本仓库可以只维护中转服务器配置和部署脚本。

目录可以是：

```text
configs/
  xray.server.example.json
scripts/
  install.ps1 或 install.sh
  start.ps1 或 start.sh
  stop.ps1 或 stop.sh
README.md
```

这种方式最符合“只是负责转发”的定位。

### 5.3 不建议第一版做 DLL 嵌入

中转服务器通常运行在独立服务器上，没必要为了“无额外进程”把 Xray-core 编成 DLL。

DLL 嵌入适合需要把 Xray 放进某个现有宿主进程的场景。中转服务器本身就是转发节点，直接运行 xray 可执行文件或容器更简单。

## 6. 配置模型

中转服务器自己的配置应尽量薄，只描述 Xray 文件位置、配置文件位置和进程管理策略。

示例：

```yaml
xray:
  executable: "./xray/xray"
  config: "./configs/xray.server.json"
  restartOnExit: true
  restartDelaySeconds: 3

logging:
  level: "info"
  file: "./logs/mid-transport-server.log"

health:
  enabled: true
  listen: "127.0.0.1:18080"
```

真正的协议、端口、加密、认证、转发目标，都放在 Xray 配置里。

## 7. Xray 配置示例方向

具体协议参数以后按实际链路确定，这里只定义方向。

```text
Xray inbound:
  - 监听中转服务器公网端口
  - 使用选定的 Xray 协议
  - 负责认证和协议握手

Xray outbound:
  - 指向下一跳或目标地址
  - 只转发 TCP 字节流
```

示意结构：

```json
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "tag": "public-in",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "按实际协议填写",
      "settings": {}
    }
  ],
  "outbounds": [
    {
      "tag": "next-hop",
      "protocol": "按实际协议填写",
      "settings": {}
    }
  ],
  "routing": {
    "rules": [
      {
        "type": "field",
        "inboundTag": ["public-in"],
        "outboundTag": "next-hop"
      }
    ]
  }
}
```

注意：

```text
- 认证、加密、传输层细节由 Xray 配置决定。
- 中转服务程序不要读取或理解业务 payload。
- 中转服务程序只需要知道 xray 是否启动成功、端口是否监听、配置是否有效。
```

## 8. 服务程序职责

如果要写 `Mid_transport_server` 程序，职责限定为：

```text
1. 读取本地配置。
2. 校验 xray executable 路径。
3. 校验 xray config 路径。
4. 调用 xray test 检查配置。
5. 启动 xray。
6. 监听进程退出。
7. 按配置决定是否重启。
8. 转发或保存 xray 日志。
9. 提供本机 health check。
10. 收到退出信号时停止 xray。
```

不要加入：

```text
- 自定义控制连接。
- 自定义数据连接。
- 连接配对逻辑。
- 自定义认证逻辑。
- 业务层路由逻辑。
```

这些都应该交给 Xray 协议和 Xray routing 完成。

## 9. 最小目录结构

建议第一版：

```text
README.md
MID_TRANSPORT_SERVER_IMPLEMENTATION_PLAN.md
configs/
  mid-transport.example.yaml
  xray.server.example.json
scripts/
  validate-config.ps1
  start.ps1
  stop.ps1
```

如果需要写服务程序，再新增：

```text
cmd/mid-transport-server/
internal/config/
internal/xray/
internal/health/
internal/logging/
```

但第一版可以先不实现复杂代码。

## 10. 启动流程

```text
1. 读取 mid-transport 配置。
2. 检查 xray executable 是否存在。
3. 检查 xray config 是否存在。
4. 执行 xray run -test -config ./configs/xray.server.json。
5. 测试通过后启动 xray。
6. 写入启动日志。
7. health check 返回 running。
```

## 11. 停止流程

```text
1. 收到退出信号。
2. 向 xray 进程发送正常停止信号。
3. 等待 xray 退出。
4. 超时后强制结束。
5. 写入退出日志。
```

## 12. 日志

最小日志即可：

```text
- config_loaded
- xray_config_test_start
- xray_config_test_success
- xray_config_test_failed
- xray_start
- xray_exit
- xray_restart
- xray_stop
- health_check_failed
```

不记录业务 payload，不记录密钥、token、证书内容。

## 13. 健康检查

第一版只需要本机健康检查：

```text
GET /healthz
```

返回：

```json
{
  "running": true,
  "xrayPid": 1234,
  "config": "./configs/xray.server.json"
}
```

健康检查只监听 `127.0.0.1`，不对公网开放。

## 14. 安全要求

```text
1. Xray 协议认证由 Xray 配置负责。
2. 中转服务程序不保存明文密钥到日志。
3. 配置文件权限要限制。
4. health check 默认只监听 127.0.0.1。
5. 公网只开放 Xray inbound 需要的端口。
6. 不实现无鉴权开放 TCP 转发。
7. 不提供公网管理 API。
```

## 15. 验证计划

第一版验证只做转发链路验证：

```text
1. xray 配置语法测试通过。
2. xray 能启动并监听指定端口。
3. 客户端能通过 Xray 协议连到中转服务器。
4. 流量能被转发到配置的下一跳。
5. 停止服务后 xray 进程退出。
6. xray 异常退出时按配置重启或记录失败。
```

不要测试业务协议内容，因为中转服务器不理解业务。

## 16. 分阶段实现

### Phase 1：配置和部署文档

```text
- 提供 xray.server.example.json。
- 提供 mid-transport.example.yaml。
- 写清楚端口、防火墙、证书/密钥文件位置。
- 提供手动启动命令。
```

### Phase 2：启停脚本

```text
- validate-config 脚本。
- start 脚本。
- stop 脚本。
- 日志目录初始化。
```

### Phase 3：轻量服务封装

仅在需要时实现：

```text
- 读取配置。
- 启动 xray。
- 监控退出。
- 本机 health check。
- 优雅停止。
```

### Phase 4：运维增强

```text
- systemd service。
- Dockerfile。
- 日志轮转示例。
- 版本输出。
```

## 17. 最小验收标准

```text
1. 中转服务器能启动固定版本 Xray-core。
2. Xray 配置测试通过后才启动。
3. 公网入口端口由 Xray 监听。
4. Xray 能把流量转发到配置的下一跳。
5. 中转服务本身不解析、不修改 payload。
6. 停止中转服务时 Xray 被正确停止。
7. 本机 health check 能反映 Xray 是否运行。
```

## 18. 总结

中转服务器服务端第一版应该保持很薄：

```text
中转服务程序负责部署、配置、启动、停止和观察 Xray。
Xray 负责协议、认证、加密、连接和转发。
业务 payload 只作为 TCP 字节流经过，不被中转服务理解或修改。
```

这样实现成本最低，也避免重复造一套 Xray 已经解决的问题。
