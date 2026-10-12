import asyncio
import logging

from apps.db import init_db
from apps.stores.users import sync_from_file


def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"loaded {sync_from_file()} user subscriptions")

    from apps.slack.app import start  # imported after init_db so the tables exist

    asyncio.run(start())


if __name__ == "__main__":
    main()
