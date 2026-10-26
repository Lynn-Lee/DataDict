# 《元数据知识库 — 产品功能设计方案 v1.0》评审

评审对象：`DataDict-PRD.md`（评审时为 v1.0）
结论：整体可作为开发依据。M6 标注工作台、M7 枚举字典、M3 重命名继承三块抓住了产品要害。
下列 **P0 五项必须在开发前修正**，否则会返工或造成不可逆的数据损失。

---

## P0：必须改

### P0-1 搜索用物化视图，会导致「标注完搜不到」（§5.3, line 874）

```sql
CREATE MATERIALIZED VIEW search_index AS ...   -- 「定时刷新」
```

**问题**：标注是实时编辑的，但搜索索引要等定时刷新。标注者填完业务含义，回搜索框验证——搜不到，
会以为没保存成功。这是标注工作台最高频的操作闭环，断在这里对标注推进是直接打击。

`REFRESH MATERIALIZED VIEW CONCURRENTLY` 虽有唯一索引可用，但仍是全量重算，且刷新期间
资源占用高；随字段增长只会更慢。

**改法**：数万字段规模下不需要物化视图。在基表上用**生成列 + GIN 索引**，写入即生效：

```sql
ALTER TABLE column_meta ADD COLUMN search_text TEXT
  GENERATED ALWAYS AS (coalesce(column_name,'') || ' ' || coalesce(raw_comment,'')) STORED;
CREATE INDEX idx_col_search ON column_meta USING GIN (search_text gin_trgm_ops);

-- 标注表同理
ALTER TABLE asset_annotation ADD COLUMN search_text TEXT
  GENERATED ALWAYS AS (coalesce(business_meaning,'') || ' ' || coalesce(sample_value,'')) STORED;
CREATE INDEX idx_anno_search ON asset_annotation USING GIN (search_text gin_trgm_ops);
```

查询时 UNION 两侧结果。真到需要物化视图的量级（20 万字段以上）再说。

---

### P0-2 搜索索引漏了表级业务域继承，「按业务域筛选字段」会基本失效（§5.3, line 892-896）

```sql
LEFT JOIN asset_annotation a ON c.urn = a.urn        -- 只 join 了字段自己的标注
LEFT JOIN business_domain d ON a.domain_id = d.id
```

**问题**：M6.1（line 257）明确写了字段的业务域「继承自表，可覆盖」——也就是**绝大多数字段
不会有自己的 `domain_id`**。但这个视图只 join 字段自身的标注，没有 fallback 到所属表的标注。

后果有两个，都很严重：
1. `domain_name` 对绝大多数字段为 NULL → **M8-1-4「按业务域筛选」对字段搜索形同虚设**
2. `d.name` 被拼进 `tsv`（line 890）→ 搜业务域名字也搜不到字段

**改法**：显式做两级 fallback。

```sql
LEFT JOIN asset_annotation ca ON ca.urn = c.urn         -- 字段级标注
LEFT JOIN asset_annotation ta ON ta.urn = c.table_urn   -- 表级标注
LEFT JOIN business_domain d ON d.id = COALESCE(ca.domain_id, ta.domain_id)
```

这个「继承自表、可覆盖」的语义**在所有查询、筛选、覆盖率统计里都要一致处理**。
建议封装成一个 SQL 视图或统一的 service 方法，不要在各处重复写 COALESCE——写漏一处就是一个 bug。
M11-2 的覆盖率统计尤其容易漏。

---

### P0-3 zhparser 的部署代价被低估，且恰好不擅长你的场景（§5.3, line 869-872）

```sql
CREATE EXTENSION IF NOT EXISTS zhparser;
```

**三个问题**：

1. **不是 PG 官方 contrib**。需要在数据库服务器上编译安装 SCWS + zhparser，意味着
   **不能直接用官方 `postgres` 镜像**，得自建镜像并长期维护；多数云 RDS 也不支持。
   §6.1 只写了「PostgreSQL 15+」，没有暴露这个约束。
