# 履约中枢日志分析与告警指南

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.0 |
| 适用日志 | app、access、audit、security、error、tests、performance |
| 主要关联键 | request_id、trace_id、audit.resource_id |
| 分析工具 | PowerShell、Python、pytest、Locust CSV |
| 当前基线日期 | 2026-11-12 |

## 1. 分析目标

日志分析需要回答五个问题：

1. 哪个请求失败了，失败发生在什么时间、哪个接口、哪个用户。
2. 失败是参数、权限、业务规则还是系统异常导致的。
3. 同一请求经过了哪些业务动作，是否产生审计记录。
4. 性能是否满足 SLA，慢请求集中在哪个接口。
5. 是否存在登录攻击、权限探测、日志注入或敏感信息泄露风险。

## 2. 数据入口

| 数据源 | 用途 | 关键字段 |
| --- | --- | --- |
| logs/access.jsonl | 请求级统计和延迟分析 | http.request_id、http.path、http.status_code、http.duration_ms |
| logs/app.jsonl | 业务事件、校验失败、慢请求、异常 | event、request_id、error.code、http.duration_ms |
| logs/error.jsonl | 5xx 和服务级故障 | event、exception、request_id |
| logs/audit.jsonl | 业务操作追溯 | audit.action、audit.resource_id、audit.result |
| logs/security.jsonl | 认证和权限事件 | auth.result、auth.username、auth.required_roles |
| logs/tests/test_execution.jsonl | 自动化执行结果 | test.case_id、test.outcome、test.duration_ms |
| reports/test-results.xml | JUnit 结果和用例耗时 | testcase、failure、skipped |
| reports/performance/locust_stats.csv | 接口级性能聚合 | Request Count、Failure Count、Requests/s、95%、99% |
| reports/performance/locust_stats_history.csv | 时间序列性能趋势 | Timestamp、User Count、Requests/s、95% |
| logs/performance/performance_run.jsonl | 压测生命周期和最终聚合 | performance_run_started、performance_run_finished、aggregated |

## 3. 基础检索方法

### 3.1 按 request_id 关联一次请求

PowerShell 示例：

```powershell
$rid = "obs-access-0001"
Get-Content logs\access.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.request_id -eq $rid -or $_.'http.request_id' -eq $rid } |
  Format-List

Get-Content logs\app.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.request_id -eq $rid } |
  Select-Object timestamp, level, event, message, 'error.code', 'http.status_code'
```

审计和安全日志使用同一方法检索 `request_id`。若请求头携带 `X-Trace-ID`，可用 trace_id 关联跨服务日志。

### 3.2 统计 HTTP 状态码

```powershell
Get-Content logs\access.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Group-Object { $_.'http.status_code' } |
  Sort-Object Count -Descending |
  Select-Object Name, Count
```

### 3.3 查找 ERROR 日志

```powershell
Get-Content logs\error.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Select-Object timestamp, event, request_id, message, exception
```

生产排障时优先看 error.jsonl；若为空，再检查 app.jsonl 中 WARNING 级别的业务错误、慢请求和安全拒绝。

## 4. 典型分析场景

### 4.1 接口 5xx 异常定位

1. 在 access.jsonl 找到 `http.status_code >= 500` 的记录，提取 request_id。
2. 在 error.jsonl 检索同一 request_id，确认 `unexpected_application_exception` 或依赖异常。
3. 在 app.jsonl 查看异常之前的业务事件，判断失败发生在校验、事务还是序列化阶段。
4. 在 audit.jsonl 确认业务动作是否已经落库，避免出现接口失败但业务成功的双写问题。
5. 若涉及订单，按 audit.resource_id 还原该订单的创建、状态变更和取消记录。

判定标准：5xx 必须产生 ERROR 日志并携带 request_id；响应体不得包含 Traceback、SQL、文件路径或密钥。

### 4.2 慢请求分析

