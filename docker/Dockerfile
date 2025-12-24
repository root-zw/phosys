# 多阶段构建 Dockerfile
# 阶段1: 构建阶段
FROM python:3.11-slim AS builder

# 设置工作目录
WORKDIR /app

# 支持构建时代理（如果设置了 ARG）
ARG http_proxy
ARG https_proxy
ARG no_proxy
ENV http_proxy=${http_proxy}
ENV https_proxy=${https_proxy}
ENV no_proxy=${no_proxy}

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 使用国内镜像源并增加超时时间
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.timeout 300 && \
    pip config set global.retries 5

# 复制依赖文件（从项目根目录）
COPY requirements.txt .

# 安装 Python 依赖（增加超时时间和重试次数）
RUN pip install --no-cache-dir --upgrade pip --timeout=300 --retries=5 && \
    pip install --no-cache-dir -r requirements.txt --timeout=300 --retries=5

# 阶段2: 运行阶段
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制 Python 环境
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制应用代码（从项目根目录）
COPY . .

# 创建必要的目录
RUN mkdir -p uploads transcripts audio_temp meeting_summaries && \
    chmod -R 755 uploads transcripts audio_temp meeting_summaries

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production

# 暴露端口
EXPOSE 8998

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8998/healthz || exit 1

# 启动命令
CMD ["python", "main.py"]

