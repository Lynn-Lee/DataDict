# DataDict 单镜像：前端构建产物由后端同源托管（FRONTEND_DIST_DIR）。

# ── 阶段 1：构建前端 ────────────────────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── 阶段 2：运行时 ──────────────────────────────────────────
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/datadict

COPY pyproject.toml ./
COPY app ./app
# 安装进 site-packages 后删掉源码副本，避免工作目录里的 app/ 遮蔽已安装的包
RUN pip install . && rm -rf app

COPY alembic.ini ./
COPY alembic ./alembic
COPY deploy/grants.sql ./deploy/grants.sql
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh
COPY scripts ./scripts
COPY --from=frontend /build/dist ./frontend-dist

# 构建上下文里的目录权限取决于宿主机（可能是 700），统一放开读权限给非 root 用户
RUN useradd --system --uid 10001 datadict \
    && chmod -R a+rX /srv/datadict \
    && chmod +x deploy/entrypoint.sh
USER datadict

ENV FRONTEND_DIST_DIR=/srv/datadict/frontend-dist
EXPOSE 8000
ENTRYPOINT ["./deploy/entrypoint.sh"]
