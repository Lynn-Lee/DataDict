# DataDict 数据库元数据知识库 —— 产品需求文档（PRD）

> **文档状态**：v1.2 · 已评审确认 · **本项目唯一的产品需求依据**
> **服务代号**：`datadict`（数据库名、DB 角色、SDK 包名均以此为前缀）
> **技术栈**：Python + FastAPI + PostgreSQL + React
> **配套文档**：[开发任务书](DataDict-DEV-TASKS.md) · [选型验证方案](DataDict-POC.md) · [评审记录 v1.0](DataDict-REVIEW-v1.0.md) / [v1.1 评审](DataDict-REVIEW-v1.1.md)
>
> 修订说明：v1.1 基于 v1.0 评审采纳 14 项变更（附录 A）；
> v1.2 修复 v1.1 评审发现的 5 项 P0 + 5 项 P1（附录 B）。

---

## 修订摘要（v1.1 → v1.2）

| 类别 | 变更 |
|---|---|
| **检索** | `SET pg_trgm.similarity_threshold` 改为 `ALTER DATABASE`（会话级 GUC 在连接池下会漂移，导致召回随机不一致）；检索 SQL 改用 SQLAlchemy 表达式，规避 `%%` 转义的驱动依赖 |
| **视图** | `v_column_effective` 去掉硬编码的 `is_deleted` 过滤（原定义与软删除恢复、孤儿巡检、变更时间线等功能冲突） |
| **数据模型** | `annotation_todo` 唯一约束改为部分唯一索引（原约束在同类待办第二次完成时会违约）；`search_log` 点击埋点拆表 |
| **权限** | Oracle 采集权限改为字典级（`ALL_*` 视图按当前用户过滤，原授权只能采到自身 schema）；补 `ALTER DEFAULT PRIVILEGES` 与幂等授权脚本（`GRANT ON ALL TABLES` 是快照授权，新建表无权限） |
| **角色** | 删除「游客」角色（权限矩阵中"部分"始终未定义） |
| **规模** | 承载指标标记为待 V0.1 实测校准 |
| **排期** | §1.4 明写数仓侧的实际等待周期 |

## 修订摘要（v1.0 → v1.1）

| 类别 | 变更 |
|---|---|
| **范围** | V1.0 明确限定为**业务系统侧 OLTP 数据库**；Hive/Doris/StarRocks/ClickHouse 等数仓类组件移出 V1.0，作为 **V1.5 单独一期**；删除 MongoDB（schema-less，模型不兼容） |
| **规模** | 承载指标按真实量级重定：**1 万张表 / 50 万字段** |
| **检索** | zhparser + 物化视图 → **pg_trgm + 生成列**；明确 ES 迁移触发线 |
| **数据模型** | 新增 5 张表（浏览日志、变更订阅、同步失败明细、标注待办、字段名黑名单）；`asset_annotation` 增加合并策略支持；`search_log` 增加点击埋点 |
| **安全** | 采集服务改用**独立数据库 role**，对标注表只授 SELECT（物理隔离，非代码纪律） |
| **排期** | 变更检测（diff + 写日志）前移到 **V0.1**；语义检索保留 V1.0 并补 pgvector 实施方案 |
| **技术栈** | 恢复 Redis / K8s / Prometheus（复用既有基础设施）；Celery 推迟到 V1.0 之后 |
| **纠偏** | 删除全部无依据的量化预估，改为实测口径 |

---

## 一、产品定位

### 1.1 一句话定义

把散落在各业务系统生产数据库中的**表结构元数据**统一采集，叠加**人工标注的业务语义**（业务含义、业务域、敏感级别、枚举字典），沉淀为一个可检索、可复用、可被系统调用的**字段级知识库**。

### 1.2 解决的核心问题

| 现状痛点 | 本产品的解法 |
|---|---|
| 新人接手模块，不知道字段什么意思，靠问老人 | 字段级业务含义沉淀，自助查询 |
| 表注释缺失或写得像没写（`comment '状态'`） | 人工标注层补齐，含枚举值字典 |
| 不知道某个业务概念落在哪张表哪个字段 | 反向检索：按业务含义/标签找字段 |
| 数据库改了字段，下游不知道 | 变更检测 + 订阅通知 |
| 不知道哪些字段是敏感数据 | 敏感级别标注，API 供权限/脱敏系统消费 |
| AI/BI 工具需要 schema 上下文，没有可靠来源 | 提供 AI 友好的语义检索 API |

### 1.3 边界

**V1.0 明确不做**

- ❌ 数仓类组件（Hive / Doris / StarRocks / ClickHouse）—— 移至 V1.5，理由见 §1.4
- ❌ MongoDB 等 schema-less 数据库 —— 数据模型不兼容，不承诺支持
- ❌ 数据血缘（表到表的加工链路）
- ❌ 数据质量监控、数据剖析（profiling）
- ❌ SQL 查询执行

**【修订 A4/B②】关于"绝不触碰业务数据"这条红线**

本产品全生命周期内**不执行任何针对业务表的 SELECT**。这条是硬约束，不接受任何功能需求突破：

- 表行数：取统计信息估算值，**禁止 `count(*)`**
- 枚举值：**不从业务表采样**，改由代码仓库解析 + 人工填写（见 M7.3）
- 取值示例：由标注者手工填写脱敏后的示例，非系统采集

> v1.0 曾在 M6.3 将"样例枚举值分布"列为 AI 输入，与本条红线直接冲突，v1.1 已删除。

### 1.4 为什么数仓类单独一期

数仓组件不只是"多写几个采集器"，而是**元数据模型的实质扩展**：

| 差异点 | OLTP | 数仓 |
|---|---|---|
| 关键结构信息 | 索引、外键 | 分区键、分桶键、排序键、存储格式、表模型 |
| 组织维度 | 业务域 | 业务域 + **数仓分层**（ODS/DWD/DWS/ADS/DIM） |
| 元数据来源 | `information_schema` | Hive 走 Metastore；CK 走 `system.*`；Doris/SR 兼容 MySQL 协议 |
| 核心痛点 | 字段语义不清 | **血缘链路**（这个指标从哪来）> 字段字典 |
| 使用人群 | 业务研发 | 数据开发、分析师 |

两侧的用户、场景、标注负责人往往不是同一批人，混在一期做容易两边都不到位。V1.1 的数据模型中**预留**数仓扩展字段（见 §5.2 注释），但 V1.0 不实现采集。

#### 【v1.2 补充】这个决策的时间代价必须对相关方讲清楚

按 §8 排期，V0.1 + V0.5 + V1.0 合计 **11~14 周**，V1.5 才启动且周期未定。也就是说：

> **数据开发与分析师群体在本平台上线后的至少 3 个月内不被服务。**

这是一个经过权衡的范围决策，不是遗漏。但必须在立项沟通中明确说出来，
避免数仓侧相关方按"下一期很快"的预期投入配合，到时反而形成负面印象。

**替代方案已评估并放弃**：曾考虑在 V1.0 内做数仓的最小只读接入（仅采表名/字段名/注释，
不做分层、分区、血缘）。放弃原因是——数仓侧真正的痛点是血缘而非字段字典，
一个只有字段名的残缺版本无法解决他们的问题，反而消耗信任。宁可晚做，不做半成品。

---

## 二、用户角色与核心场景

### 2.1 角色定义

| 角色 | 描述 | 核心诉求 | 主要使用方式 |
|---|---|---|---|
| **查询者** | 后端开发、前端、测试、产品经理、分析师 | 快速搞懂"这个字段是什么"、"这个概念在哪张表" | Web 搜索 |
| **标注者** | 各业务域的资深研发 | 高效批量标注，不做重复劳动 | 标注工作台 |
| **域管理员** | 各业务线技术负责人 | 管理表归属、推进标注覆盖率 | 管理后台 + 看板 |
| **平台管理员** | 数据平台/架构组 | 管理数据源、标签体系、权限、监控 | 系统管理 |
| **系统调用方** | 其他内部系统、AI 助手、代码生成工具 | 稳定的结构化元数据接口 | REST API |

### 2.2 关键用户场景

**场景 A：字段语义查询（最高频）**
张三排查订单问题，看到 `t_order.settle_status` 值是 3 → 搜索 `settle_status` → 看到业务含义"结算状态"、枚举字典 `1=待结算 2=结算中 3=已结算 4=结算失败`、所属域"交易域-结算"、负责人李四。

**场景 B：概念反查**
产品经理想知道"用户实名认证状态"存在哪里 → 搜索"实名认证" → 命中 `user_center.t_user_auth.auth_status` 等 3 个字段。

**场景 C：批量标注**
李四负责交易域 → 打开标注工作台 → 系统按"同名字段聚合"，`order_no` 在多张表出现 → 标注一次，选择性应用。

**场景 D：结构变更感知**
交易域改了 `t_order` 结构 → 次日同步检测到变更 → 推送给订阅者 → 生成"待标注"待办。

**场景 E：系统消费**
AI 编码助手调用 `/api/v1/search/semantic` → 返回相关表结构 + 业务含义 + 枚举值 → 生成准确 SQL。

---

## 三、功能架构总览

```
元数据知识库
│
├─ 【采集域】自动化，无人值守
│   ├─ M1 数据源管理
│   ├─ M2 元数据采集与同步
│   └─ M3 变更检测与审计
│
├─ 【知识域】人工经营，产品核心价值
│   ├─ M4 业务域管理
│   ├─ M5 标签体系管理
│   ├─ M6 标注工作台         ★ 核心模块
│   └─ M7 数据字典（枚举值管理）
│
├─ 【消费域】对外服务
│   ├─ M8 搜索与浏览门户     ★ 核心模块
│   └─ M9 开放 API
│
└─ 【支撑域】
    ├─ M10 权限与安全
    ├─ M11 运营看板
    └─ M12 系统监控
```

---

## 四、详细功能设计

### M1 数据源管理

| 编号 | 功能 | 说明 |
|---|---|---|
| M1-1 | 数据源注册 | **【修订 A4】V1.0 支持类型：MySQL、PostgreSQL、Oracle、SQL Server**。Hive/Doris/StarRocks/ClickHouse 见 V1.5。不支持 MongoDB。录入：名称、类型、环境（生产/预发/测试）、host、port、默认库、只读账号 |
| M1-2 | 连接测试 | 保存前强制连通性校验，失败给出明确错误分类（网络不通/账号无权限/驱动缺失/超时） |
| M1-3 | 采集范围配置 | 白/黑名单，支持通配符 `t_order_*`，排除 `*_bak`、`tmp_*` |
| M1-4 | 同步策略 | 调度周期（cron）、超时时间、并发度、限流阈值 |
| M1-5 | 凭证安全 | 加密存储，界面永不回显，对接密钥管理系统 |
| M1-6 | 启用/停用 | 停用后不再同步，元数据保留并标记 |
| M1-7 | 数据源分组 | 按系统/业务线分组 |

**采集账号权限要求（写入接入文档，DBA 按此授权）**

| 数据库 | 所需权限 |
|---|---|
| MySQL | `SELECT ON information_schema.*`；`SHOW VIEW`（如需采集视图定义） |
| PostgreSQL | 目标库 `CONNECT`；`pg_catalog` 默认可读；无需任何业务表权限 |
| Oracle | **`GRANT SELECT ANY DICTIONARY`**（或 `SELECT_CATALOG_ROLE`），采集走 `DBA_*` 视图。**不能只授 `ALL_*` 视图的 SELECT，原因见下** |
| SQL Server | 目标库 `VIEW DEFINITION`（库级即覆盖库内全部对象）；`SELECT ON sys.*` |

> 严禁授予任何业务表的 SELECT 权限。这是权限申请单上必须写明的一条。

#### 【v1.2 修正】Oracle 权限：`ALL_*` 视图是按当前用户过滤的

**这是 Oracle 采集最容易踩、且表现最具迷惑性的坑。**

Oracle 的 `ALL_TABLES` / `ALL_TAB_COLUMNS` / `ALL_COL_COMMENTS` 语义是
**「当前用户有权限访问的对象」**——视图内部已经按当前用户权限做过滤了。

因此只授予 `GRANT SELECT ON ALL_TAB_COLUMNS` 时，采集账号：

- 连接成功 ✅
- 查询执行成功 ✅
- 无任何报错 ✅
- 同步任务状态 SUCCESS ✅
- **但只能看到自己 schema 下的对象，其他业务 schema 一张表都采不到** ❌

与 M2 描述的「注释静默失败」是同一类问题，只是这次丢的是**全部表**。

**正确授权（二选一，写进权限申请单）**

| 方案 | 授权语句 | 采集使用的视图 |
|---|---|---|
| A（推荐） | `GRANT SELECT ANY DICTIONARY TO datadict_collector;` | `DBA_TABLES` / `DBA_TAB_COLUMNS` / `DBA_COL_COMMENTS` / `DBA_TAB_COMMENTS` / `DBA_INDEXES` |
| B（DBA 更保守时） | `GRANT SELECT_CATALOG_ROLE TO datadict_collector;` | 同上 |

若 DBA 坚决不给字典级权限，退化方案是逐 schema 授权业务表 SELECT——但这**违反本产品的
只读元数据红线**，不可接受。此时应放弃 Oracle 自动采集，改为 **DDL 导出离线导入**。

> **行动项**：字典级权限申请通常需要走审批流程，**必须在 V0.1 期间就提交**，
> 不要等 V1.0 开发时才发现被卡住。同理适用于 SQL Server 的 `VIEW DEFINITION`。

---

### M2 元数据采集与同步

