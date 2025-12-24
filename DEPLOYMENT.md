# 部署与运维指南

## 目录
1. [Docker 部署](#docker-部署)
2. [Docker Compose 部署](#docker-compose-部署)
3. [健康检查](#健康检查)
4. [配置管理](#配置管理)

## Docker 部署

### 构建镜像

从项目根目录构建：

```bash
docker build -f docker/Dockerfile -t audio-transcription:latest .
```

### 运行容器

```bash
docker run -d \
  --name audio-transcription \
  -p 8998:8998 \
  -e ENVIRONMENT=production \
  -e DIFY_API_KEY=your_key \
  -e DIFY_BASE_URL=http://your-dify:5001 \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/transcripts:/app/transcripts \
  -v $(pwd)/audio_temp:/app/audio_temp \
  -v $(pwd)/meeting_summaries:/app/meeting_summaries \
  audio-transcription:latest
```

## Docker Compose 部署

### 生产环境

1. 在项目根目录复制环境配置文件：
```bash
cp .env.example .env
# 编辑 .env 文件，填入实际配置
```

2. 启动服务（从项目根目录）：
```bash
docker compose -f docker/docker-compose.yml up -d
```

或者进入 docker 目录：
```bash
cd docker
docker compose -f docker-compose.yml up -d
```

3. 查看日志：
```bash
docker compose -f docker/docker-compose.yml logs -f
```

4. 停止服务：
```bash
docker compose -f docker/docker-compose.yml down
```

### 开发环境

使用开发配置（从项目根目录）：
```bash
docker compose -f docker/docker-compose.dev.yml up
```

或者进入 docker 目录：
```bash
cd docker
docker compose -f docker-compose.dev.yml up
```

> **注意**：本文档使用 Docker Compose V2 语法（`docker compose`）。如果您的系统使用的是 V1（独立的 `docker-compose` 命令），请将命令中的 `docker compose` 替换为 `docker-compose`。

> 更多 Docker 相关说明请参考 `docker/README.md`

## 健康检查

### 基础健康检查

```bash
curl http://localhost:8998/healthz
```

### 详细健康检查

健康检查端点会检查以下内容：

1. **模型加载状态**
   - 模型是否已加载
   - 模型池可用实例数
   - 模型池总大小

2. **存储空间**
   - 上传目录（uploads）
   - 转写输出目录（transcripts）
   - 临时文件目录（audio_temp）
   - 会议纪要目录（meeting_summaries）
   - 每个目录的：
     - 是否存在
     - 是否可写
     - 总容量
     - 可用空间
     - 使用百分比

3. **系统资源**
   - CPU 使用率
   - 内存使用率
   - 可用内存

4. **依赖服务**
   - Dify Webhook 服务可用性
   - FFmpeg 是否可用

### 健康检查响应示例

```json
{
  "status": "healthy",
  "version": "3.1.3-FunASR",
  "checks": {
    "models": {
      "status": "healthy",
      "loaded": true,
      "pool_available": 3,
      "pool_size": 6
    },
    "storage": {
      "uploads": {
        "exists": true,
        "writable": true,
        "total_gb": 500.0,
        "free_gb": 450.0,
        "used_percent": 10.0,
        "status": "healthy"
      }
    },
    "system": {
      "cpu_percent": 25.5,
      "memory_percent": 45.2,
      "memory_available_gb": 8.5,
      "status": "healthy"
    },
    "dify": {
      "configured": true,
      "available": true,
      "status": "healthy"
    },
    "ffmpeg": {
      "available": true,
      "status": "healthy"
    }
  }
}
```

### Docker 健康检查

Docker 容器内置健康检查，使用 `/healthz` 端点：
- 检查间隔：30秒
- 超时时间：10秒
- 启动等待期：60秒
- 重试次数：3次

## 配置管理

### 环境区分

项目支持三种环境：

1. **development** (开发环境)
   - 轻量配置
   - 模型池大小：1
   - 转写并发数：2
   - 限流：关闭或宽松

2. **staging** (预发布环境)
   - 中等配置
   - 模型池大小：3
   - 转写并发数：6
   - 限流：启用

3. **production** (生产环境)
   - 高性能配置
   - 模型池大小：6
   - 转写并发数：12
   - 限流：严格

### 环境变量配置

#### 基础配置

```bash
ENVIRONMENT=production  # development, staging, production
```

#### 文件目录配置（可选）

```bash
UPLOAD_DIR=/data/uploads
OUTPUT_DIR=/data/transcripts
TEMP_DIR=/data/temp
SUMMARY_DIR=/data/summaries
```

#### 并发配置（可选，会根据环境自动调整）

```bash
ASR_POOL_SIZE=6
TRANSCRIPTION_WORKERS=12
MAX_MEMORY_MB=8192
RATE_LIMIT_PER_MINUTE=36
RATE_LIMIT_PER_HOUR=240
```

#### Dify 配置

```bash
DIFY_API_KEY=your_api_key
DIFY_BASE_URL=http://your-dify:5001
DIFY_WORKFLOW_ID=optional_workflow_id
DIFY_USER_ID=your_user_id
```

#### AI 模型配置

```bash
# DeepSeek
DEEPSEEK_API_KEY=your_key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Qwen
QWEN_API_KEY=your_key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo

# GLM
GLM_API_KEY=your_key
GLM_API_BASE=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-4
```

### 配置文件优先级

1. 环境变量（最高优先级）
2. `.env.{ENVIRONMENT}` 文件（如 `.env.production`）
3. `.env` 文件
4. 代码中的默认值

### 使用示例

#### 开发环境

```bash
# .env.development
ENVIRONMENT=development
DIFY_API_KEY=dev_key
# ... 其他配置
```

#### 生产环境

```bash
# .env.production
ENVIRONMENT=production
DIFY_API_KEY=prod_key
ASR_POOL_SIZE=8
TRANSCRIPTION_WORKERS=16
# ... 其他配置
```

## 监控与日志

### Prometheus 指标

访问 `/metrics` 端点获取 Prometheus 格式指标：

```bash
curl http://localhost:8998/metrics
```

### 系统状态

访问 `/api/status` 获取系统状态：

```bash
curl http://localhost:8998/api/status
```

### 日志查看

#### Docker

```bash
docker logs -f audio-transcription
```

#### Docker Compose

```bash
docker compose logs -f
```


## 故障排查

### 健康检查失败

1. 检查模型是否加载：
   ```bash
   curl http://localhost:8998/healthz | jq '.checks.models'
   ```

2. 检查存储空间：
   ```bash
   curl http://localhost:8998/healthz | jq '.checks.storage'
   ```

3. 检查系统资源：
   ```bash
   curl http://localhost:8998/healthz | jq '.checks.system'
   ```

### 容器无法启动

1. 检查环境变量是否正确
2. 检查端口是否被占用
3. 检查数据目录权限

### 性能问题

1. 检查模型池状态
2. 检查系统资源使用
3. 调整并发配置

## 最佳实践

1. **生产环境**：
   - 使用 Docker Compose 部署，便于管理
   - 配置持久化存储
   - 启用监控和告警
   - 定期备份数据
   - 使用健康检查确保服务可用性

2. **开发环境**：
   - 使用 Docker Compose 开发配置快速启动
   - 挂载源代码目录，支持热重载
   - 使用轻量配置，节省资源

3. **配置管理**：
   - 敏感信息使用环境变量
   - 不同环境使用不同配置文件（.env.development, .env.production）
   - 定期审查和更新配置

