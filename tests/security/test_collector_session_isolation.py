"""采集路径连接池隔离契约门禁（DEV-TASKS T8.1 / §7 红线第 6 条）。

T8.1 用两套连接池对应两个数据库角色：`datadict_web`（全表读写）与
`datadict_collector`（采集层可写、知识层只读）。隔离由数据库权限强制，
但前提是**采集流程只能拿 collector 会话**——一旦有人在采集服务里误用
`web_session` / `get_web_session`，物理角色隔离就被绕过。

与仓库既有安全测试哲学一致：不连真实库，改为对采集服务模块的 import 做
AST 契约断言，把"采集路径无 web 会话"这条代码评审红线固化进 CI，防回归。
带 `@pytest.mark.gate`，随 `run-gate-tests.sh` 强制执行，不允许 skip。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# 采集/调度服务：运行在无请求上下文的后台任务里，必须走 collector 角色。
_COLLECTOR_MODULES = [
    Path("app/services/metadata_sync.py"),
    Path("app/services/sync_scheduler.py"),
]
# db.session 中的 web 角色入口，采集路径一律不得导入。
_WEB_SESSION_NAMES = {"web_session", "get_web_session"}


def _names_imported_from_db_session(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.db.session":
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.gate
@pytest.mark.parametrize("path", _COLLECTOR_MODULES, ids=lambda p: p.stem)
def test_collector_modules_do_not_use_web_session(path: Path) -> None:
    imported = _names_imported_from_db_session(path)
    leaked = imported & _WEB_SESSION_NAMES
    assert not leaked, f"{path} 采集路径导入了 web 会话 {leaked}，违反 T8.1/§7 红线第 6 条"
    assert "collector_session" in imported, (
        f"{path} 应通过 collector_session 获取采集会话，实际导入 {imported or '无'}"
    )
