# Docker 部署指南

## 快速开始

### ⚠️ 重要提示

**必须从项目根目录运行所有 Docker Compose 命令**，这样才能正确加载 `.env` 文件。

### 生产环境

1. 在项目根目录创建 `.env` 文件（参考 `.env.example`）

2. 启动服务（**从项目根目录运行**）：
```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

# 启动服务
docker compose -f docker/docker-compose.yml up -d
```

3. 查看日志（**从项目根目录运行**）：
```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

# 查看日志
docker compose -f docker/docker-compose.yml logs -f
```

4. 停止服务（**从项目根目录运行**）：
```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

# 停止服务
docker compose -f docker/docker-compose.yml down
```

> **⚠️ 重要**：所有命令必须从项目根目录（`phosys/`）运行，不能从 `docker/` 目录运行。如果在 `docker/` 目录下，请先切换到项目根目录。

### 开发环境

```bash
docker compose -f docker/docker-compose.dev.yml up
```

> **注意**：如果您的系统使用的是 Docker Compose V1（独立的 `docker-compose` 命令），请将上述命令中的 `docker compose` 替换为 `docker-compose`。

## 构建镜像

```bash
# 从项目根目录构建
docker build -f docker/Dockerfile -t audio-transcription:latest .
```

## 环境变量

所有配置通过环境变量管理，详见项目根目录的 `.env.example` 文件。

## 数据持久化

以下目录会被持久化到宿主机：
- `uploads/` - 上传的音频文件
- `transcripts/` - 转写结果文档
- `audio_temp/` - 临时文件
- `meeting_summaries/` - 会议纪要

模型缓存使用 Docker volume，可在多个容器间共享。

