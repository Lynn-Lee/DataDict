# DataDict 元数据知识库 —— 开发任务书

> **依据**：[DataDict-PRD.md](DataDict-PRD.md) v1.2（已评审确认）
> **服务代号**：`datadict` · **仓库**：`datadict`
> **文档用途**：任务分解、工时估算、依赖关系、验收标准、质量门禁

---

## 0. 阅读须知

### 0.1 团队与工时口径

本任务书的工时以**人日**为单位，假设：

| 角色 | 人数 | 说明 |
|---|---|---|
| 后端 | 待定（见 §0.2） | Python/FastAPI/PostgreSQL |
| 前端 | 1 | React/TypeScript/AntD |
| 测试 | 0.5 | 兼职，负责验收与 CI 门禁 |
| DBA 支持 | 协作 | 只读账号、权限申请、从库配置 |

估算含**编码 + 自测 + 单元测试**，不含需求澄清、跨团队协调、生产环境问题排查。

### 0.2 ★ 工时估算与 PRD 排期存在差距，需先决策

按 §2 的任务分解，**V0.1 后端约 58 人日、前端约 15 人日**。

PRD §8 定的 V0.1 周期是 **3~4 周**（15~20 工作日）。要在 4 周内完成后端 58 人日，
需要 **3 名后端**。若只有 2 名后端，实际需要 **6 周**。

三个选项：

| 选项 | 说明 | 代价 |
|---|---|---|
| A. 加到 3 后端，保持 4 周 | 按 PRD 原排期走 | 需要协调人力 |
| **✅ B. 2 后端，V0.1 延到 6 周（已采纳）** | 范围不变，如实调整排期 | 整体交付后移 2 周 |
| C. 2 后端 + 砍范围到 4 周 | 见下方削减清单 | V0.5 负担加重 |

> **已决策：采用选项 B。** V0.1 周期由 3~4 周调整为 **6 周**，范围不变，
> §0.2 的削减清单不启用（仅在 §9 风险触发时作为应急预案）。
> 后续 V0.5 / V1.0 的起始时间相应顺延，整体交付后移 2 周。

**选项 C 的可削减项**（合计约 9 人日，仍不足 18 人日缺口，故 C 需与 B 结合成 5 周）：

| 可削减 | 人日 | 影响 |
|---|---|---|
| T2.3 PostgreSQL 采集器推迟到 V0.5 | 2 | V0.1 只接 MySQL。PRD 验收要求「2 个核心生产库」，两个都是 MySQL 也满足 |
| T5.2 表内批量标注推迟到 V0.5 | 1.5 | V0.1 只有单字段标注，够验证「标注不丢失」这条生命线 |
| T3.4 `sync_fail_detail` 明细表推迟 | 1.5 | **但注释非空率告警必须保留**，那是 A3 的兜底 |
| T4.3 表检索与结果分组简化 | 1.5 | V0.1 只出字段搜索结果 |
| T6.2 基础接口由 5 个减为 3 个 | 1 | 保留表详情、字段详情、搜索 |
| T7.6 四态 UI 简化为空态+错误态 | 1.5 | 前端项，不缓解后端瓶颈 |

**不可削减项**（削减代价远大于收益，理由见括号）：

- T3.2 变更 diff 与落库（流水数据错过不可补）
- T8.1/T8.3 双 DB role 与权限测试（后补需改动全部数据访问层）
- T4.2 检索阈值实测调优（不调直接上线等于主功能失效）
- T2.4 注释断言测试（防静默失败的唯一防线）
- T1.5 `grants.sql` 纳入迁移（后补时已积累多次迁移，需回溯补授权）

> **建议选 B**。V0.1 是验证「标注不被同步覆盖」这条生命线的关键一期，
> 压缩它换来的是后面每一期都在还债。

### 0.3 任务编号规则

`T<工作包>.<序号>`，如 `T2.3`。带 ★ 的任务对应 PRD 中的 A/B/C 系列修订项，
是评审明确要求的实现约束，**不允许在实现时"简化掉"**。

---

## 1. 阻塞性前置事项（非开发任务，必须并行推进）

这些事项**不消耗开发工时，但会阻塞开发**。责任人应在 V0.1 启动同日开始推进。

| # | 事项 | 责任方 | 最晚完成 | 阻塞什么 |
|---|---|---|---|---|
| P-1 | **业务域清单定稿**（一级/二级） | 产品 + 各业务线负责人 | V0.5 启动前 | M4 全部功能；这是知识库骨架，中途返工代价极大 |
| P-2 | **各业务域标注负责人确认**，且投入被其主管认可 | 产品 + 技术负责人 | V0.5 启动前 | 整个项目的价值兑现。没有这个，产品做得再好也是空壳 |
| P-3 | **选定 MVP 试点域**（建议交易域或用户域） | 产品 | V0.1 启动前 | V0.1 接哪两个库 |
| P-4 | **网络连通性申请**：平台服务器 → 各生产库 | 运维 + 网络 | V0.1 第 2 周 | T3.1 起全部采集任务 |
| P-5 | **MySQL / PostgreSQL 只读账号** | DBA | V0.1 第 2 周 | T2.2 / T2.3 真库验证 |
| P-6 ★C5 | **Oracle `SELECT ANY DICTIONARY` / SQL Server `VIEW DEFINITION` 权限申请** | DBA + 安全 | **V0.1 期间提交** | V1.0 的 Oracle/SQLServer 采集器。字典级权限要走审批，等 V1.0 才提会直接卡住排期 |
| P-7 | 内网 K8s / Redis / Prometheus 接入资源申请 | 运维 | V0.1 第 3 周 | 部署与监控 |

> **P-6 特别说明**：Oracle 的 `ALL_*` 视图按当前用户过滤，只授其 SELECT 的话，
> 采集表现为「连接成功、SQL 成功、任务 SUCCESS、但只能采到自身 schema」，
> 极难在开发期发现。权限口径见 PRD §M1。

---

## 2. V0.1 — MVP

**目标**：跑通全链路，验证「标注不被同步覆盖」，并**立即开始积累变更流水**。

### WP0 工程基建（5 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T0.1 | 仓库与骨架 | 按 PRD §6.2 建目录；`pyproject.toml`；ruff + mypy；pre-commit；CI 流水线骨架 | — | `make lint` `make test` 可跑通 | 2 |
| T0.2 | 本地环境 | `docker-compose.yml`：`pgvector/pgvector:pg16` + Redis；Makefile 常用命令 | T0.1 | 新人 `make up` 一条命令起环境 | 1 |
| T0.3 | 配置与基础设施 | Pydantic Settings（**双 `DB_URL_WEB` / `DB_URL_COLLECTOR`**）；Loguru；统一异常与错误码；`/health` | T0.1 | 配置项全部有默认值与校验，缺失时启动即报错而非运行时 | 2 |

### WP1 数据模型与迁移（9.5 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T1.1 | 采集层表 | `data_source` / `table_meta` / `column_meta` / `index_meta`；含 `search_text` 生成列与 GIN trigram 索引 | T0.3 | 迁移可正向/回滚；生成列写入即更新 | 2 |
| T1.2 | 知识层表 | `business_domain` / `domain_rule` / `tag` / `dict` / `asset_annotation` / `asset_tag_rel` / `annotation_history` / `common_column_blacklist` | T1.1 | 同上 | 2 |
| T1.3 | 支撑层表 | `schema_change_log` / `sync_job_log` / `sync_fail_detail` / `view_log` / `search_log` / `search_click` / `annotation_todo` / `sys_user` / `user_role` / `api_key` / `user_favorite` / `feedback` | T1.1 | `annotation_todo` **必须用部分唯一索引** `UNIQUE(urn,todo_type) WHERE status='OPEN'` | 2 |
| T1.4 ★C2 | `v_column_effective` 视图 | 域/负责人两级 `COALESCE`；**不得硬编码 `is_deleted` 过滤**，该列作为普通列暴露 | T1.2 | 视图能查出 `is_deleted=TRUE` 的行；域继承对无自身标注的字段生效 | 1 |
| T1.5 ★C4 | 授权脚本 | `deploy/grants.sql`（幂等）；`ALTER DEFAULT PRIVILEGES`；**纳入 Alembic 迁移收尾步骤** | T1.3 | 新建一张测试表后重跑迁移，两角色权限自动正确 | 2 |
| T1.6 ★C1 | 检索阈值配置 | 迁移内执行 `ALTER DATABASE datadict SET pg_trgm.similarity_threshold = ...`。**禁止在应用代码里用 `SET`** | T1.1 | 新建连接的 `SHOW pg_trgm.similarity_threshold` 一致 | 0.5 |

