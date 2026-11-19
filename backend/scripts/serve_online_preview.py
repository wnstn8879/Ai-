"""Private temporary Sites bridge. Service secret is read without terminal echo."""

import argparse
import getpass
import os
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--site-id", required=True)
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--port", type=int, default=8111)
args = parser.parse_args()
secret = getpass.getpass("Private service key (hidden): ")
if len(secret) < 32:
    raise SystemExit("Service key is too short")
args.database.parent.mkdir(parents=True, exist_ok=True)
os.environ.update(
    DATABASE_URL="sqlite:///" + args.database.resolve().as_posix(),
    IMAGINE_SITE_SERVICE_KEY=secret,
    IMAGINE_SITE_ID=args.site_id,
    IMAGINE_WEB_GATEWAY_ONLY="1",
    AI_PROVIDER="ollama",
    AI_MODEL="qwen3:4b-instruct",
    AI_BASE_URL="http://127.0.0.1:11434",
    AI_MAX_OUTPUT_TOKENS="500",
    AI_OLLAMA_NUM_THREADS="2",
    AI_REQUEST_TIMEOUT_SECONDS="180",
    AI_USER_DAILY_LIMIT="60",
    AI_ROOM_DAILY_LIMIT="60",
)
from alembic import command
from alembic.config import Config

command.upgrade(Config("alembic.ini"), "head")
import uvicorn

uvicorn.run(
    "app.main:app",
    host="127.0.0.1",
    port=args.port,
    log_level="warning",
    access_log=False,
)
