# 履约中枢测试策略

## 1. 策略目标

测试策略围绕“业务正确、权限可控、数据一致、性能可度量、问题可追踪”五个质量属性展开。测试设计优先覆盖高风险路径，再用自动化把回归成本降到可接受水平。

## 2. 测试分层

| 层级 | 关注点 | 实施方式 |
| --- | --- | --- |
| 契约层 | 请求字段、响应结构、错误码、状态码 | pytest + TestClient |
| 业务层 | 金额计算、库存扣减、状态机、取消回补 | 接口自动化 + 数据库断言 |
| 安全层 | 认证、RBAC、注入、参数白名单、日志脱敏 | 攻击用例 + 响应与日志断言 |
| 并发层 | 防超卖、事务隔离、幂等竞争 | ThreadPoolExecutor + 独立数据库 |
| 性能层 | 吞吐、延迟、错误率、稳定性 | Locust 混合负载 |
| 观测层 | 请求链路、审计、安全、测试执行日志 | JSONL 解析与关联断言 |

## 3. 测试设计方法

### 3.1 等价类划分

- 订单数量：合法区间 1 至 99；小于 1 和大于 99 为非法。
- 商品库存：合法区间 0 至 1,000,000；负数或超过上限为非法。
- 订单状态：合法状态为 CREATED、PICKING、SHIPPED、COMPLETED、CANCELLED；变更接口只接受 PICKING、SHIPPED、COMPLETED。
- 用户角色：admin、operator、viewer。

### 3.2 边界值分析

- 订单数量 1、99、100。
- 备注长度 0、200、201。
- 分页 page=1、page=0；page_size=1、100、101。
- 库存 0、20、1,000,000、1,000,001。
- 商品价格 0、1、100,000,000。

### 3.3 决策表

订单取消决策：

| 当前状态 | 操作者角色 | 预期结果 |
| --- | --- | --- |
| CREATED | admin/operator | 允许取消并回补库存 |
| PICKING | admin/operator | 允许取消并回补库存 |
| SHIPPED | admin/operator | 拒绝，返回 ORDER_CANNOT_CANCEL |
| COMPLETED | admin/operator | 拒绝 |
| CANCELLED | admin/operator | 幂等返回已取消订单，不重复回补 |
| 任意 | viewer | 拒绝，返回 RBAC_FORBIDDEN |

### 3.4 状态迁移

合法链路：

`CREATED -> PICKING -> SHIPPED -> COMPLETED`

取消分支：

`CREATED/PICKING -> CANCELLED`

非法迁移包括跳过中间状态、从终态继续流转、从 SHIPPED 取消。

### 3.5 错误猜测与安全探测

- 篡改 JWT 签名、使用过期令牌、缺少 Bearer 令牌。
- 在请求体注入 `role`、`price` 等未声明字段，验证参数白名单。
- 搜索参数注入 SQL 元字符，验证参数化查询。
- 在 URL 查询参数和日志字段中放入 token、password，验证脱敏。
- 伪造超长或含特殊字符的 X-Request-ID，验证日志注入防护。

## 4. 自动化架构

| 组件 | 设计 |
| --- | --- |
| 测试框架 | pytest |
| HTTP 驱动 | FastAPI TestClient，覆盖同步接口 |
| 数据隔离 | 每个用例使用临时 SQLite 数据库，启动时自动建表和种子 |
| 认证夹具 | admin_headers、operator_headers、viewer_headers |
| 用例编号 | `@pytest.mark.case("TC-XXX-000")` 与测试管理台账一一对应 |
| 结果输出 | JUnit XML、pytest-html、coverage JSON/HTML |
| 执行日志 | `pytest_runtest_logreport` 写入 `logs/tests/test_execution.jsonl` |
| 断言风格 | 状态码 + 错误码 + 响应结构 + 数据库/接口二次查询 |

## 5. 测试数据策略

- 种子数据固定，保证演示和报告可复现。
- 功能用例使用临时数据库，避免用例顺序依赖。
- 并发用例创建独立商品，避免与其他用例共享库存。
- 性能用例使用独立 `perf.db`，执行前重建并将关键商品库存提升到 1,000,000。
- 性能脚本使用 UUID 幂等键；幂等重放场景固定商品和备注，确保请求内容一致。

## 6. 性能模型

### 6.1 负载组成

| 用户类型 | 权重 | 主要行为 |
| --- | --- | --- |
| 读用户 | 5 | 商品列表、详情、工作台、订单队列、健康检查 |
| 写用户 | 3 | 下单并取消、幂等重放、状态流转 |
| 认证用户 | 1 | 登录成功、登录失败 |

### 6.2 执行参数

- 并发用户：30
- 加压速率：5 用户/秒
- 持续时间：40 秒
- 目标主机：本机 127.0.0.1 隔离端口
- 数据库：独立 `data/perf.db`
- 日志目录：`logs/performance`

### 6.3 SLA

- 整体错误率低于 1%。
- 读接口 P95 低于 300ms。
- 写接口 P95 低于 800ms。
- 登录接口 P95 低于 500ms。
- 吞吐量不低于 50 RPS。

## 7. 可观测性验证

- 每个响应必须携带 `X-Request-ID`、`X-Trace-ID`、`X-Process-Time-Ms`。
- 访问日志必须包含方法、路径、状态码、耗时、客户端 IP、请求 ID。
- 业务审计日志必须记录订单创建、状态变更、取消、商品创建和库存更新。
- 安全日志必须记录登录失败、缺少令牌、令牌无效、RBAC 拒绝。
- 测试执行日志必须记录用例编号、结果、耗时、模块和失败摘要。
- 日志中的 password、token、authorization、secret、api_key 必须脱敏。

## 8. 质量门禁

质量门禁由 `scripts/generate_quality_report.py` 自动计算，并展示在质量看板中。任一 P0/P1 门禁失败时，版本不得进入验收。
