#!/bin/sh
# 内网部署的数据库首次初始化（仅在数据卷为空的首次启动时执行一次）。
# 与 init-local.sql 的区别：两个业务角色的密码来自环境变量，不写死在仓库里。
# 建表与分层授权由应用容器启动时的 alembic 迁移（含 deploy/grants.sql）完成。
set -eu

psql -v ON_ERROR_STOP=1 \
    -v web_pw="$DATADICT_WEB_PASSWORD" \
    -v collector_pw="$DATADICT_COLLECTOR_PASSWORD" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE datadict_web LOGIN PASSWORD :'web_pw';
CREATE ROLE datadict_collector LOGIN PASSWORD :'collector_pw';
SQL
