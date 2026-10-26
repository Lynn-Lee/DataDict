-- DataDict 数据库角色与分层授权（DEV-TASKS T1.5）。
--
-- 本脚本必须保持幂等：每次 Alembic 迁移完成后都会重跑，用来修复
-- PostgreSQL `GRANT ... ON ALL TABLES` 只对当时已存在对象生效的问题。
-- 生产密码不写入仓库；如需设置登录密码，由部署系统或 DBA 在安全通道中执行
-- `ALTER ROLE ... PASSWORD ...`。

-- ── 角色 ────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datadict_web') THEN
        CREATE ROLE datadict_web LOGIN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datadict_collector') THEN
        CREATE ROLE datadict_collector LOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE datadict TO datadict_web, datadict_collector;
GRANT USAGE ON SCHEMA public TO datadict_web, datadict_collector;

-- ── Web 角色：应用接口全表读写 ───────────────────────────────
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO datadict_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO datadict_web;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO datadict_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO datadict_web;

-- ── Collector 角色：采集层与采集流程支撑表可写 ───────────────
GRANT SELECT, INSERT, UPDATE ON
    data_source,
    table_meta,
    column_meta,
    index_meta,
    schema_change_log,
    sync_job_log,
    sync_fail_detail,
    annotation_todo
TO datadict_collector;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO datadict_collector;

-- ── Collector 角色：知识层只读，禁止覆盖人工标注 ─────────────
GRANT SELECT ON
    business_domain,
    domain_rule,
    tag,
    dict,
    asset_annotation,
    asset_tag_rel,
    annotation_history,
    common_column_blacklist
TO datadict_collector;

DO $$
BEGIN
    IF to_regclass('public.v_column_effective') IS NOT NULL THEN
        GRANT SELECT ON v_column_effective TO datadict_collector;
    END IF;
END
$$;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    business_domain,
    domain_rule,
    tag,
    dict,
    asset_annotation,
    asset_tag_rel,
    annotation_history,
    common_column_blacklist
FROM datadict_collector;