2. **对未登录词切分差**。而数据字典里全都是业务专有名词、内部缩写、系统黑话——
   正是分词器最不擅长的部分。搜「实名认证」也许可以，搜你们内部的业务术语大概率被切碎。
3. line 872 只映射了 `n,v,a,i,e,l` 六种词性到 simple，其余词性的词会被直接丢弃。

**改法**：MVP 用 **`pg_trgm`（PG 官方 contrib，任何环境开箱即用）做主检索**。
trigram 是字符三元组匹配，对中文短语和未登录词天然可用，**不需要分词器**，
搜「实名认证」能命中「用户实名认证状态」。

zhparser 作为**后续可选增强**，等确实遇到 trigram 解决不了的场景（长文本相关度排序）再引入。
不要在第一版就为搜索引入一个需要自定义数据库镜像的依赖。

---

### P0-4 变更检测排在 V0.5，但 V0.1 就在跑同步——前 4~5 周的变更历史会永久丢失（§8）

V0.1（line 1072-1077）包含 M2 采集与同步，但不含 M3 变更检测；M3 排在 V0.5（line 1090）。

**问题**：M2 采集流程第 6 步（line 176）本来就要「与上一版快照 diff」。V0.1 如果只做 upsert
不写 `schema_change_log`，那么 MVP 运行的 4~5 周里所有 schema 变更**没有任何记录，
且事后无法补回**——变更历史是流水，错过就没了。

对早期试点尤其可惜：MVP 阶段恰恰是最需要观察「生产库到底多久变一次、变什么」的时候，
这个数据能直接指导后续设计。

**改法**：把 M3 拆开——

- **V0.1 必须包含**：diff 计算 + 写 `schema_change_log`（纯后端，无 UI，工作量很小）
- **V0.5 再做**：变更时间线 UI、重命名识别与确认、订阅通知、待办生成

原则：**只要数据是流水性质、错过不可补，采集逻辑就必须在第一版落地，UI 可以推迟。**

---

### P0-5 文档内部矛盾：AI 输入要「样例枚举值分布」，但产品边界写明绝不碰业务数据

- §1.3（line 28）：「SQL 查询执行 —— 本产品只读元数据，**绝不触碰业务数据**」
- M1 约束（line 120）：「**严禁授予业务表读权限**」
- 但 M6.3（line 309）AI 辅助草稿的输入包含：「**样例枚举值分布**」
- M6.1（line 260）还有「取值示例」字段，如 `13800138000`

**问题**：枚举值分布只能靠 `SELECT status, count(*) FROM t GROUP BY status` 得到，
这需要业务表读权限，与前面两条硬约束直接冲突。按现有约束，这个输入项**根本拿不到数据**。

这个矛盾不解决，AI 草稿的效果会远低于预期——因为枚举字典恰恰是 §M7 强调的
「查询者最需要、现实中最缺失」的信息，而没有真实值分布，AI 只能靠字段名瞎猜。

**三个选项，选一个写进文档**：

| 方案 | 说明 |
|---|---|
| A. 保持纯净（推荐 MVP 采用） | 删掉「样例枚举值分布」输入项，枚举字典完全靠人工填。AI 只从字段名+注释推断含义 |
| B. 受控采样 | 对**低基数**字段（先用统计信息判断 distinct < 50）允许 `GROUP BY` 采样，**单独申请权限、单独审批数据源、全程审计**，且只取值不取明细 |
| C. 由业务方提供 | 从代码仓库的枚举类/常量定义里解析（Java enum、常量类），完全不碰数据库 |

方案 C 值得认真考虑——枚举定义本来就在代码里，比从数据反推更准确、更无风险。

---

## P1：设计缺口，开发前应补齐

### P1-1 同名字段聚合的默认动作对通用字段名是灾难（M6.2 ③, line 276-289）