| 编号 | 功能 | 说明 |
|---|---|---|
| M2-1 | 定时同步 | 按 cron 自动执行，默认每日凌晨 |
| M2-2 | 手动触发 | 数据源/库/表级别立即同步 |
| M2-3 | 采集内容 | 见下方清单 |
| M2-4 | 类型归一化 | 原始类型 → 逻辑类型，保留原始类型串 |
| M2-5 | 任务执行记录 | 汇总记录写 `sync_job_log` |
| M2-6 | **失败明细记录** | **【新增】**单表失败不阻断整体，明细写入 `sync_fail_detail`，支持按明细重试 |
| M2-7 | 采集限流 | 控制并发和请求频率 |
| M2-8 | **注释采集断言** | **【修订 A3】**见下方「注释采集专项」 |

**采集内容清单**

*库级*：库名、字符集、排序规则
*表级*：表名、表注释、表类型（table/view）、引擎、估算行数、数据大小、创建时间
*字段级*：字段名、序号、原始类型、长度/精度/标度、是否可空、默认值、**字段注释**、是否主键、是否自增、是否唯一
*索引级*：索引名、类型、包含字段及顺序
*外键*：约束名、引用表、引用字段

#### 【修订 A3】注释采集专项 —— 最高优先级的实现风险

**风险性质**：字段注释在各数据库中取法完全不同，实现不到位会**静默失败**——采集成功、表入库、日志显示正常，但注释全空。因为 MVP 先接 MySQL（`column_comment` 直接可取），这个坑要等接第二个库时才暴露，届时可能已经有人基于空注释做了大量无谓的人工标注。

**各库注释取法对照表（实现必须严格遵照）**

| 数据库 | 表注释 | 字段注释 |
|---|---|---|
| **MySQL** | `information_schema.tables.table_comment` | `information_schema.columns.column_comment` |
| **PostgreSQL** | `obj_description(c.oid, 'pg_class')` | `col_description(c.oid, a.attnum)`<br>⚠️ `information_schema.columns` **没有** comment 列 |
| **Oracle** | `all_tab_comments.comments` | `all_col_comments.comments`<br>⚠️ 需与 `all_tab_columns` 关联 |
| **SQL Server** | `sys.extended_properties` where `name='MS_Description'`, `minor_id=0` | `sys.extended_properties` where `name='MS_Description'`, `minor_id=column_id`<br>⚠️ 不在 `information_schema` |

**PostgreSQL 参考实现**

```sql
SELECT
    n.nspname                          AS schema_name,
    c.relname                          AS table_name,
    a.attname                          AS column_name,
    a.attnum                           AS ordinal,
    format_type(a.atttypid, a.atttypmod) AS raw_type,
    NOT a.attnotnull                   AS is_nullable,
    col_description(c.oid, a.attnum)   AS column_comment,   -- 关键
    obj_description(c.oid, 'pg_class') AS table_comment
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE c.relkind IN ('r','p','v')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND n.nspname NOT IN ('pg_catalog','information_schema');
```

**强制断言测试（每个采集器必须有，纳入 CI）**

```python
@pytest.mark.parametrize("db_type", ["mysql", "postgresql", "oracle", "sqlserver"])
async def test_comment_not_all_empty(db_type, fixture_source):
    """针对预置了中文注释的 fixture 库，断言注释采集非空。
    这个测试是防止注释静默丢失的唯一防线，不允许 skip。"""
    collector = get_collector(db_type, fixture_source)
    columns = await collector.list_columns("meta_test_db")

    assert len(columns) > 0, "未采集到任何字段"
    with_comment = [c for c in columns if c.raw_comment and c.raw_comment.strip()]
    assert len(with_comment) > 0, f"{db_type} 注释采集全空，实现有误"

    # 中文注释必须正确解码，防止编码问题导致乱码
    zh = [c for c in with_comment if any('\u4e00' <= ch <= '\u9fff' for ch in c.raw_comment)]
    assert len(zh) > 0, f"{db_type} 中文注释解码异常"
```

每接入一种新数据库，必须先准备带中文注释的 fixture 库并让该测试通过，才允许接生产。

**运行时兜底监控**：若某次同步后，某数据源的字段注释非空率相比上次下降超过 50%，触发告警。

**类型归一化映射表（V1.0 范围）**

| 逻辑类型 | MySQL | PostgreSQL | Oracle | SQL Server |
|---|---|---|---|---|
| STRING | varchar, char, text, longtext | varchar, character varying, text | VARCHAR2, CHAR, CLOB, NVARCHAR2 | varchar, nvarchar, char, text |
| INT | int, bigint, smallint, tinyint, mediumint | integer, bigint, smallint | NUMBER(p,0) | int, bigint, smallint, tinyint |
| DECIMAL | decimal, numeric | numeric, decimal, money | NUMBER(p,s) | decimal, numeric, money |
| FLOAT | float, double | real, double precision | BINARY_FLOAT, BINARY_DOUBLE | float, real |
| DATETIME | datetime, timestamp | timestamp, timestamptz | DATE, TIMESTAMP | datetime, datetime2, smalldatetime |
| DATE | date | date | — | date |
| TIME | time | time | — | time |
| BOOL | tinyint(1) ※启发式 | boolean | NUMBER(1) ※启发式 | bit |
| JSON | json | json, jsonb | — | — |
| BINARY | blob, binary, varbinary | bytea | BLOB, RAW | varbinary, image |

> 标 ※ 的为启发式判断，允许人工在标注层通过 `logical_type_override` 覆盖。

**采集流程**

```
1.  读取数据源配置 → 解密凭证 → 建立只读连接
2.  获取 PG advisory lock / Redis 锁（同数据源互斥）
3.  拉取库列表 → 白/黑名单过滤
4.  逐库批量拉取表/字段/索引（一次查询取整库，禁止逐表查询）
5.  类型归一化
6.  与库内现有快照 diff → 生成变更记录          ← 【修订 A6】V0.1 即实现
7.  写入 schema_change_log                      ← 【修订 A6】V0.1 即实现
8.  Upsert 采集层表（asset_annotation 无 UPDATE 权限，物理隔离）
9.  消失对象标记 is_deleted=true（软删除）
10. 注释非空率校验 → 异常则告警
11. 写 sync_job_log（汇总）+ sync_fail_detail（失败明细）
12. 同步后治理链路：按本轮新增/改类型/改注释的字段做增量聚类 → 与已定版标准比对挂载 → 生成待办   ← 【修订 B⑤】V0.1 即实现
```

##### 【修订 B⑤】同步后治理链路（V0.1 已实现，取代原「生成标注待办」）

标准定义库是唯一真相源，所以同步进来的新增/变更字段不是「待标注」，而是「待归标」。同步完成后
（cron 与手动同步都算）由 web 会话按顺序做三件事，采集角色不碰知识层：

1.  **增量聚类**：只重聚本轮变更涉及的**字段名**（同名的全部存量字段一起算，否则类型分布会失真），
    产出/刷新 DRAFT 候选；每日 1 次全量重聚兜底（兜住 Excel 新导入、标准新定版等无同步事件触发的变化）。
2.  **挂载比对**：按「字段名 + 释义哈希 → 字段名」两级匹配已定版标准；释义级标准的成员按释义定义，
    注释变了会自动重挂到正确组或摘除错挂，名级标准下的人工归组关系不被扫描推翻。
3.  **两类待办**：`STANDARD_CONFLICT`（字段类型与标准不一致，按字段）；`STANDARD_MISSING`
    （该表仍有字段没关联任何已定版标准，**按表聚合**一表一条，附字段预览与"有候选待定版/需新建标准"提示）。
    缺口清零自动关闭；人工豁免/忽略后只有缺口变大才重新开单——否则每轮扫描都会复活已处理的提醒，豁免等于失效。

---

### M3 变更检测与审计

| 编号 | 功能 | 说明 | 版本 |
|---|---|---|---|
| M3-1 | 变更识别 | 表新增/删除、字段新增/删除、类型变更、注释变更、索引变更 | **V0.1** |
| M3-2 | 变更记录落库 | 写入 `schema_change_log` | **V0.1** |
| M3-3 | 疑似重命名识别 | 同表内同时出现字段删除 A + 新增 B 且类型一致 → 标记疑似重命名 | V0.5 |
| M3-4 | 标注继承（含合并策略） | 见下方【修订 A5】 | V0.5 |
| M3-5 | 变更时间线 UI | 任意表/字段的历史变更可视化 | V0.5 |
| M3-6 | 变更订阅通知 | 按数据源/业务域/表 订阅，推企微/钉钉/邮件/Webhook | V1.0 |
| M3-7 | 待办生成 | 新增/变更字段 → 增量聚类出候选 + 生成治理待办（见【修订 B⑤】，V0.1 已实现；不再是"待标注"） | **V0.1** |
| M3-8 | 软删除与恢复 | 保留 90 天，重现则自动恢复标注 | V0.5 |

#### 【修订 A6】为什么 diff 必须前移到 V0.1

v1.0 排期中同步在 V0.1、变更检测在 V0.5，中间 4~5 周的 schema 变更流水**永久丢失且不可补录**——快照能重建，流水不能。

改动成本几乎为零：diff 逻辑本身在同步流程中就必须计算（用来决定 upsert 哪些行），只是把结果多写一张日志表。V0.1 只做后端落库，UI 展示留在 V0.5。

#### 【修订 A5】标注继承的合并策略

**原问题**：`asset_annotation.urn` 是 UNIQUE。重命名迁移时若新字段已被规则引擎预填过标注，`UPDATE ... SET urn = 新urn` 会直接违反唯一约束，事务失败。

这个场景概率不低——顺序天然是：同步发现新字段 → 规则引擎自动打标 → 人工才来确认重命名。

**合并策略（按新标注的 `source_type` 分流）**

| 新字段已有标注的来源 | 处理方式 |
|---|---|
| 无标注 | 直接迁移，`inherited_from` 记录来源 URN |
| `RULE`（规则引擎自动） | **旧的人工标注覆盖新的机器标注**，覆盖前将新标注快照写入 `annotation_history` |
| `AI`（AI 草稿） | 同上，人工标注优先 |
| `MANUAL`（已有人工标注） | **不自动迁移**，生成人工比对任务，双方内容并排展示由人裁决 |

**实现要点**：必须在同一事务内先删后插，不能直接 UPDATE 主键列。

```python
async def inherit_annotation(session, old_urn: str, new_urn: str, operator_id: int):
    old = await get_annotation(session, old_urn)
    if not old:
        return
    new = await get_annotation(session, new_urn)

    if new and new.source_type == 'MANUAL':
        await create_merge_task(session, old_urn, new_urn)   # 转人工比对
        return

    async with session.begin_nested():
        if new:
            await snapshot_to_history(session, new, operator_id)
            await session.delete(new)
            await session.flush()          # 关键：先释放 urn 唯一约束
        old.urn = new_urn
        old.inherited_from = old_urn
        old.updated_by = operator_id
    await migrate_tag_relations(session, old_urn, new_urn)
```

---

### M4 业务域管理

| 编号 | 功能 | 说明 |
|---|---|---|
| M4-1 | 树形业务域 | 多级，建议不超过 3 级 |
| M4-2 | 域基本信息 | 名称、编码、描述、负责人、对应技术团队 |
| M4-3 | 表归属配置 | 手工指定 / 按前缀规则批量 / 按数据源整体归属 |
| M4-4 | 归属规则引擎 | 新采集的表自动归属 |
| M4-5 | 未归属清单 | 督促认领 |
| M4-6 | 域视角浏览 | 从业务域进入浏览表和字段 |
| M4-7 | **字段域继承语义明确化** | **【修订 A1】**见下方 |

#### 【修订 A1】字段业务域的继承语义

**原问题**：M6.1 规定字段业务域"继承自表，可覆盖"，但 §5.3 搜索视图只 JOIN 了字段级标注。绝大多数字段的 `asset_annotation.domain_id` 为 NULL，导致「按业务域筛选字段」形同虚设，业务域名也搜不到。

**修订**：定义**有效业务域**的唯一口径，并封装为统一视图，**禁止在任何 SQL 中手写这段 JOIN 逻辑**。

```sql
CREATE OR REPLACE VIEW v_column_effective AS
SELECT
    c.urn,
    c.table_urn,
    c.column_name,
    c.ordinal,
    c.raw_type,
    c.logical_type,
    c.is_nullable,
    c.is_primary_key,
    c.raw_comment,
    c.is_deleted,
    t.db_name,
    t.table_name,
    t.table_comment,
    t.source_id,
    ca.business_meaning,
    ca.dict_id,
    ca.dict_inline,
    ca.sample_value,
    ca.usage_note,
    ca.status            AS annotation_status,
    ca.source_type       AS annotation_source,
    COALESCE(ca.logical_type_override, c.logical_type) AS effective_type,
    COALESCE(ca.domain_id, ta.domain_id)               AS effective_domain_id,  -- 核心
    d.name                                             AS domain_name,
    d.code                                             AS domain_code,
    COALESCE(ca.owner_id, ta.owner_id)                 AS effective_owner_id
FROM column_meta c
JOIN table_meta t              ON c.table_urn = t.urn
LEFT JOIN asset_annotation ca  ON ca.urn = c.urn      AND ca.asset_type = 'COLUMN'
LEFT JOIN asset_annotation ta  ON ta.urn = c.table_urn AND ta.asset_type = 'TABLE'
LEFT JOIN business_domain d    ON d.id = COALESCE(ca.domain_id, ta.domain_id);
-- 【v1.2 修正】此处不再过滤 is_deleted，原因见下
```

#### 【v1.2 修正】视图不得硬编码 `is_deleted` 过滤

v1.1 的视图定义末尾带 `WHERE c.is_deleted = FALSE`，与「禁止绕过视图」的约定直接冲突——
下列功能**必须**访问已下线的字段：

