"""pytest 共享夹具：每个测试用独立临时数据库，互不影响。

测试绝不访问真实 LLM：这里先把模式钉成 mock，.env 里的设置不会覆盖它。
"""

from __future__ import annotations

import os

os.environ["ATB_LLM_MODE"] = "mock"
os.environ.pop("LLM_API_KEY", None)

import pytest  # noqa: E402

from app.db import Database  # noqa: E402
from app.engine import Engine  # noqa: E402


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture()
def engine(db) -> Engine:
    return Engine(db)


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(Database(tmp_path / "api.db"))
    with TestClient(app) as c:
        yield c
