-- 本地开发环境初始化（仅 docker-compose 首次启动时执行一次）。
--
-- 生产环境的角色与授权以 deploy/grants.sql 为准（DEV-TASKS T1.5）。
-- 本文件只负责把本地环境拉起来：建扩展、建两个角色、设检索阈值。

-- ── 扩展 ────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- 中文检索，PRD §M8
CREATE EXTENSION IF NOT EXISTS vector;    -- 语义检索，PRD §5.4（V1.0 启用）

-- ── 检索阈值 ────────────────────────────────────────────────
-- PRD §M8【v1.2 修正】/ DEV-TASKS T1.6：
-- 必须用 ALTER DATABASE。会话级 SET 在连接池下会漂移，导致召回随机不一致。
-- 0.1 是起始值，V0.1 的 T4.2 实测调优后以迁移脚本为准。
ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1;

-- ── 角色 ────────────────────────────────────────────────────
-- PRD §M10-8：采集与 Web 必须是不同角色，标注表的隔离由数据库强制。
-- 本地密码固定，仅用于开发；生产密码走密钥管理系统注入。
CREATE ROLE datadict_web LOGIN PASSWORD 'datadict_web_local';
CREATE ROLE datadict_collector LOGIN PASSWORD 'datadict_collector_local';

GRANT CONNECT ON DATABASE datadict TO datadict_web, datadict_collector;
GRANT USAGE   ON SCHEMA public    TO datadict_web, datadict_collector;

-- 建表由 Alembic 负责，此处只设默认权限规则，
-- 保证后续迁移新建的表自动对 web 角色可用（DEV-TASKS T1.5 / C4）。
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO datadict_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO datadict_web;

-- collector 的权限是**按表分层的**（采集层可写 / 知识层只读），
-- 无法用默认权限表达，必须由 deploy/grants.sql 在每次迁移后重跑。