| 功能 | 位置 |
|---|---|
| 软删除与恢复（字段重现时自动复原标注） | M3-8 |
| 孤儿标注巡检 | §9 风险表 |
| 变更时间线（需展示已删除字段的历史） | M3-5 |
| 表详情页「显示已下线字段」 | M8-2-3 |

这些功能要么绕过视图（违反约定被评审打回），要么做不了。

**修正**：视图**不过滤** `is_deleted`，将其作为普通列暴露（`c.is_deleted`、`c.deleted_at`
已在 SELECT 列表中），由调用方按需过滤。域继承逻辑仍然只有一处定义，约定依然成立。

```sql
-- 搜索、覆盖率统计等场景由调用方显式过滤
SELECT ... FROM v_column_effective WHERE NOT is_deleted AND ...
```

> **配套明确**：表被删除时（`table_meta.is_deleted = TRUE`），其下字段的
> `column_meta.is_deleted` 必须由 diff 逻辑**级联置位**，否则视图会出现
> 「表已下线但字段仍显示在用」的不一致。此规则写入 `diff_service` 并加单测。

**约定**：M8 搜索、M9 API、M11 看板的所有覆盖率统计，一律基于 `v_column_effective`。代码评审中出现手写 `JOIN asset_annotation` 的一律打回。

---

### M5 标签体系管理

| 编号 | 功能 | 说明 |
|---|---|---|
| M5-1 | 标签分类 | 不同类别不同约束 |
| M5-2 | 标签 CRUD | 名称、编码、描述、颜色 |
| M5-3 | 单选/多选约束 | 类别级 `exclusive` 控制 |
| M5-4 | 使用统计 | 便于清理僵尸标签 |
| M5-5 | 标签合并 | 重复标签合并，关联自动迁移 |

**标签分类体系**

| 类别 | 约束 | 示例标签 |
|---|---|---|
| **敏感级别** | 单选 | L0 公开 / L1 内部 / L2 敏感 / L3 核心机密 |
| **数据类型语义** | 多选 | 手机号、身份证号、邮箱、银行卡号、地址、姓名、IP、金额、时间戳 |
| **字段角色** | 单选 | 业务主键、技术主键、外键、状态字段、逻辑删除标记、审计字段、扩展字段 |
| **合规属性** | 多选 | PII、需脱敏、需加密存储、留痕要求 |
| **数据质量** | 多选 | 存在脏数据、已废弃、历史遗留、含义与字段名不符 |

> 「敏感级别」和「合规属性」是本产品对外价值最高的部分，可直接被数据权限系统、脱敏中间件、安全审计消费（见 M9 安全类接口）。

---

### M6 标注工作台 ★ 核心模块

> **【V0.1 落地修正（2026-10-27）】本模块的定位已被 M13 标准定义库取代。**
> 业务释义与业务标签只挂在**标准**上；在具体字段上写释义、打标签会制造分散的第二真相，与"字段定义统一"的目标相悖。
> 字段的正确动作是**关联到某个标准**（`standard_field_item` + `conforms`），人工标注与 Excel 导入都降级为
> 候选生成与异名归组的**原料**，不是交付物。因此 M6.2 的四种批量标注模式（尤其"应用到全部"）不再实现，
> 由 M13-1 的同名聚类 + M13-2 的人工定版替代。表详情页保留字段级"业务含义"行内编辑属历史遗留，后续移除。

#### M6.1 标注内容项

**字段级**

| 项 | 类型 | 必填 | 说明 |
|---|---|---|---|
| 业务含义 | 文本 | ✅ | 业务语言描述，如"用户完成实名认证的时间" |
| 业务域 | 关联 | — | 缺省继承自表，可覆盖（口径见 M4-7） |
| 标签 | 多关联 | — | 见 M5 |
| 枚举字典 | 结构化 | 条件必填 | 状态类字段必填 |
| 取值示例 | 文本 | — | **人工填写脱敏示例，非系统采集** |
| 来源/计算说明 | 文本 | — | 如"由风控系统回写"、"= 订单金额 - 优惠金额" |
| 使用注意 | 文本 | — | 如"历史数据可能为 null"、"已废弃，改用 xxx" |
| 负责人 | 关联用户 | — | 缺省继承自表 |
| 逻辑类型覆盖 | 枚举 | — | 覆盖归一化结果 |

**表级**：业务含义、业务域、负责人、使用场景说明、生命周期状态（在用/待下线/已废弃）

#### M6.2 四种标注模式

**① 单字段标注** —— 标准表单，用于精细打磨核心字段。

**② 表内批量标注** —— 行内编辑表格展示全部字段，Tab 键切换，无需反复进出弹窗。

**③ 同名字段聚合标注**

按 `字段名 + 逻辑类型` 聚合全库字段，一次标注可选择性应用到多处。

##### 【修订 A8】通用字段名黑名单（安全阀，必做）

**原问题**：v1.0 用 `order_no` 举例（语义确实全局一致），但 `status`、`type`、`name`、`code` 这类字段几乎每张表都有、类型相同、**语义完全不同**。一键"应用到全部"会批量注入错误知识。

**错误标注比空白危害大得多**——空白时用户会去问人，错误时用户会直接采信。

**机制设计**

- 维护 `common_column_blacklist` 表，命中字段名的聚合项：
  - **不展示"应用到全部"按钮**（从 UI 移除，不是禁用）
  - 强制进入"逐表确认"模式，展示每个表的表名 + 表业务含义 + 该字段原始注释辅助判断
  - 顶部显示警示条：`该字段名在不同表中语义通常不同，请逐表确认`
- 黑名单初始清单（V1.0 业务系统侧）：
  ```
  status, state, type, kind, category, name, title, code, value, content,
  remark, comment, description, desc, note, memo, ext, ext_info, extra,
  data, info, config, params, result, message, reason, source, target,
  level, priority, sort, seq, num, count, amount, flag, version
  ```
  > `dt`、`ds`、`pt`、`etl_time`、`load_date`、`inc_day` 等数仓专属项在 V1.5 补充。
- 支持管理员增删；系统自动检测**候选项**：同一字段名在 5 张以上表中出现，且已标注的业务含义文本相似度低于阈值 → 提示加入黑名单
- 反向机制：安全字段名（如 `order_no`、`user_id`）经域管理员确认后可加入白名单，UI 上给出更醒目的批量应用入口
- **V0.1 落地修正（T-S11，2026-10-27）**：标准定义库成为唯一真相源后，"批量标注"这条交互已被"同名聚类生成候选 → 人工定版"取代，于是黑名单的作用从**排除**变成**分组方式**：命中 `common_column_blacklist` 的通用字段名不再被踢出候选生成（否则 `status`/`type`/`remark` 这类字段永远定不了标，与"源库每个字段最终都挂到某个标准"的目标冲突），而是按**字段名 + 注释释义**聚成多个候选组（`standard_field.sub_key` 存该组释义哈希，空串表示按字段名整体定标），`status`(运单状态) 与 `status`(工单状态) 各成一条候选、可各自定版。配套口径：同名标准唯一性从"按名"改为"按名 + 释义组"；释义级候选定版/合并时**不**把通用名沉淀为业务别名（否则会误引所有同名字段）；相似标准提示对释义级候选只给释义相似（MEANING），不给同名（NAME）；治理扫描按"字段名 + 释义哈希 → 字段名"两级匹配挂载，找不到对应释义组的不挂载、不产生待办；注释为空的通用名字段单独成一组，由人工补释义定版。

**④ 规则引擎自动标注**

| 规则条件 | 自动动作 |
|---|---|
| 字段名 `*_time` / `*_at` 且类型 DATETIME | 打标签「审计字段」 |
| 字段名 `is_delete*` / `deleted` | 打标签「逻辑删除标记」，字典 `0=未删除 1=已删除` |
| 字段名含 `mobile` / `phone` | 标签「手机号」「PII」「需脱敏」，敏感级别 L2 |
| 字段名含 `id_card` / `idno` | 标签「身份证号」「PII」，敏感级别 L3 |
| 字段名 `id` 且主键自增 | 业务含义"主键 ID"，标签「技术主键」 |
| 字段名含 `amount` / `price` / `fee` 且类型 DECIMAL | 标签「金额」，提示确认单位（元/分） |

规则结果一律 `source_type='RULE'`、`status='PENDING'`，人工批量确认后转 `CONFIRMED`。

#### M6.3 AI 辅助草稿（可选开启）

- **输入**：表名、表注释、字段名、字段原始注释、同表其他字段名
- **明确不输入**：业务表中的任何实际数据（红线，见 §1.3）
- **输出**：业务含义建议、标签建议
- 全部标记 `source_type='AI'`、`status='PENDING'`，人工确认后生效
- 门户展示时，未确认内容加灰色「待确认」标识

#### M6.4 标注任务管理

| 编号 | 功能 | 说明 |
|---|---|---|
| M6-4-1 | 我的待办 | **【新增 todo 表】**待标注字段、待审核草稿、待确认重命名、待处理纠错、待人工比对 |
| M6-4-2 | 任务分派 | 域管理员分派一批表给指定人 |
| M6-4-3 | 认领机制 | 未分派表自主认领 |
| M6-4-4 | 审核流 | 可配置：核心域需二次审核 |
| M6-4-5 | 标注历史 | 全量留痕，可回滚 |
| M6-4-6 | Excel 导入导出 | 兼容习惯表格作业的团队 |

#### 【修订 A9】关于标注工作量预估

**v1.0 中"去重后 6000~8000 语义单元""工作量降低 85%""日均 300 字段"三个数字均无依据，本版全部删除。**

正确做法：V0.1 采集跑通后，用一条 SQL 实测真实去重率，再据此制定 V0.5 验收标准。

```sql
-- 整体去重率
SELECT
    count(*)                                          AS total_columns,
    count(DISTINCT (column_name, logical_type))       AS distinct_units,
    round(100.0 * (1 - count(DISTINCT (column_name, logical_type))::numeric
                     / count(*)), 1)                  AS dedup_rate_pct
FROM column_meta
WHERE is_deleted = FALSE;

-- 扣除黑名单后的可批量比例（更接近真实收益）
SELECT
    count(DISTINCT (column_name, logical_type)) FILTER (
        WHERE column_name NOT IN (SELECT column_name FROM common_column_blacklist)
    ) AS batchable_units,
    count(DISTINCT (column_name, logical_type)) FILTER (
        WHERE column_name IN (SELECT column_name FROM common_column_blacklist)
    ) AS manual_units
FROM column_meta
WHERE is_deleted = FALSE;
```

**V0.5 验收标准占位**：待 V0.1 实测后填入，本文档不预设数字。

---

### M7 数据字典（枚举值管理）

| 编号 | 功能 | 说明 |
|---|---|---|
| M7-1 | 字典定义 | `值 / 名称 / 描述 / 是否废弃` |
| M7-2 | 全局字典复用 | 多字段引用同一字典，改一处全部生效 |
| M7-3 | **枚举值来源** | **【修订 B②】**见下方 |
| M7-4 | 字典版本 | 变更留痕，废弃值标记而非删除（便于理解历史数据） |
| M7-5 | 缺失提醒 | 「打了状态字段标签但无字典」进入待办 |

#### 【修订 B②】枚举值的合规来源

**禁止**：从业务表 `SELECT DISTINCT` 采样（违反 §1.3 红线）。

**允许的三个来源，按优先级：**

1. **代码仓库解析（V1.0 实现，主要来源）**
   扫描指定 Git 仓库，识别：
   - Java `enum` 定义、常量类（`public static final int STATUS_PAID = 2`）
   - `@ApiModelProperty` / Swagger 注解中的枚举说明
   - MyBatis `@EnumValue`、TypeHandler 映射
   - 前端字典常量文件（`const ORDER_STATUS = {1:'待支付', ...}`）

   **实现原则：不做全自动。** 各项目写法差异大，解析结果一律进「候选队列」，由标注者确认后才写入字典。

2. **人工录入（V0.5 实现，兜底）**
   标注者根据业务知识直接填写，永远是最终裁决方式。

3. **既有字典系统导入（若公司已有）**
   通过 API 或 Excel 导入，标记来源便于追溯。

---

### M8 搜索与浏览门户 ★ 核心模块

> **【V0.1 落地修正（2026-10-26）】独立的「搜索」页面已从导航移除**：同一件事有两个入口会让用户搞不清哪个答案作数，
> 而唯一真相源是 M13 标准定义库。字段名/释义的检索与浏览由 M13-3「标准定义库」页面承担（pg_trgm 检索方案 B① 不变，
> 阈值仍按数据库级配置）；表目录/表详情继续承担资产浏览与字段→标准的关联入口。

#### 【修订 B①】检索方案：pg_trgm + 生成列

**为什么放弃 zhparser + 物化视图**

| 问题 | zhparser | 物化视图 |
|---|---|---|
| 部署 | 需编译安装扩展，多数云托管 PG **不支持** | — |
| 实时性 | — | 刷新有延迟，**标注完搜不到**，体验很差 |
| 运维 | 词典维护成本 | 需额外刷新调度 |

pg_trgm 是 PG contrib 标配，托管环境基本都有；生成列 STORED 实时更新，标注即刻可搜。

**实施方案**

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 采集层搜索列
ALTER TABLE column_meta ADD COLUMN search_text TEXT
  GENERATED ALWAYS AS (
    coalesce(column_name,'') || ' ' || coalesce(raw_comment,'')
  ) STORED;
CREATE INDEX idx_col_trgm ON column_meta USING GIN(search_text gin_trgm_ops);

ALTER TABLE table_meta ADD COLUMN search_text TEXT
  GENERATED ALWAYS AS (
    coalesce(table_name,'') || ' ' || coalesce(table_comment,'')
  ) STORED;
