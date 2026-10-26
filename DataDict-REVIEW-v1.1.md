# v1.1 评审

评审对象：`DataDict-PRD.md`（评审时为 v1.1）
结论：v1.0 的 14 项问题都已正确修订，方案可以进入开发。下列 **5 项 P0 会在运行期暴露**，
其中 3 项是数据库层的隐蔽问题，建议开发前改掉。

> 说明：本轮未自动修改 PRD，逐条讨论后再定。

---

## P0-1 `SET pg_trgm.similarity_threshold` 在连接池下会漂移 ★最隐蔽

**位置**：§M8「中文短查询必须实测阈值」，line 643

```sql
SET pg_trgm.similarity_threshold = 0.1;   -- 起始值，必须实测调优
```

**问题**：`SET` 是**会话级 GUC**，作用于当前连接，并在该连接归还连接池后**继续保留**。
在 SQLAlchemy 连接池下的实际表现是：

- 执行过这条 `SET` 的连接，阈值 = 0.1
- 从未执行过的连接，阈值 = 默认 0.3
- 同一个查询，命中不同连接时**召回结果数量不同**

这类 bug 的特征是**间歇性、不可复现**：测试环境单连接跑得好好的，生产多连接后用户反馈
"同样的词有时搜得到有时搜不到"，排查方向会完全跑偏到分词、索引、缓存上。

**改法**：改为数据库级持久配置，写进 Alembic 迁移。

```sql
-- 迁移脚本中执行，对所有新建连接生效
ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1;
```

需要按查询动态调阈值时，用 `SET LOCAL` 并**确保在显式事务内**（`SET LOCAL` 在事务结束时
自动回滚，不会污染连接）。

---

## P0-2 `v_column_effective` 硬编码 `is_deleted = FALSE`，与「禁止绕过视图」的约定冲突

**位置**：§M4-7，line 387 与 line 390

```sql
LEFT JOIN business_domain d ON d.id = COALESCE(ca.domain_id, ta.domain_id)
WHERE c.is_deleted = FALSE;          -- ← 视图内硬编码
```

> line 390：「M8 搜索、M9 API、M11 看板的所有覆盖率统计，一律基于 `v_column_effective`。
> 代码评审中出现手写 `JOIN asset_annotation` 的一律打回。」

**问题**：视图把已下线字段永久排除，但下列功能**必须**访问 `is_deleted = TRUE` 的行：

| 功能 | 位置 |
|---|---|
| 软删除与恢复（字段重现自动恢复标注） | M3-8 |
| 孤儿标注巡检 | §9 风险表 |
| 变更时间线（要展示已删除字段的历史） | M3-5 |
| 表详情页「显示已下线字段」 | M8-2-3 |

这些功能要么绕过视图（违反约定、被评审打回），要么做不了。**约定与视图定义互相矛盾。**

**改法**：视图**不过滤** `is_deleted`，把它作为一个列暴露出去，由调用方按需过滤。

```sql
CREATE OR REPLACE VIEW v_column_effective AS
SELECT ..., c.is_deleted, c.deleted_at, ...
FROM column_meta c
JOIN table_meta t ON ...
-- 无 WHERE 子句
```

搜索/覆盖率统计侧统一加 `WHERE NOT is_deleted`。这样约定仍然成立（域继承逻辑只有一处），
同时不牺牲软删除相关功能。

> 补充：`t.is_deleted`（表被删）在当前视图里也完全没体现——表删了它的字段
> `column_meta.is_deleted` 未必同步置位，需要在 diff 逻辑里明确级联规则。

---

## P0-3 `annotation_todo` 的唯一约束会在第二次完成同类待办时炸掉

**位置**：§5.2，line 1341

```sql
UNIQUE(urn, todo_type, status)
```

**问题**：`status ∈ {OPEN, DONE, IGNORED}`。这条约束的真实含义是
「同一 urn + todo_type，每种状态最多一行」。

失败场景：

1. 字段 A 新增 → 生成 `(A, NEW_COLUMN, OPEN)`
2. 标注完成 → `UPDATE status='DONE'` → 表中存在 `(A, NEW_COLUMN, DONE)`
3. 字段 A 后续又变更 → 再生成 `(A, NEW_COLUMN, OPEN)`，✅ 不冲突
4. 再次完成 → `UPDATE status='DONE'` → **与第 2 步遗留的 DONE 行冲突，事务失败**

