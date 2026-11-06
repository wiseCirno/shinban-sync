# NAS 部署

三套示例都使用 GitHub Actions 发布的多架构镜像：

```text
ghcr.io/wisecirno/shinban-sync:latest
```

先复制配置文件，并至少填写 TMDB、Aria2 和存储配置：

```bash
cp config.example.yml config.yml
```

默认网页端口是 **3325**。配置目录和日志目录建议单独保存；如果使用 `local` 存储，还要把 Aria2 下载目录挂载到 `/app/aria2`，媒体库挂载到 `/app/target`，并在 `config.yml` 使用这两个容器内路径。

## Unraid

导入 [`examples/nas/unraid/compose.yaml`](../examples/nas/unraid/compose.yaml)，并将 [`examples/nas/unraid/config.example.yml`](../examples/nas/unraid/config.example.yml) 复制为同目录的 `config.yml`。示例主机配置目录是 `/mnt/user/appdata/shinban-sync/`，可按自己的 Unraid 共享目录调整。

## 群晖 DSM

在 Container Manager 的「项目」中导入 [`examples/nas/synology/compose.yaml`](../examples/nas/synology/compose.yaml)，并将 [`examples/nas/synology/config.example.yml`](../examples/nas/synology/config.example.yml) 复制为同目录的 `config.yml`。DSM 共享文件夹路径通常是 `/volume1/...`，请按实际目录修改。

## 飞牛 OS

在 Docker/Compose 项目中导入 [`examples/nas/fnos/compose.yaml`](../examples/nas/fnos/compose.yaml)，并将 [`examples/nas/fnos/config.example.yml`](../examples/nas/fnos/config.example.yml) 复制为同目录的 `config.yml`。卷左侧的路径请替换为飞牛文件管理器中显示的实际绝对路径。

## 访问与组合模块

启动后访问：

```text
http://NAS_IP:3325
```

示例默认只启用 Web。需要 Telegram 和定时同步时，把 compose 中的：

```yaml
command: ["run", "--modules", "web", ...]
```

改成：

```yaml
command: ["run", "--modules", "web,bot,schedule", "--host", "0.0.0.0", "--port", "3325", "-c", "/app/config.yml"]
```

首次使用建议先只启用 Web，确认配置和 Aria2 连通后，再开启定时任务。
