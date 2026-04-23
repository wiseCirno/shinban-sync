FROM python:3.13-slim

WORKDIR /shinban-sync

# 安装必要的系统依赖 (如果有需要可以自行添加，比如 tzdata 用于时区)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
# 如果要用 TG 机器人就改成 true
ENV ENABLE_TELEGRAM_BOT=false

# 复制依赖配置并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY src/ ./src/

# 配置容器
VOLUME /app

# 设置启动命令，默认寻找 /app/config.yml 并且常驻运行
ENTRYPOINT ["python", "-m", "src.shinban_sync.main"]
CMD ["-l", "-c", "/app/config.yml"]
