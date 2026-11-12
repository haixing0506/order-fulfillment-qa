# 履约中枢 - 接口自动化与性能测试项目

面向订单履约业务的接口测试作品集。项目提供一套可运行的 FastAPI + SQLite 演示系统，并围绕它完成需求分析、测试设计、接口自动化、性能压测、缺陷管理、风险跟踪、质量门禁和企业级日志验证。

项目只做接口自动化，不包含 UI 自动化。页面仅作为人工演示入口，所有质量结论均来自 pytest、Locust 和结构化日志的真实执行结果。

## 技术栈

| 层次 | 选型 |
| --- | --- |
| 被测服务 | FastAPI、SQLite、JWT、RBAC |
| 接口自动化 | pytest、httpx、pytest-cov、pytest-html |
| 性能测试 | Locust |
| 日志体系 | JSON Lines、request_id 关联、脱敏、审计、10MB x 10 轮转 |
| 开发工具 | PyCharm、Python 3.11+ |
| 质量报告 | 自研脚本生成 JSON 汇总、HTML 看板与 Excel 工作簿 |

## 快速开始

### 1. 在 PyCharm 中打开

直接用 PyCharm 打开项目根目录 `F:\项目文件\项目一`。项目已提供共享运行配置和模块文件，首次打开只需配置解释器：

1. 打开 `Settings -> Project -> Python Interpreter`。
2. 选择已有 Python 3.11+ 环境，或新建 `.venv` 虚拟环境。
3. 在 PyCharm 终端执行 `python -m pip install -r requirements.txt`。
4. 等待索引完成后，右上角运行配置下拉框会出现本项目的 5 个配置。

### 2. 共享运行配置

| 运行配置 | 作用 |
| --- | --- |
| 启动履约平台 (127.0.0.1:8000) | 启动被测系统 |
| 接口自动化 - 全量回归 | 执行全部接口测试并生成 JUnit |
| 接口自动化 - 覆盖率与 HTML 报告 | 执行测试并生成覆盖率、HTML 报告 |
| 性能测试 - Locust 基线 | 启动独立性能环境并执行 30 并发压测 |
| 质量报告 - 生成汇总与看板 | 汇总测试、覆盖率、性能、缺陷、风险与日志 |

### 3. 命令行方式

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python scripts\run_app.py
python -m pytest
python scripts\run_performance.py
python scripts\generate_quality_report.py
```

被测系统默认地址为 `http://127.0.0.1:8000`。端口占用时可通过环境变量 `OMS_PORT` 或 `python scripts\run_app.py --port 8001` 调整。

## 演示入口

启动服务后访问：

| 入口 | 地址 |
| --- | --- |
| 登录页 | `http://127.0.0.1:8000/login` |
| 业务看板 | `http://127.0.0.1:8000/` |
| Swagger 接口文档 | `http://127.0.0.1:8000/api/docs` |
| 质量看板 | `http://127.0.0.1:8000/reports/quality_dashboard.html` |
| 接口测试 HTML 报告 | `http://127.0.0.1:8000/reports/test-report.html` |
| 覆盖率报告 | `http://127.0.0.1:8000/reports/coverage/index.html` |
| Locust 性能报告 | `http://127.0.0.1:8000/reports/performance/locust-report.html` |
| Excel 质量报告 | `http://127.0.0.1:8000/reports/企业级质量保障报告.xlsx` |

内置账号：

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `Admin@123` | 管理员 |
| `operator` | `Operator@123` | 运营 |
| `viewer` | `Viewer@123` | 只读 |

## 质量结果

以下数据来自本仓库最近一次真实执行，重新运行后会由 `scripts/generate_quality_report.py` 自动刷新。

| 指标 | 结果 |
| --- | --- |
| 接口自动化用例 | 60/60 通过，通过率 100% |
| 代码综合覆盖率 | 95.3%（含分支） |
| 性能场景 | 30 并发、5 用户/秒、持续 40 秒 |
| 请求总量 | 3222 |
| 请求失败 | 0，错误率 0.00% |
| 吞吐量 | 82.1 RPS |
| 响应时间 | P95 60ms、P99 81ms、最大 178.57ms |
| 性能 ERROR 日志 | 0 字节 |
| 需求追踪 | 20/20 需求项已关联执行 |
| 缺陷 | 7 项，已关闭 5 项，已接受 1 项，待处理 1 项 |
| 风险 | 10 项，已缓解 9 项，监控中 1 项 |

性能数据来自单机 SQLite 演示环境，用于展示压测方法和基线分析，不等同于生产容量结论。

## 测试流程

项目按完整测试流程组织证据链：

1. 需求分析：拆解认证、商品、订单、权限、系统与可观测性需求。
2. 测试计划：明确范围、环境、进度、角色、进入退出准则和交付物。
3. 测试设计：使用等价类、边界值、决策表、状态迁移和错误猜测设计用例。
4. 自动化实现：用 pytest 夹具隔离数据库，通过用例编号绑定自动化脚本。
5. 测试执行：生成 JUnit、HTML、覆盖率和结构化执行日志。
6. 缺陷管理：记录复现、定级、根因、修复、验证和关闭全过程。
7. 性能测试：用 Locust 执行混合读写负载，输出统计 CSV 与 HTML 报告。
8. 质量评估：由质量门禁汇总通过率、覆盖率、P95、错误率、缺陷和追踪率。

