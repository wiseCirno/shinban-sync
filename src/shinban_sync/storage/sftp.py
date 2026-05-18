import re

import paramiko

from src.shinban_sync.models.bangumi import BangumiInfo
from src.shinban_sync.models.config import BangumiConfig, SftpStorageConfig
from src.shinban_sync.storage.base import BaseProvider


class SftpProvider(BaseProvider):
    def __init__(self, storage: SftpStorageConfig) -> None:
        super().__init__(storage)

        self.storage: SftpStorageConfig = storage
        self.transport = paramiko.Transport((self.storage.host, self.storage.port))

        if self.storage.password:
            self.transport.connect(username = self.storage.user, password = self.storage.password)
        elif self.storage.pub_key:
            pkey = paramiko.RSAKey.from_private_key_file(self.storage.pub_key)
            self.transport.connect(username = self.storage.user, pkey = pkey)
        else:
            raise ValueError("password 和 pub_key 字段必须要有一个存在")

        self.sftp = paramiko.SFTPClient.from_transport(self.transport)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, 'sftp'): self.sftp.close()
        if hasattr(self, 'transport'): self.transport.close()

    def _makedirs(self, path: str):
        folders = path.replace('\\', '/').split('/')
        current_path = ""
        for folder in folders:
            if not folder:
                continue
            current_path += f"/{folder}"
            try:
                self.sftp.stat(current_path)
            except IOError:
                self.sftp.mkdir(current_path)

    def _move(self, src: str, dest: str) -> bool:
        try:
            self.sftp.rename(src, dest)
            return True
        except IOError:
            return False

    def rename_and_move_bangumi(self, info: BangumiInfo, config: BangumiConfig, file_name: str) -> str:
        src_dir = self.storage.aria2_path.rstrip('/')
        src_path = f"{src_dir}/{file_name}"
        target_dir = self.get_target_dir(config).rstrip('/')
        self._makedirs(target_dir)

        new_filename = self.get_standardized_filename(info, config, file_name)
        try:
            self.sftp.rename(src_path, f"{target_dir}/{new_filename}")
            return f"{target_dir}/{new_filename}"
        except IOError as e:
            raise IOError(f"移动文件 {file_name} 失败: {e}")

    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        try:
            episodes = self.sftp.listdir(self.get_target_dir(config))
            matches = [int(re.search(r'S\d+E(\d+)', f).group(1))
                       for f in episodes if re.search(r'S\d+E(\d+)', f)]

            return matches
        except IOError:
            return []
