import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from shinban_sync.utils.numbers import parse_int

DEFAULT_CRON = "0 4 * * *"
CRON_FILE = Path("/etc/cron.d/shinban-sync")


class ScheduleError(ValueError):
    pass


def validate_cron(expr: str) -> str:
    text = (expr or "").strip()
    if not text:
        raise ScheduleError("cron 表达式不能为空")
    if any(ch in text for ch in "\r\n;|&$`"):
        raise ScheduleError("cron 表达式包含非法字符")
    parts = text.split()
    if len(parts) != 5:
        raise ScheduleError("cron 需要 5 段：分 时 日 月 周")
    return text


def sync_argv(config_path: str) -> list[str]:
    executable = shutil.which("shinban-sync")
    if executable:
        return [executable, "sync", "-c", str(config_path)]
    return [sys.executable, "-m", "shinban_sync", "sync", "-c", str(config_path)]


def sync_command(config_path: str) -> str:
    return " ".join(shlex.quote(part) for part in sync_argv(config_path))


def cron_file_text(cron_expr: str, config_path: str) -> str:
    cron_expr = validate_cron(cron_expr)
    command = sync_command(config_path)
    return (
        "SHELL=/bin/sh\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        f"{cron_expr} root {command} >> /var/log/shinban-sync.log 2>&1\n"
    )


def cron_binary() -> str | None:
    for candidate in ("/usr/sbin/cron", "/usr/sbin/crond"):
        if Path(candidate).exists():
            return candidate
    return shutil.which("cron") or shutil.which("crond")


def install_system_cron(cron_expr: str, config_path: str) -> Path:
    if cron_binary() is None:
        raise ScheduleError("未找到 cron。请在镜像内安装 cron，或把下面的命令交给宿主机 crontab")
    text = cron_file_text(cron_expr, config_path)
    CRON_FILE.write_text(text, encoding = "utf-8")
    CRON_FILE.chmod(0o644)
    return CRON_FILE


WEEKDAYS = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")
INTERVAL_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)


def _clock_part(value: object, low: int, high: int, label: str) -> int:
    try:
        number = parse_int(value)
    except ValueError as exc:
        raise ScheduleError(f"{label}必须是整数") from exc
    if number < low or number > high:
        raise ScheduleError(f"{label}超出范围")
    return number


def _infer_from_cron(cron_expr: str) -> dict[str, Any]:
    minute_text, hour_text, _day, _month, weekday_text = validate_cron(cron_expr).split()
    minute = parse_int(minute_text, 0) if minute_text.isdigit() else 0
    if hour_text.startswith("*/") and hour_text[2:].isdigit():
        return {
            "mode": "interval",
            "hour": 4,
            "minute": minute,
            "interval_hours": parse_int(hour_text[2:]),
            "weekday": 1,
        }
    hour = parse_int(hour_text, 4) if hour_text.isdigit() else 4
    if weekday_text.isdigit():
        return {
            "mode": "weekly",
            "hour": hour,
            "minute": minute,
            "interval_hours": 12,
            "weekday": parse_int(weekday_text),
        }
    return {
        "mode": "daily",
        "hour": hour,
        "minute": minute,
        "interval_hours": 12,
        "weekday": 1,
    }


def friendly_schedule(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = data or {}
    inferred = _infer_from_cron(str(raw.get("cron") or DEFAULT_CRON))
    mode = (
        raw.get("mode") if raw.get("mode") in ("daily", "interval", "weekly") else inferred["mode"]
    )
    hour = _clock_part(raw.get("hour", inferred["hour"]), 0, 23, "小时")
    minute = _clock_part(raw.get("minute", inferred["minute"]), 0, 59, "分钟")
    interval_hours = _clock_part(
        raw.get("interval_hours", inferred["interval_hours"]), 1, 24, "间隔小时"
    )
    if interval_hours not in INTERVAL_HOURS:
        raise ScheduleError("间隔只能是 1、2、3、4、6、8、12 或 24 小时")
    weekday = _clock_part(raw.get("weekday", inferred["weekday"]), 0, 6, "星期")
    if mode == "interval":
        cron = (
            f"{minute} */{interval_hours} * * *"
            if interval_hours != 24
            else f"{minute} {hour} * * *"
        )
        summary = f"每隔 {interval_hours} 小时，在第 {minute:02d} 分"
    elif mode == "weekly":
        cron = f"{minute} {hour} * * {weekday}"
        summary = f"每{WEEKDAYS[weekday]} {hour:02d}:{minute:02d}"
    else:
        mode = "daily"
        cron = f"{minute} {hour} * * *"
        summary = f"每天 {hour:02d}:{minute:02d}"
    return {
        "enabled": bool(raw.get("enabled", False)),
        "mode": mode,
        "hour": hour,
        "minute": minute,
        "interval_hours": interval_hours,
        "weekday": weekday,
        "summary": summary,
        "cron": validate_cron(cron),
    }


def describe_schedule(cron_expr: str, config_path: str) -> dict[str, Any]:
    cron_expr = validate_cron(cron_expr or DEFAULT_CRON)
    command = sync_command(config_path)
    return {
        "cron": cron_expr,
        "command": command,
        "crontab": f"{cron_expr} {command}",
        "docker_once": f"docker run --rm -v {shlex.quote(str(config_path))}:/app/config.yml IMAGE sync -c /app/config.yml",
        "docker_schedule": "docker run -d -v ./config.yml:/app/config.yml IMAGE run --modules schedule -c /app/config.yml",
    }