## 测试资产

| 资产 | 路径 | 说明 |
| --- | --- | --- |
| 测试计划 | `test_design/test_plan.md` | 范围、目标、环境、里程碑与退出准则 |
| 测试策略 | `test_design/test_strategy.md` | 分层策略、设计方法、性能模型与质量门禁 |
| 测试用例 | `test_design/test_cases.csv` | 66 项：60 项接口自动化 + 6 项性能场景 |
| 需求追踪矩阵 | `test_design/traceability_matrix.csv` | 20 个需求项与用例、脚本、缺陷、风险关联 |
| 风险登记册 | `test_design/risk_register.csv` | 10 项风险及缓解措施 |
| 缺陷台账 | `defect_management/defect_register.csv` | 7 项缺陷及完整生命周期字段 |
| 缺陷流程 | `defect_management/defect_lifecycle.md` | 缺陷分级、流转与回归规则 |
| 日志规范 | `docs/logging_standard.md` | 字段字典、级别、脱敏、轮转与审计要求 |
| 日志分析 | `docs/log_analysis.md` | 关联检索、典型场景、告警规则与排障模板 |
| 质量汇总 | `reports/quality_summary.json` | 机器可读的质量门禁结果 |
| 质量看板 | `reports/quality_dashboard.html` | 可浏览的质量报告 |
| 企业级质量保障报告 | `reports/企业级质量保障报告.xlsx` | 10 个工作表，汇总用例、执行、覆盖率、缺陷、风险、性能、日志、追踪与数据来源 |

## 接口自动化范围

`tests/api` 覆盖以下风险面：

- 认证：登录成功与失败、令牌过期、签名篡改、声明校验、用户枚举防护。
- 商品：目录查询、中文搜索、分类筛选、分页、创建、库存更新、重复 SKU。
- 订单：服务端计价、库存扣减、状态机、取消回补、幂等重放、并发防超卖。
- 权限：匿名访问、角色隔离、越权请求体提权、viewer 数据范围。
- 边界与契约：数量、备注长度、库存、价格、分页边界、统一响应结构。
- 安全：安全响应头、request_id 替换、未知字段拒绝、畸形 JSON、SQL 元字符。
- 可观测性：访问日志关联、审计日志、敏感字段脱敏、错误日志级别。

测试数据采用每个用例独立临时数据库，避免执行顺序依赖。并发用例使用独立商品和线程屏障验证库存一致性。

## 企业级日志

运行日志位于 `logs/`，按职责拆分：

| 文件 | 内容 |
| --- | --- |
| `logs/access.jsonl` | HTTP 方法、路径、状态码、耗时、request_id |
| `logs/app.jsonl` | 应用生命周期、业务事件、异常 |
| `logs/audit.jsonl` | 登录、订单创建、状态变更、库存调整等审计事件 |
| `logs/security.jsonl` | 登录失败、认证失败、RBAC 拒绝 |
| `logs/error.jsonl` | ERROR 及以上级别日志 |
| `logs/tests/test_execution.jsonl` | pytest 用例编号、结果、耗时 |
| `logs/performance/` | 压测期间的独立日志与编排记录 |

日志统一使用 UTC 时间和 JSON Lines，包含 `timestamp`、`level`、`logger`、`event`、`service.name`、`request_id` 等基线字段，并对密码、令牌、密钥和敏感查询参数脱敏。单文件按 10MB 轮转，保留 10 个历史文件。

## 缺陷与风险

当前遗留事项：

- `BUG-006`：登录接口未内置应用层限流与账户锁定，状态为待处理，建议在网关或 WAF 增加 IP + 账号维度限流，并补充审计告警。
- `BUG-007`：viewer 可查看全量订单，产品确认后台审核场景需要该能力，状态为已接受。
- `RISK-006`：SQLite 在高并发下可能出现写锁等待，当前保持监控，后续生产化建议迁移到 PostgreSQL 并复测。

## 目录结构

```text
.
├── app/                     # 被测 FastAPI 服务
│   ├── api/                 # 认证、商品、订单、看板、健康检查
│   ├── observability/       # 日志、审计、request_id 中间件
│   └── services/            # 订单与商品领域逻辑
├── tests/api/               # 60 项接口自动化用例
├── test_design/             # 计划、策略、用例、追踪矩阵、风险
├── defect_management/       # 缺陷台账与生命周期
├── docs/                    # 日志规范与分析指南
├── scripts/                 # 启动、压测、质量报告脚本
├── reports/                 # JUnit、HTML、覆盖率、性能、质量看板
├── logs/                    # 企业级 JSONL 日志
└── .idea/runConfigurations/ # PyCharm 共享运行配置
```

## 说明

- 不包含 UI 自动化、浏览器驱动或截图用例。
- 演示数据由启动时的种子逻辑生成，接口测试使用隔离数据库，不会污染演示库。
- 若质量看板显示旧数据，依次运行“接口自动化 - 覆盖率与 HTML 报告”“性能测试 - Locust 基线”“质量报告 - 生成汇总与看板”即可刷新。
