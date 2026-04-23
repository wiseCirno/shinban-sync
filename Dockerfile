FROM python:3.10-slim

WORKDIR /app

# 安装必要的系统依赖 (如果有需要可以自行添加，比如 tzdata 用于时区)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 设置默认时区，推荐为亚洲/上海
ENV TZ=Asia/Shanghai

# 复制依赖配置并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY src/ ./src/

# 设置启动命令，默认寻找 /app/config.yml 并且常驻运行
CMD ["python", "-m", "src.shinban_sync.main", "-b", "-l"]
