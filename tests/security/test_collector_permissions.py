"""G2/G3 采集角色权限门禁（DEV-TASKS T8.3 / §6）。

与本仓库既有测试哲学一致：不连真实数据库，改为对 `deploy/grants.sql`
做契约断言，并**交叉核对 ORM 模型**——这样一旦有人新增采集层表却漏写
授权、或新增知识层表却漏 REVOKE，门禁会立即变红，正是 G2/G3 要防的两类回归：

    G2 `test_collector_cannot_write_annotation` —— 采集角色越权写知识层（覆盖人工标注）
    G3 `test_collector_can_write_collection_tables` —— 新建采集表漏授权导致运行时 permission denied

这两个测试带 `@pytest.mark.gate`，随 `run-gate-tests.sh` 在 CI 强制执行，不允许 skip。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.models import knowledge as knowledge_models
from app.models import metadata as metadata_models

GRANTS_SQL = Path("deploy/grants.sql")

_COLLECTOR_WRITE_GRANT = ("GRANT SELECT, INSERT, UPDATE ON", "TO datadict_collector;")
_COLLECTOR_WRITE_REVOKE = ("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON", "FROM datadict_collector;")


def _model_tables(module: ModuleType) -> set[str]:
    """枚举某个模型模块里定义的所有物理表名。"""
    tables: set[str] = set()
    for obj in vars(module).values():
        if inspect.isclass(obj) and getattr(obj, "__module__", None) == module.__name__:
            tablename = getattr(obj, "__tablename__", None)
            if isinstance(tablename, str):
                tables.add(tablename)
    return tables


def _tables_between(sql: str, head: str, tail: str) -> set[str]:
    """抓取 `<head> ... <tail>` 之间列出的表名集合。"""
    match = re.search(re.escape(head) + r"(.*?)" + re.escape(tail), sql, re.DOTALL)
    if match is None:
        return set()
    return {token.strip() for token in re.split(r"[,\s]+", match.group(1)) if token.strip()}


@pytest.mark.gate
def test_collector_can_write_collection_tables() -> None:
    """采集层每张表都必须授予 collector 写权限，防新表漏授权。"""
    sql = GRANTS_SQL.read_text(encoding="utf-8")
    granted = _tables_between(sql, *_COLLECTOR_WRITE_GRANT)
    collection_tables = _model_tables(metadata_models)

    assert collection_tables, "未从 app.models.metadata 枚举到任何采集层表"
    missing = collection_tables - granted
    detail = f"采集层表漏授权 collector 写权限（会运行时 permission denied）：{sorted(missing)}"
    assert not missing, detail


@pytest.mark.gate
def test_collector_cannot_write_annotation() -> None:
    """知识层（含 asset_annotation）对 collector 只读，且必须显式 REVOKE 写权限。"""
    sql = GRANTS_SQL.read_text(encoding="utf-8")
    write_granted = _tables_between(sql, *_COLLECTOR_WRITE_GRANT)
    revoked = _tables_between(sql, *_COLLECTOR_WRITE_REVOKE)
    knowledge_tables = _model_tables(knowledge_models)

    assert "asset_annotation" in knowledge_tables, "asset_annotation 应属于知识层模型"

    leaked = knowledge_tables & write_granted
    assert not leaked, f"知识层表被授予 collector 写权限，标注可能被采集覆盖：{sorted(leaked)}"

    not_revoked = knowledge_tables - revoked
    assert not not_revoked, f"知识层表未对 collector 显式 REVOKE 写权限：{sorted(not_revoked)}"
