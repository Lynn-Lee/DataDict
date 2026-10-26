# 内网单机测试部署

适用：一台 Linux 机器 + Docker Compose，用于内网功能测试。不是生产高可用方案。

部署内容：PostgreSQL（pgvector/pg16）、Redis、MetaHub 应用（单镜像，后端同源托管前端静态资源）。
只有应用端口对外，PostgreSQL 和 Redis 仅在 compose 内部网络可达。

## 前置条件

- Docker 24+ 与 Docker Compose v2（`docker compose version`）。
- 机器能拉取 Docker Hub 镜像、`pip`/`npm` 依赖（构建时需要）。
- 机器到被采集的业务库（MySQL / PostgreSQL）网络可达，并已有**只读采集账号**（PRD §M1，严禁授予业务表 SELECT）。

## 部署步骤

```bash
git clone <仓库地址> metahub && cd metahub/deploy
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
| 备份数据库 | `docker compose -f docker-compose.intranet.yml exec -T postgres pg_dump -U postgres metahub > metahub.sql` |

## 已知限制

- 只有 HTTP，没有 TLS。需要 HTTPS 时在前面放内网网关或 Nginx。
- 调度器跑在应用进程内，因此固定单 worker、单实例，不要水平扩容。
- 两个业务角色的密码只在数据卷首次初始化时设置；之后改密码需手工 `ALTER ROLE` 并同步修改 `.env`。
- 只支持 MySQL / PostgreSQL 采集（Oracle、SQL Server 在 V1.0）。