CREATE INDEX idx_tbl_trgm ON table_meta USING GIN(search_text gin_trgm_ops);

-- 标注层搜索列（生成列只能引用本表列，故必须分开建）
ALTER TABLE asset_annotation ADD COLUMN search_text TEXT
  GENERATED ALWAYS AS (
    coalesce(business_meaning,'') || ' ' ||
    coalesce(usage_note,'')       || ' ' ||
    coalesce(source_desc,'')
  ) STORED;
CREATE INDEX idx_anno_trgm ON asset_annotation USING GIN(search_text gin_trgm_ops);
```

**已知代价（明确记录，不回避）**

生成列只能引用**本表列**，因此无法把 `column_name` 和 `business_meaning` 合进同一个搜索列——这是物化视图方案反而更方便的地方。检索时需两路查询后合并打分。

##### 【v1.2 修正】用 SQLAlchemy 表达式，不要写裸 SQL

v1.1 的示例 SQL 中混用了 `:q`（SQLAlchemy 命名参数）与 `%%`（psycopg2 `pyformat` 下的
`%` 转义），**两者对驱动的假设互相冲突**：

| 驱动 | `%%` 是否正确 |
|---|---|
| psycopg2（sync，`pyformat`） | ✅ 需要转义 |
| **asyncpg**（async，`$1` 占位符） | ❌ `%%` 会被当作字面量传下去，SQL 报错 |

而 §6.1 明确要求同时配置 async 与 sync session，两套都会存在，照抄裸 SQL 必踩。

**改用 Core 表达式，把转义交给驱动层**：

```python
from sqlalchemy import select, union_all, func, literal

col_hits = (
    select(ColumnMeta.urn.label('urn'),
           func.similarity(ColumnMeta.search_text, q).label('score'))
    .where(ColumnMeta.search_text.op('%')(q),        # 转义由驱动负责
           ColumnMeta.is_deleted.is_(False))
)
anno_hits = (
    select(AssetAnnotation.urn.label('urn'),
           (func.similarity(AssetAnnotation.search_text, q) * 1.2).label('score'))
    .where(AssetAnnotation.search_text.op('%')(q),
           AssetAnnotation.asset_type == 'COLUMN')
)
hits = union_all(col_hits, anno_hits).cte('hits')

stmt = (
    select(v_column_effective, func.max(hits.c.score).label('score'))
    .join(hits, hits.c.urn == v_column_effective.c.urn)
    .where(v_column_effective.c.is_deleted.is_(False))   # 视图不再自带过滤
    .group_by(*v_column_effective.c)
    .order_by(func.max(hits.c.score).desc())
    .limit(limit).offset(offset)
)
```

标注层加权 1.2，因为人工业务含义命中的相关性高于原始字段名。

**中文短查询必须实测阈值**

pg_trgm 对中文按字符切三字组，2 字查询词（如"订单"）经空格 padding 后仍能走索引，但默认相似度阈值 0.3 会导致召回率很差。

##### 【v1.2 修正】阈值必须用 `ALTER DATABASE`，不能用 `SET`

```sql
-- ❌ 错误：会话级 GUC，在连接池下会漂移
SET pg_trgm.similarity_threshold = 0.1;

-- ✅ 正确：数据库级持久配置，写进 Alembic 迁移
ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1;
```

**为什么这是个严重问题**：`SET` 作用于当前连接，并在该连接**归还连接池后继续保留**。
实际表现是：

- 执行过该 `SET` 的连接 → 阈值 0.1
- 从未执行过的连接 → 仍是默认 0.3
- **同一个查询命中不同连接时，召回结果数量不同**

这类 bug 的特征是**间歇性、不可复现**：测试环境单连接一切正常，生产多连接后
用户反馈「同样的词有时搜得到有时搜不到」，排查方向会完全跑偏到分词、索引、缓存上。

需要按查询动态调阈值时，用 `SET LOCAL` 并**确保处于显式事务内**——
`SET LOCAL` 在事务结束时自动回滚，不会污染连接。

**V0.1 必做一项**：采集跑通后，用真实数据构造 30~50 条典型查询词（2字/4字中文、英文字段名、混合），实测召回率与 P95 延迟，据此定阈值并写入配置。**不允许照抄默认值上线。**

**ES 迁移触发线（满足任意两条即启动评估）**
- 字段数 > 200 万
- 搜索 P95 > 800ms 且已完成索引与 SQL 优化
- 出现 PG 无法满足的需求：同义词词典、拼音检索、模糊纠错、多字段加权打分
- 搜索 QPS > 50

> 在此之前，投入标注覆盖率的收益远高于更换检索引擎——**搜不到的主因几乎总是没标注，不是引擎不行**。

#### M8.1 搜索功能

| 编号 | 功能 | 说明 |
|---|---|---|
| M8-1-1 | 全局搜索框 | 同时检索表名、字段名、注释、业务含义、标签、枚举值名称 |
| M8-1-2 | 中文检索 | pg_trgm 方案，阈值实测调优 |
| M8-1-3 | 结果分组 | 表 / 字段 / 业务域 / 术语 四类标签页 |
| M8-1-4 | 高级筛选 | 数据源、环境、**业务域**（基于 `effective_domain_id`）、标签、敏感级别、数据类型、是否已标注 |
| M8-1-5 | 结果排序 | 相关度 + **热度**（基于 `view_log`）+ 标注完整度 |
| M8-1-6 | 搜索联想 | 输入时下拉联想 |
| M8-1-7 | 同义词配置 | 管理员配置，如「手机号 = 电话 = mobile = phone」，查询时做词扩展 |
| M8-1-8 | 无结果引导 | 提示提交词条需求，形成闭环 |
| M8-1-9 | **点击埋点** | **【修订 A2】**记录 `search_log.clicked_urn`，用于评估搜索质量 |

#### M8.2 浏览功能

| 编号 | 功能 | 说明 |
|---|---|---|
| M8-2-1 | 业务域导航 | 左侧域树 |
| M8-2-2 | 数据源导航 | 数据源 > 库 > 表 |
| M8-2-3 | 表详情页 | 见下方 |
| M8-2-4 | 字段详情抽屉 | 完整信息 + 枚举字典 + 变更历史 |
| M8-2-5 | 我的收藏 | `user_favorite` |
| M8-2-6 | 最近浏览 | **基于新增的 `view_log`** |

**表详情页结构**

```
┌─ 头部 ────────────────────────────────────┐
│ t_order  订单主表                          │
│ 交易域 > 订单   |  order_db@生产   |  ★收藏 │
│ 负责人：李四    |  约 1200 万行             │
│ 业务说明：存储用户下单产生的订单主记录...    │
└───────────────────────────────────────────┘

[字段列表] [索引] [变更历史] [相关表] [DDL]

┌──────────┬─────────┬────┬──────────────┬──────────┬────────┐
│ 字段名    │ 类型     │空  │ 业务含义      │ 标签      │ 枚举   │
├──────────┼─────────┼────┼──────────────┼──────────┼────────┤
│ id  🔑   │ bigint  │否  │ 主键ID        │ 技术主键  │ —      │
│ order_no │varchar32│否  │ 订单编号,全局唯一│业务主键  │ —      │
│ status   │ tinyint │否  │ 订单状态       │状态字段  │ 查看▸  │
│ mobile   │varchar20│是  │ 联系手机号     │PII·L2·脱敏│ —     │
└──────────┴─────────┴────┴──────────────┴──────────┴────────┘
  [搜索字段] [只看已标注/未标注] [导出 Excel]
```

#### M8.3 辅助功能

| 编号 | 功能 | 说明 |
|---|---|---|
| M8-3-1 | 一键复制 | 字段名 / 建表 DDL / SELECT 字段列表 |
| M8-3-2 | 生成代码 | Java Entity / Python dataclass / TypeScript interface |
| M8-3-3 | 结构对比 | 预发 vs 生产同名表差异 |
| M8-3-4 | 纠错反馈 | 任何用户可提，流转给标注者 |
| M8-3-5 | 分享链接 | 稳定 URL |

---

### M9 开放 API

#### 【修订：URN 传参方式】

URN 形如 `mysql:cluster:db:table`，冒号放在 path 中虽合法，但库名含特殊字符时会出错，且各层反向代理对编码处理不一致。

**统一约定：URN 一律通过 query 参数传递，不放 path。**

```
✅ GET /api/v1/tables?urn=mysql:order_cluster:order_db:t_order
❌ GET /api/v1/tables/mysql:order_cluster:order_db:t_order
```

FastAPI 侧用 Pydantic 校验 URN 格式：

```python
URN_PATTERN = re.compile(r'^[a-z]+:[^:]+:[^:]+:[^:]+(:[^:]+)?$')

class UrnQuery(BaseModel):
    urn: str = Field(..., max_length=768)

    @field_validator('urn')
    @classmethod
    def validate_urn(cls, v: str) -> str:
        if not URN_PATTERN.match(v):
            raise ValueError('URN 格式非法')
        return v
```

#### 接口清单

**元数据查询类**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/datasources` | 数据源列表 |
| GET | `/api/v1/databases` | 库列表 |
| GET | `/api/v1/tables` | 表列表（筛选）或表详情（传 urn） |
| GET | `/api/v1/columns` | 字段列表（传 table_urn）或字段详情（传 urn） |
| GET | `/api/v1/tables/ddl?urn=` | 建表语句 |
| GET | `/api/v1/changes` | 变更时间线（按表/字段过滤，来自 `schema_change_log`） |

**标准定义与治理类（M13，V0.1 已实现）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/standard-fields` | 候选与定版标准列表（`status` / `conflict` / `q` 筛选；同名不同义多条用 `sub_key` 区分） |
| GET | `/api/v1/standard-fields/library` | **终版标准定义库**（含业务标签）；设计态查询与 AI/MCP 消费的入口 |
| GET | `/api/v1/standard-fields/{id}` | 标准详情 + 组内存量源字段清单（`conforms` 结果） |
| POST | `/api/v1/standard-fields/generate` | 按字段名聚类生成/刷新 DRAFT 候选（幂等；通用名按释义拆组） |
| POST | `/api/v1/standard-fields/{id}/confirm` | 定版：名称/类型/逻辑类型/释义可改；改名撞活跃标准返回 409 + `existing_id` |
| POST | `/api/v1/standard-fields/{id}/merge-into/{target_id}` | 同义候选归并：存量关联迁到目标、候选置 MERGED、名级候选的来源字段名沉淀为业务别名 |
| POST/DELETE | `/api/v1/standard-fields/{id}/tags[/{tag_id}]` | 业务标签（各业务域叫法）增删，复用 M5 标签体系，urn 约定 `standard:{id}` |
| GET | `/api/v1/standard-fields/tag-options` | 已有业务别名标签名，供前端补全 |
| POST | `/api/v1/governance/sweep` | 手动触发治理扫描（挂载/重挂/conforms 回算 + 两类待办；不做聚类） |
| GET | `/api/v1/governance/todos` | 待办列表，`todo_type` 可筛 `STANDARD_CONFLICT` / `STANDARD_MISSING` |
| POST | `/api/v1/governance/todos/{id}/resolve` | 处理待办：ADOPT / EXEMPT（必填原因）/ IGNORE |
| POST | `/api/v1/imports/excel` | 上传历史数据字典 .xlsx（`dry_run` 仅解析预览），按 `source_file` 幂等 |
| POST | `/api/v1/datasources/{id}/sync` | 手动同步（后台执行），完成后自动接「增量聚类 → 扫描 → 待办」链路 |

**检索类**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/search` | 全文检索 |
| GET | `/api/v1/search/columns` | 字段检索 |
| POST | `/api/v1/search/semantic` | 语义检索（V1.0，见下方补充方案） |

**标签与业务域类**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/domains` | 业务域树 |
| GET | `/api/v1/domains/{id}/tables` | 域下的表 |
| GET | `/api/v1/tags` | 标签列表 |
| GET | `/api/v1/tags/{id}/columns` | 打了某标签的字段 |

**合规安全类**（供权限/脱敏系统消费，本产品对外价值最高的接口）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/security/sensitive-columns` | 敏感字段清单，按级别筛选 |
| GET | `/api/v1/security/pii-columns` | PII 字段清单 |

**变更类**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/changes` | 变更记录 |
| POST/GET/DELETE | `/api/v1/subscriptions` | 变更订阅管理 |

**写入类（受控）**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/sync/trigger` | 触发同步 |
| PUT | `/api/v1/annotations?urn=` | 更新标注（需写权限） |

#### 【修订 B④】语义检索实施方案（保留 V1.0）