按 `字段名 + 逻辑类型` 聚合，主操作是 `[应用到全部 62 处]`。

`order_no` 是好例子。但 `status`、`type`、`name`、`code`、`remark`、`state` 这类字段名
在几乎每张表都有、逻辑类型都是 INT/STRING，**语义却完全不同**（订单状态/用户状态/审核状态）。
一键全应用会造成大面积错误标注——**错误信息比没有信息危害更大**，用户被坑一次就不再信任这个平台。

**改法**：
- 聚合键加第三维：`字段名 + 逻辑类型 + 原始注释相似度`，注释不同的分到不同组
- 维护一个**通用字段名黑名单**（status/type/name/code/id/remark/state/value/data/content/ext…），
  命中时**不提供「应用到全部」按钮**，强制走选择性应用
- 应用前展示「这 62 处中，有 15 处原始注释与你选的样本不同」的警示

### P1-2 「工作量降低 85%」缺乏依据，而 V0.5 验收标准建立在它之上（line 289 / 1094）

line 289 断言 5 万字段去重后约 6000~8000 个语义单元；line 1094 据此定下
「单人日均标注量 > 300 字段」的验收标准。

真实情况通常是**两极分化**：通用字段（`id`/`create_time`/`is_deleted`）聚合率极高，
核心业务字段几乎聚合不了——而后者正是标注价值最大、也最费时的部分。

**改法**：这是一条 SQL 就能验证的事，别拿假设排期。采集跑通后立刻执行：

```sql
SELECT count(*) AS total,
       count(DISTINCT (column_name, logical_type)) AS units,
       1 - count(DISTINCT (column_name, logical_type))::float / count(*) AS dedup_rate
FROM column_meta WHERE is_deleted = FALSE;
```

拿到真实去重率再定 V0.5 的验收标准。

### P1-3 重命名标注继承会撞 UNIQUE 约束，冲突策略未定义（line 728 / 193）

`asset_annotation.urn` 是 UNIQUE。M3-3 说确认重命名后「原字段的全部标注自动迁移到新字段」。

**冲突场景**：新字段 B 出现时，M6.2④ 规则引擎可能已经给它写了 annotation 行
（规则会预填业务含义、枚举字典——见 line 298、301），M3-6 也会生成待标注待办。
此时把 A 的标注 UPDATE 成 urn=B 会**直接违反唯一约束，事务失败**。

`asset_tag_rel` 的 `UNIQUE(urn, tag_id)`（line 758）同样会撞。

**改法**：明确合并策略并写进文档。建议：
- 目标 URN 已有 annotation 且 `source_type IN ('RULE','AI')`（机器产生）→ **人工标注覆盖机器标注**
- 目标已有 `source_type='MANUAL'` → **不自动迁移**，转人工在界面上左右对比后选择
- 标签迁移用 `INSERT ... ON CONFLICT DO NOTHING`
- 无论哪种，都要写 `inherited_from`（表已有该字段，line 742）和 `annotation_history`

### P1-4 软删除「保留 90 天」后删什么，未定义；标注可能变孤儿（M3-7, line 197）

`asset_annotation` 只有 `urn` 字符串，**与 `column_meta` 无外键关联**（line 728）。
若 90 天后物理删除 `column_meta` 行，annotation 会永久滞留成孤儿数据——
§9 风险表（line 1124）提到要做「孤儿标注巡检」，说明作者意识到了，但没有对应的机制设计。

**改法**，写一条明确原则进文档：

> **采集元数据可以清理，人工标注永不自动删除。**

理由：标注是人力投入沉淀下来的知识资产，比 schema 本身值钱得多，且体量很小（数万行），
留着的存储成本可以忽略。字段哪天回来了标注能自动复原，这正是软删除机制的价值。

具体：90 天后可清理 `column_meta` 中 `is_deleted=true` 的行；`asset_annotation` 保留，
并在界面上标注为「关联字段已下线」。