慢请求事件为 `slow_request_detected`，本地默认阈值为 800ms，性能环境为 1000ms。字段包括 http.path、http.status_code、http.duration_ms 和 slo_threshold_ms。

```powershell
Get-Content logs\app.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.event -eq 'slow_request_detected' } |
  Sort-Object { [double]$_.'http.duration_ms' } -Descending |
  Select-Object -First 20 timestamp, 'http.path', 'http.status_code', 'http.duration_ms', 'slo_threshold_ms', request_id
```

分析时同时查看 Locust 的 P95、P99 和 `locust_stats_history.csv`，区分偶发抖动与持续劣化。若慢请求集中在订单写入，检查 SQLite 写锁、事务时长和并发用户数；若集中在查询，检查索引、分页大小和搜索条件。

### 4.3 RBAC 权限拒绝分析

安全日志事件为 `rbac_access_denied`，审计日志动作为 `rbac.denied`。两者应具有相同 request_id。

关注字段：

- auth.actual_role：实际角色。
- auth.required_roles：接口要求的角色。
- audit.detail：所需角色与实际角色快照。

若同一用户在短时间内大量触发 403，需判断是前端菜单暴露了无权限入口，还是存在越权探测。合法业务拒绝不应升级为系统告警，但持续高频拒绝应触发安全告警。

### 4.4 登录失败与账号枚举分析

失败登录在 security.jsonl 中记录为 `login_failed`，包含 auth.username 和 auth.result=FAILED；访问日志可通过 http.client_ip 补充来源 IP。

建议按用户名和来源 IP 双维度统计：

```powershell
Get-Content logs\security.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.event -eq 'login_failed' } |
  Group-Object { $_.'auth.username' } |
  Sort-Object Count -Descending |
  Select-Object Name, Count
```

错误密码和未知用户均返回相同的 AUTH_INVALID_CREDENTIALS，未知用户也会执行 dummy PBKDF2 校验，降低用户名枚举的响应差异。登录接口当前未内置应用层限流，属于已登记缺陷 BUG-006，生产环境需在网关或 WAF 增加 IP 与账号维度限流。

### 4.5 订单业务链路重建

按 audit.resource_id 检索订单的全部审计动作：

```powershell
$orderId = 128
Get-Content logs\audit.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.'audit.resource_id' -eq $orderId } |
  Sort-Object timestamp |
  Select-Object timestamp, 'audit.action', 'audit.result', 'audit.detail', request_id
```

正常链路示例：`order.created -> order.status_changed -> order.status_changed -> order.cancelled`。取消动作只允许回补一次库存，审计明细中的 restored_items 可用于核对回补范围。

### 4.6 性能结果分析

压测结果由三层数据组成：

1. performance_run.jsonl：记录启动参数、库存准备和最终聚合结果。
2. locust_stats.csv：记录接口级请求数、失败数、RPS、P50、P95、P99。
3. locust_stats_history.csv：记录随时间的吞吐和延迟趋势。

分析步骤：

1. 确认 performance_run_finished 的 exit_code 为 0。
2. 确认 Failure Count 为 0，或所有失败均有明确业务解释。
3. 按接口比较 P95，识别最慢接口。
4. 对照 SLO：读接口 P95 低于 300ms，写接口 P95 低于 800ms，吞吐不低于 50 RPS。
5. 检查 logs/performance/error.jsonl 是否为空。
6. 若失败集中在业务 409，先核对压测数据、库存和幂等键，再判断是否为系统缺陷。

## 5. 告警规则建议

