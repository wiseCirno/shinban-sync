# Docker 部署

项目的 GitHub Actions 会在推送到 `main` / `master` 后构建并发布 Linux `amd64`、`arm64` 多架构镜像到 GitHub Container Registry（GHCR）。默认分支镜像标签为 `latest`，分支镜像标签与分支名相同。NAS 通常直接拉取镜像，不需要安装 Python、Poetry 或 pnpm。

镜像：[`ghcr.io/wisecirno/shinban-sync`](https://github.com/wiseCirno/shinban-sync/pkgs/container/shinban-sync)

## Compose 启动 Web

先把 [`config.example.yml`](../config.example.yml) 复制为 `config.yml` 并填写需要的配置，再创建 `logs/` 目录。项目根目录的 `docker-compose.yml` 已配置好镜像、端口和持久化目录：

```bash
cp config.example.yml config.yml
mkdir -p logs
docker compose up -d
```

访问 <http://127.0.0.1:3325>。更新到最新 `latest` 镜像：

```bash
docker compose pull
docker compose up -d
```

若镜像设为私有，需要先运行 `docker login ghcr.io`；公开镜像无需登录。

## 一次性同步

需要立即更新一次，不必启动常驻服务：

```bash
docker run --rm \
  -v "$PWD/config.yml:/app/config.yml" \
  -v "$PWD/logs:/app/logs" \
  ghcr.io/wisecirno/shinban-sync:latest \
  sync -c /app/config.yml
```

一次性容器不要设置 `restart: unless-stopped`。定时任务则在 NAS 的 Compose 项目中启用 `schedule` 模块。

## NAS 示例

- [Unraid](nas.md#unraid)
- [群晖 DSM](nas.md#群晖-dsm)
- [飞牛 OS](nas.md#飞牛-os)

示例 Compose 和配置文件位于 [`examples/nas/`](../examples/nas/)，也可看 [NAS 部署说明](nas.md)。本地存储时请把 NAS 上的下载目录、媒体库映射到容器 `/app/aria2` 和 `/app/target`，并确保 `config.yml` 使用相同容器路径。NAS 具体共享目录因个人设置不同，按实际路径替换示例中的主机路径。

容器默认时区为 `Asia/Shanghai`。更多参数见[配置说明](配置.md)。
