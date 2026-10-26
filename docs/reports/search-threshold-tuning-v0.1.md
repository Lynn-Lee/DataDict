# DataDict V0.1 检索阈值调优报告

日期：2026-08-06

## 结论

V0.1 继续采用数据库级 `pg_trgm.similarity_threshold = 0.10`。

本次用 36 条代表性查询词和本地 PostgreSQL fixture 实测：`0.10` 在召回率、候选噪音和延迟之间最稳，达到 94.4% 召回率，P95 为 4.665 ms，平均候选数 2.64。更低阈值 `0.05` / `0.08` 召回率更高，但候选数明显增加；更高阈值从 `0.12` 起召回跌破 94%。

当前本地库只有 `table_meta=1`、`column_meta=1`、`asset_annotation=1`，不足以代表真实生产元数据。本报告基于脚本内置代表性 fixture，真实核心库只读账号到位后必须用同一脚本复跑，并在 T9.1 / T9.3 验收时替换或补充本报告数据。

下表是一次本地运行记录；P95 会随本机负载轻微波动，阈值选择主要依据召回率与平均候选数。

## 测评方法

命令：

```bash
.venv/bin/python scripts/search_threshold_benchmark.py --min-recall 0.94
```

测评约束：

- 查询词数量：36 条
- 查询词类型：中文 2 字、中文 4 字、英文字段名、中英混合
- 数据集：脚本内置代表性 fixture，事务内临时写入后回滚
- 搜索语句：复用 `build_column_search_statement()`，即 T4.1 的 SQLAlchemy Core 查询
- 阈值调整：显式事务内使用 `SET LOCAL pg_trgm.similarity_threshold`
- 推荐规则：先满足召回率不低于 94%、P95 不高于 500 ms，再选择最高阈值以减少噪音

## 实测结果

| threshold | recall | p95_ms | avg_result_count |
|---:|---:|---:|---:|
| 0.05 | 0.972 | 2.557 | 3.17 |
| 0.08 | 0.972 | 4.708 | 2.75 |
| 0.10 | 0.944 | 4.665 | 2.64 |
| 0.12 | 0.917 | 3.703 | 2.39 |
| 0.15 | 0.889 | 1.896 | 2.03 |
| 0.20 | 0.861 | 2.668 | 1.58 |
| 0.30 | 0.639 | 3.452 | 0.89 |

推荐阈值：`0.10`

## 阈值落库状态

阈值已在迁移 `alembic/versions/20260806_0005_search_similarity_threshold.py` 中以数据库级配置写入：

```sql
ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1;
```

没有在应用代码检索路径使用会话级 `SET`。

## 后续复跑要求

生产或核心测试库只读账号到位后，使用同一命令改为真实数据模式：

```bash
DB_URL_WEB=postgresql+asyncpg://... \
.venv/bin/python scripts/search_threshold_benchmark.py --no-fixture --min-recall 0.94
```

真实数据复跑时，应把 `build_v01_query_cases()` 中的 expected URN 替换为核心库人工确认的字段，并至少覆盖订单、用户、支付、结算、物流、发票等核心概念。
