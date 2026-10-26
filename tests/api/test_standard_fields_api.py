from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import standard_fields
from app.core.exceptions import register_exception_handlers
from app.db.session import get_web_session


class RejectingSession:
    async def execute(self, statement: object, parameters: object | None = None) -> None:
        del statement, parameters
        raise AssertionError("payload 校验应在数据库访问之前完成")

    async def commit(self) -> None:
        raise AssertionError("payload 校验失败不应产生提交")


async def fake_session() -> AsyncIterator[RejectingSession]:
    yield RejectingSession()


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(standard_fields.router)
    app.dependency_overrides[get_web_session] = fake_session
    return TestClient(app)


def test_confirm_rejects_empty_business_meaning_before_db_access() -> None:
    response = _client().post(
        "/standard-fields/1/confirm",
        json={"raw_type": "varchar(32)", "logical_type": "STRING", "business_meaning": ""},
    )

    assert response.status_code == 422


def test_confirm_rejects_missing_raw_type_before_db_access() -> None:
    response = _client().post(
        "/standard-fields/1/confirm",
        json={"logical_type": "STRING", "business_meaning": "运单号"},
    )

    assert response.status_code == 422