### P1-5 非功能指标按 100 万字段写，实际是数万——差 20 倍，会引发过度设计（§7, line 1061）

「支持 100 个数据源、5 万张表、100 万字段」。实际规模是**数千表 / 数万字段**。

这个 20 倍的差距不是无害的：它会正当化 Redis 缓存、Celery、K8s 这一整套东西（§6.1 都列了），
而这些在真实规模下**每一个都是纯粹的运维负担**。数万字段的搜索，PG 加个 GIN 索引就是毫秒级。

**改法**：非功能指标按真实规模写（比如「支持 20 个数据源、5000 张表、10 万字段」，
已经留了 2-3 倍余量）。§6.1 中 Redis、Celery 明确标注为「暂不引入，预留扩展点」。
APScheduler + PG 单库能扛到你规模的十倍。

---

## P2：建议

| # | 问题 | 建议 |
|---|---|---|
| P2-1 | §6.4 line 1046 称「物理上不可能触碰 `asset_annotation` 表」，但保证只来自「代码里没写」 | 落成真机制：采集服务用**独立 DB role**，对 `asset_annotation`/`asset_tag_rel` 只授 SELECT 不授 INSERT/UPDATE。一行 GRANT 换一个真正的物理保证 |
| P2-2 | `/search/semantic`（line 438）承诺自然语言检索，但 §6.1 技术栈无任何向量检索/LLM 组件 | 要么补方案（`pgvector` + embedding，PG 官方扩展，代价可控），要么 V1.0 先降级为「关键词抽取 + 现有全文检索」，别在 API 文档里承诺做不到的能力 |
| P2-3 | M1-1（line 110）数据源类型含 MongoDB，但类型映射表（§2）、采集器目录（§6.2）全无对应 | MongoDB 是 schema-less，元数据要靠抽样推断，与其他库不是一个模型。建议第一版**删掉**，需要时单独设计 |
| P2-4 | M8-1-5 排序要用「被查看次数」、M8-2-6「最近浏览」，但只有 `search_log` 和 `user_favorite`，无浏览记录表 | 补 `view_log(user_id, urn, created_at)`，或在 `search_log` 加 `clicked_urn` |
| P2-5 | 权限矩阵（line 537）「游客 / 搜索浏览 / 部分」，「部分」未定义 | 内网系统建议直接**删掉游客角色**。少一个角色少一类权限 bug |
| P2-6 | `asset_annotation` 无 `asset_type` 索引（line 748-749），但搜索结果要按表/字段分组 | 视实际查询计划补 `(asset_type, domain_id)` 联合索引 |

---

## 值得肯定的部分

以下几点是这份方案里做得对、且容易被忽略的，实施时不要因为赶工砍掉：

- **M6.2 四种标注模式的分层**——认识到「标注效率决定项目成败」，并给出了具体机制而不是口号
- **M6.2④ 规则引擎结果一律进待审核**（line 304）——保住了质量控制权在人手里
- **M7 枚举字典 + 全局字典复用**——这是查询者最需要、现实中最缺失的信息，抓得准
- **M5「敏感级别」「合规属性」标签可被脱敏中间件/权限系统 API 消费**（line 242）——
  这是本产品最容易产生外部价值、最能证明 ROI 的部分，建议在 V1.0 就找一个真实消费方接入
- **§十 启动前三件事**——尤其第 2 条「标注责任人的投入要被其主管认可」，这是产品之外的
  组织问题，但恰恰是这类项目最常见的死因

---

## 修改优先级

| 阶段 | 动作 |
|---|---|
| **开发前必改** | P0-1 ~ P0-5，均涉及架构或不可逆的数据损失 |
| **V0.1 开发中** | P1-1、P1-2（跑一条 SQL 就能验证）、P1-5 |
| **V0.5 前** | P1-3、P1-4 |
| **择机** | P2 全部 |
