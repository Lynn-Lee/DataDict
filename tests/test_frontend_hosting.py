from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # app.main 在 import 时就会创建应用并读取配置，必须等 conftest 注入环境变量之后再导入
    from app.main import mount_frontend

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("secret")

    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    mount_frontend(app, tmp_path, "/api/v1")
    return TestClient(app)


def test_serves_index_and_spa_routes(client: TestClient) -> None:
    assert "spa" in client.get("/").text
    assert "spa" in client.get("/search").text
    assert "spa" in client.get("/tables/mysql:abc").text


def test_serves_assets_and_root_files(client: TestClient) -> None:
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"


def test_api_routes_win_and_unknown_api_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/ping").json() == {"ok": "yes"}
    assert client.get("/api/v1/nope").status_code == 404


def test_path_traversal_does_not_leak_files(client: TestClient) -> None:
    response = client.get("/..%2Fsecret.txt")
    assert "secret" not in response.text