### WP2 采集器（9 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T2.1 | 采集器框架 | `BaseCollector` 抽象；`registry` 注册表；`type_mapper` 类型归一（PRD §M2 映射表） | T0.3 | 新增一种库只需实现一个类并注册，不改其他代码 | 2 |
| T2.2 | MySQL 采集器 | `information_schema` **批量 SQL，一次拉整库**，禁止逐表查询；表/字段/索引/注释 | T2.1 | 500 张表的库全量采集 < 3 分钟 | 2 |
| T2.3 | PostgreSQL 采集器 | `pg_catalog` + **`col_description()` / `obj_description()`**（`information_schema` 无 comment 列） | T2.1 | 中文注释正确采集 | 2 |
| T2.4 ★A3 | 注释断言测试 | 各库带中文注释的 fixture；`test_comment_not_all_empty` 参数化测试；**纳入 CI，不允许 skip** | T2.2 T2.3 | CI 中该测试通过；故意注释掉取注释逻辑时测试必须失败 | 2 |
| T2.5 | 限流与熔断 | 并发控制、请求频率限制、查询超时熔断 | T2.2 | 采集期间对生产库 QPS 增量 < 10 | 1 |

### WP3 同步与变更检测（11 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T3.1 | 同步主流程 | 凭证解密 → 连接 → 白/黑名单过滤 → 批量 upsert（`ON CONFLICT`，1000 条/批）；Redis 锁 + PG advisory lock 双保险 | T2.2 T1.5 | 同一数据源并发触发只有一个任务执行；重复执行结果幂等 | 3 |
| T3.2 ★A6 | 变更 diff 与落库 | 6 类变更识别 + 索引变更；写 `schema_change_log`。**V0.1 只做后端落库，无 UI** | T3.1 | 构造增/删/改字段的 fixture，变更记录准确 | 3 |
| T3.3 ★C2 | 软删除与级联 | 消失对象标 `is_deleted`；**表删除时其字段必须级联置位**（否则视图出现"表已下线但字段在用"） | T3.2 | 单测覆盖表删除级联场景 | 1.5 |
| T3.4 | 执行记录与告警 | `sync_job_log` 汇总 + `sync_fail_detail` 明细；**注释非空率计算，环比下降 > 50% 触发告警** | T3.1 | 单表失败不阻断整体，明细可查、可重试 | 2 |
| T3.5 | 调度 | APScheduler cron 调度 + 手动触发（数据源/库/表级） | T3.1 | 定时任务按配置执行，重启后恢复 | 1.5 |

### WP4 检索（6.5 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T4.1 ★C6 | 检索服务 | 采集层/标注层两路查询 + 合并打分（标注层加权 1.2）。**必须用 SQLAlchemy Core 表达式，禁止裸 SQL**（`%%` 转义在 asyncpg 下会出错） | T1.4 T1.6 | 单测覆盖两路命中与去重 | 3 |
| T4.2 ★必做 | 阈值实测调优 | 构造 **30~50 条典型查询词**（2字/4字中文、英文字段名、混合），实测**召回率与 P95 延迟**，据此定阈值写入迁移 | T4.1 T3.1 | 产出调优报告；**不允许照抄默认值上线** | 2 |
| T4.3 | 表检索与分组 | 表维度检索；结果按表/字段分组返回 | T4.1 | — | 1.5 |

### WP5 标注后端（4 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T5.1 | 单字段标注 | `asset_annotation` CRUD；每次修改写 `annotation_history`；**接口层拒绝写入任何采集层字段** | T1.2 | 尝试通过标注接口改 `raw_type` 返回 400 | 2.5 |
| T5.2 | 表内批量标注 | 一次提交整表多字段的业务标注 | T5.1 | 部分失败时整体回滚，返回逐字段错误 | 1.5 |

### WP6 API（4 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T6.1 | URN 规范 | Pydantic 校验器；**URN 一律走 query 参数，不放 path** | T0.3 | 非法 URN 返回 422 | 1 |
| T6.2 | 基础查询接口 | `/datasources` `/tables` `/columns` `/search` `/tables/ddl` | T4.1 T6.1 | 全部接口有分页与 `total` | 2.5 |
| T6.3 | OpenAPI 文档 | 补全 summary/description/示例 | T6.2 | `/docs` 可直接作为对接文档 | 0.5 |

### WP7 前端（14.5 人日 · 前端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T7.1 | 工程初始化 | Vite + TS + AntD 5 + TanStack Query + Zustand；布局与路由 | — | — | 2 |
| T7.2 | 登录 | 简单账号登录 + 会话保持 | T8.4 | — | 1 |
| T7.3 | 搜索页 | 全局搜索框（首页即搜索）；结果列表；命中词高亮；表/字段 Tab | T6.2 | **查询词 < 2 字时前端提示，不发请求** | 4 |
| T7.4 | 表详情页 | 头部信息 + 字段表格 + DDL Tab | T6.2 | 表格列宽固定，长文本截断不撑破布局 | 3 |
| T7.5 | 字段行内编辑 | 业务含义等业务字段行内编辑，Tab 键切换 | T5.1 | 保存后**立即可搜到**（验证生成列方案） | 3 |
| T7.6 | 四态处理 | 空态、加载态、错误态、无权限态 | T7.3 | 每个页面四态均有设计稿对应实现 | 1.5 |

### WP8 权限与安全（6 人日 · 后端）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T8.1 ★A7 | 双角色双连接池 | `datadict_web` / `datadict_collector` 两套 session；**采集任务强制走 collector 池** | T1.5 | 代码审查确认采集路径无 web session | 2 |
| T8.2 | 凭证保护 | Fernet 加解密，主密钥经环境变量注入；界面永不回显 | T0.3 | 数据库中无明文；接口响应无密码字段 | 1.5 |
| T8.3 ★A7C4 | CI 权限测试 | 正向：collector 对采集层每张表可写（防新表漏授权）<br>反向：collector 写 `asset_annotation` 必须被拒 | T8.1 | 两个测试均在 CI 中通过，**不允许 skip** | 1.5 |
| T8.4 | 登录后端 | 简单账号体系 + 会话/JWT | T1.3 | — | 1 |

### WP9 摸底与验收（2.5 人日 · 后端 + 测试）

| ID | 任务 | 内容要点 | 依赖 | 验收标准 | 人日 |
|---|---|---|---|---|---|
| T9.1 | 注释覆盖率摸底 | 统计各库 `raw_comment` 非空比例，出报告 | T3.1 | **若 < 50%，AI 草稿须从 V1.0 提前到 V0.5**，当期决策 | 0.5 |
| T9.2 ★A9 | 去重率实测 | 执行 PRD §M6 的两条 SQL，产出整体去重率与扣除黑名单后的可批量比例 | T3.1 | **据此填定 V0.5 验收标准**（PRD 中该数字目前为占位） | 0.5 |
| T9.3 | 真库接入验证 | 接入 2 个核心生产库；人工抽查 20 张表核对注释 | P-4 P-5 T3.1 | 注释与源库一致 | 1 |
| T9.4 ★生命线 | 标注不丢失验收 | 完成一批人工标注 → 触发一次全量同步 → 复查标注 | T5.1 T3.1 | **标注 100% 完好**。此项不通过则 V0.1 不予验收 | 0.5 |

### V0.1 验收标准（全部满足方可进入 V0.5）

1. 接入 2 个核心生产库，团队成员能搜到中文字段并看到人工标注
2. 注释非空率与源库人工抽查（20 张表）一致
3. `test_comment_not_all_empty` 与两项权限测试在 CI 中通过
4. **完成人工标注后再跑一次同步，标注 100% 不丢失**
5. 标注保存后立即可搜到（无刷新延迟）
6. 产出去重率实测数据，并据此填定 V0.5 验收标准
7. 产出检索阈值调优报告，阈值已写入迁移

### V0.1 开发执行记录