**方案：pgvector + 进程内 embedding，不新增独立服务。**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE asset_embedding (
    urn         VARCHAR(768) PRIMARY KEY,
    asset_type  VARCHAR(16)  NOT NULL,
    corpus_text TEXT         NOT NULL,     -- 向量化的原文，便于调试
    embedding   vector(512)  NOT NULL,     -- bge-small-zh-v1.5 维度
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_emb_hnsw ON asset_embedding
  USING hnsw (embedding vector_cosine_ops);
```

**关键设计一：语料必须是业务语言，不是 schema**

用户查询是"查用户已完成订单"这类业务语言，拿它去匹配 `varchar(32) order_no` 效果极差。语料应拼装成自然语言描述：

```python
def build_corpus(table, columns) -> str:
    """表级语料：业务语言优先，schema 信息只作补充"""
    parts = [
        f"{table.business_meaning or table.table_comment or table.table_name}",
        f"所属业务域：{table.domain_name}" if table.domain_name else "",
        "包含字段：" + "、".join(
            c.business_meaning or c.raw_comment or c.column_name
            for c in columns[:40]          # 宽表截断，避免语料稀释
        ),
    ]
    return "。".join(p for p in parts if p)
```

**关键设计二：这是一条硬前置依赖**

> **语义检索的效果完全依赖标注覆盖率。标注覆盖率低于 70% 时，语料里全是字段名而非业务含义，向量检索效果不会比关键词检索更好。**

因此 V1.0 上线该功能的准入条件是：**目标业务域字段标注覆盖率 ≥ 70%**。未达标的域，`/search/semantic` 自动降级为关键词检索并在响应中标注 `degraded: true`。

**关键设计三：两个必须避开的工程坑**

1. **内存**：`uvicorn --workers N` 时每个 worker 各加载一份模型。bge-small-zh 约 400MB，4 worker = 1.6GB。**建议 worker 数控制在 2，或将 embedding 路由拆到独立 K8s Deployment**（既有 K8s 可复用，拆分成本低，且能独立伸缩——鉴于基础设施已具备，推荐直接拆）。

2. **阻塞（最容易踩）**：embedding 推理是 CPU 密集的**同步**操作，写在 `async def` 里会阻塞整个 event loop，单次几百毫秒，并发请求全部卡死。

```python
# ❌ 错误：阻塞 event loop
@router.post("/search/semantic")
async def semantic_search(req: SemanticQuery):
    vec = model.encode(req.query)      # 阻塞！
    ...

# ✅ 正确：普通 def，FastAPI 自动丢线程池
@router.post("/search/semantic")
def semantic_search(req: SemanticQuery, db: Session = Depends(get_sync_db)):
    vec = model.encode(req.query)
    return search_by_vector(db, vec, req.top_k)

# ✅ 或在 async 路由中显式转交
@router.post("/search/semantic")
async def semantic_search(req: SemanticQuery):
    loop = asyncio.get_running_loop()
    vec = await loop.run_in_executor(EMBED_POOL, model.encode, req.query)
    ...
```

**Embedding 更新策略**：标注变更后异步重算该资产的向量（Redis 队列 + 后台 worker，既有 Redis 可复用）；全量重建作为运维命令保留。

**响应示例**

```jsonc
// POST /api/v1/search/semantic
{ "query": "查询用户最近30天已完成的订单和金额", "top_k": 5, "domain_filter": ["交易域"] }

// Response
{
  "degraded": false,
  "annotation_coverage": 0.83,
  "tables": [{
    "urn": "mysql:order_cluster:order_db:t_order",
    "table_name": "t_order",
    "business_meaning": "订单主表，存储用户下单产生的订单主记录",
    "domain": "交易域 > 订单",
    "relevance": 0.91,
    "columns": [
      { "name": "status", "logical_type": "INT", "raw_type": "tinyint(4)",
        "business_meaning": "订单状态",
        "enum_dict": [{"value":"1","label":"待支付"},{"value":"4","label":"已完成"}],
        "tags": ["状态字段"] },
      { "name": "pay_amount", "logical_type": "DECIMAL",
        "business_meaning": "实付金额，单位：元", "tags": ["金额"] }
    ]
  }]
}
```

#### SDK

提供 Python SDK（`pip install datadict-client`）降低内部接入成本。

---

### M10 权限与安全

| 编号 | 功能 | 说明 |
|---|---|---|
| M10-1 | 统一登录 | 对接 SSO / LDAP / OAuth2 |
| M10-2 | RBAC 角色 | 查询者、标注者、域管理员、平台管理员。**【v1.2】删除「游客」**——内网系统全员登录，且原权限矩阵中游客的"部分可见"始终未定义。少一个角色少一类权限漏洞 |
| M10-3 | 数据权限 | 高敏数据源/业务域限定可见人员 |
| M10-4 | 字段级脱敏展示 | L3 字段取值示例对普通用户隐藏 |
| M10-5 | 操作审计日志 | 数据源配置、权限、批量标注、API Key 全留痕 |
| M10-6 | API Key 管理 | 权限范围、限流阈值、调用日志 |
| M10-7 | 凭证保护 | 加密存储、不回显、密钥管理系统 |
| M10-8 | **采集服务权限物理隔离** | **【修订 A7】**见下方 |

#### 【修订 A7】标注表的物理隔离

**原问题**：v1.0 声称"物理上不可能触碰 `asset_annotation`"，但依据只是"upsert 的 SET 子句里没写这些列"——那是**代码纪律，不是物理保证**。任何人加一行代码即可破防，而标注被覆盖是**不可恢复的人力损失**。

**修订：用独立数据库 role 落成真正的物理保证。几行 GRANT 换一个不可逆的安全边界。**

```sql
-- 采集服务专用角色：对采集层可写，对知识层只读
CREATE ROLE datadict_collector LOGIN PASSWORD :'collector_pwd';

GRANT CONNECT ON DATABASE datadict TO datadict_collector;
GRANT USAGE   ON SCHEMA public   TO datadict_collector;

-- 采集层：完整读写
GRANT SELECT, INSERT, UPDATE ON
    table_meta, column_meta, index_meta,
    schema_change_log, sync_job_log, sync_fail_detail, annotation_todo
TO datadict_collector;

-- 知识层：只读，无 INSERT / UPDATE / DELETE
GRANT SELECT ON
    asset_annotation, asset_tag_rel, annotation_history,
    business_domain, tag, dict
TO datadict_collector;

-- 序列权限
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO datadict_collector;

-- 显式收回，防止默认权限或后续 DDL 意外放开
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    asset_annotation, asset_tag_rel, annotation_history
FROM datadict_collector;

-- Web 服务角色：全表读写
CREATE ROLE datadict_web LOGIN PASSWORD :'web_pwd';
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO datadict_web;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO datadict_web;
```

##### 【v1.2 修正】`GRANT ON ALL TABLES` 是快照授权，不是规则

上面的 `GRANT ... ON ALL TABLES IN SCHEMA public` **只对执行时已存在的表生效**。
后续每次 Alembic 迁移新建表，两个角色对新表**都没有任何权限**，应用运行时直接
`permission denied`。

这个坑在 V0.1 不会暴露（建表与授权同时做），但之后**每一次加表迁移都会复现**，
而且报错位置离根因很远，排查成本高。

**修正一：web 角色用默认权限规则**

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO datadict_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO datadict_web;
```

**修正二：collector 角色的权限是按表分层的**（采集层可写 / 知识层只读），
无法用默认权限表达。因此必须：

1. 把全部授权语句维护成一个**幂等的 `deploy/grants.sql`**
2. **纳入 Alembic 迁移的收尾步骤或部署流水线**，每次迁移后自动重跑
3. 新增表时，开发者必须在 `grants.sql` 中显式声明其归属层——这一步写进开发规范

**修正三：补一个反向测试**。现有的 `test_collector_cannot_write_annotation`
只能捕获「权限过大」，捕获不了「新表漏授权」：

```python
COLLECTION_TABLES = ['table_meta', 'column_meta', 'index_meta',
                     'schema_change_log', 'sync_job_log',
                     'sync_fail_detail', 'annotation_todo']

@pytest.mark.parametrize("tbl", COLLECTION_TABLES)
async def test_collector_can_write_collection_tables(collector_session, tbl):
    """采集角色对采集层每张表都必须可写——防止新表漏授权"""
    async with collector_session.begin() as tx:
        await collector_session.execute(text(f"SELECT 1 FROM {tbl} LIMIT 1"))
        await tx.rollback()
```

新增采集层表时同步往 `COLLECTION_TABLES` 里加一行，CI 即可拦住漏授权。

**应用侧配置两个独立连接池**

```python
class Settings(BaseSettings):
    DB_URL_WEB: str        # datadict_web
    DB_URL_COLLECTOR: str  # datadict_collector

# 采集任务强制使用 collector 连接池
async def run_sync(source_id: int):
    async with collector_session_factory() as session:
        await sync_service.execute(session, source_id)
```

**验收测试（纳入 CI，不允许 skip）**

```python
async def test_collector_cannot_write_annotation(collector_session):
    """采集角色写标注表必须被数据库拒绝"""
    with pytest.raises(ProgrammingError, match="permission denied"):
        await collector_session.execute(
            text("UPDATE asset_annotation SET business_meaning='x' WHERE id=1")
        )
```

**权限矩阵**

| 功能 | 查询者 | 标注者 | 域管理员 | 平台管理员 |
|---|---|---|---|---|
| 搜索浏览 | ✅ | ✅ | ✅ | ✅ |
| 查看敏感标记 | ✅ | ✅ | ✅ | ✅ |
| 查看 L3 字段取值示例 | ❌ | 授权域内 | 本域全部 | ✅ |
| 提交纠错 | ✅ | ✅ | ✅ | ✅ |
| 标注字段 | ❌ | 授权域内 | 本域全部 | ✅ |
| 管理业务域 | ❌ | ❌ | 本域 | ✅ |
| 管理标签体系 | ❌ | ❌ | ❌ | ✅ |
| 管理数据源 | ❌ | ❌ | ❌ | ✅ |
| 管理 API Key | ❌ | ❌ | ❌ | ✅ |

---

### M11 运营看板

| 编号 | 功能 | 说明 |
|---|---|---|
| M11-1 | 资产总览 | 数据源/库/表/字段数，环比 |
| M11-2 | 标注覆盖率 | 整体 + 按域 + 按数据源，**基于 `v_column_effective`** |
| M11-3 | 覆盖率排行 | 各域排名 |
| M11-4 | 贡献榜 | 按人月度统计 |
| M11-5 | 质量指标 | 未归属表数、状态字段缺字典数、待审核草稿数、待处理纠错数 |
| M11-6 | 使用热度 | 搜索量趋势、热门词、**热门表 TOP 20（基于 `view_log`）**、无结果词 |
| M11-7 | **搜索质量** | **【新增】**基于 `search_log.clicked_urn` 统计点击率、无点击率、平均点击位次 |
| M11-8 | API 调用统计 | 按 Key 统计量、成功率、P95 |
| M11-9 | 同步健康度 | 各数据源同步状态、失败次数、耗时、**注释非空率趋势** |

---

### M12 系统监控

| 编号 | 功能 | 说明 |
|---|---|---|
| M12-1 | 同步任务监控 | 列表、状态、日志、失败明细 |
| M12-2 | 失败告警 | 连续失败 N 次推送值班群 |
| M12-3 | 健康检查 | `/health` 检查 DB / Redis 连通性 |
| M12-4 | 指标暴露 | `/metrics` 暴露 Prometheus 指标（复用既有监控体系） |
| M12-5 | 慢查询监控 | 搜索响应时间 |

---

### M13 标准定义库与字段统一治理 ★ 本项目的真实目标（V0.1 已实现）

M1~M12 是"可检索的元数据知识库"，M13 才是立项动机：**一个公司内同一业务含义的字段，最终只有一个标准定义**（字段名 + 类型含长度 + 中文释义）。起因是不同研发各自建模，同一个"寄件网点"落成了 `send_site_code varchar(16)` / `create_site_code bigint` / `send_site_name varchar(64)`，下游汇总与表间关联因此失真。

**权威模型**：标准定义库是唯一的知识资产与真相源。业务释义与业务标签（同一含义在各业务域的叫法）都挂在**标准**上；源库字段**不携带独立释义**，它只做一件事——关联到某个标准（`standard_field_item` + `conforms`）。因此 M6 的字段级标注不是交付物，只是归组原料；表目录的职能是浏览 + 字段→标准的关联入口 + 单表变更审计。

**闭环（已实现的部分全部可幂等重跑）**

| 步骤 | 做法 | 位置 |
|---|---|---|
| ① 原样同步 | 各源库表结构按现状采集，不做改造 | M2/M3 |
| ② 候选生成 | 按**字段名**聚类（通用字段名再按注释释义拆组，见【修订 A8】），源库与 Excel 历史字典是**并集**的两路输入 | M13-1 |
| ③ 人工定版 | 名称/类型/逻辑类型/释义全部可编辑；相似度提示"标准库疑似已有同一概念"，可一键关联合并 | M13-2 |
| ④ 归属与度量 | 定版后按「字段名 + 类型**都**一致」回算 `conforms`；存量表不改造，只标记不符合 | M13-3 |
| ⑤ 同步后拦截 | 新增/变更字段 → 增量聚类 → 两级挂载比对 → `STANDARD_CONFLICT`（按字段）与 `STANDARD_MISSING`（按表）两类待办，见【修订 B⑤】 | M13-4 |
| ⑥ 设计态消费 | 定版标准对外提供查询接口，供新表建模与 AI 写 DDL 前先查（脚手架/MCP 接入） | M9/M13-5 |

| 编号 | 功能 | 说明 | 版本 |
|---|---|---|---|
| M13-1 | 候选聚类生成 | 同名字段聚合 + 类型分布统计 + 同名不同型自动标冲突；通用名按释义拆组；空释义单独成组 | **V0.1** |
| M13-2 | 定版工作台 | 全字段可编辑定版、相似标准提示（NAME/ALIAS/MEANING）、关联合并（`merge-into`）、Excel 上传导入 | **V0.1** |
| M13-3 | 标准定义库 | 终版定义 + 业务标签（各业务域叫法）浏览与检索；标准定义库是唯一的搜索入口（原 M8 搜索页已移除） | **V0.1** |
| M13-4 | 治理待办闭环 | 冲突/缺口两类待办的列表、筛选、采纳/豁免（原因留痕）/忽略 | **V0.1** |
| M13-5 | 设计态查询 API / MCP | 按名称、释义、别名检索标准定义，供 AI 建表与设计评审消费 | V0.5 |
| M13-6 | 标准覆盖率看板 | 已关联已定版标准的字段占比、符合/不符合数、收敛趋势 | V0.5 |

**关键口径（踩过的坑，改动前请先读）**

- 同名标准的唯一性是「标准名 + 释义组」而非只按名：`status`(运单状态) 与 `status`(工单状态) 允许并存，各代表一个概念；但**改名**撞上任何同名活跃标准一律 409 引导合并，防止定版出两个同义标准。
- 释义级（通用名拆组）标准**不**把 `status` 这类裸名沉淀为业务别名，相似提示也跳过 NAME/ALIAS——否则等于把同名不同义又并回一个。
- 治理扫描只纠正释义级标准的成员归属；挂在名级标准下的人工异名归组关系不被自动推翻。
- `STANDARD_MISSING` 按表聚合，缺口清零自动关闭，人工豁免后只有缺口变大才重开。

**状态机**：`standard_field.status` = `DRAFT`（候选）→ `CONFIRMED`（已定版）→ `DEPRECATED`；定版时若发现同义标准则本条转 `MERGED` 并记 `merged_into_id`，存量字段关联迁到目标标准。

---

### 5.1 URN 设计

```
表：    {type}:{cluster}:{database}:{table}
字段：  {type}:{cluster}:{database}:{table}:{column}

示例：
mysql:order_cluster:order_db:t_order
mysql:order_cluster:order_db:t_order:settle_status
```

规则：全部小写；各段不允许含冒号（原始名含冒号时按 `\:` 转义）；通过 query 参数传递（见 M9）。

### 5.2 建表 DDL（PostgreSQL）

> **【修订 A7】** 下方 DDL 中，「采集层」与「支撑层」的表授予 `datadict_collector` 写权限；「知识层」的表对该角色仅 SELECT。

```sql
-- ═══════════ 采集层（机器写入，可被同步覆盖）═══════════

CREATE TABLE data_source (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(64)  NOT NULL UNIQUE,
    name            VARCHAR(128) NOT NULL,
    db_type         VARCHAR(32)  NOT NULL,      -- V1.0: mysql/postgresql/oracle/sqlserver
    env             VARCHAR(16)  NOT NULL,      -- prod/pre/test
    host            VARCHAR(255) NOT NULL,
    port            INT          NOT NULL,
    default_db      VARCHAR(128),
    username        VARCHAR(128) NOT NULL,
    password_cipher TEXT         NOT NULL,
    include_rules   JSONB        DEFAULT '[]',
    exclude_rules   JSONB        DEFAULT '[]',
    sync_cron       VARCHAR(64)  DEFAULT '0 2 * * *',
    group_name      VARCHAR(64),
    enabled         BOOLEAN      DEFAULT TRUE,
    last_sync_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE table_meta (
    id             BIGSERIAL PRIMARY KEY,
    urn            VARCHAR(512) NOT NULL UNIQUE,
    source_id      BIGINT       NOT NULL REFERENCES data_source(id),
    db_name        VARCHAR(128) NOT NULL,
    table_name     VARCHAR(128) NOT NULL,
    table_type     VARCHAR(32)  DEFAULT 'TABLE',
    table_comment  TEXT,
    engine         VARCHAR(32),
    row_count      BIGINT,                      -- 统计估算，禁止 count(*)
    data_size      BIGINT,
    db_created_at  TIMESTAMPTZ,
    -- ↓ V1.5 数仓扩展预留，V1.0 恒为 NULL
    dw_layer       VARCHAR(16),                 -- ODS/DWD/DWS/ADS/DIM
    partition_keys JSONB,
    distribution_keys JSONB,
    sort_keys      JSONB,
    storage_format VARCHAR(32),
    table_model    VARCHAR(32),
    -- ↑ V1.5 预留
    is_deleted     BOOLEAN      DEFAULT FALSE,
    deleted_at     TIMESTAMPTZ,
    synced_at      TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX idx_table_meta_source ON table_meta(source_id, db_name);
CREATE INDEX idx_table_meta_name   ON table_meta(table_name);

CREATE TABLE column_meta (
    id             BIGSERIAL PRIMARY KEY,
    urn            VARCHAR(768) NOT NULL UNIQUE,
    table_urn      VARCHAR(512) NOT NULL,
    column_name    VARCHAR(128) NOT NULL,
    ordinal        INT          NOT NULL,
    raw_type       VARCHAR(128) NOT NULL,
    logical_type   VARCHAR(32)  NOT NULL,
    data_length    INT,
    num_precision  INT,
    num_scale      INT,
    is_nullable    BOOLEAN      DEFAULT TRUE,
    default_value  TEXT,
    raw_comment    TEXT,
    is_primary_key BOOLEAN      DEFAULT FALSE,
    is_auto_incr   BOOLEAN      DEFAULT FALSE,
    is_unique      BOOLEAN      DEFAULT FALSE,
    is_partition_key BOOLEAN    DEFAULT FALSE,  -- V1.5 预留
    is_deleted     BOOLEAN      DEFAULT FALSE,
    deleted_at     TIMESTAMPTZ,
    synced_at      TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX idx_column_meta_table ON column_meta(table_urn);
CREATE INDEX idx_column_meta_name  ON column_meta(column_name, logical_type);

CREATE TABLE index_meta (
    id          BIGSERIAL PRIMARY KEY,
    table_urn   VARCHAR(512) NOT NULL,
    index_name  VARCHAR(128) NOT NULL,
    index_type  VARCHAR(32),
    columns     JSONB        NOT NULL,
    synced_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(table_urn, index_name)
);

-- ═══════════ 知识层（人工写入，采集角色只读）═══════════

CREATE TABLE business_domain (
    id          BIGSERIAL PRIMARY KEY,
    parent_id   BIGINT REFERENCES business_domain(id),
    code        VARCHAR(64)  NOT NULL UNIQUE,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    owner_id    BIGINT,
    sort_order  INT DEFAULT 0,
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE domain_rule (
    id            BIGSERIAL PRIMARY KEY,
    domain_id     BIGINT NOT NULL REFERENCES business_domain(id),
    source_id     BIGINT,
    db_pattern    VARCHAR(128),
    table_pattern VARCHAR(128),
    priority      INT DEFAULT 0,
    enabled       BOOLEAN DEFAULT TRUE
);

CREATE TABLE tag (
    id          BIGSERIAL PRIMARY KEY,
    category    VARCHAR(64)  NOT NULL,
    code        VARCHAR(64)  NOT NULL,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    color       VARCHAR(16),
    exclusive   BOOLEAN DEFAULT FALSE,
    enabled     BOOLEAN DEFAULT TRUE,
    UNIQUE(category, code)
);

CREATE TABLE dict (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(64)  NOT NULL UNIQUE,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    items       JSONB NOT NULL,
    source_type VARCHAR(16) DEFAULT 'MANUAL',   -- MANUAL/CODE_SCAN/IMPORT
    version     INT DEFAULT 1,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE asset_annotation (
    id                    BIGSERIAL PRIMARY KEY,
    urn                   VARCHAR(768) NOT NULL UNIQUE,
    asset_type            VARCHAR(16)  NOT NULL,   -- TABLE/COLUMN
    domain_id             BIGINT REFERENCES business_domain(id),
    business_meaning      TEXT,
    logical_type_override VARCHAR(32),
    dict_id               BIGINT REFERENCES dict(id),
    dict_inline           JSONB,
    sample_value          TEXT,                    -- 人工填写的脱敏示例
    source_desc           TEXT,
    usage_note            TEXT,
    owner_id              BIGINT,
    lifecycle             VARCHAR(16) DEFAULT 'ACTIVE',
    status                VARCHAR(16) DEFAULT 'CONFIRMED',  -- DRAFT/PENDING/CONFIRMED
    source_type           VARCHAR(16) DEFAULT 'MANUAL',     -- MANUAL/RULE/AI/INHERIT
    inherited_from        VARCHAR(768),
    search_text           TEXT GENERATED ALWAYS AS (
                              coalesce(business_meaning,'') || ' ' ||
                              coalesce(usage_note,'')       || ' ' ||
                              coalesce(source_desc,'')
                          ) STORED,
    created_by            BIGINT,
    updated_by            BIGINT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_annotation_domain ON asset_annotation(domain_id);
CREATE INDEX idx_annotation_status ON asset_annotation(status, source_type);

CREATE TABLE asset_tag_rel (
    id         BIGSERIAL PRIMARY KEY,
    urn        VARCHAR(768) NOT NULL,
    tag_id     BIGINT NOT NULL REFERENCES tag(id),
    created_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(urn, tag_id)
);
CREATE INDEX idx_asset_tag_tag ON asset_tag_rel(tag_id);

CREATE TABLE annotation_history (
    id          BIGSERIAL PRIMARY KEY,
    urn         VARCHAR(768) NOT NULL,
    before_data JSONB,
    after_data  JSONB,
    operator_id BIGINT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_anno_hist_urn ON annotation_history(urn, created_at DESC);

-- 【新增 A8】通用字段名黑名单
CREATE TABLE common_column_blacklist (
    id           BIGSERIAL PRIMARY KEY,
    column_name  VARCHAR(128) NOT NULL UNIQUE,
    reason       TEXT,
    is_whitelist BOOLEAN DEFAULT FALSE,      -- true = 确认语义全局一致，可放心批量
    created_by   BIGINT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════ M13 标准定义库（迁移 0007→0010，V0.1 已实现）═══════════
-- 字段统一治理的核心实体，也是业务释义的唯一真相源；属知识层（collector 角色只读）
CREATE TABLE standard_field (
    id                BIGSERIAL PRIMARY KEY,
    standard_name     VARCHAR(128) NOT NULL,   -- 标准字段名，可被人工改名定版
    cluster_key       VARCHAR(128),            -- 候选来源字段名：改名/合并后重聚仍按它匹配，不复活重复候选
    sub_key           VARCHAR(32)  NOT NULL DEFAULT '',
        -- 通用字段名（status/type 等）同名不同义时按注释释义拆组的哈希；'' = 按字段名整体定标
    merged_into_id    BIGINT REFERENCES standard_field(id),  -- 同义候选归并的目标标准
    business_meaning  TEXT,                    -- 标准中文释义（唯一权威释义挂在这里，不挂字段上）
    logical_type      VARCHAR(32)  NOT NULL,
    raw_type          VARCHAR(128),            -- 标准类型含长度，如 varchar(16)；冲突组定版前为空
    status            VARCHAR(16) DEFAULT 'DRAFT',     -- DRAFT / CONFIRMED / DEPRECATED / MERGED
    source_type       VARCHAR(16) DEFAULT 'CLUSTER',   -- CLUSTER / IMPORT / MANUAL
    has_conflict      BOOLEAN DEFAULT FALSE,           -- 组内逻辑类型不一致，必须人工裁决
    type_distribution JSONB,                           -- {原始类型: 出现次数}，两路证据合并后的分布
    candidate_count   INTEGER DEFAULT 0,               -- 源库同步中出现次数
    doc_count         INTEGER DEFAULT 0,               -- Excel 文档中出现次数（并集的另一路）
    version           INTEGER DEFAULT 1,
    confirmed_by      BIGINT,
    confirmed_at      TIMESTAMPTZ,
    created_by        BIGINT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
-- 同名标准唯一性按「标准名 + 释义组」：status(运单状态) 与 status(工单状态) 可并存，各自不能重复
CREATE UNIQUE INDEX uq_standard_field_active_name_sub ON standard_field(standard_name, sub_key)
    WHERE status IN ('DRAFT', 'CONFIRMED');
CREATE INDEX idx_standard_field_status ON standard_field(status);
CREATE INDEX idx_standard_field_cluster_sub ON standard_field(cluster_key, sub_key);

-- 标准与存量源字段的关联；conforms = 字段名与类型**都**符合标准（异名或异型都算不符合）
CREATE TABLE standard_field_item (
    id                BIGSERIAL PRIMARY KEY,
    standard_field_id BIGINT NOT NULL REFERENCES standard_field(id),
    column_urn        VARCHAR(768) NOT NULL,
    conforms          BOOLEAN,                    -- 未定版时为 NULL
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(standard_field_id, column_urn)
);
CREATE INDEX idx_standard_field_item_urn ON standard_field_item(column_urn);

-- Excel 历史数据字典的字段文档留档：与 column_meta 平级的第二路输入，按 source_file 幂等
CREATE TABLE excel_field_doc (
    id           BIGSERIAL PRIMARY KEY,
    source_file  VARCHAR(255) NOT NULL,
    sheet_name   VARCHAR(128),
    table_name   VARCHAR(128) NOT NULL,
    table_desc   TEXT,
    column_name  VARCHAR(128) NOT NULL,
    column_desc  TEXT,
    column_type  VARCHAR(128),
    remark       TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_excel_doc_column ON excel_field_doc(column_name);
CREATE INDEX idx_excel_doc_table ON excel_field_doc(table_name, column_name);
CREATE INDEX idx_excel_doc_file ON excel_field_doc(source_file);

-- 【新增 B④】向量索引
CREATE TABLE asset_embedding (
    urn         VARCHAR(768) PRIMARY KEY,
    asset_type  VARCHAR(16)  NOT NULL,
    corpus_text TEXT         NOT NULL,
    embedding   vector(512)  NOT NULL,
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX idx_emb_hnsw ON asset_embedding USING hnsw (embedding vector_cosine_ops);

-- ═══════════ 支撑层 ═══════════

CREATE TABLE schema_change_log (
    id               BIGSERIAL PRIMARY KEY,
    urn              VARCHAR(768) NOT NULL,
    table_urn        VARCHAR(512),
    asset_type       VARCHAR(16),
    change_type      VARCHAR(32) NOT NULL,
    before_value     JSONB,
    after_value      JSONB,
    rename_candidate VARCHAR(768),
    rename_status    VARCHAR(16),           -- PENDING/CONFIRMED/REJECTED
    detected_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_change_time  ON schema_change_log(detected_at DESC);
CREATE INDEX idx_change_table ON schema_change_log(table_urn);

CREATE TABLE sync_job_log (
    id             BIGSERIAL PRIMARY KEY,
    source_id      BIGINT NOT NULL,
    trigger_type   VARCHAR(16),
    status         VARCHAR(16),            -- RUNNING/SUCCESS/FAILED/PARTIAL
    scanned_tables INT DEFAULT 0,
    changed_count  INT DEFAULT 0,
    fail_count     INT DEFAULT 0,
    comment_fill_rate NUMERIC(5,2),        -- 注释非空率，用于 A3 兜底监控
    error_msg      TEXT,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    duration_ms    BIGINT
);

-- 【新增】同步失败明细（M2-6）
CREATE TABLE sync_fail_detail (
    id          BIGSERIAL PRIMARY KEY,
    job_id      BIGINT NOT NULL REFERENCES sync_job_log(id),
    source_id   BIGINT NOT NULL,
    db_name     VARCHAR(128),
    table_name  VARCHAR(128),
    stage       VARCHAR(32),               -- CONNECT/LIST_TABLE/LIST_COLUMN/LIST_INDEX/WRITE
    error_type  VARCHAR(64),
    error_msg   TEXT,
    retry_count INT DEFAULT 0,
    resolved    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_fail_job ON sync_fail_detail(job_id, resolved);

-- 【新增 A2】浏览日志
CREATE TABLE view_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT,
    urn        VARCHAR(768) NOT NULL,
    asset_type VARCHAR(16),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_view_urn  ON view_log(urn, created_at DESC);
CREATE INDEX idx_view_user ON view_log(user_id, created_at DESC);

-- 【修订 A2 / v1.2 调整】搜索日志与点击埋点拆表
-- v1.1 把 clicked_urn 直接放在 search_log 上，一次搜索一行、点击时回写。
-- 问题：用户常连点多个结果，后一次 UPDATE 覆盖前一次，
--       M11-7「平均点击位次」会系统性偏向最后一次点击，指标失真。
CREATE TABLE search_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT,
    keyword     VARCHAR(255),
    result_cnt  INT,
    search_type VARCHAR(16) DEFAULT 'KEYWORD',  -- KEYWORD/SEMANTIC
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_search_kw ON search_log(keyword, created_at DESC);

CREATE TABLE search_click (
    id         BIGSERIAL PRIMARY KEY,
    search_id  BIGINT NOT NULL REFERENCES search_log(id),
    urn        VARCHAR(768) NOT NULL,
    rank       INT NOT NULL,               -- 点击位次，用于评估排序质量
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_click_search ON search_click(search_id);

-- M11-7 统计口径（明确写入看板说明，避免歧义）：
--   点击率     = 有至少一次点击的搜索数 / 总搜索数
--   无点击率   = 1 - 点击率（无结果搜索单独统计，不混入）
--   平均点击位次 = 每次搜索取 min(rank) 后求平均（首个点击位次，反映排序质量）

-- 【新增】变更订阅（M3-6）
CREATE TABLE change_subscription (
    id            BIGSERIAL PRIMARY KEY,
    scope_type    VARCHAR(16) NOT NULL,    -- SOURCE/DOMAIN/TABLE
    scope_value   VARCHAR(768) NOT NULL,
    change_types  JSONB DEFAULT '["COL_ADD","COL_DROP","COL_TYPE_CHANGE"]',
    channel       VARCHAR(16) NOT NULL,    -- WECOM/DINGTALK/EMAIL/WEBHOOK
    target        TEXT NOT NULL,           -- webhook url / 群 id / 邮箱
    subscriber_id BIGINT,
    enabled       BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sub_scope ON change_subscription(scope_type, scope_value) WHERE enabled;

-- 【新增】标注待办（M6-4-1）
CREATE TABLE annotation_todo (
    id           BIGSERIAL PRIMARY KEY,
    urn          VARCHAR(768) NOT NULL,
    todo_type    VARCHAR(32) NOT NULL,     -- 已实现：STANDARD_CONFLICT(urn=字段，类型与标准不一致) /
                                          -- STANDARD_MISSING(urn=**表**，该表仍有字段未关联已定版标准，按表聚合防刷屏)
                                          -- 规划：NEW_COLUMN/REVIEW_DRAFT/CONFIRM_RENAME/MERGE_CONFLICT/HANDLE_FEEDBACK/MISSING_DICT
    domain_id    BIGINT,
    assignee_id  BIGINT,
    priority     INT DEFAULT 0,
    status       VARCHAR(16) DEFAULT 'OPEN',   -- OPEN/DONE/IGNORED
    payload      JSONB,                        -- 类型相关的附加数据
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    done_at      TIMESTAMPTZ
    -- 【v1.2 修正】原 UNIQUE(urn, todo_type, status) 会在同类待办第二次完成时违约：
    --   ① 字段 A 新增 → (A, NEW_COLUMN, OPEN)
    --   ② 完成 → UPDATE status='DONE'，表中留下 (A, NEW_COLUMN, DONE)
    --   ③ 字段 A 再次变更 → 又生成 (A, NEW_COLUMN, OPEN)，不冲突
    --   ④ 再次完成 → UPDATE status='DONE' → 与 ② 遗留的行冲突，事务失败
    -- 这与 A5（asset_annotation.urn UNIQUE 撞重命名迁移）是同一类问题：
    -- 用唯一约束去表达一个随状态流转的关系。改用部分唯一索引。
);
-- 语义："同一 urn + todo_type 同时只能有一个未完成的待办"
CREATE UNIQUE INDEX uq_todo_open ON annotation_todo(urn, todo_type)
    WHERE status = 'OPEN';
CREATE INDEX idx_todo_assignee ON annotation_todo(assignee_id, status);
CREATE INDEX idx_todo_domain   ON annotation_todo(domain_id, status);

CREATE TABLE sys_user (
    id         BIGSERIAL PRIMARY KEY,
    username   VARCHAR(64) NOT NULL UNIQUE,
    real_name  VARCHAR(64),
    email      VARCHAR(128),
    enabled    BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_role (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL,
    role      VARCHAR(32) NOT NULL,        -- VIEWER/ANNOTATOR/DOMAIN_ADMIN/ADMIN
    domain_id BIGINT,
    UNIQUE(user_id, role, domain_id)
);

CREATE TABLE api_key (
    id         BIGSERIAL PRIMARY KEY,
    key_name   VARCHAR(128) NOT NULL,
    key_hash   VARCHAR(128) NOT NULL UNIQUE,
    scopes     JSONB DEFAULT '["read"]',
    rate_limit INT DEFAULT 1000,
    enabled    BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_favorite (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    urn        VARCHAR(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, urn)
);

CREATE TABLE feedback (
    id          BIGSERIAL PRIMARY KEY,
    urn         VARCHAR(768) NOT NULL,
    content     TEXT NOT NULL,
    status      VARCHAR(16) DEFAULT 'OPEN',
    reporter_id BIGINT,
    handler_id  BIGINT,
    handled_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 5.3 检索索引与统一视图

见 §M4-7（`v_column_effective`）与 §M8 开头（pg_trgm 生成列）。两者是全系统查询的唯一入口，**禁止绕过**。

---

## 六、技术架构

### 6.1 技术选型

> **【修订 B③】** 原评审建议"技术栈瘦身"的前提是无既有基础设施。经确认 Redis / K8s / Prometheus 均已具备且可直接复用，故恢复原方案——复用成熟基础设施的边际运维成本为零，且直接获得告警、伸缩、可观测能力。

| 层次 | 选型 | 说明 |
|---|---|---|
| Web 框架 | **FastAPI** | 自动 OpenAPI、Pydantic 校验、异步性能 |
| ORM | **SQLAlchemy 2.0** + Alembic | 需同时配置 async 和 sync session（sync 供 embedding 路由使用） |
| 数据校验 | **Pydantic v2** | — |
| 元数据库 | **PostgreSQL 15+** | 需扩展：`pg_trgm`、`vector`（V1.0 语义检索） |
| 缓存/队列 | **Redis**（复用既有） | 热点缓存、分布式锁、限流、embedding 重算队列 |
| 任务调度 | **APScheduler** | 场景是"每天几十个数据源各跑一次"，够用。**Celery 推迟到 V1.0 之后**——不是为省组件，是避免 MVP 阶段引入分布式调试复杂度 |
| 数据库驱动 | pymysql / asyncpg / oracledb / pymssql | V1.0 四种 |
| Embedding | sentence-transformers + bge-small-zh-v1.5 | 见 §M9 语义检索的两个工程坑 |
| 前端 | **React 18 + TypeScript + Ant Design 5** | 表格/树/标签组件开箱即用 |
| 前端状态 | TanStack Query + Zustand | — |
| 部署 | **K8s**（复用既有） | Web / Collector / Embedding 三个 Deployment |
| 监控 | **Prometheus + Grafana**（复用既有） | 暴露 `/metrics` |
| 日志 | Loguru → 既有 ELK | — |

**K8s 部署拆分建议**

| Deployment | 副本 | DB 角色 | 说明 |
|---|---|---|---|
| `datadict-web` | 2+ | `datadict_web` | API + 前端静态资源 |
| `datadict-collector` | 1 | `datadict_collector` | 采集调度，单副本 + PG advisory lock 双保险 |
| `datadict-embedding` | 1~2 | `datadict_web`（只读为主） | 独立部署避免模型内存乘以 web 副本数 |

### 6.2 项目结构

```
datadict/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py              # 双 DB_URL 配置
│   │   ├── security.py            # JWT / API Key
│   │   ├── crypto.py              # 凭证加解密
│   │   ├── deps.py                # 依赖注入、权限校验
│   │   └── exceptions.py
│   ├── db/
│   │   ├── session.py             # web_session / collector_session 两套
│   │   └── base.py
│   ├── models/
│   │   ├── datasource.py
│   │   ├── metadata.py
│   │   ├── annotation.py
│   │   ├── change.py
│   │   └── system.py
│   ├── schemas/
│   ├── api/v1/
│   │   ├── router.py
│   │   └── endpoints/
│   │       ├── datasources.py  tables.py     columns.py
│   │       ├── search.py       semantic.py   domains.py
│   │       ├── tags.py         dicts.py      annotations.py
│   │       ├── todos.py        changes.py    subscriptions.py
│   │       ├── security.py     dashboard.py  admin.py
│   ├── services/
│   │   ├── sync_service.py
│   │   ├── diff_service.py        # 变更检测 + 重命名识别 + 合并策略
│   │   ├── annotation_service.py  # 批量标注、同名聚合、黑名单校验
│   │   ├── rule_service.py
│   │   ├── search_service.py      # 关键词检索
│   │   ├── embedding_service.py   # 向量化与语义检索
│   │   ├── todo_service.py
│   │   └── notify_service.py
│   ├── collectors/
│   │   ├── base.py                # BaseCollector 抽象类
│   │   ├── mysql.py  postgresql.py  oracle.py  sqlserver.py
│   │   ├── registry.py
│   │   └── type_mapper.py
│   ├── tasks/
│   │   ├── scheduler.py
│   │   └── jobs.py
│   └── utils/
├── alembic/
├── tests/
│   ├── collectors/                # 含注释非空断言测试（A3）
│   ├── security/                  # 含采集角色权限测试（A7）
│   └── fixtures/                  # 各库带中文注释的 fixture
├── frontend/
├── deploy/                        # K8s manifests
└── pyproject.toml
```

### 6.3 采集器扩展点

```python
# app/collectors/base.py
from abc import ABC, abstractmethod

class BaseCollector(ABC):
    """所有采集器的抽象基类。全部方法只读，禁止任何业务表查询。"""

    def __init__(self, config: DataSourceConfig):
        self.config = config

    @abstractmethod
    async def test_connection(self) -> bool: ...

    @abstractmethod
    async def list_databases(self) -> list[DatabaseInfo]: ...

    @abstractmethod
    async def list_tables(self, db_name: str) -> list[TableInfo]:
        """必须包含 table_comment，取法见 M2 注释对照表"""

    @abstractmethod
    async def list_columns(self, db_name: str) -> list[ColumnInfo]:
        """一次拉取整库字段，禁止逐表查询。
        必须包含 raw_comment，取法见 M2 注释对照表。"""

    @abstractmethod
    async def list_indexes(self, db_name: str) -> list[IndexInfo]: ...

    @abstractmethod
    def normalize_type(self, raw_type: str) -> str: ...
```

**新增采集器的准入 checklist**（写进开发规范）

- [ ] 实现全部抽象方法
- [ ] 类型映射表覆盖该库常见类型
- [ ] 准备带中文注释的 fixture 库
- [ ] `test_comment_not_all_empty` 通过
- [ ] 确认采集 SQL 不含任何业务表查询
- [ ] 确认已在 `registry` 注册
- [ ] 在预发环境跑通一轮全量同步

### 6.4 同步幂等与并发控制

- Redis 分布式锁（同数据源互斥）+ PG advisory lock 兜底
- Upsert 采用 `INSERT ... ON CONFLICT (urn) DO UPDATE`，天然幂等
- **采集服务使用 `datadict_collector` 角色，对标注表无写权限——这是数据库强制的，非代码约定**
- 大库分批提交，每批 1000 条

---

## 七、非功能需求

> **【修订 A10】** 承载指标按真实规模重定：真实约数千张表 / 数十万字段，留 2 倍余量。
>
> **【v1.2 待校准】** 此前口头确认的规模是「数千表 / **数万**字段」，与本表的「数十万字段」
> 相差约 10 倍。按数千表（取 5000）× 平均 40 字段 ≈ 20 万字段推算，本表数字更合理，
> 但**必须在 V0.1 采集跑通后用实数替换**，并连带复核下面两项：
> - 50 万字段规模下，GIN trigram 索引体积与 `P95 < 500ms` 是否成立
> - 阈值调到 0.1 会显著放大候选集，**调优时必须同时看召回率和延迟**，不能只看召回

| 维度 | 指标 |
|---|---|
| **承载规模** | **1 万张表 / 50 万字段 / 50 个数据源**（待 V0.1 实测校准） |
| 搜索响应 | P95 < 500ms |
| 语义检索响应 | P95 < 1s（含 embedding 推理） |
| 表详情页加载 | P95 < 300ms |
| API 响应 | P95 < 200ms（单表查询） |
| 同步性能 | 单库 500 张表全量采集 < 3 分钟 |
| **生产库影响** | 采集期间 QPS 增量 < 10，无锁等待，**零业务表查询** |
| 可用性 | 99.5% |
| 浏览器兼容 | Chrome / Edge 最近两个大版本 |

---

## 八、迭代路线图

### V0.1 — MVP（3~4 周）

**目标**：跑通全链路，验证价值，**并立即开始积累变更流水**

- M1 数据源管理（MySQL + PostgreSQL）
- M2 元数据采集与同步 + **注释采集断言测试**
- **M3-1/M3-2 变更检测与落库（后端，无 UI）** ← 前移
- M8 基础搜索（pg_trgm）+ 表详情页 + 字段列表
- **pg_trgm 相似度阈值实测调优** ← 必做
- M9 基础查询 API（5 个接口）
- M6 单字段标注 + 表内批量标注
- **M10-8 数据库角色隔离 + `deploy/grants.sql` 纳入迁移流程** ← 从第一天就落地，后补代价大
- 简单登录
- **【v1.2】提交 Oracle `SELECT ANY DICTIONARY` / SQL Server `VIEW DEFINITION` 权限申请**
  ← 审批要走流程，等 V1.0 才提会直接卡住排期

**验收标准**
- 接入 2 个核心生产库，团队成员能查到字段并看到人工标注
- 注释非空率符合预期（对照源库人工抽查 20 张表）
- `test_collector_cannot_write_annotation` 通过
- **产出去重率实测数据，据此填定 V0.5 验收标准**

### V0.5 — 标注提效（4~5 周）

- M6-2③ 同名字段聚合标注 + **通用字段名黑名单**
- M6-2④ 规则引擎自动标注
- M4 业务域管理 + 归属规则 + `v_column_effective` 视图
- M5 标签体系
- M7 数据字典（人工录入）
- M3-3/M3-4 重命名识别 + 标注继承合并策略
- M3-5 变更时间线 UI
- M6-4 标注任务管理（含 `annotation_todo`）
- M11 覆盖率看板
- Excel 导入导出

**验收标准**：核心域标注覆盖率 60%；单人日均标注量 **待 V0.1 实测后填定**。

### V1.0 — 完整交付（4~5 周）

- 补齐 Oracle / SQL Server 采集器
- M7-3 代码仓库枚举解析
- M9 完整开放 API + **语义检索（pgvector）** + Python SDK
- M10 完整 RBAC + API Key + 审计日志
- M8-3 生成代码、结构对比、纠错反馈
- M3-6 变更订阅通知
- M11 完整运营看板（含搜索质量）
- M12 监控接入 Prometheus

**验收标准**
- 全部业务系统数据源接入，整体字段标注覆盖率 > 70%
- 至少 2 个内部系统通过 API 接入
- 语义检索仅对覆盖率 ≥70% 的域开启，其余降级

### V1.5 — 数仓侧（单独一期，独立评估）

- 数据模型扩展：分区键、分桶键、排序键、存储格式、表模型、数仓分层
- 采集器：Doris / StarRocks（复用 MySQL 采集器 + 类型映射）、ClickHouse（`system.*`）、Hive（Metastore 直读）
- 数仓分层自动识别与筛选维度
- 字段名黑名单补充数仓专属项（`dt`、`ds`、`pt`、`etl_time` 等）

### V2.0 — 演进方向

- 数据血缘（SQL 解析构建表级/字段级血缘）——数仓侧的真正核心痛点
- 与数据权限系统、脱敏中间件深度集成
- MCP Server 形态，供 AI 编码助手直接接入
- 影响分析（改这个字段影响哪些下游）

---

## 九、风险与应对

| 风险 | 影响 | 应对措施 |
|---|---|---|
| **标注推不动，覆盖率长期低位** | 项目沦为"表结构查看器" | ① 高层背书，覆盖率纳入团队季度目标 ② 域管理员责任到人 ③ 排行榜 ④ 优先标注高频表 ⑤ 规则引擎降低人工成本 |
| **注释采集静默失败** | 采集"成功"但注释全空，用户白做大量标注 | ① 各库注释取法对照表 ② 强制断言测试纳入 CI ③ 注释非空率运行时监控 + 告警 |
| **批量标注注入错误知识** | 比空白危害更大，摧毁知识库可信度 | ① 通用字段名黑名单 ② 命中时移除批量按钮 ③ 自动检测候选黑名单项 |
| **标注被同步覆盖** | 不可恢复的人力损失 | ① 独立 DB role + 只授 SELECT ② CI 权限测试 ③ 全量标注变更留痕 |
| **采集影响生产库** | 生产事故 | ① 只读账号，权限最小化 ② 避开高峰 ③ 限流 ④ 禁止 count(*) ⑤ 零业务表查询 ⑥ 超时熔断 |
| **凭证泄露** | 安全事故 | ① 加密存储 ② 不回显 ③ 密钥管理系统 ④ 定期轮换 ⑤ 审计 |
| **字段重命名致标注丢失** | 知识资产流失 | ① 重命名识别 + 人工确认 ② 合并策略（含唯一约束处理） ③ 软删除 90 天 ④ 孤儿标注巡检 |
| **中文检索召回率差** | 搜不到，使用率低 | ① V0.1 实测调阈值 ② 同义词配置 ③ 无结果词反哺标注优先级 ④ 点击埋点评估质量 |
| **语义检索效果不及预期** | V1.0 功能落空 | ① 硬性前置：覆盖率 ≥70% 才开启 ② 未达标自动降级 ③ 语料用业务语言而非 schema |
| **embedding 阻塞 event loop** | 服务整体卡死 | ① 用普通 def 路由或 run_in_executor ② 独立 Deployment ③ 压测验证 |
| **标注质量参差** | 知识库不可信 | ① 标注规范 + 示例 ② 核心域二次审核 ③ 纠错闭环 ④ 定期抽查 |

---

## 十、启动前必须完成的三件事

1. **业务域清单先定**——拉各业务线负责人开一次会，定下一级/二级业务域。这是知识库骨架，中途返工代价极大。
2. **明确标注责任人**——每个域必须有明确负责人，且投入被其主管认可。没有这个，产品做得再好也是空壳。
3. **选定 MVP 试点域**——挑数据规范度好、负责人配合度高的域（通常是交易域或用户域）做试点，拿到第一个成功案例再推广。

---

## 附录 A：修订清单（v1.0 → v1.1）

| # | 位置 | 问题 | 修订 |
|---|---|---|---|
| A1 | §5.3 / M4-7 | 搜索视图只 JOIN 字段级标注，但字段业务域继承自表 → 按域筛选形同虚设 | 新增 `v_column_effective` 视图，`COALESCE(ca.domain_id, ta.domain_id)`，禁止各处手写 |
| A2 | §5.2 / M8 | 热度排序、最近浏览、热门表依赖浏览记录，但无该表 | 新增 `view_log`；`search_log` 增加 `clicked_urn` / `clicked_rank` |
| A3 | M2 | 缺各库注释取法差异，实现不到位会静默丢失全部注释 | 补对照表 + PG 参考 SQL + 强制断言测试 + 非空率运行时监控 |
| A4 | M1-1 | 支持清单含 MongoDB（schema-less，无对应设计） | 删除 MongoDB；数仓类（Hive/Doris/SR/CK）移至 V1.5，数据模型预留字段 |
| A5 | M3-4 | `urn` UNIQUE，重命名迁移若目标已有标注则 UPDATE 违约 | 定义按 `source_type` 分流的合并策略；先删后插 + `flush()` |
| A6 | §8 | 变更检测排 V0.5，V0.1 已跑同步 → 4~5 周变更流水永久丢失 | diff + 写 `schema_change_log` 前移 V0.1，UI 留 V0.5 |
| A7 | §6.4 / M10-8 | 称"物理不可能触碰标注表"，实为代码纪律 | 独立 `datadict_collector` role，标注表只授 SELECT；CI 权限测试 |
| A8 | M6-2③ | `status`/`type`/`name` 等通用名类型相同语义不同，一键批量注入错误 | 新增 `common_column_blacklist`，命中时移除批量按钮，强制逐表确认 |
| A9 | M6 | "6000~8000 单元""降低 85%""日均 300 字段"均无依据 | 删除全部预估，改为 V0.1 实测 SQL，V0.5 标准待实测后填 |
| A10 | §7 | 表数高估约 5 倍（字段数属合理余量） | 重定为 1 万表 / 50 万字段 |
| B① | §5.3 / M8 | zhparser 部署受限，物化视图有刷新延迟 | 改 pg_trgm + 生成列；明确两表分列的代价与合并查询；阈值须实测 |
| B② | §1.3 / M6.3 / M7 | "绝不触碰业务数据"与"样例枚举值分布"矛盾 | 删除采样输入；枚举改代码仓库解析（进候选队列）+ 人工录入 |
| B③ | §6.1 | 原建议技术栈瘦身 | **不采纳**——Redis/K8s/Prometheus 为既有可复用基础设施；仅 Celery 推迟 |
| B④ | M9 | 语义检索排 V1.0 但无向量组件方案 | 补 pgvector 方案；业务语言语料；覆盖率 ≥70% 硬前置；内存与阻塞两个工程坑 |
| 补1 | M3-6 / §5.2 | 变更订阅无配置表 | 新增 `change_subscription` |
| 补2 | M2-6 / §5.2 | 失败重试无明细表 | 新增 `sync_fail_detail` |
| 补3 | M6-4-1 / §5.2 | 我的待办无支撑表 | 新增 `annotation_todo` |
| 补4 | M9 | URN 含冒号放 path 有风险 | 统一改 query 参数 + Pydantic 格式校验 |

## 附录 B：修订清单（v1.1 → v1.2）

| # | 级别 | 位置 | 问题 | 修订 |
|---|---|---|---|---|
| C1 | **P0** | M8 检索阈值 | `SET pg_trgm.similarity_threshold` 是会话级 GUC，连接池下会漂移 → 同一查询命中不同连接时召回数量不同，表现为间歇性不可复现 | 改 `ALTER DATABASE ... SET`，写进 Alembic 迁移；动态调整用 `SET LOCAL` 且必须在显式事务内 |
| C2 | **P0** | M4-7 视图 | `v_column_effective` 硬编码 `WHERE is_deleted = FALSE`，与「禁止绕过视图」的约定冲突，导致软删除恢复、孤儿巡检、变更时间线、显示已下线字段四项功能无法实现 | 视图去掉该过滤，`is_deleted` 作为普通列暴露，调用方按需过滤；补「表删除时字段级联置位」规则 |
| C3 | **P0** | §5.2 `annotation_todo` | `UNIQUE(urn, todo_type, status)` 在同类待办第二次完成时违约（与 A5 同型问题：用唯一约束表达状态流转关系） | 改部分唯一索引 `UNIQUE(urn, todo_type) WHERE status='OPEN'` |
| C4 | **P0** | M10-8 授权 | `GRANT ... ON ALL TABLES IN SCHEMA` 是快照授权，每次迁移新建表后两角色均无权限 | web 角色加 `ALTER DEFAULT PRIVILEGES`；collector 分层授权维护为幂等 `deploy/grants.sql` 并纳入迁移收尾；补「新表漏授权」反向测试 |
| C5 | **P0** | M1 权限表 | Oracle `ALL_*` 视图按当前用户过滤，只授其 SELECT 只能采到自身 schema，且**连接成功/SQL成功/任务 SUCCESS/无数据**，极具迷惑性 | 改 `SELECT ANY DICTIONARY`（或 `SELECT_CATALOG_ROLE`）+ 走 `DBA_*` 视图；权限申请提前到 V0.1 |
| C6 | P1 | M8 检索 SQL | `:q`（SQLAlchemy 命名参数）与 `%%`（psycopg2 转义）驱动假设冲突，asyncpg 下必踩 | 改用 SQLAlchemy Core 表达式，转义交给驱动层 |
| C7 | P1 | §5.2 `search_log` | 单行记录点击，多次点击互相覆盖 → 平均点击位次系统性失真 | 拆出 `search_click` 表；明确 M11-7 三项统计口径 |
| C8 | P1 | M10-2 / 权限矩阵 | 「游客」角色残留，其"部分可见"始终未定义 | 删除游客角色；权限矩阵补「查看 L3 取值示例」一行 |
| C9 | P1 | §7 | 承载规模 1 万表/50 万字段 与口头确认的「数千表/数万字段」相差约 10 倍 | 标记为待 V0.1 实测校准；连带复核 GIN 索引体积与低阈值下的延迟 |
| C10 | P1 | §1.4 | 数仓移至 V1.5 的**时间代价**未写明，相关方易误判节奏 | 明写「数仓侧至少 3 个月内不被服务」；记录「最小只读接入」方案已评估并放弃的理由 |

---

*文档结束*