| 告警编号 | 条件 | 级别 | 处理建议 |
| --- | --- | --- | --- |
| ALERT-001 | 5xx 比例连续 5 分钟超过 1% | P1 | 查看 error.jsonl 和最近发布版本，必要时回滚 |
| ALERT-002 | 读接口 P95 连续 5 分钟超过 300ms | P2 | 检查慢请求、数据库锁和连接池 |
| ALERT-003 | 写接口 P95 连续 5 分钟超过 800ms | P2 | 检查事务、SQLite 写锁和磁盘 IO |
| ALERT-004 | 单 IP 每分钟登录失败超过 20 次 | P2 | 触发限流或封禁，核查账号枚举 |
| ALERT-005 | 单用户每分钟 RBAC 拒绝超过 50 次 | P2 | 核查越权探测和前端权限配置 |
| ALERT-006 | error.jsonl 5 分钟内出现任意 ERROR | P1 | 立即查看 request_id、异常堆栈和影响范围 |
| ALERT-007 | 2 分钟内无任何 access 日志但健康检查失败 | P1 | 检查进程、端口、反向代理和数据库 |
| ALERT-008 | 日志中出现明文 password、token、secret 或 api_key | P1 | 立即停止写入、修复脱敏并评估泄露范围 |
| ALERT-009 | 审计日志写入失败或订单动作缺少审计记录 | P1 | 检查磁盘、权限和审计链路，暂停相关写操作 |
| ALERT-010 | 日志目录使用率超过 80% | P3 | 扩容或清理归档，确认轮转正常 |

## 6. 分级与处置

| 级别 | 判定 | 响应时限 | 处置 |
| --- | --- | --- | --- |
| P0 | 核心交易不可用、数据损坏、敏感信息大规模泄露 | 立即 | 启动应急，隔离影响，保留现场日志 |
| P1 | 主要接口 5xx、订单/库存一致性异常、审计缺失 | 15 分钟内 | 定位 request_id，回滚或降级，通知负责人 |
| P2 | 性能劣化、频繁权限拒绝、登录攻击迹象 | 1 小时内 | 调整限流、索引或权限配置，持续观察 |
| P3 | 单次慢请求、低频校验失败、日志目录告警 | 1 个工作日内 | 记录并纳入迭代 |

## 7. 当前基线分析

2026-11-12 的最终接口与性能基线如下：

| 指标 | 结果 | 结论 |
| --- | --- | --- |
| 接口自动化 | 60/60 通过 | 功能、边界、权限、安全和可观测性全部通过 |
| 性能请求数 | 3222 | 混合读写、登录、幂等和状态流转 |
| 性能失败数 | 0 | 错误率 0% |
| 吞吐量 | 82.11 RPS | 高于 50 RPS 目标 |
| 中位延迟 | 12ms | 响应稳定 |
| P95 | 60ms | 低于读 300ms、写 800ms 目标 |
| P99 | 81ms | 长尾可控 |
| 最大延迟 | 178.57ms | 未出现秒级阻塞 |
| 性能错误日志 | 0 字节 | 压测窗口内无 ERROR |
| 性能访问日志 | 6437 条 | 可用于请求级追踪 |
| 性能审计日志 | 3705 条 | 订单动作可追溯 |
| 性能安全日志 | 117 条 | 包含预期失败登录与安全事件 |

接口级重点结果：商品列表 478 次、P95 37ms；订单创建 838 次、P95 50ms；订单取消 553 次、P95 41ms；状态流转 384 次、P95 39ms；登录成功 169 次、P95 100ms；登录失败 60 次、P95 78ms。登录接口因 PBKDF2 计算成本高于普通查询，延迟明显高于其他接口，但仍在 SLO 内，且未知用户与错误密码执行等价校验，安全性与性能取得平衡。

## 8. 排障记录模板

| 字段 | 内容 |
| --- | --- |
| 告警编号 | ALERT-XXX |
| 发生时间 | UTC 时间 |
| 影响接口 | method + path |
| request_id | 关联 ID |
| 影响用户 | username、role、client_ip |
| 现象 | 状态码、错误码、耗时 |
| 日志证据 | access、app、error、audit、security 关键行 |
| 根因 | 代码、配置、数据或环境原因 |
| 临时措施 | 回滚、限流、降级、重启 |
| 永久修复 | 代码变更、测试补充、监控调整 |
| 验证结果 | 回归用例和性能复测结果 |
| 负责人 | 开发、测试、运维或安全 |
