"""
Phoenix Proxy — Entry point.
Starts all three services concurrently in a single asyncio event loop:
  1. MTProto Proxy Engine (asyncio TCP server)
  2. Web Admin Panel (FastAPI via uvicorn)
  3. Telegram Bot (optional, only if BOT_TOKEN is set)

Fa: نقطه شروع برنامه — هر سه سرویس را همزمان اجرا می‌کند.
"""
import asyncio
import os
import signal
import sys

import uvicorn

from proxy.config import ProxyConfig
from proxy.server import MTProtoProxyServer
from panel.database import Database
from panel.app import create_app
from utils.logger import setup_logger

logger = setup_logger("phoenix.main")


class PhoenixApp:
    """Orchestrates proxy + panel + bot lifecycle."""

    def __init__(self) -> None:
        self.config = ProxyConfig.from_env()
        self.db = Database(self.config.database_path)
        self.proxy_server: MTProtoProxyServer | None = None
        self.bot_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Initialize DB, then launch all services."""
        logger.info("=" * 60)
        logger.info("Phoenix Proxy starting up...")
        logger.info("=" * 60)

        # 1) Database first — everything depends on it
        await self.db.init()
        await self.db.seed_defaults(self.config)
        logger.info("Database ready at %s", self.config.database_path)

        # 2) Proxy engine
        self.proxy_server = MTProtoProxyServer(self.config, self.db)
        proxy_coro = self.proxy_server.start(
            host="0.0.0.0", port=self.config.proxy_port
        )

        # 3) Panel (FastAPI/uvicorn) — run inside this loop
        app = create_app(self.config, self.db, self.proxy_server)
        uv_config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.config.panel_port,
            log_level=self.config.log_level.lower(),
            access_log=False,
        )
        uv_server = uvicorn.Server(uv_config)
        # Prevent uvicorn from installing its own signal handlers
        uv_server.install_signal_handlers = lambda: None

        # 4) Telegram bot (optional)
        bot_coro = None
        if self.config.bot_token:
            from bot.telegram_bot import run_bot
            bot_coro = run_bot(self.config, self.db, self.proxy_server)
            logger.info("Telegram bot enabled")
        else:
            logger.info("Telegram bot disabled (no BOT_TOKEN)")

        # Launch everything
        tasks = [
            asyncio.create_task(proxy_coro, name="proxy"),
            asyncio.create_task(uv_server.serve(), name="panel"),
        ]
        if bot_coro:
            tasks.append(asyncio.create_task(bot_coro, name="bot"))

        logger.info("Panel:  http://0.0.0.0:%d", self.config.panel_port)
        logger.info("Proxy:  0.0.0.0:%d", self.config.proxy_port)

        self._install_signal_handlers()
        await self._shutdown_event.wait()

        # Graceful shutdown
        logger.info("Shutting down services...")
        if self.proxy_server:
            await self.proxy_server.shutdown()
        uv_server.should_exit = True
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.db.close()
        logger.info("Shutdown complete. Goodbye.")

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._shutdown_event.set)
            except NotImplementedError:
                # Windows fallback
                signal.signal(sig, lambda *_: self._shutdown_event.set())


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app = PhoenixApp()
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
