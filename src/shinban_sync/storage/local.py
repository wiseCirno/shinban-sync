import os
import re
import shutil

from src.shinban_sync.models.bangumi import BangumiInfo
from src.shinban_sync.models.config import BangumiConfig
from src.shinban_sync.storage.base import BaseProvider


class LocalProvider(BaseProvider):
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        target_dir = self.get_target_dir(config)

        if not os.path.exists(target_dir):
            return []

        try:
            episodes = os.listdir(target_dir)
            matches = [int(re.search(r'S\d+E(\d+)', f).group(1))
                       for f in episodes if re.search(r'S\d+E(\d+)', f)]

            return matches

        except Exception as e:
            raise IOError(f"无法读取目录 {target_dir}: {e}")

    def rename_and_move_bangumi(self, info: BangumiInfo, config: BangumiConfig, file_name: str) -> str:
        src_dir = self.storage.aria2_path.rstrip('/')
        src_path = f"{src_dir}/{file_name}"
        target_dir = self.get_target_dir(config).rstrip('/')

        os.makedirs(target_dir, exist_ok = True)

        new_filename = self.get_standardized_filename(info, config, file_name)
        target_path = f"{target_dir}/{new_filename}"

        try:
            shutil.move(src_path, target_path)
            return target_path

        except FileNotFoundError:
            raise FileNotFoundError(f"找不到下载好的源文件: {src_path}")
        except Exception as e:
            raise IOError(f"移动文件 {file_name} 失败: {e}")
