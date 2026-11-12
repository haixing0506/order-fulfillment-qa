# 履约中枢企业级日志规范

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.0 |
| 适用系统 | order-fulfillment 1.0.0 |
| 适用环境 | local、test、performance、production |
| 日志格式 | JSON Lines（UTF-8） |
| 时间标准 | UTC ISO 8601，毫秒精度 |
| 关联字段 | request_id、trace_id、user_id、username、role |
| 实现位置 | app/observability/logging.py、context.py、middleware.py、audit.py |

## 1. 目标与原则

日志必须同时满足排障、审计、安全和质量度量四类用途。所有服务日志遵循以下原则：

1. 结构化：一行一个 JSON 对象，禁止输出多行拼接文本，便于采集、检索和聚合。
2. 可关联：HTTP 请求、业务动作、安全事件和测试执行都携带 request_id；跨服务调用可透传 trace_id。
3. 最小敏感：密码、令牌、密钥、卡号等字段不得进入日志；查询参数和自由文本在写入前统一脱敏。
4. 职责分离：应用、访问、审计、安全和错误日志独立落盘，避免审计信息被普通调试日志淹没。
5. 稳定契约：字段名、事件名和错误码一经发布保持兼容；新增字段不得改变既有含义。
6. 可验证：日志格式、关联性、脱敏和轮转由自动化用例持续验证。
7. 时间统一：日志时间统一使用 UTC，前端展示时再转换为本地时区，避免跨时区排障歧义。

## 2. 日志文件与职责

| 文件 | 记录器 | 级别 | 职责 | 轮转策略 |
| --- | --- | --- | --- | --- |
| logs/app.jsonl | root | INFO 及以上 | 应用生命周期、业务事件、校验失败、慢请求和未处理异常 | 10MB × 10 |
| logs/error.jsonl | root | ERROR 及以上 | 未处理异常和系统级错误，供告警与快速检索 | 10MB × 10 |
| logs/access.jsonl | app.access | INFO 及以上 | 每个 HTTP 请求的访问记录 | 10MB × 10 |
| logs/audit.jsonl | app.audit | INFO 及以上 | 登录、订单创建、状态变更、取消和 RBAC 拒绝 | 10MB × 10 |
| logs/security.jsonl | app.security | INFO 及以上 | 认证缺失、令牌非法、登录失败和权限拒绝 | 10MB × 10 |
| logs/tests/test_execution.jsonl | qa.test_runner | INFO 及以上 | pytest 会话、用例结果、耗时和失败摘要 | 10MB × 5 |
| logs/performance/app.jsonl | root | INFO 及以上 | 独立性能环境的服务和业务日志 | 10MB × 10 |
| logs/performance/access.jsonl | app.access | INFO 及以上 | 独立性能环境的访问日志 | 10MB × 10 |
| logs/performance/audit.jsonl | app.audit | INFO 及以上 | 性能环境业务审计日志 | 10MB × 10 |
| logs/performance/security.jsonl | app.security | INFO 及以上 | 性能环境安全日志 | 10MB × 10 |
| logs/performance/error.jsonl | root | ERROR 及以上 | 性能环境错误日志 | 10MB × 10 |
| logs/performance/performance_run.jsonl | 压测编排器 | INFO 及以上 | 压测启动、库存准备、结束和聚合结果 | 按次追加 |

性能测试使用独立数据库 `data/perf.db` 和独立日志目录 `logs/performance`，避免压测数据污染功能测试与演示数据。

## 3. 格式规范

### 3.1 JSON Lines

- 文件编码为 UTF-8，换行符为 LF。
- 每行必须是完整、可独立解析的 JSON 对象。
- 禁止在 message、异常堆栈或用户输入中直接拼接原始换行；异常堆栈放在 `exception` 字段中。
- 字符串统一使用双引号；布尔值使用 true/false；空值使用 null。
- 数字字段保持数值类型，不以字符串代替，例如 `http.duration_ms`、`http.status_code`。

### 3.2 时间与命名

- `timestamp` 格式为 `YYYY-MM-DDTHH:MM:SS.sss+00:00`，统一 UTC。
- `event` 使用小写 snake_case，例如 `order_created`、`login_failed`。
- 扩展字段使用点分命名，例如 `http.status_code`、`audit.resource_id`、`test.case_id`。
- 字段名一旦投入使用，不随意重命名；废弃字段先标记再按版本下线。

### 3.3 标准基线

