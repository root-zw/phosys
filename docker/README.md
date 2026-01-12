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

### 重要提示

1. **`.env` 文件位置**：必须在项目根目录，不能放在 `docker/` 目录下
   - `docker-compose.yml` 使用 `../.env` 路径（相对于 docker 目录）
   - `config.py` 在项目根目录查找 `.env` 文件

2. **环境变量加载顺序**：
   - `env_file` 中的 `.env` 文件（项目根目录）
   - `environment` 中的环境变量（会覆盖 `env_file` 中的值）
   - 注意：`DIFY_BASE_URL` 完全从 `.env` 文件加载，不在 `docker-compose.yml` 中设置默认值

3. **修改环境变量后**：
   - 不需要重新构建镜像
   - 只需重启容器：`docker compose -f docker/docker-compose.yml restart`

## 数据持久化

以下目录会被持久化到宿主机：
- `uploads/` - 上传的音频文件
- `transcripts/` - 转写结果文档
- `audio_temp/` - 临时文件
- `meeting_summaries/` - 会议纪要

模型缓存使用 Docker volume，可在多个容器间共享。

## 常见问题

### 1. 环境变量未生效

**问题**：修改 `.env` 文件后，容器中的环境变量没有更新。

**解决方案**：
1. 确保 `.env` 文件在项目根目录
2. 确保从项目根目录运行 Docker Compose 命令
3. 重启容器：
   ```bash
   docker compose -f docker/docker-compose.yml restart
   ```

### 2. 容器健康检查失败

**问题**：容器显示为 `unhealthy`。

**可能原因**：
- 模型未加载（这是正常状态，延迟加载模式）
- 存储空间不足
- FFmpeg 不可用
- 系统资源不足

**检查方法**：
```bash
# 查看健康检查详细响应
docker exec audio-transcription-service curl http://localhost:8998/healthz

# 查看容器健康状态
docker inspect audio-transcription-service --format='{{json .State.Health}}' | jq '.'
```

**说明**：
- 模型未加载不影响服务功能（延迟加载模式）
- Dify 服务是可选服务，未配置不影响系统运行

### 3. Dify Webhook 连接失败

**问题**：日志显示 Dify Webhook 连接超时或失败。

**可能原因**：
- Docker 容器网络无法访问 Dify 服务地址
- `.env` 文件中的 `DIFY_BASE_URL` 配置错误

**解决方案**：
1. 检查 `.env` 文件中的 `DIFY_BASE_URL` 配置
2. 确保容器可以访问该地址：
   ```bash
   docker exec audio-transcription-service curl http://your-dify-address:5001/health
   ```
3. 如果 Dify 在宿主机上，可能需要使用 `host.docker.internal` 或宿主机网关 IP

**注意**：Dify 是可选服务，连接失败不影响系统正常运行。

