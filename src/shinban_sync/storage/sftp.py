import re
from types import TracebackType
from typing import override

import paramiko

from shinban_sync.models.bangumi import BangumiInfo
from shinban_sync.models.config import BangumiConfig, SftpStorageConfig
from shinban_sync.storage.base import BaseProvider
from shinban_sync.utils.numbers import parse_int


class SftpProvider(BaseProvider):
    def __init__(self, storage: SftpStorageConfig) -> None:
        super().__init__(storage)
        remote: SftpStorageConfig = storage

        self.transport: paramiko.Transport = paramiko.Transport((remote.host, remote.port))
        self.transport.set_keepalive(30.0)  # 避免等待 aria2 过久时出现 broken pipe

        if remote.password:
            self.transport.connect(username = remote.user, password = remote.password)
        elif remote.pub_key:
            pkey = paramiko.RSAKey.from_private_key_file(remote.pub_key)
            self.transport.connect(username = remote.user, pkey = pkey)
        else:
            raise ValueError("password 和 pub_key 字段必须要有一个存在")

        client = paramiko.SFTPClient.from_transport(self.transport)
        if client is None:
            raise RuntimeError("无法建立 SFTP 连接")
        self.sftp: paramiko.SFTPClient = client

    @override
    def __enter__(self):
        return super().__enter__()

    @override
    def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        if hasattr(self, "sftp"):
            self.sftp.close()
        if hasattr(self, "transport"):
            self.transport.close()
        super().__exit__(exc_type, exc_val, exc_tb)

    def _makedirs(self, path: str):
        folders = path.replace("\\", "/").split("/")
        current_path = ""
        for folder in folders:
            if not folder:
                continue
            current_path += f"/{folder}"
            try:
                self.sftp.stat(current_path)
            except OSError:
                self.sftp.mkdir(current_path)

    def _move(self, src: str, dest: str) -> bool:
        try:
            self.sftp.rename(src, dest)
            return True
        except OSError:
            return False

    @override
    def rename_and_move_bangumi(
            self, info: BangumiInfo, config: BangumiConfig, file_name: str
    ) -> str:
        src_dir = self.storage.aria2_path.rstrip("/")
        src_path = f"{src_dir}/{file_name}"
        target_dir = self.get_target_dir(config).rstrip("/")
        self._makedirs(target_dir)

        new_filename = self.get_standardized_filename(info, config, file_name)
        try:
            self.sftp.rename(src_path, f"{target_dir}/{new_filename}")
            return f"{target_dir}/{new_filename}"
        except OSError as e:
            raise OSError(f"移动文件 {file_name} 失败: {e}") from e

    @override
    def get_existing_episodes(self, config: BangumiConfig) -> list[int]:
        try:
            matches = []
            for name in self.sftp.listdir(self.get_target_dir(config)):
                found = re.search(r"S\d+E(\d+)", name)
                if found:
                    matches.append(parse_int(found.group(1)))
            return matches
        except OSError:
            return []
