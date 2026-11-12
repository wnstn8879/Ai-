from app.local_dev import configure_local_database


def test_usb_database_is_private_and_overrides_inherited_production_url(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://must-not-connect.invalid/production"
    )
    target = tmp_path / "folder with spaces" / "local.db"
    assert configure_local_database(target) == target.resolve()
    assert target.parent.is_dir()
    import os

    assert os.environ["DATABASE_URL"] == "sqlite:///" + target.resolve().as_posix()