| 日期 | 任务 | 状态 | 交付内容 | 验证 |
|---|---|---|---|---|
| 2026-08-05 | T1.3 支撑层表 | 已完成 | 新增 `schema_change_log` / `sync_job_log` / `sync_fail_detail` / `view_log` / `search_log` / `search_click` / `annotation_todo` / `sys_user` / `user_role` / `api_key` / `user_favorite` / `feedback` ORM 与 Alembic 迁移；`annotation_todo` 使用部分唯一索引 `UNIQUE(urn,todo_type) WHERE status='OPEN'`；修正 Alembic asyncpg 在线迁移路径与本地迁移账号。 | `pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`、`alembic upgrade head --sql`、本地 PostgreSQL `upgrade -> downgrade 20260805_0002 -> upgrade` |
| 2026-08-06 | T1.4 `v_column_effective` 视图 | 已完成 | 新增 `v_column_effective` Alembic 迁移；通过 `COALESCE(ca.domain_id, ta.domain_id)` 与 `COALESCE(ca.owner_id, ta.owner_id)` 统一字段有效域/负责人；`is_deleted` 作为普通列暴露，视图内不做硬过滤。 | `pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`、`alembic upgrade head --sql`、本地 PostgreSQL fixture readback 验证 `is_deleted=TRUE` 可查且字段继承表级域/负责人、`downgrade 20260805_0003 -> upgrade head` |
| 2026-08-06 | T1.5 授权脚本 | 已完成 | 新增幂等 `deploy/grants.sql`；Web 角色全表读写并设置默认权限；Collector 角色对采集层和采集流程支撑表可写、对知识层只读且显式收回写权限；Alembic 在线迁移完成后自动重跑授权脚本。 | `pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`、`alembic upgrade head --sql`、本地 PostgreSQL `upgrade head` 后 Collector 分层权限 readback、Web 新建测试表默认权限验证 |
| 2026-08-06 | T1.6 检索阈值配置 | 已完成 | 新增 Alembic 迁移 `20260806_0005_search_similarity_threshold.py`，数据库级执行 `ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1`；回滚时 `RESET` 数据库级配置；新增迁移契约测试，防止退回应用会话级 `SET`。 | `pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`、`alembic upgrade head --sql`、本地 PostgreSQL `upgrade head` 后 `SELECT version_num` 为 `20260806_0005` 且新连接 `SHOW pg_trgm.similarity_threshold` 返回 `0.1`、`downgrade 20260806_0004 -> upgrade head` |
| 2026-08-06 | T2.1 采集器框架 | 已完成 | 新增 `BaseCollector` 抽象、`DataSourceConfig` / `DatabaseInfo` / `TableInfo` / `ColumnInfo` / `IndexInfo` 采集 DTO、采集器注册表与 PRD §M2 类型归一映射；新增库可通过实现一个采集器类并调用 `register_collector()` 接入，框架无需改动。 | 红灯：`pytest -q tests/collectors/test_collector_framework.py` 因 `BaseCollector` 未导出失败；绿灯：`pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app` |
| 2026-08-06 | T2.2 MySQL 采集器 | 已完成 | 新增 `MySQLCollector` 并注册 `mysql`；通过 `information_schema.schemata` / `tables` / `columns` / `statistics` 批量读取库、表、字段、索引元数据；表注释走 `tables.table_comment`，字段注释走 `columns.column_comment`，字段类型接入 `type_mapper` 归一。 | 红灯：`pytest -q tests/collectors/test_mysql_collector.py` 因 `app.collectors.mysql` 不存在失败；绿灯：`pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`；focused test 断言表/字段/索引列表方法每次仅执行 1 条整库 `information_schema` 查询 |
| 2026-08-06 | T2.3 PostgreSQL 采集器 | 已完成 | 新增 `PostgreSQLCollector` 并注册 `postgresql`；通过 `pg_database` / `pg_class` / `pg_namespace` / `pg_attribute` / `pg_index` 批量读取库、表、字段、索引元数据；表注释走 `obj_description(c.oid, 'pg_class')`，字段注释走 `col_description(c.oid, a.attnum)`，不依赖 `information_schema.columns`。 | 红灯：`pytest -q tests/collectors/test_postgresql_collector.py` 因 `app.collectors.postgresql` 不存在失败；绿灯：`pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`；focused test 断言表/字段/索引列表方法每次仅执行 1 条 `pg_catalog` 批量查询，且 SQL 不含 `information_schema` |
| 2026-08-06 | T2.4 注释断言测试 | 已完成 | 新增 `test_comment_not_all_empty` gate 测试，参数化覆盖 MySQL / PostgreSQL 带中文注释 fixture；断言采集字段非空、注释非空且含中文字符；新增契约测试确保该 gate 测试存在并带 `@pytest.mark.gate`。 | 红灯：`pytest -q tests/collectors/test_comment_gate_contract.py` 因 `test_comment_assertions.py` 不存在失败；绿灯：`./scripts/run-gate-tests.sh`、`pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app` |
| 2026-08-06 | T2.5 限流与熔断 | 已完成 | 在 `BaseCollector` 增加统一查询 guard；`DataSourceConfig` 新增 `max_query_concurrency`、`min_query_interval_seconds`、`query_timeout_seconds`，默认最小查询间隔 `0.1s` 对应单采集器最多约 10 QPS；MySQL / PostgreSQL fetch 路径统一走并发 semaphore、最小间隔等待与 `asyncio.wait_for()` 超时熔断。 | 红灯：`pytest -q tests/collectors/test_query_limits.py` 因 `DataSourceConfig` 不支持限流字段失败；绿灯：`./scripts/run-gate-tests.sh`、`pytest -v`、`ruff check app tests alembic`、`ruff format --check app tests alembic`、`mypy app`；focused test 覆盖并发上限、最小查询间隔、超时熔断与 MySQL/PostgreSQL fetch 使用 guard |
| 2026-08-06 | T3.1 同步主流程 | 已完成 | 新增 `MetadataSyncService` 同步骨架：读取 `data_source` 配置、解密凭证后构造采集器、使用 Redis NX + PostgreSQL advisory lock 同源互斥、按 `include_rules` / `exclude_rules` 过滤库表、生成标准 URN，并通过 `INSERT ... ON CONFLICT` 分批 upsert `table_meta` / `column_meta` / `index_meta`；本切片不提前实现 T3.2 diff、T3.3 软删除和 T3.4 执行日志。 | 红灯：`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py` 因 `app.services.metadata_sync` 不存在失败，表名白名单边界测试在修复前失败；绿灯：`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T3.2 变更 diff 与落库 | 已完成 | 新增 `schema_diff` 服务：识别表新增/删除、字段新增/删除、字段类型变更、字段注释变更、索引新增/删除/变化，并写入 `schema_change_log`；`MetadataSyncService` 在 upsert 前调用 diff logger 并返回 `changed_count`；旧快照读取按本次扫描库范围过滤，避免白/黑名单局部同步误报删除。本切片不提前实现 T3.3 的 `is_deleted` 置位。 | 红灯：`.venv/bin/pytest -q tests/services/test_schema_diff_service.py` 因 `app.services.schema_diff` 不存在失败，局部同步旧快照过滤边界测试在修复前失败；绿灯：`.venv/bin/pytest -q tests/services/test_schema_diff_service.py`、`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T3.3 软删除与级联 | 已完成 | `schema_diff` 在写入变更日志后消费 `TABLE_DROPPED` / `COLUMN_DROPPED`：消失表更新 `table_meta.is_deleted=true` / `deleted_at`，并级联将其下 `column_meta` 置为已删除；单独消失字段只置位对应字段；旧快照读取过滤已软删除表/字段，避免后续同步重复记录删除。 | 红灯：`.venv/bin/pytest -q tests/services/test_schema_diff_service.py::test_schema_change_logger_soft_deletes_dropped_tables_and_cascades_columns` 因 `mark_soft_deletes` 不存在失败，active 快照过滤边界测试在修复前失败；绿灯：`.venv/bin/pytest -q tests/services/test_schema_diff_service.py`、`.venv/bin/pytest -q tests/services/test_schema_diff_service.py tests/services/test_metadata_sync_service.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T3.4 执行记录与告警 | 已完成 | 新增 `sync_run` 服务：计算字段注释非空率、写入 `sync_job_log` 汇总、写入 `sync_fail_detail` 明细，并在本次注释非空率较上次下降超过 50% 时触发可注入告警；`MetadataSyncService` 接入 run recorder，单库/单表元数据异常记录失败明细并继续处理其他库表，返回 `fail_count` 与 `comment_fill_rate`。 | 红灯：`.venv/bin/pytest -q tests/services/test_sync_run_service.py` 因 `app.services.sync_run` 不存在失败，`MetadataSyncService` 缺少 `run_recorder` 注入点，表级失败明细缺 `table_name`；绿灯：`.venv/bin/pytest -q tests/services/test_sync_run_service.py`、`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py`、`.venv/bin/pytest -q tests/services/test_sync_run_service.py tests/services/test_metadata_sync_service.py tests/services/test_schema_diff_service.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T3.5 调度 | 已完成 | 新增 `MetadataSyncScheduler`：启动时从启用的 `data_source.sync_cron` 重建 APScheduler cron job，job id 固定为 `sync-source-{source_id}` 且 `replace_existing` / `coalesce` / `max_instances=1` 防重复；cron job 以 `CRON` 类型触发同步，手动触发支持数据源、库、表三级范围；FastAPI lifespan 启停调度器，进程重启后由数据库配置恢复任务。 | 红灯：`.venv/bin/pytest -q tests/services/test_sync_scheduler_service.py` 因 `app.services.sync_scheduler` 不存在失败，`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py::test_sync_source_can_be_manually_scoped_to_one_table` 因 `sync_source` 缺 `db_name` / `table_name` 参数失败，`.venv/bin/pytest -q tests/test_app_lifespan.py` 因应用入口未接入调度器失败；绿灯：`.venv/bin/pytest -q tests/services/test_sync_scheduler_service.py tests/services/test_metadata_sync_service.py tests/test_app_lifespan.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T4.1 检索服务 | 已完成 | 新增 `ColumnSearchService` 与 `build_column_search_statement`：基于 `column_meta.search_text` 与 `asset_annotation.search_text` 两路 pg_trgm 命中，标注层分数乘 1.2，经 `UNION ALL` CTE 汇总后 JOIN `v_column_effective`，用 `max(score)` 对同一字段去重排序；检索路径全程使用 SQLAlchemy Core 表达式，不写裸 SQL，不手写 JOIN `asset_annotation`，并过滤已软删除字段。本切片只做字段检索服务，不提前实现 T4.2 阈值实测和 T4.3 表检索分组。 | 红灯：`.venv/bin/pytest -q tests/services/test_search_service.py` 因 `app.services.search` 不存在失败；绿灯：`.venv/bin/pytest -q tests/services/test_search_service.py`、`.venv/bin/pytest -q tests/services/test_search_service.py tests/services/test_metadata_sync_service.py tests/models/test_effective_column_view.py tests/models/test_search_threshold_migration.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic`、`.venv/bin/ruff format --check app tests alembic`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T4.2 检索阈值实测调优 | 已完成（代表性 fixture） | 新增 `search_tuning` 指标模块和 `scripts/search_threshold_benchmark.py`：内置 36 条 V0.1 查询词，覆盖中文 2 字、中文 4 字、英文字段名、中英混合；benchmark 在显式事务内临时写入代表性 fixture、使用 T4.1 SQLAlchemy Core 检索语句逐阈值测召回率/P95/平均候选数并回滚；产出 `docs/reports/search-threshold-tuning-v0.1.md`，推荐继续使用已在 Alembic 迁移写入的数据库级阈值 `0.10`。当前本地库仅 1 表/1 字段/1 标注，真实核心库只读账号到位后需用同一脚本 `--no-fixture` 复跑补充报告。 | 红灯：`.venv/bin/pytest -q tests/services/test_search_tuning.py` 因 `app.services.search_tuning` 不存在失败，fixture 构造函数缺失时失败；绿灯：`.venv/bin/pytest -q tests/services/test_search_tuning.py`、`.venv/bin/pytest -q tests/services/test_search_tuning.py tests/services/test_search_service.py`、`.venv/bin/python scripts/search_threshold_benchmark.py --min-recall 0.94`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T4.3 表检索与分组 | 已完成 | 新增 `SearchService` 作为全局检索入口，保留 `ColumnSearchService` 兼容已有调用；新增 `build_table_search_statement`，基于 `table_meta.search_text` 与 `asset_annotation(asset_type='TABLE').search_text` 两路 pg_trgm 命中并用 `max(score)` 去重排序；新增表结果、字段分组和 grouped 返回结构，按表聚合字段命中结果。本切片只覆盖 V0.1 的表/字段分组，不提前实现业务域/术语标签页、高级筛选、热度排序或 API 层。 | 红灯：`.venv/bin/pytest -q tests/services/test_search_service.py` 因 `SearchService` 不存在失败；绿灯：`.venv/bin/pytest -q tests/services/test_search_service.py`、`.venv/bin/pytest -q tests/services/test_search_service.py tests/services/test_search_tuning.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T5.1 单字段标注 | 已完成 | 新增 `FieldAnnotationPayload` / `FieldAnnotationOut`、`SQLAlchemyAnnotationService` 和 `/annotations/field?urn=...` GET/PUT/DELETE；PUT 使用 `INSERT ... ON CONFLICT` 创建或更新 `asset_annotation(asset_type='COLUMN')`，DELETE 删除字段标注；每次 upsert/delete 都写入 `annotation_history` 的 before/after 快照；接口层在业务 payload 解析前拒绝 `raw_type` / `column_name` / `raw_comment` 等采集层字段并返回 400。本切片不提前实现登录鉴权、表内批量标注或 T6.2 基础查询接口。 | 红灯：`.venv/bin/pytest -q tests/services/test_annotation_service.py tests/api/test_annotations_api.py` 因 `app.schemas.annotations` / annotations endpoint 不存在失败；绿灯：`.venv/bin/pytest -q tests/services/test_annotation_service.py tests/api/test_annotations_api.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-06 | T5.2 表内批量标注 | 已完成 | 新增 `TableFieldAnnotationsPayload` / `TableFieldAnnotationsOut` 与 `/annotations/table/fields?table_urn=...`；批量项复用单字段标注 payload，服务层在同一事务窗口内逐字段写 `asset_annotation` 与 `annotation_history`，全部成功才统一 `commit`；任一字段校验失败、字段 URN 不属于当前表或写入异常时统一 `rollback`，通过 `AnnotationBatchError` 返回逐字段 `errors`。本切片不提前实现前端行内编辑、登录鉴权或同名字段聚合。 | 红灯：`.venv/bin/pytest -q tests/services/test_annotation_service.py tests/api/test_annotations_api.py` 因 `AnnotationBatchError` / batch payload 不存在失败；绿灯：`.venv/bin/pytest -q tests/services/test_annotation_service.py tests/api/test_annotations_api.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-08 | T6.1 URN 规范 | 已完成 | 新增 `app.schemas.urns` 的 `TableUrn` / `ColumnUrn` Pydantic 约束，统一四段表 URN 与五段字段 URN 格式；标注 API 的 `urn` / `table_urn` 继续全部走 query 参数并接入校验，非法 URN 在业务逻辑和数据库访问前返回 422；批量标注 item 字段 URN 复用同一 schema。本切片不提前实现 T6.2 基础查询接口或 T6.3 OpenAPI 示例补全。 | 红灯：`.venv/bin/pytest -q tests/schemas/test_urns.py tests/api/test_annotations_api.py` 因 `app.schemas.urns` 不存在失败；绿灯：`.venv/bin/pytest -q tests/schemas/test_urns.py tests/api/test_annotations_api.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-08 | T6.2 基础查询接口 | 已完成 | 新增 `app.api.v1.endpoints.metadata_queries`、`app.schemas.metadata_queries` 与 `SQLAlchemyMetadataQueryService`；接入 `/datasources`、`/tables`、`/columns`、`/tables/ddl`、`/search`，全部使用 query 参数传 URN 并返回分页 `total`；`/columns` 基于 `v_column_effective` 返回字段有效业务语义，`/search` 复用 T4.3 表/字段检索并保留字段分组。本切片不提前实现 `/databases`、`/search/columns`、鉴权、前端表详情或 V1.0 语义检索。 | 红灯：`.venv/bin/pytest -q tests/api/test_metadata_query_api.py tests/services/test_metadata_query_service.py` 因 `metadata_queries` endpoint / schema / service 不存在失败；绿灯：`.venv/bin/pytest -q tests/api/test_metadata_query_api.py tests/services/test_metadata_query_service.py`、`.venv/bin/pytest -q tests/api/test_metadata_query_api.py tests/services/test_metadata_query_service.py tests/api/test_annotations_api.py tests/services/test_search_service.py tests/schemas/test_urns.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-08 | T6.3 OpenAPI 文档 | 已完成 | 补全 T6.2 基础查询接口和 T5 标注接口的 OpenAPI `summary` / `description` / query 参数示例 / requestBody 示例 / response schema 示例；`/docs` 可直接查看 URN query 传参、分页参数、搜索参数、字段标注 payload 和批量标注 payload。本切片只补对接文档元数据，不改变业务逻辑、鉴权、错误码或接口路径。 | 红灯：`.venv/bin/pytest -q tests/api/test_openapi_docs.py` 因 operation description、query examples 与 schema/requestBody examples 缺失失败；绿灯：`.venv/bin/pytest -q tests/api/test_openapi_docs.py tests/api/test_metadata_query_api.py tests/api/test_annotations_api.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -v`、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/search_threshold_benchmark.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-12 | T8.3 CI 权限测试（G2/G3） | 已完成 | 新增 `tests/security/test_collector_permissions.py` 两个 `@pytest.mark.gate` 门禁：`test_collector_can_write_collection_tables`（G3）从 `app.models.metadata` 枚举采集层表，逐表核对 `deploy/grants.sql` 是否授予 collector 写权限，防新表漏授权；`test_collector_cannot_write_annotation`（G2）从 `app.models.knowledge` 枚举知识层表，断言其未被授予 collector 写权限且已显式 REVOKE。与仓库既有测试哲学一致：不连真实库，改为 grants.sql 契约 + ORM 交叉核对；CI `run-gate-tests.sh` 强制执行，不允许 skip。**限制**：契约级测试保证授权脚本正确，真实角色权限漂移需真库集成测试兜底，后者需 CI 先跑迁移+grants（后续基建决策，未在本切片改动 CI 结构）。 | 红灯：`.venv/bin/pytest tests/security/test_collector_permissions.py` 文件不存在失败；用缺失 `column_meta` 授权的 grants 副本验证 G3 能检出漏授权变红；绿灯：`.venv/bin/pytest -q -m gate`（4 passed）、`.venv/bin/pytest -q`（106 passed）、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app`、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-12 | T8.4 登录后端 | 已完成 | 新增 `app.core.security`（pbkdf2_sha256 密码哈希 + `hmac.compare_digest` 常量时间校验、PyJWT HS256 令牌签发/解码）、`app.services.auth.AuthService`（账号密码核对签发 JWT、令牌还原当前用户；账号不存在/停用/密码错误统一回同一提示防枚举）、`app.schemas.auth`、`/auth/login` 与 `/auth/me`（`HTTPBearer(auto_error=False)`，缺令牌抛 `UnauthenticatedError`→DATADICT-5000）；`SysUser` 增 nullable `password_hash` 列（迁移 `20260812_0006`，SSO 用户留空）；新增 `pyjwt>=2.9` 依赖；新增 `scripts/create_user.py` 幂等建号/改密（密码 pbkdf2 落库，明文不入库）。RBAC 强制留给 V1.0 T23.1，本切片只做认证不做授权。 | 红灯：`.venv/bin/pytest tests/core/test_security.py tests/services/test_auth_service.py tests/api/test_auth_api.py` 因 `app.core.security` / `app.services.auth` / `auth` endpoint 不存在失败；绿灯：上述 19 项通过、`.venv/bin/pytest -q`（125 passed，含 4 gate）、`.venv/bin/ruff check app tests alembic scripts`、`.venv/bin/ruff format --check app tests alembic scripts`、`.venv/bin/mypy app scripts/create_user.py`、本地 PostgreSQL `alembic upgrade head` + `downgrade -1` + 回 head、`scripts/create_user.py` 建号后库中 `password_hash` 为 pbkdf2 且幂等、`.venv/bin/alembic upgrade head --sql` |
| 2026-08-12 | T7.1 前端工程初始化 + T7.2 登录 | 已完成 | 新增 `frontend/`：Vite 5 + React 18 + TypeScript(strict) + Ant Design 5 + TanStack Query + Zustand + react-router-dom；`AppLayout`（Sider 菜单 + Header 用户信息/退出）、`createBrowserRouter` 路由与 `RequireAuth` 守卫（会话未定态显示 Spin，未登录跳 `/login`）；`api/client.ts` 统一 fetch 客户端（注入 Bearer、解析后端 `{code,message}` 错误体、令牌存 localStorage）；`stores/auth.ts` Zustand 会话（login/logout/hydrate，启动用已存令牌换 `/auth/me`，401 自动清理）；`LoginPage` 接 `/auth/login`；`SearchPage` 为 T7.3 占位。本切片只做脚手架与登录，搜索/表详情/行内编辑留 T7.3–T7.5。 | `npm install`（exit 0）、`npm run build`（tsc --noEmit 类型检查 + vite build 均通过，✓ built）；后端真库端到端冒烟：`POST /auth/login` 返回有效 JWT（expires_in 28800）、`GET /auth/me` 带令牌返回用户资料、错误密码 401、无令牌 401，前端 API 契约（`access_token`/`token_type`/`/auth/me` 结构）与后端一致 |
| 2026-08-12 | T7.3 搜索页 | 已完成 | 新增 `frontend/src/api/search.ts`（`SearchResult`/`TableHit`/`ColumnHit`/`FieldSearchGroup` 类型 + `search(q,page,pageSize)`，契约对齐后端 `SearchOut`）；重写 `SearchPage`：`Input` 全局搜索框（首页即搜索，`allowClear`/`autoFocus`）+ 300ms 防抖；**查询词 trim 后 < 2 字时前端提示且 `useQuery` `enabled=false` 不发请求**（对齐后端 `q` `min_length=2`）；表/字段 Tab（`表 (n)`/`字段 (n)` 带计数），`<mark>` 命中词高亮（正则元字符转义、大小写不敏感），表命中/字段命中分组卡片各展示 db/URN/类型/PK/域/score；四态齐备——未足字数/加载 Spin/错误(403→无权限 warning，其余 error+重试)/空结果 Empty；`Pagination` 按 `total`/`page_size` 翻页，词变化回第一页，`placeholderData` 保留上页避免闪烁。表命中暂不导航（表详情路由留 T7.4）。 | `npm run build`（`tsc --noEmit` 严格类型检查 + `vite build` 均通过，✓ built in 2.10s；chunk 体积告警为既有 antd 打包问题，非本切片改动）。真库端到端冒烟受 WP9 既有阻塞（P-4 网络 / P-5 只读账号）未跑，为剩余风险 |
| 2026-08-12 | T7.5 字段行内编辑 | 已完成 | 新增 `frontend/src/api/annotations.ts`（`getFieldAnnotation`/`upsertFieldAnnotation` + `mergeAnnotationPayload`，契约对齐 `/annotations/field` GET/PUT）；表详情页「业务含义」列改为行内编辑：点击进入 `Input`，**Enter 保存并退出、Tab 保存并切到下一行、Esc 取消、失焦保存**（`editingRef` 去重迟到 blur、`savingRef` 防并发）；**因后端 upsert 为整体替换，保存前先 GET 现有标注再合并 business_meaning 回填**，避免清空 domain_id/usage_note 等其他业务字段；空值前端拦截提示不发请求，保存成功后 `invalidateQueries(["columns"])` 即时刷新有效业务语义。验收「保存后立即可搜到」由后端生成列保证——`asset_annotation.search_text` 为 `Computed(coalesce(business_meaning,'')||…)` GIN trgm 索引，PUT 写入即更新，前端走的正是 T5.1 已验证的 PUT 端点。 | `npm run build`（`tsc --noEmit` 严格类型检查 + `vite build` 均通过，✓ built in 2.25s；chunk 体积告警为既有 antd 打包问题，非本切片改动）。真库端到端冒烟受 WP9 既有阻塞（P-4 网络 / P-5 只读账号）未跑，「立即可搜到」为生成列既有能力、由 T4.3/T5.1 测试覆盖，前端保存链路真库回归为剩余风险 |
| 2026-08-12 | T7.4 表详情页 | 已完成 | 新增 `frontend/src/api/tables.ts`（`TableDetail`/`ColumnMeta`/`MetadataPage<T>`/`TableDdl` 类型 + `getTable`/`listColumns`/`getTableDdl`，契约对齐 `/tables`、`/columns`、`/tables/ddl`）；新增 `TableDetailPage` 与路由 `/tables/:urn`（URN 经 `encodeURIComponent` 传参、`useParams` 自动解码）：头部 `Descriptions`（表名/类型/dw_layer/删除标记 + 库名/行数/大小/URN 可复制/表注释），**字段表格 `tableLayout="fixed"` 固定列宽 + `scroll.x=910` + 长文本 `Tooltip` 截断不撑破布局**（#/字段名含 PK/类型含采集类型 tip/可空/业务含义/数据域），DDL Tab 懒加载（切到才请求）+ 等宽代码块 + 一键复制；四态齐备（加载 Spin / 403 无权限 / 其余错误 + 重试 / 空 items 归“表不存在”Empty）；字段列表分页 `page_size=50`。同时把 T7.3 搜索结果的表命中与字段分组表头接上 `Link` 跳转到详情页。 | `npm run build`（`tsc --noEmit` 严格类型检查 + `vite build` 均通过，✓ built in 2.32s；chunk 体积告警为既有 antd 打包问题，非本切片改动）。真库端到端冒烟受 WP9 既有阻塞（P-4 网络 / P-5 只读账号）未跑，为剩余风险 |
| 2026-08-14 | T7.6 四态处理 | 已完成 | 新增 `frontend/src/components/QueryStates.tsx` 统一收口四态：`LoadingState`（居中 `Spin`，`size`/`padding` 可调）、`ErrorState`（后端 **403 归无权限 warning 无重试、其余 error + 重试**，`forbiddenMessage`/`errorMessage` 可定制）、`EmptyState`（`simple` 切换简约/大图）。`SearchPage` 与 `TableDetailPage`（表头查询 / `ColumnsTab` / `DdlTab`）全部改用共享组件，消除各处重复的居中 Spin、`Alert`+重试、403 分支内联判断。**补齐无权限态缺口**：原 `ColumnsTab`、`DdlTab` 只有通用 error 无 403 分支，现经 `ErrorState` 一致处理。四态与文案逐页对齐：搜索（未足字数/加载/搜索失败或无权限/空结果）、表详情（加载/加载失败或无权限/表不存在/字段与 DDL 各自四态）。本切片只做前端四态统一，不改后端、路由或业务逻辑。 | `npm run build`（`tsc --noEmit` 严格类型检查 + `vite build` 均通过，✓ built in 2.36s；chunk 体积告警为既有 antd 打包问题，非本切片改动）。四态中「无权限（403）」与「错误」分支需真库/真实无权限账号触发，受 WP9 既有阻塞未端到端跑，为剩余风险；加载/空态在构建后 UI 逻辑上已齐备 |
| 2026-08-16 | T8.1 双角色双连接池 | 已完成（收尾） | 双连接池运行时实现随 T3.1 已落地：`app/db/session.py` 用 `DB_URL_WEB` / `DB_URL_COLLECTOR` 建 `web`/`collector` 两套引擎与 sessionmaker，采集/调度服务（`metadata_sync` / `sync_scheduler`）一律走 `collector_session`。本切片补齐**固化 §7 红线第 6 条的契约门禁**：新增 `tests/security/test_collector_session_isolation.py`，用 AST 断言两个采集服务模块只 `from app.db.session import collector_session`、**不导入 `web_session` / `get_web_session`**，一旦采集路径误用 web 会话即变红；带 `@pytest.mark.gate` 随 `run-gate-tests.sh` 在 CI 强制执行。验收「代码审查确认采集路径无 web session」由此从人工评审升级为自动门禁。 | 红灯：先临时给 `metadata_sync` 加 `web_session` 导入验证门禁变红；绿灯：`.venv/bin/pytest -q tests/security/test_collector_session_isolation.py`（2 passed）、`./scripts/run-gate-tests.sh`（6 passed）、`.venv/bin/pytest -q`（131 passed）、`.venv/bin/ruff check/format`、`.venv/bin/mypy app` |
| 2026-08-16 | T8.2 凭证保护 | 已完成 | 新增 `app/core/credentials.py` 统一数据源凭证 **Fernet 对称加解密**（`encrypt_credential` / `decrypt_credential`，主密钥 `CREDENTIAL_SECRET_KEY` 仅环境注入、不入库不写日志；与 `core.security` 单向口令哈希区分——数据源密码须可逆才能连库）；`metadata_sync` 解密改为委托该模块并清理重复的内联 `Fernet` 实现（删除 orphan import）。**补齐加密入口缺口**：新增 `scripts/create_datasource.py` 幂等录入数据源，`--password` 明文经 `encrypt_credential` 加密写入 `password_cipher`，**明文不落库、不回显**（按 `code` upsert，可用于轮换密码）。验收「数据库中无明文」由录入即加密保证；「接口响应无密码字段」由 T6.2 `/datasources` schema 本就不含 `password_cipher` 满足。本切片解锁真库接入（T9.3）的凭证录入前置。 | 红灯：`.venv/bin/pytest -q tests/core/test_credentials.py` 因 `app.core.credentials` 不存在失败；绿灯：`.venv/bin/pytest -q tests/core/test_credentials.py`（4 passed：加解密往返 / 密文≠明文 / 换密钥 `InvalidToken` / 空值拒绝）、`.venv/bin/pytest -q tests/services/test_metadata_sync_service.py`、`./scripts/run-gate-tests.sh`、`.venv/bin/pytest -q`（131 passed）、`.venv/bin/ruff check/format`、`.venv/bin/mypy app scripts/create_datasource.py`、`.venv/bin/alembic upgrade head --sql` |
| 2026-10-26 | T-S3 标准定义确认工作台（API + 前端） | 已完成 | 后端新增 `/api/v1/standard-fields` 四个接口：`POST /generate`（触发同名聚类，幂等）、`GET /`（status/conflict/q 筛选 + 分页）、`POST /{id}/confirm`（定版：写入裁决类型与释义、DRAFT→CONFIRMED、对组内存量字段回算 conforms）、`GET /{id}`（详情 + 源字段清单）；修复冲突候选不写 `standard_field_item` 的缺陷（否则裁决后无法回算 conforms）。前端新增「标准定义」菜单页 `StandardFieldsPage`：Segmented 筛选（全部/待确认/冲突待裁决/已定版）、类型分布 Tag、确认定版 Modal（类型 Radio 选择 + 释义必填，冲突项警示条且不给自动推荐）、详情 Drawer（存量字段 conforms 符合/不符合标记）、重新聚类按钮。新增 `scripts/seed_standard_demo.py` 灌入真实业务风格演示数据（53 字段/8 表，含 varchar-bigint 语义冲突与黑名单排除场景）。鉴权与现有标注接口保持一致（暂不控角色，RBAC 在 V1.0 T23.1）。 | 红灯：confirm 接口 500（`dict(Result)` 不可迭代，ruff unsafe-fix 引入）；冲突候选 items=0。绿灯：`.venv/bin/pytest -q`（145 passed，含 2 个新 API 校验测试）、`ruff check/format`、`mypy`（新增 4 文件无错）、`alembic upgrade head`、本地 PG 集成：seed → 聚类 15 候选/2 冲突 → curl 定版 `waybill_no`（6 items 全符合）与 `send_site_code varchar(16)`（tab_exception.bigint 标记不符合）→ 前端 `npm run build` 通过 → 浏览器实测 localhost:5173：列表/筛选/确认弹窗/冲突裁决/详情抽屉/定版提示全链路可用。**注**：mypy 存量 2 错误（search.py/metadata_queries.py）仍未修，与本次无关 |
| 2026-10-26 | T-S1/T-S2 标准字段模型与同名聚类服务（V0.5 范围修订，字段统一治理） | 已完成 | 新增 `standard_field`（标准字段定义：DRAFT→CONFIRMED→DEPRECATED，部分唯一索引保证同名同时仅一个活跃定义，`has_conflict` 标记类型冲突强制人工裁决，`type_distribution` 记录类型分布，`source_type` CLUSTER/IMPORT/MANUAL）与 `standard_field_item`（源字段关联 + `conforms` 回算列）ORM 与 Alembic 迁移 `20261026_0007`；两张表归入知识层（collector 只读），`deploy/grants.sql` 同步授权/收回。新增 `app/services/standard_field.py`：`build_name_clusters` 纯函数聚类（按字段名聚合、类型众数推荐、逻辑类型不一致置冲突、最高频原始注释预填释义、黑名单排除）+ `generate_standard_field_candidates` 幂等生成（已有 CONFIRMED 同名标准跳过，DRAFT 刷新统计并整体替换 items）。**背景**：项目真实目标为字段定义统一治理（同义字段全公司唯一定义），V0.5 路径调整为「同名聚类冷启动 → 冲突裁决 → 异名语义归组 → 定版 → 同步比对拦截」，详见 PRD 后续修订。 | 红灯：`pytest -q tests/services/test_standard_field_clustering.py` 因模块不存在失败；绿灯：5 个聚类单测、本地 PG `alembic upgrade head`（含 0007）、集成验证（事务内 seed 6 字段 → `mobile` 生成无冲突候选含 3 items、`site_code` 冲突候选 `raw_type=None` 待裁决、`status` 被黑名单排除）、`.venv/bin/pytest -q`（143 passed）、`ruff check/format`、`mypy app/services/standard_field.py`；**注**：`mypy app` 存在 2 个与本次改动无关的存量错误（重建 venv 后依赖更新导致 `search.py`/`metadata_queries.py` Select 推断变化），待单独修复 |
| 2026-10-26 | T-S6a 标准定义库展示页 + 业务标签 | 已完成 | 终版（CONFIRMED）标准定义独立展示页：后端新增 `GET /standard-fields/library`（含业务标签）、`GET /standard-fields/tag-options`、`POST /{id}/tags`、`DELETE /{id}/tags/{tag_id}`；业务标签承载「同一标准释义在不同业务域的叫法」（多值），复用 PRD M5 `tag`/`asset_tag_rel` 表，URN 约定 `standard:{id}`，标签不存在时按类别「业务别名」自动创建。前端新增「标准定义库」菜单页 `StandardLibraryPage`：字段名/标准类型/逻辑类型/标准释义/业务标签（可增删、Popover+Select tags 输入、已有标签自动补全）/覆盖表数/存量字段入口；详情抽屉抽为共享组件 `StandardFieldDrawer`（工作台与定义库复用，消除重复）。seed 脚本升级为一条命令出完整演示状态（聚类 + 定版 waybill_no/send_site_code + 演示标签）。 | 红灯：`pytest -q tests/api/test_standard_fields_api.py` 空标签名用例先行失败；绿灯：`.venv/bin/pytest -q`（146 passed）、`ruff check/format`、`mypy`、`npm run build` 通过、浏览器实测 localhost:5173/standard-library：列表含标签渲染、UI 添加标签「运输单号」成功、点 × 删除成功、搜索「网点」正确过滤为 1 条、curl 验证 library/tag-options/attach/detach 四接口 |
| 2026-10-26 | T-S7 数据源管理菜单页（PRD M1 缺口补齐） | 已完成 | 后端新增 `/datasources` 管理接口：`POST`（注册，密码 Fernet 加密落库、code 唯一校验）、`PUT /{id}`（编辑，password 留空不改，code 不可改）、`GET /{id}`（编辑回填）、`POST /{id}/test`（连接测试，错误按 网络不通/账号无权限/驱动缺失/超时 分类，15s 超时）、`POST /{id}/sync`（202 手动触发，BackgroundTasks 走调度器 trigger_manual）；`DataSourceOut` 扩展 username/sync_cron/last_sync_at/include_rules/exclude_rules（密码密文永不出现在响应）；`app.state.sync_scheduler` 挂到 lifespan。前端新增「数据源管理」页：列表（类型/环境 Tag、地址、cron、最近同步、启停 Switch、编辑/测试连接/立即同步）、新建/编辑 Modal 表单（白/黑名单每行一条 `库模式[:表模式]` 与 JSONB 规则互转）。**修复存量 bug**：`sync_source` 失败路径在 rollback 后访问过期 ORM 属性触发同步 IO 崩溃，导致连接级失败不写 `sync_job_log`（失败不可见）——提前取纯量值，并在异常路径补记 FAILED 汇总 + CONNECT 失败明细；顺带修复 `search.py`/`metadata_queries.py` 两个存量 mypy 错误，`mypy app` 全量清零。 | 红灯：UI 新建数据源 500（Fernet 主密钥非法 base64，本地 env 问题）；触发同步后 `sync_job_log` 0 行（存量失败路径 bug）。绿灯：`.venv/bin/pytest -q`（149 passed，含 3 个新数据源校验测试 + lifespan 桩修复）、`ruff check/format`、`mypy app` 无错、`npm run build` 通过；浏览器实测：新建数据源成功且密码密文落库（gAAAA 开头、明文不在库）、响应无密码字段、规则文本域与 JSONB 互转正确、编辑回填 code 禁改、启停 Switch 提示正确且停用后「立即同步」置灰、测试连接对不可达主机 5s 内返回分类错误、手动同步 202 后 `sync_job_log` 记 MANUAL/FAILED + `sync_fail_detail` 记 CONNECT 明细 |
| 2026-10-26 | 导航精简：移除「搜索」页，标准定义库为唯一搜索入口 | 已完成 | 按产品决策（字段统一治理为第一目标），删除前端 `SearchPage` 与 `api/search.ts`；菜单精简为 标准定义库 / 表目录 / 标准定义工作台 三项，登录后默认落地标准定义库；表详情「返回搜索」改「返回表目录」，登录/404 跳转目标同步更新。**保留**后端 `/api/v1/search` 接口与检索服务（API 消费方仍可用；字段级 UI 检索暂由表目录关键词过滤 + 表详情覆盖，未定版字段的注释/业务含义全文检索待标准定义覆盖后评估是否需要恢复）。 | `npm run build` 通过；浏览器实测：`/` 重定向 `/standard-library`、菜单三项无搜索、库页搜索/标签/抽屉功能不回归 |

---

## 3. V0.5 — 标注提效（约 4~5 周）

**目标**：让标注工作真正跑起来。本期是决定项目成败的一期。

| ID | 任务 | 内容要点 | PRD | 人日 |
|---|---|---|---|---|
| T10.1 | 业务域管理 | 树形 CRUD、域基本信息、表归属配置 | M4 | 3 |
| T10.2 | 归属规则引擎 | 按数据源/库/表名前缀自动归属；未归属清单 | M4-4/5 | 2.5 |
| T10.3 | 标签体系 | 标签 CRUD、分类约束（单选/多选）、使用统计、标签合并 | M5 | 3.5 |
| T10.4 | 数据字典 | 字典定义、全局复用、绑定、版本、缺失提醒 | M7 | 4 |
| T11.1 ★A8 | 同名字段聚合 | 按 `字段名 + 逻辑类型` 聚合；选择性应用 | M6-2③ | 4 |
| T11.2 ★A8 | 通用字段名黑名单 | 命中时**从 UI 移除**"应用到全部"按钮（不是禁用）；逐表确认模式；警示条；候选项自动检测 | M6-2③ | 3 |
| T11.3 | 规则引擎自动标注 | 6 条内置规则；结果一律 `PENDING` 待人工确认 | M6-2④ | 3.5 |
| T12.1 | 重命名识别 | 同表内增删配对 + 类型一致判定 | M3-3 | 2.5 |
| T12.2 ★A5 | 标注继承合并策略 | 按 `source_type` 分流；**先删后插 + `flush()`**，不可直接 UPDATE 主键列 | M3-4 | 3 |
| T12.3 | 变更时间线 UI | 表/字段历史变更可视化 | M3-5 | 3 |
| T13.1 | 标注待办 | `annotation_todo` 全流程；我的待办、分派、认领 | M6-4 | 4 |
| T13.2 | 审核流 | 核心域二次审核可配置 | M6-4-4 | 2 |
| T13.3 | Excel 导入导出 | 兼容表格作业习惯 | M6-4-6 | 3 |
| T14.1 | 覆盖率看板 | 整体/按域/按数据源；**必须基于 `v_column_effective`** | M11-2/3 | 3.5 |
| T14.2 | 前端：标注工作台 | 聚合标注页、批量应用交互、待办中心 | M6 | 8 |
| T14.3 | 前端：业务域浏览 | 左树右列表、认领 | M4-6 | 3 |

**V0.5 验收标准**：核心域字段标注覆盖率 60%；单人日均标注量 **待 V0.1 的 T9.2 实测后填定**。

---

## 4. V1.0 — 完整交付（约 4~5 周）

| ID | 任务 | 内容要点 | PRD | 人日 |
|---|---|---|---|---|
| T20.1 ★C5 | Oracle 采集器 | **走 `DBA_*` 视图**（`ALL_*` 按当前用户过滤）；`DBA_COL_COMMENTS` 关联取注释 | M1/M2 | 3.5 |
| T20.2 | SQL Server 采集器 | `sys.columns` + `sys.extended_properties`（`MS_Description`）取注释 | M2 | 3.5 |
| T20.3 | 采集器准入验证 | 按 PRD §6.3 checklist 逐项过；两库 fixture + 断言测试 | §6.3 | 2 |
| T21.1 | 代码仓库枚举解析 | 扫描 Java enum / 常量类 / 前端字典常量；**结果进候选队列，人工确认后入库** | M7-3 | 5 |
| T22.1 | 语义检索 | pgvector + `bge-small-zh-v1.5`；HNSW 索引；业务语言语料拼装 | M9 | 4 |
| T22.2 ★工程坑 | Embedding 工程处理 | ① 独立 Deployment 避免模型内存 × worker 数<br>② **普通 `def` 路由或 `run_in_executor`**，禁止在 `async def` 中同步推理 | M9 | 2.5 |
| T22.3 | 覆盖率准入 | 覆盖率 < 70% 的域自动降级为关键词检索，响应标 `degraded: true` | M9 | 1.5 |
| T23.1 | 完整 RBAC | 4 角色 + 域级作用域 + 数据权限 | M10 | 4 |
| T23.2 | API Key 与审计 | Key 管理、限流、调用日志、操作审计 | M10-5/6 | 3 |
| T23.3 | 合规安全接口 | `/security/sensitive-columns` `/security/pii-columns` | M9 | 1.5 |
| T23.4 ★ROI | 外部系统接入 | **至少 1 个真实消费方**（脱敏中间件/权限系统）通过 API 接入 | M5 | 2 |
| T24.1 | 变更订阅通知 | `change_subscription`；企微/钉钉/邮件/Webhook | M3-6 | 3.5 |
| T24.2 | 辅助功能 | 一键复制、生成代码、结构对比、纠错反馈、分享链接 | M8-3 | 5 |
| T24.3 | 完整运营看板 | 含搜索质量（基于 `search_click`） | M11 | 4 |
| T24.4 | 监控接入 | `/metrics` 接 Prometheus；失败告警 | M12 | 2 |
| T24.5 | Python SDK | `datadict-client` | M9.3 | 2.5 |

**V1.0 验收标准**：全部业务系统数据源接入；整体字段标注覆盖率 > 70%；
至少 2 个内部系统通过 API 接入；语义检索仅对覆盖率 ≥ 70% 的域开启。

---

## 5. V1.5 — 数仓侧（独立一期，周期另评估）

按 PRD §1.4，数仓侧不是"多写几个采集器"，而是元数据模型的实质扩展，故独立立项。

范围：数据模型扩展（分区键/分桶键/排序键/存储格式/表模型/数仓分层）、
Doris & StarRocks & ClickHouse & Hive 采集器、数仓分层识别、字段名黑名单补充数仓专属项。

> **需向相关方明确**：按上述排期，数据开发与分析师群体在平台上线后
> **至少 3 个月内不被服务**。这是经权衡的范围决策，须在立项沟通中说明，
> 避免相关方按"下一期很快"的预期投入配合。

---

## 6. 质量门禁（CI 必过，不允许 skip）

| 门禁 | 检查内容 | 拦截什么 |
|---|---|---|
| G1 ★A3 | `test_comment_not_all_empty` 各库参数化通过 | 注释静默丢失——采集成功但注释全空 |
| G2 ★A7 | `test_collector_cannot_write_annotation` | 采集角色越权写标注表 |
| G3 ★C4 | `test_collector_can_write_collection_tables` | 新建表漏授权导致运行时 permission denied |
| G4 | 迁移正向 + 回滚均可执行 | 不可回滚的迁移 |
| G5 | ruff + mypy 无错 | — |
| G6 | 采集 SQL 静态检查：不含业务表查询、不含 `count(*)` | 触碰业务数据的红线 |
| G7 | 代码扫描：无手写 `JOIN asset_annotation` | 绕过 `v_column_effective` 导致域继承逻辑不一致 |

---

## 7. 开发规范红线

以下七条在代码评审中**一律打回**，不接受"这次特殊"：

1. **禁止对业务表执行任何 SELECT**，包括 `count(*)`、`SELECT DISTINCT` 采样
2. **禁止逐表查询采集**——每种库一条批量 SQL 拉整库
3. **禁止手写 `JOIN asset_annotation`**——统一走 `v_column_effective`
4. **禁止在应用代码中 `SET pg_trgm.similarity_threshold`**——会话级 GUC 在连接池下会漂移
5. **禁止在检索路径写裸 SQL**——用 SQLAlchemy Core 表达式，规避 `%%` 的驱动依赖
6. **禁止采集流程写入知识层表**——数据库权限已强制，代码层也不应尝试
7. **禁止在 `async def` 中执行 embedding 同步推理**——会阻塞整个 event loop

---

## 8. 交付物清单

| 类别 | 交付物 |
|---|---|
| 代码 | `datadict` 仓库（后端 + `frontend/`） |
| 数据库 | Alembic 迁移全集 + `deploy/grants.sql` |
| 部署 | `docker-compose.yml`（本地）+ `deploy/` K8s manifests |
| 文档 | OpenAPI（`/docs` 自动生成）、采集器接入指南、标注规范与示例、运维手册 |
| 报告 | 注释覆盖率摸底报告、去重率实测报告、检索阈值调优报告 |
| 测试 | 单元测试 + 各库 fixture + CI 门禁 G1~G7 |

---

## 9. 风险登记（开发视角，产品风险见 PRD §9）

| 风险 | 触发信号 | 应对 |
|---|---|---|
| **P-6 权限申请被卡** | V0.1 结束仍未获批 | V1.0 的 Oracle/SQLServer 采集器顺延；提前准备 DDL 导出离线导入的降级方案 |
| **V0.1 工时超支** | 第 2 周末进度 < 40% | 按 §0.2 削减清单砍范围，**不动五项不可削减项** |
| **注释覆盖率过低**（T9.1 < 50%） | 摸底报告 | AI 草稿从 V1.0 提前到 V0.5，V0.5 工时 +5 人日 |
| **去重率远低于预期**（T9.2） | 实测报告 | V0.5 验收标准下调；同时提高"核心表优先"的权重 |
| **检索阈值调不出可用区间** | T4.2 召回与延迟无法兼顾 | 引入同义词配置提前到 V0.5；仍不行则重新评估 zhparser 作为补充（非替代） |
| **前端单人成为瓶颈** | V0.5 起前端任务量 11 人日/期以上 | V0.5 的 T14.2 标注工作台交互复杂度高，建议增援或提前拆分设计稿 |

---

## 10. 首周行动清单

**第 1 天**
- [ ] 定 §0.2 的排期选项（A / B / C）
- [ ] 提交 P-4 网络连通性、P-5 只读账号、**P-6 Oracle/SQLServer 字典权限**三项申请
- [ ] 确认 P-3 试点域

**第 1 周**
- [ ] T0.1 ~ T0.3 工程基建完成，新人可一条命令起环境
- [ ] T1.1 ~ T1.3 数据模型迁移完成
- [ ] 启动 P-1 业务域清单的第一次评审会

**第 2 周**
- [x] T1.4 ~ T1.6 视图、授权脚本、阈值配置落地
- [x] T2.1 ~ T2.5 采集器框架、MySQL/PostgreSQL 采集器、注释门禁、限流熔断
- [x] T3.1 同步主流程骨架落地（锁、过滤、分批 upsert、幂等）
- [x] T3.2 变更 diff 与 `schema_change_log` 后端落库
- [x] T3.3 软删除与表删除字段级联
- [x] T3.4 `sync_job_log` / `sync_fail_detail` 与注释非空率告警
- [x] T3.5 APScheduler 调度与手动范围触发
- [x] T4.1 字段检索服务、两路命中合并与去重
- [x] T4.2 检索阈值代表性 fixture 调优报告
- [ ] 只读账号到位后立即跑 T9.1 注释覆盖率摸底——**这个结果影响 V0.5 范围，越早越好**