| 字段 | 类型 | 必填 | 说明 | 示例 |
| --- | --- | --- | --- | --- |
| timestamp | string | 是 | UTC 时间，毫秒精度 | 2026-11-12T03:49:40.973+00:00 |
| level | string | 是 | DEBUG、INFO、WARNING、ERROR、CRITICAL | INFO |
| logger | string | 是 | 记录器名称 | app.orders |
| service | string | 是 | 服务名 | order-fulfillment |
| environment | string | 是 | 环境标识 | test |
| version | string | 是 | 服务或工具版本 | 1.0.0 |
| host | string | 是 | 主机名 | pengdaxuan |
| pid | number | 是 | 进程 ID | 30112 |
| thread | string | 是 | 线程名 | MainThread |
| message | string | 是 | 稳定事件描述，已完成脱敏 | order_created |
| event | string | 推荐 | 机器可读事件名 | order_created |
| request_id | string | 请求内必填 | 单次请求关联 ID | obs-access-0001 |
| trace_id | string | 请求内必填 | 跨服务链路 ID，默认等于 request_id | obs-access-0001 |
| user_id | number/null | 认证后必填 | 当前用户 ID | 2 |
| username | string | 认证后必填 | 当前用户名 | operator |
| role | string | 认证后必填 | 当前角色 | operator |

未发生认证或脱离请求上下文时，`request_id`、`trace_id`、`username`、`role` 使用 `-`，`user_id` 使用 null。

## 4. 领域字段字典

### 4.1 HTTP 访问字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| http.method | string | HTTP 方法 |
| http.path | string | 请求路径，不包含查询字符串 |
| http.query | string | 脱敏并截断到 500 字符的查询字符串 |
| http.status_code | number | 响应状态码 |
| http.duration_ms | number | 服务端处理耗时，毫秒 |
| http.client_ip | string | 客户端 IP |
| http.user_agent | string | User-Agent，缺失时为 `-` |
| http.request_id | string | 访问日志中的请求关联 ID |
| slo_threshold_ms | number | 慢请求判定阈值 |

### 4.2 业务审计字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| audit.action | string | 业务动作，例如 order.created、order.status_changed、order.cancelled、auth.login、rbac.denied |
| audit.result | string | SUCCESS、FAILED、DENIED |
| audit.resource_type | string | 资源类型，例如 order、session、endpoint |
| audit.resource_id | string/number | 资源 ID |
| audit.detail | object | 审计明细，只允许非敏感业务字段 |

### 4.3 安全字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| auth.result | string | MISSING、INVALID、INACTIVE、FAILED、DENIED |
| auth.username | string | 登录尝试使用的用户名 |
| auth.required_roles | array | 接口要求的角色集合 |
| auth.actual_role | string | 当前用户实际角色 |

### 4.4 测试执行字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| test.nodeid | string | pytest 节点 ID |
| test.case_id | string | 用例编号，例如 TC-ORD-001 |
| test.outcome | string | PASSED、FAILED、SKIPPED |
| test.duration_ms | number | 用例耗时，毫秒 |
| test.module | string | 测试模块路径 |
| test.failure | string | 失败摘要，最长保留 2500 字符 |
| test.collected | number | 会话收集用例数 |
| test.exit_status | number | pytest 退出码 |
| test.elapsed_seconds | number | 会话总耗时 |

### 4.5 性能编排字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| performance_run_started | event | 压测开始 |
| performance_run_finished | event | 压测结束 |
| base_url | string | 被测服务地址 |
| users | number | 并发用户数 |
| spawn_rate | number | 每秒启动用户数 |
| duration | string | 压测持续时间 |
| server_pid | number | 被测服务进程 ID |
| elapsed_seconds | number | 实际执行耗时 |
| aggregated | object | Locust 聚合统计，包括请求数、失败数、RPS、P95 和 P99 |

## 5. 日志级别

| 级别 | 使用场景 | 示例 |
| --- | --- | --- |
| DEBUG | 本地诊断信息，生产默认关闭 | 缓存命中、内部状态快照 |
| INFO | 正常业务和生命周期事件 | application_started、order_created、http_request |
| WARNING | 可恢复异常、安全拒绝、慢请求 | login_failed、rbac_access_denied、slow_request_detected |
| ERROR | 未处理异常、依赖不可用、数据一致性风险 | unexpected_application_exception |
| CRITICAL | 服务不可用或需要立即人工介入 | 数据库损坏、关键安全事件 |

业务校验失败（例如 422、409）通常记录 INFO 或 WARNING，不记录 ERROR；ERROR 仅用于系统级故障，避免告警噪声。

## 6. 脱敏规范

### 6.1 脱敏对象

以下键名不区分大小写，命中后值统一替换为 `***`：

- password、passwd、pwd
- token、authorization
- secret、api_key、api-key
- card_no、card-no

自由文本中的 `password=...`、`token=...`、`secret=...`、`api_key=...` 等形式同样替换为 `***`。嵌套字典、列表和异常文本均递归处理。

### 6.2 访问日志限制

- 查询字符串只记录脱敏后的内容，最大 500 字符。
- 不记录完整请求体、响应体和 Authorization 请求头。
- 用户名可以记录，密码和令牌永不允许记录。
- 请求 ID 仅接受 1 至 64 位字母、数字、点、横线或下划线；非法值由服务生成 32 位十六进制 ID。

