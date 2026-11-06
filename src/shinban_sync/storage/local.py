import os
import re
import shutil
from typing import override

from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.config import BangumiConfig
from shinban_sync.storage.base import BaseProvider
from shinban_sync.utils.numbers import parse_int


class LocalProvider(BaseProvider):
    @override
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        target_dir = self.get_target_dir(config)

        if not os.path.exists(target_dir):
            return []

        try:
            matches = []
            for name in os.listdir(target_dir):
                found = re.search(r"S\d+E(\d+)", name)
                if found:
                    matches.append(parse_int(found.group(1)))
            return matches

        except OSError as e:
            raise OSError(f"无法读取目录 {target_dir}: {e}") from e

    @override
    def rename_and_move_bangumi(
            self, info: BangumiInfo, config: BangumiConfig, file_name: str
    ) -> str:
        src_dir = self.storage.aria2_path.rstrip("/")
        src_path = f"{src_dir}/{file_name}"
        target_dir = self.get_target_dir(config).rstrip("/")

        os.makedirs(target_dir, exist_ok = True)

        new_filename = self.get_standardized_filename(info, config, file_name)
        target_path = f"{target_dir}/{new_filename}"

        try:
            shutil.move(src_path, target_path)
            return target_path

        except FileNotFoundError:
            raise FileNotFoundError(f"找不到下载好的源文件: {src_path}")
        except OSError as e:
            raise OSError(f"移动文件 {file_name} 失败: {e}") from e
