import io
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import imports
from app.core.exceptions import register_exception_handlers
from app.db.session import get_web_session


class RejectingSession:
    async def execute(self, statement: object, parameters: object | None = None) -> None:
        del statement, parameters
        raise AssertionError("文件校验应在数据库访问之前完成")

    async def commit(self) -> None:
        raise AssertionError("文件校验失败不应产生提交")


async def fake_session() -> AsyncIterator[RejectingSession]:
    yield RejectingSession()


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(imports.router)
    app.dependency_overrides[get_web_session] = fake_session
    return TestClient(app)


def test_import_rejects_non_xlsx_before_db_access() -> None:
    response = _client().post(
        "/imports/excel",
        files={"file": ("字典.xls", io.BytesIO(b"legacy"), "application/vnd.ms-excel")},
    )

    assert response.status_code == 400
    assert "xlsx" in response.json()["message"]


def test_import_rejects_empty_file_before_db_access() -> None:
    response = _client().post(
        "/imports/excel",
        files={
            "file": (
                "字典.xlsx",
                io.BytesIO(b""),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400


def test_import_rejects_corrupt_xlsx_with_readable_error() -> None:
    response = _client().post(
        "/imports/excel",
        files={
            "file": (
                "字典.xlsx",
                io.BytesIO(b"not-a-real-zip"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "解析失败" in response.json()["message"]
