import pytest
from sqlalchemy.engine import make_url

from ai_tutor.config import Settings


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_hosted_database_url_uses_installed_driver(scheme):
    settings = Settings(
        _env_file=None,
        database_url=f"{scheme}://user:p%40ss@db.example:5432/tutor?sslmode=require",
    )
    url = make_url(settings.database_url)
    assert url.get_dialect().driver == "psycopg"
    assert url.username == "user"
    assert url.password == "p@ss"
    assert url.host == "db.example"
    assert url.port == 5432
    assert url.database == "tutor"
    assert url.query["sslmode"] == "require"
