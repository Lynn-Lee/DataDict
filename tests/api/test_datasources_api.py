from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import datasources
from app.core.exceptions import register_exception_handlers
from app.db.session import get_web_session


class RejectingSession:
    async def execute(self, statement: object, parameters: object | None = None) -> None:
        del statement, parameters
        raise AssertionError("payload 校验应在数据库访问之前完成")

    async def get(self, entity: object, ident: object) -> None:
        del entity, ident
        raise AssertionError("payload 校验应在数据库访问之前完成")

    async def commit(self) -> None:
        raise AssertionError("payload 校验失败不应产生提交")


async def fake_session() -> AsyncIterator[RejectingSession]:
    yield RejectingSession()


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(datasources.router)
    app.dependency_overrides[get_web_session] = fake_session
    return TestClient(app)


_BASE = {
    "code": "prod_tidb_operdb",
    "name": "运营库",
    "db_type": "mysql",
    "env": "prod",
    "host": "10.0.0.1",
    "port": 4000,
    "username": "datadict_ro",
    "password": "s3cret",
}


def test_create_rejects_unsupported_db_type_before_db_access() -> None:
    response = _client().post("/datasources", json={**_BASE, "db_type": "oracle"})

    assert response.status_code == 422


def test_create_rejects_invalid_code_pattern_before_db_access() -> None:
    response = _client().post("/datasources", json={**_BASE, "code": "Prod TIDB!"})

    assert response.status_code == 422


def test_create_rejects_out_of_range_port_before_db_access() -> None:
    response = _client().post("/datasources", json={**_BASE, "port": 70000})

    assert response.status_code == 422
