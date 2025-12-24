# Docker 快速启动指南

## Docker Compose 版本说明

Docker Compose 有两个版本：
- **V1**: 独立的 `docker-compose` 命令（已弃用）
- **V2**: Docker CLI 插件 `docker compose`（推荐，当前默认）

本文档使用 **V2 语法**（`docker compose`）。

## 快速启动

### 1. 准备环境变量

在项目根目录创建 `.env` 文件：

```bash
cd /home/lizhipeng/work/nvoice/phosys
cp .env.example .env
# 编辑 .env 文件，填入实际配置
```

### 2. 启动服务

**⚠️ 必须从项目根目录运行**（这样才能正确加载 `.env` 文件）：

```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

# 启动服务
docker compose -f docker/docker-compose.yml up -d
```

### 3. 查看日志

```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

docker compose -f docker/docker-compose.yml logs -f
```

### 4. 停止服务

```bash
# 确保在项目根目录
cd /home/lizhipeng/work/nvoice/phosys

docker compose -f docker/docker-compose.yml down
```

> **⚠️ 注意**：所有命令必须从项目根目录运行。如果在 `docker/` 目录下，路径会变成 `docker/docker/docker-compose.yml`（错误）。

## 常用命令

```bash
# 启动（后台运行）
docker compose -f docker/docker-compose.yml up -d

# 启动（前台运行，查看日志）
docker compose -f docker/docker-compose.yml up

# 停止
docker compose -f docker/docker-compose.yml down

# 停止并删除卷
docker compose -f docker/docker-compose.yml down -v

# 查看日志
docker compose -f docker/docker-compose.yml logs -f

# 重启服务
docker compose -f docker/docker-compose.yml restart

# 查看状态
docker compose -f docker/docker-compose.yml ps
```

## 开发环境

```bash
docker compose -f docker/docker-compose.dev.yml up
```

## 如果使用 Docker Compose V1

如果您的系统只有 `docker-compose` 命令（V1），请将上述所有命令中的 `docker compose` 替换为 `docker-compose`：

```bash
# V1 语法示例
docker-compose -f docker/docker-compose.yml up -d
```

## 检查 Docker Compose 版本

```bash
# 检查 V2（推荐）
docker compose version

# 检查 V1（如果已安装）
docker-compose --version
```

