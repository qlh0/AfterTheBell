"""pytest 共享夹具：每个测试用独立临时数据库，互不影响。"""

from __future__ import annotations

import pytest

from app.db import Database
from app.engine import Engine


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