这和 A5（`asset_annotation.urn` UNIQUE 撞重命名迁移）是**完全同一类 bug**——
用唯一约束去表达一个随状态流转的关系。A5 已经修了，这里是漏网的同型问题。

**改法**：用**部分唯一索引**，只约束"同时只能有一个未完成"：

```sql
-- 去掉表定义里的 UNIQUE(urn, todo_type, status)
CREATE UNIQUE INDEX uq_todo_open ON annotation_todo(urn, todo_type)
    WHERE status = 'OPEN';
```

历史 DONE/IGNORED 记录可自由累积，正好也是待办审计需要的。

---

## P0-4 `GRANT ALL ON ALL TABLES` 是快照授权，新建表无权限

**位置**：§M10-8，line 928-950

```sql
GRANT SELECT, INSERT, UPDATE ON table_meta, column_meta, ... TO datadict_collector;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO datadict_web;
```

**问题**：`ON ALL TABLES IN SCHEMA` 只对**执行时已存在**的表生效，不是规则。
**每次 Alembic 迁移新建表后，两个角色对新表都没有任何权限**，应用运行时直接
`permission denied`。

这个坑在 V0.1 不明显（建表和授权同时做），会在后续每一次加表迁移时复现，
而且报错位置离根因很远。

**改法**：

```sql
-- web 角色：默认权限规则，后续新建表自动继承
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO datadict_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO datadict_web;
```

collector 角色的权限是**按表分层的**（采集层可写 / 知识层只读），无法用默认权限表达，
因此必须：

1. 把授权语句维护成一个**幂等的 `grants.sql`**
2. **纳入 Alembic 迁移的收尾步骤**或部署流水线，每次迁移后自动重跑
3. 现有的 `test_collector_cannot_write_annotation` 只能捕获"权限过大"，
   建议**补一个反向测试**捕获"权限缺失"：

```python
async def test_collector_can_write_collection_tables(collector_session):
    """采集角色对采集层表必须可写——防止新表漏授权"""
    for tbl in ['table_meta', 'column_meta', 'index_meta',
                'schema_change_log', 'sync_job_log', 'sync_fail_detail']:
        await collector_session.execute(text(f"SELECT 1 FROM {tbl} LIMIT 1"))
        # 用回滚事务验证写权限
```

---

## P0-5 Oracle 权限要求写错了，V1.0 接 Oracle 时会采到空数据

**位置**：§M1「采集账号权限要求」，line 155

```
| Oracle | SELECT ON ALL_TABLES / ALL_TAB_COLUMNS / ALL_COL_COMMENTS / ... |
```

**问题**：Oracle 的 `ALL_*` 数据字典视图，语义是
**「当前用户有访问权限的对象」**——视图内部已经按当前用户权限做了过滤。

所以给采集账号 `GRANT SELECT ON ALL_TAB_COLUMNS` 之后，它查这个视图**能查成功**，
但返回的只有该账号自己 schema 下的对象，**其他业务 schema 的表一张都看不到**。

表现形式极具迷惑性：**连接成功、SQL 成功、无任何报错、采集任务显示 SUCCESS、就是没数据**。
和 A3 描述的"注释静默失败"是同一类问题，但这次丢的是全部表。

**改法**（二选一，写进权限申请单）：

| 方案 | 授权 | 采集用的视图 |
|---|---|---|
| A（推荐） | `GRANT SELECT ANY DICTIONARY TO datadict_collector;` | `DBA_TAB_COLUMNS` / `DBA_COL_COMMENTS` / `DBA_TABLES` |
| B（DBA 更保守时） | `GRANT SELECT_CATALOG_ROLE TO datadict_collector;` | 同上 |

若 DBA 坚持不给字典级权限，则退化为**逐 schema 授权**
（`GRANT SELECT ON <schema>.<table> ...`），但这与"严禁授予业务表 SELECT"的红线冲突，
且不可持续——**这种情况下应放弃 Oracle 自动采集，改用 DDL 导出离线导入**。

> 建议在 M1 权限表里对 Oracle 补一句说明，并把这条列入 V1.0 开发前的
> **DBA 沟通事项**——权限申请通常要走流程，发现得晚会直接卡住 V1.0。

---

# P1：建议修改

### P1-1 检索 SQL 里 `%%` 与 `:q` 的驱动假设冲突

