import argparse
import asyncio
import sys

from shinban_sync.core.config import ConfigError, ConfigManager
from shinban_sync.core.schedule import (
    ScheduleError,
    cron_binary,
    describe_schedule,
    install_system_cron,
    sync_argv,
)
from shinban_sync.core.sync import check_network_connectivity, run_once
from shinban_sync.utils.logger import logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog = "shinban-sync",
        description = "新番同步。sync 跑完即退出；web、bot、schedule 按需单独启用。",
    )
    sub = parser.add_subparsers(dest = "command", required = True)

    sync = sub.add_parser("sync", help = "检索、下载并归档一轮，然后退出")
    _add_config_arg(sync)

    bot = sub.add_parser("bot", help = "只启动 Telegram 模块")
    _add_config_arg(bot)

    web = sub.add_parser("web", help = "只启动 Web 管理界面")
    _add_config_arg(web)
    _add_bind_args(web)

    run = sub.add_parser("run", help = "按模块启动，供 Docker 启动参数使用")
    _add_config_arg(run)
    _add_bind_args(run)
    run.add_argument(
        "--modules",
        required = True,
        help = "逗号分隔：sync、web、bot、schedule。sync 不能和其他模块同时使用",
    )
    return parser


def _add_config_arg(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-c", "--config", help = "配置文件路径。若 BANGUMI_CONFIG_PATH 指向已存在文件，则优先使用它"
    )


def _add_bind_args(parser: argparse.ArgumentParser):
    parser.add_argument("--host", help = "Web 监听地址，默认读配置，否则 127.0.0.1")
    parser.add_argument("--port", type = int, help = "Web 监听端口，默认读配置，否则 3325")


async def execute_sync(config_path: str | None) -> int:
    from pathlib import Path

    from shinban_sync.utils.runlog import begin_run_log

    try:
        resolved = str(ConfigManager(config_path).config_path)
    except ConfigError as exc:
        logger.error(str(exc))
        return 1
    sink = logger.add(
        begin_run_log(Path(resolved)),
        format = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        colorize = False,
        encoding = "utf-8",
    )
    code = 0
    try:
        if not check_network_connectivity():
            logger.error("网络异常，无法访问 acg.rip，请检查网络或代理")
            code = 1
        else:
            await run_once(resolved)
            logger.info("本轮检索已完成，进程退出")
    except ConfigError as exc:
        logger.error(str(exc))
        code = 1
    finally:
        logger.remove(sink)
    return code


async def serve_bot(config_path: str | None):
    from shinban_sync.telegram.bot import Bot

    config = ConfigManager(config_path)
    bot = Bot(config)
    logger.info("🤖 [系统启动] 正在初始化 Telegram Bot...")
    await bot.app.initialize()
    await bot.app.start()
    if bot.app.updater is None:
        raise ConfigError("Telegram updater 未初始化")
    await bot.app.updater.start_polling()
    logger.info("🤖 [系统启动] Telegram Bot 已开始接收消息")
    try:
        await asyncio.Event().wait()
    finally:
        logger.info("🛑 [系统停止] 正在关闭 Telegram Bot...")
        await bot.app.updater.stop()
        await bot.app.stop()
        await bot.app.shutdown()


async def serve_web(config_path: str | None, host: str | None, port: int | None):
    import uvicorn

    from shinban_sync.web.app import create_app, ensure_frontend

    ensure_frontend()
    config = ConfigManager(config_path)
    settings = config.get_web_settings()
    bind_host = host or settings["host"]
    bind_port = port or settings["port"]
    app = create_app(str(config.config_path))
    server = uvicorn.Server(uvicorn.Config(app, host = bind_host, port = bind_port, log_level = "info"))
    logger.info(f"🌐 [Web] 管理界面监听 http://{bind_host}:{bind_port}")
    await server.serve()


async def start_schedule(config_path: str | None) -> asyncio.subprocess.Process:
    config = ConfigManager(config_path)
    schedule = config.get_schedule()
    resolved = str(config.config_path)
    shown = describe_schedule(schedule["cron"], resolved)
    try:
        install_system_cron(schedule["cron"], resolved)
    except OSError as exc:
        raise ScheduleError(f"无法写入系统 cron：{exc}。可手动安装：{shown['crontab']}") from exc
    binary = cron_binary()
    if binary is None:
        raise ScheduleError(f"未找到 cron。可手动安装：{shown['crontab']}")
    logger.info(f"⏱️ [定时] 已安装系统 cron：{shown['crontab']}")
    logger.info("⏱️ [定时] 先拉起一轮 CLI，结束后由 cron 按计划再次调用")
    initial = await asyncio.create_subprocess_exec(*sync_argv(resolved))
    asyncio.create_task(_wait_initial_sync(initial))
    return await asyncio.create_subprocess_exec(binary, "-f")


async def _wait_initial_sync(process: asyncio.subprocess.Process):
    code = await process.wait()
    logger.info(f"✅ [定时] 启动时的一轮同步已结束，退出码 {code}")


def parse_modules(raw: str) -> list[str]:
    modules = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = sorted(set(modules) - {"sync", "web", "bot", "schedule"})
    if unknown:
        raise ConfigError(f"未知模块: {', '.join(unknown)}")
    if not modules:
        raise ConfigError("至少启用一个模块")
    if "sync" in modules and len(modules) > 1:
        raise ConfigError(
            "sync 是一次性命令，不能和 web、bot、schedule 同时启用。定期更新请使用 schedule"
        )
    return modules


async def run_modules(
        config_path: str | None, modules: list[str], host: str | None, port: int | None
) -> int:
    if modules == ["sync"]:
        return await execute_sync(config_path)

    tasks: list[asyncio.Task[object]] = []
    cron_proc: asyncio.subprocess.Process | None = None
    try:
        if "web" in modules:
            tasks.append(asyncio.create_task(serve_web(config_path, host, port)))
        if "bot" in modules:
            tasks.append(asyncio.create_task(serve_bot(config_path)))
        if "schedule" in modules:
            cron_proc = await start_schedule(config_path)
            tasks.append(asyncio.create_task(cron_proc.wait()))
        if not tasks:
            raise ConfigError("没有可启动的模块")

        done, pending = await asyncio.wait(tasks, return_when = asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if cron_proc is not None and cron_proc.returncode is None:
            cron_proc.terminate()
        for task in done:
            error = task.exception()
            if error:
                raise error
        return 0
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


async def dispatch(args: argparse.Namespace) -> int:
    if args.command == "sync":
        return await execute_sync(args.config)
    if args.command == "bot":
        await serve_bot(args.config)
        return 0
    if args.command == "web":
        await serve_web(args.config, args.host, args.port)
        return 0
    modules = parse_modules(args.modules)
    return await run_modules(args.config, modules, args.host, args.port)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
        return asyncio.run(dispatch(args))
    except KeyboardInterrupt:
        logger.info("🛑 [系统停止] 收到中断，退出")
        return 0
    except (ConfigError, ScheduleError) as exc:
        logger.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
