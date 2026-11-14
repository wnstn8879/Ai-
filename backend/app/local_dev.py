"""Private USB-development server; never adopts a production DATABASE_URL."""

import argparse
import os
from pathlib import Path


def configure_local_database(path: Path):
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + path.as_posix()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-file", required=True, type=Path)
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    from dotenv import dotenv_values

    for name, value in dotenv_values(backend / ".env").items():
        if (
            name
            in {
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "AI_USER_DAILY_LIMIT",
                "AI_ROOM_DAILY_LIMIT",
            }
            and value is not None
        ):
            os.environ.setdefault(name, value)
    configure_local_database(args.database_file)
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(backend / "alembic.ini")), "head")
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