**位置**：§M8，line 618、622

```sql
WHERE c.search_text %% :q AND c.is_deleted = FALSE
```

`:q` 是 SQLAlchemy 命名参数风格，`%%` 是 psycopg2 `pyformat` 下的 `%` 转义。
两者对驱动的假设不一致：

- 走 **psycopg2**（sync）→ `%%` 正确
- 走 **asyncpg**（async，$1 占位符）→ `%%` 会被当作**字面量**传下去，SQL 报错

而 §6.1 明确要求「同时配置 async 和 sync session」，两套都会存在，照抄必踩。

**建议**：不写裸 SQL，用 SQLAlchemy Core 表达式，让驱动层处理转义：

```python
from sqlalchemy import func

stmt = select(ColumnMeta).where(
    ColumnMeta.search_text.op('%')(q),      # 转义由驱动负责
    ColumnMeta.is_deleted.is_(False),
).order_by(func.similarity(ColumnMeta.search_text, q).desc())
```

### P1-2 `search_log` 单行记录点击，多次点击会互相覆盖

**位置**：§5.2 line 1303-1312、M11-7

一次搜索一行，点击时回写 `clicked_urn` / `clicked_rank`。但用户常常连点多个结果，
后一次 UPDATE 会覆盖前一次，M11-7 的「平均点击位次」会系统性偏向最后一次点击。

**建议**：拆一张 `search_click(search_id, urn, rank, created_at)`；
或明确只记录**首次点击**（`UPDATE ... WHERE clicked_urn IS NULL`），并在看板口径里注明。

### P1-3 「游客」角色残留，且"部分"仍未定义

**位置**：M10-2 line 906、权限矩阵 line 981

权限矩阵里「搜索浏览 / 游客 / 部分」的"部分"没有任何定义。内网系统全员登录，
建议直接删除游客角色——少一个角色少一类权限漏洞，也少一处需要定义的边界。

### P1-4 承载规模的两个数字不自洽

**位置**：§7 line 1544、1548

> 「真实约数千张表 / 数十万字段，留 2 倍余量」→ 1 万表 / 50 万字段

数千表（按 5000 算）× 平均 40 字段 ≈ 20 万字段，与「数十万」吻合；
但此前口头确认的规模是「数千表 / **数万**字段」，二者差约 10 倍。

**建议**：V0.1 采集跑通后用实数替换，同时验证 —— 50 万字段 + 阈值调到 0.1 时，
GIN trigram 的候选集会显著变大，`P95 < 500ms` 不是自动成立的。
§M8 的阈值调优必须**同时看召回率和延迟**（原文 line 646 已提到，保持即可）。

### P1-5 数仓侧实际要等 3~4 个月，需与相关方明确

§1.4 把数仓移到 V1.5 的论证是站得住的（核心痛点是血缘而非字段字典，用户群也不同）。
但按 §8 的排期，V0.1+V0.5+V1.0 = **11~14 周**，V1.5 才启动，且未给周期。

也就是说数据开发和分析师**至少 3 个月内完全不被这个平台服务**。这是个范围决策不是缺陷，
但建议：

- 在 §1.4 明确写出这个时间影响，避免相关方误以为"下一期很快"
- 或在 V1.0 内做一个**最小只读接入**（仅采集 Hive 表名/字段名/注释，不做分层、分区、血缘），
  先让数仓侧能查到东西

---

## 已确认修订正确的项

A1~A10、B①B②B④ 均已正确落实，其中三项质量高于我原本的建议：

| 项 | 说明 |
|---|---|
| **A3 注释采集** | 补了 PG 参考 SQL、CI 断言测试、以及**运行时非空率下降告警**——第三条我没想到，是防止后续回归的关键 |
| **B④ 语义检索** | 指出了我方案里的两个真实缺陷：uvicorn 多 worker 导致模型内存乘数、以及同步推理阻塞 event loop。后者是我完全漏掉的严重工程坑 |
| **B① 检索阈值** | 「padding 后 2 字仍可走索引，真正要调的是 `similarity_threshold`」比我原先"限制查询词至少 2 字"的说法准确 |

B③ 不采纳技术栈瘦身的理由（Redis/K8s/Prometheus 为既有可复用基础设施）成立——
我原判断的前提是从零搭建，前提变了结论就该变。
