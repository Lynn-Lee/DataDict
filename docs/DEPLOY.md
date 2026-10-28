# 内网单机测试部署

适用：一台 Linux 机器 + Docker Compose，用于内网功能测试。不是生产高可用方案。

部署内容：PostgreSQL（pgvector/pg16）、Redis、DataDict 应用（单镜像，后端同源托管前端静态资源）。
只有应用端口对外，PostgreSQL 和 Redis 仅在 compose 内部网络可达。

## 前置条件

- Docker 24+ 与 Docker Compose v2（`docker compose version`）。
- 机器能拉取 Docker Hub 镜像、`pip`/`npm` 依赖（构建时需要）。
- 机器到被采集的业务库（MySQL / PostgreSQL）网络可达，并已有**只读采集账号**（PRD §M1，严禁授予业务表 SELECT）。

## 部署步骤

```bash
git clone <仓库地址> datadict && cd datadict/deploy
cp deploy.env.example .env
```

编辑 `deploy/.env`，填满所有密码和密钥（生成方式见文件内注释）。**`CREDENTIAL_SECRET_KEY` 丢失后，已录入的数据源密码无法解密，务必备份。**

```bash
docker compose -f docker-compose.intranet.yml up -d --build --wait
```

首次启动会依次：初始化数据库（扩展、两个业务角色）→ 应用容器执行 `alembic upgrade head`（建表并重跑 `deploy/grants.sql` 做分层授权）→ 启动服务。

访问：`http://<机器IP>:8000/`（`APP_PORT` 可改），接口文档 `http://<机器IP>:8000/docs`。

## 初始化账号与数据源

```bash
docker compose -f docker-compose.intranet.yml exec app \
    python scripts/create_user.py --username admin --password '<密码>' --real-name 管理员

docker compose -f docker-compose.intranet.yml exec app \
    python scripts/create_datasource.py --code prod_mysql_core --name '核心交易库' \
    --db-type mysql --env prod --host <库IP> --port 3306 \
    --username <只读账号> --password '<密码>' --default-db <库名> --sync-cron '0 2 * * *'
```

`create_datasource.py` 把密码用 `CREDENTIAL_SECRET_KEY` 加密后落库，明文不入库。同源会按 `--sync-cron` 定时同步。

## 验证

```bash
curl http://localhost:8000/api/v1/health
```

应返回 `status: ok`，且 `db_web`、`db_collector`、`redis` 三项均为 `ok`。

## 常用操作

| 操作 | 命令 |
|---|---|
| 查看日志 | `docker compose -f docker-compose.intranet.yml logs -f app` |
| 升级版本 | `git pull && docker compose -f docker-compose.intranet.yml up -d --build`（启动时自动迁移） |
| 停止（保留数据） | `docker compose -f docker-compose.intranet.yml down` |
| 清空重来 | `docker compose -f docker-compose.intranet.yml down -v`（**删除全部数据**） |
| 备份数据库 | `docker compose -f docker-compose.intranet.yml exec -T postgres pg_dump -U postgres datadict > datadict.sql` |

## 升级注意（跨版本部署，2026-10-28 这次必须逐条确认）

1. **先备份**：`docker compose -f docker-compose.intranet.yml exec -T postgres pg_dump -U postgres datadict > datadict-$(date +%F).sql`。
2. **`CREDENTIAL_SECRET_KEY` 不能换**：数据源密码是 Fernet 对称加密落库的，密钥与加密时不一致会导致解密失败，
   同步在连接阶段就 FAILED（密文无法找回，只能重新录入各数据源密码）。
3. **迁移是自动的**：`entrypoint.sh` 启动时执行 `alembic upgrade head` 并重跑 `deploy/grants.sql` 做分层授权，
   所以**采集角色的知识层只读权限会在每次迁移后被重新收紧**，不要手动给 `datadict_collector` 加写权限。
   若这次跨度较大（如 `20261026_0007 → 20261027_0010`，新增标准定义库三张表与 `sub_key`），
   启动日志里应能看到每条迁移的执行记录；迁移失败容器会退出，`docker compose logs app` 看栈。
4. **回滚**：`alembic downgrade -1` 逐级回退（`0010` 会删掉 `sub_key` 并把同名唯一性收回按名，已拆出的同名不同义标准会冲突，
   回滚前先确认 `standard_field` 是否已产生业务价值数据）。
5. **调度器在应用进程内**：升级会重启调度 job；同步定时表达式取自各数据源 `sync_cron`，
   另有每日 03:30(UTC) 的全量重聚 + 治理扫描兜底 job。

## 部署后验收清单（字段统一治理链路）

```bash
curl http://localhost:8000/api/v1/health                      # 三项组件 ok
docker compose -f docker-compose.intranet.yml exec app alembic current   # 应为 20261027_0010 (head)
```

- 打开「标准定义工作台」→ 点「重新聚类」→ 记录候选数量、同名不同义拆组数量（通用名 `status/type/remark` 应能看到多条）。
- 对真实生产数据源点「同步」→ 后台执行完成后看「同步比对待办」：
  - `类型冲突` 待办 = 字段类型与已定版标准不一致（按字段）
  - `未挂标准` 待办 = 该表仍有字段没关联任何已定版标准（**按表聚合**，一表一条，可展开字段清单）
- 首轮 `未挂标准` 数量约等于"还有gap的表数"，属预期；确认噪音可接受后再逐个豁免或定标。
- 若只需比对不需重新聚类，可单独调 `POST /api/v1/governance/sweep`（该接口不做聚类）。

## 已知限制

- 只有 HTTP，没有 TLS。需要 HTTPS 时在前面放内网网关或 Nginx。
- 调度器跑在应用进程内，因此固定单 worker、单实例，不要水平扩容。
- 两个业务角色的密码只在数据卷首次初始化时设置；之后改密码需手工 `ALTER ROLE` 并同步修改 `.env`。
- 只支持 MySQL / PostgreSQL 采集（Oracle、SQL Server 在 V1.0）。