### 6.3 审计与安全边界

- 审计日志记录“谁在什么时间对什么资源做了什么操作以及结果”，不记录密码、令牌和完整请求体。
- 登录失败记录用户名、结果和 request_id，用于攻击检测；不记录尝试的密码。
- RBAC 拒绝记录所需角色与实际角色，便于权限问题定位。

## 7. 关联与上下文

请求进入 `RequestContextMiddleware` 后生成或校验 request_id，并在 contextvars 中绑定 trace_id。认证成功后绑定 user_id、username、role。后续应用日志、访问日志、审计日志和安全日志自动继承这些字段。

推荐排障顺序：

1. 从响应头或响应体的 request_id 定位请求。
2. 在 access.jsonl 查看 method、path、status、duration。
3. 在 app.jsonl 查看同 request_id 的业务事件和异常。
4. 在 audit.jsonl 还原业务动作。
5. 在 security.jsonl 判断是否存在认证或权限问题。
6. 若响应为 5xx，再到 error.jsonl 检索异常堆栈。

## 8. 保留、归档与治理

- 本地环境保留 10 个轮转文件，单文件 10MB；测试执行日志保留 5 个轮转文件。
- 生产环境建议在线保留 30 天，归档保留 180 天；审计日志按合规要求单独延长。
- 归档文件必须保持 JSONL 格式和原始 request_id，不得二次拼接。
- 新增事件或字段需要同步更新本规范、字段字典和日志自动化用例。
- 日志字段变更遵循向后兼容原则；破坏性变更需要提升日志 schema 版本。
- 日志中不得写入个人信息以外的业务机密；确需记录时使用脱敏值或哈希值。

## 9. 示例

访问日志：

```json
{"timestamp":"2026-11-12T03:49:12.104+00:00","level":"INFO","logger":"app.access","service":"order-fulfillment","environment":"performance","version":"1.0.0","host":"pengdaxuan","pid":30112,"thread":"MainThread","message":"http_request","request_id":"obs-access-0001","trace_id":"obs-access-0001","user_id":2,"username":"operator","role":"operator","event":"http_request","http.method":"GET","http.path":"/api/v1/products","http.query":"token=***","http.status_code":200,"http.duration_ms":8.42,"http.client_ip":"127.0.0.1","http.user_agent":"python-httpx/0.28.1","http.request_id":"obs-access-0001"}
```

审计日志：

```json
{"timestamp":"2026-11-12T03:49:13.221+00:00","level":"INFO","logger":"app.audit","service":"order-fulfillment","environment":"performance","version":"1.0.0","host":"pengdaxuan","pid":30112,"thread":"MainThread","message":"business_audit","request_id":"a1b2c3d4","trace_id":"a1b2c3d4","user_id":2,"username":"operator","role":"operator","event":"business_audit","audit.action":"order.created","audit.result":"SUCCESS","audit.resource_type":"order","audit.resource_id":128,"audit.detail":{"order_no":"ORD-20261112-ABC123","items":1,"total":699.0}}
```

安全日志：

```json
{"timestamp":"2026-11-12T03:49:14.882+00:00","level":"WARNING","logger":"app.security","service":"order-fulfillment","environment":"performance","version":"1.0.0","host":"pengdaxuan","pid":30112,"thread":"MainThread","message":"login_failed","request_id":"e5f6a7b8","trace_id":"e5f6a7b8","user_id":null,"username":"-","role":"-","event":"login_failed","auth.result":"FAILED","auth.username":"performance-probe"}
```

测试执行日志：

```json
{"timestamp":"2026-11-12T02:40:53.107+00:00","level":"INFO","logger":"qa.test_runner","service":"qa-test-runner","environment":"test","version":"1.0.0","host":"pengdaxuan","pid":2888,"thread":"MainThread","message":"test_finished","request_id":"-","trace_id":"-","user_id":null,"username":"-","role":"-","event":"test_finished","test.nodeid":"tests/api/test_auth.py::test_admin_login_returns_token_and_profile","test.case_id":"TC-AUTH-001","test.outcome":"PASSED","test.duration_ms":51.73,"test.module":"tests/api/test_auth.py"}
```

## 10. 落地检查清单

- 新增日志事件已登记 event 名称和字段。
- 日志为单行 JSON，UTF-8 编码。
- timestamp 为 UTC 毫秒格式。
- 请求内日志均带 request_id 和 trace_id。
- 认证后日志均带 user_id、username、role。
- 敏感键和敏感文本已脱敏。
- 未记录请求体、响应体、完整 Authorization 头。
- 错误日志只用于系统级故障。
- 审计动作包含操作者、资源、结果和 request_id。
- 轮转、保留和归档策略已确认。
- 对应自动化用例通过。
