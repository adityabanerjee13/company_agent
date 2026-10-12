"""Serve the dashboard: `uv run python -m dashboard [--port 8787] [--host 127.0.0.1]`."""
import argparse
import logging
import os

import uvicorn
from dotenv import load_dotenv


def main():
    # before importing the app: it reads DB_PATH and TRACES_DIR at import
    load_dotenv()
    parser = argparse.ArgumentParser(description="Read-only dashboard for agent.db and traces/")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(f"db: {os.path.abspath(os.environ.get('DB_PATH', 'agent.db'))}")
    print(f"traces: {os.path.abspath(os.environ.get('TRACES_DIR', 'traces'))}")
    from dashboard.server import app
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
