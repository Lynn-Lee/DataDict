#!/bin/sh
# 容器入口：先迁移（含 grants.sql 重跑），再启动服务。
# 调度器跑在进程内，只能单 worker，否则同步任务会被多个进程重复触发。
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
