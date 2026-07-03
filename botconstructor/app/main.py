import asyncio
import logging

from app.engine.manager import manager


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)  # не спамить в лог служебными апдейтами

    try:
        await asyncio.gather(manager.sync_loop(), manager.load_monitor_loop())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
