import os
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from shinban_sync.cli import build_parser, parse_modules
from shinban_sync.core.catalog import subscription_from_discovery
from shinban_sync.core.config import ConfigError, ConfigManager
from shinban_sync.core.schedule import (
    ScheduleError,
    cron_file_text,
    friendly_schedule,
    validate_cron,
)
from shinban_sync.utils.runlog import list_logs, read_log
from shinban_sync.web.app import create_app


@pytest.fixture(autouse=True)
def _ignore_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BANGUMI_CONFIG_PATH", raising=False)


def test_parser_accepts_module_commands():
    args = build_parser().parse_args(
        ["run", "--modules", "web,bot", "-c", "config.yml", "--port", "3325"]
    )
    assert args.command == "run"
    assert args.modules == "web,bot"
    assert args.port == 3325


def test_sync_cannot_combine_with_resident_modules():
    assert parse_modules("web,schedule") == ["web", "schedule"]
    try:
        parse_modules("sync,web")
    except ConfigError as exc:
        assert "一次性" in str(exc)
    else:
        raise AssertionError("sync 不应和其他模块组合")


def test_cron_rejects_injection_and_renders_command(tmp_path: Path):
    try:
        validate_cron("0 4 * * *; rm -rf /")
    except ScheduleError:
        pass
    else:
        raise AssertionError("非法 cron 应被拒绝")

    text = cron_file_text("0 4 * * *", str(tmp_path / "config.yml"))
    assert text.endswith("\n")
    assert "sync -c" in text
    assert "\n" not in text.strip().splitlines()[-1].split(" root ", 1)[0]


def test_settings_round_trip_keeps_blank_secrets(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "tmdb_token": "keep-me",
                "downloader": {"aria2": {"base_url": "http://aria", "token": "secret"}},
                "storage": {
                    "provider": "local",
                    "local": {"aria2_path": "/a", "target_path": "/b"},
                },
                "anime": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manager = ConfigManager(str(path))
    view = manager.public_view()
    assert view["tmdb_token_set"] is True
    assert "keep-me" not in str(view)
    preserved = manager.raw_config["tmdb_token"]
    manager.apply_settings({"tmdb_token": "", "storage": {"provider": "local"}})
    assert ConfigManager(str(path)).raw_config["tmdb_token"] == preserved


def test_add_and_remove_subscription(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("anime: []\n", encoding="utf-8")
    manager = ConfigManager(str(path))
    created = manager.add_anime_config(
        {
            "search_keyword": "测试番",
            "filename": "Test Show",
            "subtitle": "ANi",
            "season_air_date": "2026-04-11",
        }
    )
    assert created is True
    assert (
        manager.add_anime_config(
            {
                "search_keyword": "测试番",
                "filename": "Test Show",
                "subtitle": "ANi",
                "season_air_date": "2026-04-11",
            }
        )
        is False
    )
    assert manager.remove_anime_config("Test Show", 1) is True


def test_subscription_payload_uses_selected_group():
    payload = subscription_from_discovery(
        {
            "series": {"original_name": "Orig", "first_air_date": "2020-01-01", "name": "名"},
            "season": {"season_number": 2, "air_date": "2026-04-01", "episode_count": 12},
            "groups": [{"name": "ANi", "search_keyword": "关键词", "language": "chs"}],
        },
        "ANi",
    )
    assert payload["filename"] == "Orig"
    assert payload["title"] == "名"
    assert payload["season"] == 2
    assert payload["search_keyword"] == "关键词"


def test_friendly_schedule_does_not_require_a_cron_string():
    daily = friendly_schedule({"mode": "daily", "hour": 4, "minute": 30, "enabled": True})
    assert daily["summary"] == "每天 04:30"
    assert daily["cron"] == "30 4 * * *"
    weekly = friendly_schedule({"mode": "weekly", "weekday": 1, "hour": 21, "minute": 0})
    assert weekly["summary"] == "每周一 21:00"
    assert "*/" not in weekly["cron"]
    every = friendly_schedule({"mode": "interval", "interval_hours": 6, "minute": 15})
    assert every["cron"] == "15 */6 * * *"


def test_run_logs_drop_entries_older_than_seven_days(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("anime: []\n", encoding="utf-8")
    folder = path.parent / "logs"
    folder.mkdir()
    stale = folder / "20260401-000000.log"
    stale.write_text("旧日志\n", encoding="utf-8")
    stale.touch()
    old = datetime.now().timestamp() - 8 * 24 * 3600
    os.utime(stale, (old, old))
    assert list_logs(path) == []
    assert not stale.exists()


def test_run_logs_are_listed_without_color_codes(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("anime: []\n", encoding="utf-8")
    log = path.parent / "logs"
    log.mkdir()
    (log / "20260411-120000.log").write_text("\x1b[32m完成\x1b[0m\n", encoding="utf-8")
    listed = list_logs(path)
    assert listed[0]["name"] == "20260411-120000.log"
    assert read_log(path, listed[0]["name"]) == "完成\n"
    try:
        read_log(path, "../config.yml")
    except ValueError:
        pass
    else:
        raise AssertionError("不能读配置目录以外的文件")


def test_web_hides_secrets_and_serves_ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.yml"
    path.write_text("tmdb_token: hidden\nweb:\n  token: gate\nanime: []\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Shinban Sync</title>", encoding="utf-8")
    monkeypatch.setenv("SHINBAN_WEB_DIST", str(dist))
    client = TestClient(create_app(str(path)))
    assert client.get("/api/health").status_code == 200
    assert "Shinban Sync" in client.get("/").text
    assert client.get("/api/settings").status_code == 401
    allowed = client.get("/api/settings", headers={"X-Shinban-Token": "gate"})
    assert allowed.status_code == 200
    assert allowed.json()["tmdb_token_set"] is True
    assert allowed.json()["web"]["port"] == 3325
    assert "hidden" not in allowed.text
