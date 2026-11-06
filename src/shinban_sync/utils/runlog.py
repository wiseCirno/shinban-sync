import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_KEEP_DAYS = 7

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain_log(text: str) -> str:
    return _ANSI.sub("", text)


def log_dir(config_path: Path) -> Path:
    path = Path(config_path).resolve().parent / "logs"
    path.mkdir(parents = True, exist_ok = True)
    return path


def prune_logs(config_path: Path) -> None:
    cutoff = datetime.now() - timedelta(days = _KEEP_DAYS)
    directory = log_dir(config_path)
    for path in directory.glob("*.log"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified < cutoff:
            path.unlink(missing_ok = True)


def begin_run_log(config_path: Path) -> Path:
    prune_logs(config_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return log_dir(config_path) / f"{stamp}.log"


def list_logs(config_path: Path) -> list[dict[str, Any]]:
    prune_logs(config_path)
    directory = log_dir(config_path)
    items = []
    for path in sorted(directory.glob("*.log"), reverse = True):
        if not path.is_file():
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return items[:50]


def read_log(config_path: Path, name: str) -> str:
    if "/" in name or "\\" in name or not re.fullmatch(r"[0-9]{8}-[0-9]{6}\.log", name):
        raise ValueError("日志名称不合法")
    path = log_dir(config_path) / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return plain_log(path.read_text(encoding = "utf-8", errors = "replace"))
