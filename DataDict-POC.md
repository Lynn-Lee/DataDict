# OpenMetadata POC 方案（2-3 天）

## 目的

用最小成本判断：**采用 OpenMetadata，还是自建**。

不是"体验一下功能"，而是跑完后能给出一个二选一的结论。因此下面每项都有明确的
通过/不通过标准，测完直接填评分卡。

## 背景约束（决定了评判标准）

| 项 | 值 |
|---|---|
| 规模 | 数千表 / 数万字段 |
| 数据源 | MySQL、PostgreSQL、Oracle、SQL Server、大数据类（Hive/CK/Doris）均有 |
| 核心场景 | 产研同学搜**中文业务含义**（"手机号""订单金额"） |
| 业务语义来源 | 人工在后台标注 |
| 部署 | 内网自部署 |

关键背景：OpenMetadata 官方给出的生产配置为 Server 4vCPU/16GiB + 数据库 4vCPU/16GiB +
ElasticSearch 2vCPU/8GiB，且官方说明 Docker 部署仅适合小规模试用，生产建议 Kubernetes。
**为数千张表长期运维这套栈，是本次决策的主要成本项。**

---

## 一票否决项（第 1 天就测，不过就直接自建）

### V1. 中文检索效果 ★最高优先级

**为什么是要害**：核心使用场景就是中文检索。OpenMetadata 搜索后端为 ES/OpenSearch，
默认分析器对中文按单字切分，中文短语召回可能很差；官方文档亦未见明确的中文分词支持说明。

**怎么测**：
1. 接入一个**注释写得比较全的真实库**（不要用玩具数据，注释质量直接决定结论）
2. 在搜索框依次输入：`手机号`、`订单金额`、`创建时间`、`是否删除`、一个业务专有名词
3. 记录每个词的召回结果数、Top5 是否相关

**通过标准**：中文词能召回相关字段，且 Top5 命中率可接受。
**不通过**：只能靠英文字段名搜到，中文注释搜不出来，或必须精确全串匹配。

> 若不通过，可再花半天试配置 IK 分词插件。配不通 → 直接判自建。

### V2. 批量标注能力

**为什么是要害**：数万字段，纯手工一个个标必然烂尾。`user_id` 可能出现在 200 张表里，
必须能标一次批量应用。

**怎么测**：找一个在多张表中重复出现的字段名，尝试一次性给它们全部打上同一个 Glossary Term
或 Tag，记录需要多少次点击。

**通过标准**：存在批量/规则化打标能力（自动打标策略、批量选择、或 API 批量写入）。
**不通过**：只能逐个资产手动点。

---

## 重要项（第 2 天测）

### V3. 采集器对你们的实际库版本可连通

不要只测 MySQL。**重点测 Oracle 和 SQL Server**——这两个是自建方案里最费劲的部分，
也正是开源方案价值最大的地方。如果这里连不上，选 OpenMetadata 的主要理由就没了。

记录：各库能否连通、是否能正确取到**中文字段注释**（Oracle 的注释在 `all_col_comments`，
SQL Server 在 `extended_properties`，采集器实现不到位会直接丢注释）。

### V4. API 是否满足消费方需求

用一个请求拿到"某张表的全部字段 + 数据类型 + 业务含义 + 业务域 + 标签"。

记录：需要几次请求、响应结构是否好用、鉴权方式是否适合内部系统调用。

### V5. 运维重量实测

`docker stats` 记录实际内存/CPU 占用，评估：团队是否有人能长期维护这套栈（含升级、
ES 索引重建、故障排查）。

---

## 评分卡（测完直接填）

| 项 | 权重 | OpenMetadata 实测 | 自建方案对照 |
|---|---|---|---|
| V1 中文检索 | 否决 | | PG `pg_trgm` trigram，中文短语天然可用，无需分词器 |
| V2 批量标注 | 否决 | | 自己设计，可做「同名字段一键批量」 |
| V3 Oracle/SQLServer 采集 | 高 | | 需自行实现，各库注释取法不同，工作量集中在此 |
| V4 API | 中 | | 自建 FastAPI 原生 OpenAPI，按需定制 |
| V5 运维重量 | 高 | | 单个 PG + 一个 Python 服务 |
| 定制能力（对接内部权限/CMDB） | 视需求 | | 完全可控 |

## 决策规则

- **V1 或 V2 不通过** → 直接自建，不用再看后面
- **V1、V2 通过，V3 也通过** → 用 OpenMetadata，把精力投在业务域梳理和标注推进上
- **V1、V2 通过但 V3 不行** → 仍倾向 OpenMetadata，自己补采集器推元数据进去（它有 API）
- **不要选"OpenMetadata 存储 + 自研前端"的混合方案**：两边的复杂度都吃到了，收益最少

---

## 执行注意

1. **POC 用只读账号连真实库**（可用测试库，但注释质量要接近生产，否则 V1 结论不可信）
2. Docker Compose 部署文件从 [OpenMetadata 官方 Releases](https://github.com/open-metadata/OpenMetadata/releases)
   取对应版本，不要用第三方魔改版
3. 准备好至少 16GB 可用内存的机器，否则起不来会误判
4. POC 期间**并行推进**：生产库网络连通性申请 + 只读账号申请（这是后续唯一的外部依赖，
   通常比写代码慢）

## 同期要做的摸底（不依赖 POC 结论，两条路都要用）

- **DDL 注释覆盖率**：写个脚本统计各库 `column_comment` 非空的比例。
  若覆盖率低于 50%，无论选哪条路，都必须把「AI 预填业务含义草稿 + 人工审核」提到第一期，
  否则平台上线即空壳。
- **业务域清单**：这个必须业务方参与定，是整个知识库的骨架，与技术选型无关，可以现在就开始。
- **核心表清单**：找出被引用最多的 top 20% 表，第一轮标注只做这些，覆盖 80% 查询需求。

Sources:
- [Minimum Requirements | OpenMetadata Documentation](https://docs.open-metadata.org/latest/deployment/minimum-requirements)
- [Production-Ready Requirements for OpenMetadata Deployment](https://docs.open-metadata.org/latest/deployment/requirements)
- [OpenMetadata Releases](https://github.com/open-metadata/OpenMetadata/releases)
