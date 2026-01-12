# 🎙️ 音频转写系统

> 基于 AI 的实时语音识别与声纹分离系统  
> Domain-Driven Design (DDD) 三层架构设计

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)
[![ModelScope](https://img.shields.io/badge/ModelScope-1.11.0-orange.svg)](https://modelscope.cn/)

## 📋 目录

- [系统概述](#系统概述)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [API 接口](#api-接口)
- [使用指南](#使用指南)
- [配置说明](#配置说明)
- [技术栈](#技术栈)
- [更新日志](#更新日志)

## 🎯 系统概述

音频转写系统是一个专业的 AI 音频处理平台，能够自动识别音频中的多个说话人，进行精准的语音转文字转换，并可生成结构化的会议纪要。系统采用领域驱动设计（DDD）架构，具有高扩展性和可维护性。

### 主要特点

- 🎯 **多说话人识别**：基于 ModelScope CAM++ 模型，自动识别并区分不同说话人
- 📝 **高精度 ASR**：采用 SeACo-Paraformer 大模型，支持热词定制，识别准确率高
- 🔤 **智能标点恢复**：自动为识别文本添加标点符号，输出格式规范
- 📄 **文档自动生成**：支持导出 Word 格式的转写文档和会议纪要
- 🤖 **AI 会议纪要**：集成 DeepSeek/Qwen/GLM API，自动生成结构化会议纪要
- ⚡ **批量处理**：支持多文件并发转写，提高处理效率
- 🔄 **实时推送**：WebSocket 实时推送处理进度和状态
- 🌐 **现代化界面**：基于 FastAPI 的响应式 Web 界面
- 📊 **历史记录**：自动保存转写历史，支持查询和管理
- 🎯 **词级别时间戳**：支持逐词时间戳，实现精确的音字同步
- ✨ **音字同步高亮**：播放音频时自动高亮对应的转写文字，提升用户体验
- 📈 **平滑进度显示**：智能进度追踪器平滑推进，避免进度条跳跃

## ✨ 核心功能

### 1. 声纹分离 (Speaker Diarization)
- 自动检测音频中的说话人数量
- 识别每个说话人的发言时间段
- 支持 1-10 人的多说话人场景

### 2. 语音识别 (ASR)
- 基于 ModelScope FunASR 框架
- 支持中文、英文、中英混合、方言等多语言
- 可自定义热词，提升专业术语识别准确率
- 配合 VAD（语音端点检测）和 PUNC（标点恢复）模块
- **词级别时间戳**：自动生成每个词或短语的精确时间戳（优先使用 FunASR 原生时间戳，否则使用 Jieba 分词 + 线性插值）

### 3. 会议纪要生成
- 集成 DeepSeek/Qwen/GLM 等多种 AI 模型 API
- 支持自定义提示词模板，灵活控制生成格式
- 自动生成结构化会议纪要
- 包含会议主题、参与人员、讨论内容、行动清单等
- **提示词输入**：支持在 Web 界面中自定义提示词模板，使用 `{transcript}` 占位符或自动追加转写内容
- **格式化显示**：自动清理 AI 返回的确认消息、Markdown 格式等，以纯文本形式展示会议纪要
- **模型选择**：支持在 DeepSeek、Qwen、GLM 等模型间切换

### 4. 文件管理
- 支持多种音频格式（mp3, wav, m4a, flac, aac, ogg, wma 等）
- 文件上传、删除、下载功能
- 转写历史记录持久化存储
- 支持重新转写和追加生成纪要
- 支持停止转写任务（真正中断转写进程）
- 支持一键清空所有历史记录

### 5. 音字同步高亮显示
- **词级别时间戳**：后端返回每个词或短语的精确开始和结束时间
- **实时高亮**：播放音频时，前端自动高亮当前播放位置对应的转写文字
- **点击跳转**：点击转写文字可跳转到对应音频位置
- **平滑滚动**：高亮词自动滚动到可见区域，提升阅读体验
- **兼容性**：支持词级别和句子级别两种模式，向后兼容旧数据

## 🏗️ 系统架构

项目采用 **DDD（领域驱动设计）三层架构**：

```
voice/
├── domain/              # 领域层：核心业务逻辑
│   └── voice/
│       ├── audio_processor.py      # 音频处理逻辑
│       ├── text_processor.py       # 文本处理逻辑
│       ├── diarization.py          # 声纹分离逻辑
│       └── transcriber.py          # 转写协调器
│
├── application/         # 应用层：业务流程编排
│   └── voice/
│       ├── pipeline_service.py     # 转写流水线服务
│       └── actions.py              # 业务动作定义
│
├── infra/              # 基础设施层：技术实现
│   ├── audio_io/       # 音频存储管理
│   │   └── storage.py
│   ├── runners/        # 模型运行器
│   │   ├── asr_runner_funasr.py    # ASR 模型运行器（FunASR）
│   │   └── model_pool.py            # 模型池管理
│   ├── websocket/      # WebSocket 连接管理
│   │   └── connection_manager.py
│   ├── monitoring/      # 监控和指标
│   │   ├── dify_webhook_sender.py  # Dify Webhook 报警
│   │   ├── metrics.py              # 系统指标
│   │   └── prometheus_metrics.py   # Prometheus 指标
│   ├── middleware/     # 中间件
│   │   └── rate_limiter.py
│   ├── cache/          # 缓存
│   └── repos/          # 数据仓库（预留）
│
├── api/                # API 层：对外接口
│   └── routers/
│       ├── voice_gateway.py        # 语音服务网关（主路由定义）
│       ├── file_handlers.py        # 文件处理（上传、下载、删除）
│       ├── file_manager.py         # 线程安全的文件管理器
│       ├── history_manager.py      # 历史记录管理（加载、保存）
│       ├── transcription_service.py # 转写服务（转写任务管理）
│       ├── summary_generator.py    # 会议纪要生成服务
│       ├── document_generator.py   # Word 文档生成（转写文档、会议纪要）
│       └── utils.py                # 工具函数（WebSocket、文件验证等）
│
├── templates/          # 前端模板
│   ├── index.html      # 主页面
│   └── result.html     # 结果页面
│
├── static/             # 静态资源
├── uploads/            # 文件上传目录
├── transcripts/        # 转写结果目录
├── audio_temp/         # 临时音频文件
├── meeting_summaries/   # 会议纪要存储目录
│
├── main.py             # 应用入口
└── config.py           # 配置文件
```

### 架构设计原则

- **Domain（领域层）**：包含核心业务逻辑，不依赖外部框架
- **Application（应用层）**：编排业务流程，协调领域对象
- **Infrastructure（基础设施层）**：提供技术支持（数据库、文件系统、第三方服务等）
- **API（接口层）**：处理 HTTP 请求，调用应用层服务

### 模块化设计

项目采用模块化设计，将功能拆分到独立模块：

#### API 层模块说明

- **`voice_gateway.py`**：主路由定义文件，包含所有 API 端点的路由定义
  - 负责路由注册和请求分发
  - 初始化各个服务模块
  - 处理 WebSocket 连接

- **`file_handlers.py`**：文件处理模块
  - 文件上传（支持多文件）
  - 文件下载（音频、转写文档、会议纪要）
  - 文件删除（单个文件、清空所有历史）
  - 集成 Dify Webhook 事件通知

- **`file_manager.py`**：线程安全的文件管理器
  - 使用递归锁（RLock）保证线程安全
  - 管理文件信息（上传、处理中、已完成、错误）
  - 提供文件查询、更新、删除接口

- **`transcription_service.py`**：转写服务模块
  - 管理转写任务的执行
  - 支持任务取消（真正的进程中断）
  - 处理转写进度更新
  - 保存转写结果和历史记录

- **`history_manager.py`**：历史记录管理
  - 从磁盘加载历史记录（JSON 格式）
  - 保存历史记录到磁盘
  - 支持历史记录的持久化存储

- **`summary_generator.py`**：会议纪要生成服务
  - 集成 DeepSeek/Qwen/GLM 等 AI 模型
  - 支持自定义提示词模板
  - 自动清理 AI 返回的格式和确认消息
  - 生成默认统计型纪要（无 API 密钥时）

- **`document_generator.py`**：Word 文档生成
  - 生成转写文档（包含说话人、时间戳、文本）
  - 生成会议纪要文档
  - 支持中英文格式
  - 自动格式化（标题、段落、表格等）

- **`utils.py`**：工具函数
  - WebSocket 消息发送（同步代码中调用异步函数）
  - 文件格式验证（allowed_file）
  - 转写结果清理（clean_transcript_words）
  - 主事件循环管理

这种模块化设计提高了代码的可维护性、可测试性和可扩展性。

## 🚀 快速开始

### 系统要求

- **Python**: 3.8 或更高版本
- **FFmpeg**: 用于音频格式转换
- **内存**: 建议 4GB 以上
- **GPU**: 可选，支持 CUDA 加速

### 安装步骤

#### 1. 安装 FFmpeg

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg -y

# macOS
brew install ffmpeg

# Windows
# 下载并安装：https://ffmpeg.org/download.html
```

#### 2. 安装 Python 依赖

```bash
# 安装依赖包
pip install -r requirements.txt

# 如果使用国内镜像（推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

#### 3. 配置环境变量（可选）

```bash
# 配置 AI 模型 API（用于生成会议纪要）
# 支持 DeepSeek、Qwen、GLM 三种模型，在 config.py 中配置
# 或通过环境变量配置（可选，优先使用 config.py 中的配置）
export DEEPSEEK_API_KEY="your-api-key"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"

# Qwen 模型配置（可选）
export QWEN_API_KEY="your-api-key"
export QWEN_API_BASE="https://dashscope.aliyuncs.com/compatible-mode/v1"

# GLM 模型配置（可选）
export GLM_API_KEY="your-api-key"
export GLM_API_BASE="https://open.bigmodel.cn/api/paas/v4"

# 预加载模型（可选，首次启动会自动下载）
export PRELOAD_MODELS="true"

# 设置转写线程数（默认5）
export TRANSCRIBE_WORKERS="5"
```

#### 4. 启动服务

```bash
# 方式1：使用主程序启动
python main.py

# 方式2：使用 uvicorn 启动（开发模式）
uvicorn main:app --host 0.0.0.0 --port 8998 --reload

# 方式3：后台运行
nohup python main.py > app.log 2>&1 &
```

### 访问服务

启动成功后，访问以下地址：

- 🌐 **主页面**: http://localhost:8998
- 📚 **API 文档**: http://localhost:8998/docs
- 📖 **ReDoc 文档**: http://localhost:8998/redoc
- 💚 **健康检查**: http://localhost:8998/healthz

## 📡 API 接口

### RESTful 文件资源接口

#### GET `/api/voice/files`

**功能**: 列出所有文件，支持过滤、排序、分页和统计。返回的文件对象包含可访问的下载URL。

**查询参数**:
- `status`: 过滤状态（`uploaded`/`processing`/`completed`/`error`）
- `limit`: 返回数量限制（分页大小）
- `offset`: 分页偏移量（默认 `0`）
- `include_history`: 是否包含历史记录（默认 `false`，从磁盘加载已完成的文件）

**排序规则**:
- 按状态优先级排序：`processing` > `uploaded` > `completed` > `error`
- 相同状态按 `upload_time` 降序排列（最新的在前）

**响应字段**:
- `files[]`: 文件列表，每个文件包含：
  - `id`: 文件唯一标识
  - `filename`: 存储文件名
  - `original_name`: 原始文件名
  - `filepath`: 服务器本地路径（**前端不可直接访问**）
  - `download_urls`: **可访问的下载链接**（重要！）
    - `audio`: 音频文件下载URL（**推荐使用此字段访问音频**）
    - `transcript`: 转写文档下载URL（如果存在）
    - `summary`: 会议纪要下载URL（如果存在）
  - `status`: 文件状态
  - `progress`: 处理进度（0-100）
  - 其他字段...

**重要说明**:
- ⚠️ **不要使用 `filepath` 字段**：这是服务器本地路径，前端无法直接访问
- ✅ **使用 `download_urls.audio`**：这是HTTP可访问的API路径

**示例**:
```bash
# 获取所有文件
curl "http://localhost:8998/api/voice/files"

# 获取所有已完成的文件
curl "http://localhost:8998/api/voice/files?status=completed&limit=10"

# 获取所有处理中的文件
curl "http://localhost:8998/api/voice/files?status=processing"

# 获取包含历史记录的所有文件
curl "http://localhost:8998/api/voice/files?include_history=true"

# 分页查询（第2页，每页20条）
curl "http://localhost:8998/api/voice/files?limit=20&offset=20"
```

#### GET `/api/voice/files/{file_id}`

**功能**: 获取文件详情

**查询参数**:
- `include_transcript`: 是否包含转写结果（默认 false）
- `include_summary`: 是否包含会议纪要（默认 false）

**示例**:
```bash
# 获取文件详情和转写结果
curl "http://localhost:8998/api/voice/files/{file_id}?include_transcript=true&include_summary=true"
```

#### PATCH `/api/voice/files/{file_id}`

**功能**: 更新文件（重新转写、生成纪要）

**请求体**:
```json
{
  "action": "retranscribe | generate_summary",
  "language": "zh",
  "hotword": "自定义热词"
}
```

**示例**:
```bash
# 重新转写
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{"action": "retranscribe", "language": "zh"}'

# 生成会议纪要（使用默认提示词和模型）
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{"action": "generate_summary"}'

# 生成会议纪要（自定义提示词和模型）
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "generate_summary",
    "prompt": "请根据以下会议转录内容，生成一份结构化的会议纪要。\n\n会议转录内容：\n{transcript}\n\n请按照以下格式输出：\n会议主题：\n参会人员：\n讨论内容：\n行动清单：",
    "model": "deepseek"
  }'
```

#### DELETE `/api/voice/files/{file_id}`

**功能**: 删除文件和相关数据

**特殊操作**:
- `file_id = "_clear_all"`: 清空所有历史记录（删除所有转写文件、音频文件和历史记录）

**示例**:
```bash
# 删除单个文件
curl -X DELETE "http://localhost:8998/api/voice/files/{file_id}"

# 清空所有历史记录
curl -X DELETE "http://localhost:8998/api/voice/files/_clear_all"
```

**响应示例（清空所有历史记录）**:
```json
{
  "success": true,
  "message": "清空所有历史记录成功",
  "deleted": {
    "audio_files": 10,
    "transcript_files": 10,
    "records": 10
  }
}
```

**注意事项**:
- 已停止转写的文件（`_cancelled = True`）可以正常删除
- 正在转写中的文件（`status = 'processing'` 且未取消）无法删除

### 向后兼容接口

为保持向后兼容，系统保留了以下传统接口：

| 方法 | 端点 | 功能 | 推荐新接口 |
|------|------|------|-----------|
| POST | `/api/voice/upload` | 上传音频文件 | `/api/voice/transcribe` |
| POST | `/api/voice/transcribe` | 开始转写 | - |
| GET | `/api/voice/status/{file_id}` | 获取转写状态 | `/api/voice/files/{file_id}` |
| GET | `/api/voice/result/{file_id}` | 获取转写结果 | `/api/voice/files/{file_id}?include_transcript=true` |
| POST | `/api/voice/stop/{file_id}` | 停止转写 | - |
| GET | `/api/voice/history` | 获取历史记录 | `/api/voice/files?status=completed` |
| POST | `/api/voice/generate_summary/{file_id}` | 生成会议纪要 | `PATCH /api/voice/files/{file_id}` |

### 下载接口

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/api/voice/audio/{file_id}?download=1` | 下载音频文件 |
| GET | `/api/voice/download_transcript/{file_id}` | 下载转写文档 |
| GET | `/api/voice/download_summary/{file_id}` | 下载会议纪要 |
| GET | `/api/voice/download_file/{filename}` | 下载输出文件 |

### WebSocket 接口

#### WS `/api/voice/ws`

**功能**: 实时接收文件处理状态更新

**消息格式**:
```json
{
  "type": "file_status",
  "file_id": "文件ID",
  "status": "processing | completed | error",
  "progress": 50,
  "message": "正在转写..."
}
```

**客户端示例**:
```javascript
const ws = new WebSocket('ws://localhost:8998/api/voice/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('进度更新:', data);
    
    if (data.type === 'file_status') {
        console.log(`文件 ${data.file_id}: ${data.status} (${data.progress}%)`);
    }
};

// 订阅特定文件的状态更新
ws.send(JSON.stringify({
    type: 'subscribe',
    file_id: 'your-file-id'
}));
```

## 📖 使用指南

### Web 界面使用

1. 打开浏览器访问 http://localhost:8998
2. 拖拽或选择音频文件上传（支持多文件）
3. 选择语言类型（中文/英文/中英混合/方言）
4. 可选：输入热词（空格分隔），如 "人工智能 深度学习"
5. 点击"开始转写"按钮
6. 实时查看转写进度
7. 转写完成后：
   - 查看转写结果
   - 下载 Word 文档
   - 生成会议纪要（可选）

### 命令行/API 使用

#### 场景1：快速转写单个文件

```bash
# 1. 上传文件
FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3" | jq -r '.file.id')

# 2. 开始转写（wait=true 等待完成）
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": true}"
```

#### 场景2：批量转写多个文件

```bash
# 循环处理多个文件
for file in file1.mp3 file2.mp3 file3.mp3; do
  FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
    -F "audio_file=@$file" | jq -r '.file.id')
  
  curl -X POST "http://localhost:8998/api/voice/transcribe" \
    -H "Content-Type: application/json" \
    -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": true}"
done
```

#### 场景3：转写并生成会议纪要

```bash
# 1. 上传文件
FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3" | jq -r '.file.id')

# 2. 开始转写（带热词）
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"hotword\": \"季度报告 销售业绩 市场策略\", \"wait\": true}"

# 3. 生成会议纪要（使用默认提示词和模型）
curl -X POST "http://localhost:8998/api/voice/generate_summary/$FILE_ID" \
  -H "Content-Type: application/json" \
  -d '{}'

# 或者使用自定义提示词和模型
curl -X POST "http://localhost:8998/api/voice/generate_summary/$FILE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "请根据以下会议转录内容，生成一份结构化的会议纪要。\n\n会议转录内容：\n{transcript}\n\n请按照以下格式输出：\n会议主题：\n参会人员：\n讨论内容：\n行动清单：",
    "model": "deepseek"
  }'
```

#### 场景4：分步处理（上传 → 转写 → 查询）

```bash
# 1. 上传文件
RESULT=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3")
FILE_ID=$(echo $RESULT | jq -r '.file.id')

# 2. 开始转写
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\"}"

# 3. 查询状态
curl "http://localhost:8998/api/voice/status/$FILE_ID"

# 4. 获取结果
curl "http://localhost:8998/api/voice/result/$FILE_ID"

# 5. 下载文档
curl "http://localhost:8998/api/voice/download_transcript/$FILE_ID" \
  -o transcript.docx
```

### Python SDK 示例

```python
import requests
import time

# 转写音频文件
def transcribe_audio(audio_path, language='zh', wait=True):
    base_url = 'http://localhost:8998/api/voice'
    
    # 1. 上传文件
    with open(audio_path, 'rb') as f:
        files = {'audio_file': f}
        response = requests.post(f'{base_url}/upload', files=files)
        upload_result = response.json()
        
        if not upload_result.get('success'):
            raise Exception(f"上传失败: {upload_result.get('message')}")
        
        file_id = upload_result['file']['id']
    
    # 2. 开始转写（wait=True 等待完成）
    transcribe_data = {
        'file_id': file_id,
        'language': language,
        'wait': wait
    }
    response = requests.post(f'{base_url}/transcribe', json=transcribe_data)
    result = response.json()
    
    if result.get('success') and result.get('status') == 'completed':
        return result
    
    # 如果 wait=False，需要轮询状态
    if not wait:
        while True:
            response = requests.get(f'{base_url}/files/{file_id}')
            status_result = response.json()
            status = status_result['file']['status']
            
            if status == 'completed':
                # 获取转写结果
                response = requests.get(f'{base_url}/result/{file_id}')
                return response.json()
            elif status == 'error':
                raise Exception("转写失败")
            
            time.sleep(2)  # 等待2秒后重试
    
    return result

# 使用
result = transcribe_audio('meeting.mp3', wait=True)
if result.get('transcript'):
    print(f"转写完成，共 {len(result['transcript'])} 段")
```

## ⚙️ 配置说明

### config.py 配置文件

#### 文件路径配置

```python
FILE_CONFIG = {
    "output_dir": "transcripts",  # 转写结果保存目录
    "temp_dir": "audio_temp",     # 临时文件目录
    "upload_dir": "uploads"       # 上传文件目录
}
```

#### 模型配置

```python
MODEL_CONFIG = {
    # 声纹分离模型
    "diarization": {
        "model_id": 'iic/speech_campplus_speaker-diarization_common',
        "revision": 'master'
    },
    
    # ASR 模型（语音转文字）
    "asr": {
        "model_id": 'iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # VAD 模型（语音端点检测）
    "vad": {
        "model_id": 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # PUNC 模型（标点恢复）
    "punc": {
        "model_id": 'iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch',
        "model_revision": 'v2.0.4'
    },
    
    # 热词配置（可选）
    "hotword": ''  # 示例：'人工智能 深度学习 神经网络'
}
```

#### 语言配置

```python
LANGUAGE_CONFIG = {
    "zh": {
        "name": "中文普通话",
        "description": "适用于标准普通话音频"
    },
    "zh-dialect": {
        "name": "方言混合",
        "description": "适用于包含方言的音频"
    },
    "zh-en": {
        "name": "中英混合",
        "description": "适用于中英文混合的音频"
    },
    "en": {
        "name": "英文",
        "description": "适用于纯英文音频"
    }
}
```

#### 音频处理配置

```python
AUDIO_PROCESS_CONFIG = {
    "sample_rate": 16000,  # 采样率
    "channels": 1          # 声道数
}

# 音频预处理配置（上传时预处理）
AUDIO_PREPROCESS_CONFIG = {
    "enabled": True,              # 是否启用上传时预处理
    "replace_original": True,      # 是否替换原文件
    "target_sample_rate": 16000,  # 目标采样率
    "target_channels": 1,         # 目标声道数
    "output_format": "wav",       # 输出格式
    "output_codec": "pcm_s16le",  # 输出编码
    "use_gpu_accel": False,       # 是否使用GPU加速
    "fallback_on_error": True     # 预处理失败时保留原文件
}
```

#### AI 模型 API 配置（用于生成会议纪要）

```python
# 支持多个模型：DeepSeek、Qwen、GLM
AI_MODEL_CONFIG = {
    "deepseek": {
        "api_key": "your-api-key",
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "display_name": "Deepseek"
    },
    "qwen": {
        "api_key": "your-api-key",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "display_name": "Qwen"
    },
    "glm": {
        "api_key": "your-api-key",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4",
        "display_name": "GLM"
    }
}
```

**配置说明**：
- 在 `config.py` 中配置 `AI_MODEL_CONFIG`，支持同时配置多个模型
- 前端界面可以选择使用哪个模型生成会议纪要
- 如果未配置 API 密钥，系统会生成默认的统计型纪要

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（可选，优先使用 config.py 配置） | - |
| `DEEPSEEK_API_BASE` | DeepSeek API 地址 | https://api.deepseek.com |
| `DEEPSEEK_MODEL` | DeepSeek 模型名称 | deepseek-chat |
| `QWEN_API_KEY` | Qwen API 密钥（可选，优先使用 config.py 配置） | - |
| `QWEN_API_BASE` | Qwen API 地址 | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| `GLM_API_KEY` | GLM API 密钥（可选，优先使用 config.py 配置） | - |
| `GLM_API_BASE` | GLM API 地址 | https://open.bigmodel.cn/api/paas/v4 |
| `PRELOAD_MODELS` | 启动时预加载模型 | false |
| `TRANSCRIBE_WORKERS` | 转写线程数 | 5 |
| `AUDIO_PREPROCESS_ENABLED` | 是否启用上传时音频预处理 | true |
| `AUDIO_PREPROCESS_GPU` | 是否使用GPU加速预处理 | false |
| `DIFY_API_KEY` | Dify API 密钥（可选） | - |
| `DIFY_BASE_URL` | Dify API 地址（可选） | - |
| `DIFY_WORKFLOW_ID` | Dify 工作流 ID（可选） | - |
| `DIFY_USER_ID` | Dify 用户 ID（可选） | - |

## 🛠️ 技术栈

### 后端框架
- **FastAPI** 0.109.0 - 现代化、高性能 Web 框架
- **Uvicorn** - ASGI 服务器
- **Python 3.8+** - 编程语言

### AI 模型
- **ModelScope** 1.11.0 - 阿里达摩院开源模型平台
- **FunASR** 1.0.0 - 阿里巴巴达摩院语音识别工具
- **SeACo-Paraformer** - 大规模语音识别模型（支持热词）
- **CAM++** - 声纹分离模型
- **FSMN-VAD** - 语音端点检测模型
- **CT-Transformer** - 标点恢复模型

### 音频处理
- **FFmpeg** - 音频格式转换
- **soundfile** 0.12.1 - 音频文件读写
- **pydub** - 音频切片和处理
- **PyTorch** 2.0+ - 深度学习框架

### 文档生成
- **python-docx** 1.1.0 - Word 文档生成

### 其他工具
- **jieba** 0.42.1 - 中文分词（热词处理）
- **OpenAI SDK** 2.6.1 - AI 模型 API 调用（兼容 DeepSeek/Qwen/GLM API）
- **WebSockets** 12.0 - 实时通信
- **slowapi** 0.1.9 - API 速率限制

## 🔍 故障排除

### 常见问题

#### 1. FFmpeg 未找到

```bash
# 检查 FFmpeg 是否安装
which ffmpeg
ffmpeg -version

# Ubuntu/Debian 安装
sudo apt install ffmpeg

# macOS 安装
brew install ffmpeg
```

#### 2. 模型下载失败

首次运行时会自动从 ModelScope 下载模型（约 1-2GB），需要良好的网络连接。

如果下载失败：
- 检查网络连接
- 尝试使用代理
- 手动下载模型到 `~/.cache/modelscope/hub/` 目录

#### 3. 内存不足

```bash
# 减少并发转写线程数
export TRANSCRIBE_WORKERS="2"

# 或者增加系统交换空间
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

#### 4. 转写结果为空

检查：
- 音频文件格式是否正确
- 音频是否包含有效语音内容
- 音频质量是否过低
- 查看日志文件 `app.log` 获取详细错误信息

#### 5. 会议纪要生成失败

需要配置 AI 模型 API 密钥（在 `config.py` 中配置或通过环境变量）：
```bash
# 方式1：在 config.py 中配置（推荐）
# 编辑 config.py 中的 AI_MODEL_CONFIG，配置 DeepSeek、Qwen 或 GLM 的 API 密钥

# 方式2：通过环境变量配置（可选）
export DEEPSEEK_API_KEY="your-api-key"
# 或
export QWEN_API_KEY="your-api-key"
# 或
export GLM_API_KEY="your-api-key"
```

如果未配置 API 密钥，系统会生成默认的统计型纪要。

#### 6. Docker 容器健康检查失败

如果 Docker 容器显示为 `unhealthy`：

1. **检查健康检查响应**：
   ```bash
   docker exec audio-transcription-service curl http://localhost:8998/healthz
   ```

2. **常见原因**：
   - 模型池未初始化（延迟加载模式，首次请求时加载）
   - 存储空间不足
   - FFmpeg 不可用
   - 系统资源不足（内存/CPU）

3. **解决方案**：
   - 模型未加载是正常状态（延迟加载），不影响服务功能
   - 检查存储空间和系统资源
   - 确保 FFmpeg 已正确安装

#### 7. Docker 环境变量未生效

如果修改 `.env` 文件后环境变量未生效：

1. **确保从项目根目录运行**：
   ```bash
   cd /home/lizhipeng/work/nvoice/phosys
   docker compose -f docker/docker-compose.yml down
   docker compose -f docker/docker-compose.yml up -d
   ```

2. **检查 `.env` 文件位置**：
   - `.env` 文件必须在项目根目录
   - `docker-compose.yml` 使用 `../.env` 路径（相对于 docker 目录）

3. **验证环境变量**：
   ```bash
   docker exec audio-transcription-service env | grep DIFY
   ```

## 📝 更新日志

### v3.1.6-FunASR (2025-12-29)

**配置简化与性能优化**

#### 配置简化
- ✅ **移除环境区分**：移除 development/staging/production 环境区分，统一使用简化配置
  - `config.py` 不再根据 `ENVIRONMENT` 环境变量加载不同配置
  - Docker 配置移除 `ENVIRONMENT` 环境变量
  - 简化部署流程，减少配置错误
- ✅ **简化配置加载**：直接使用 `load_dotenv()` 加载环境变量
- ✅ **AI模型配置优化**：为 DeepSeek/Qwen/GLM 添加默认 API 地址和模型名称
  - 只需配置 API Key 即可使用，无需配置 API Base URL 和模型名称

#### 新增功能
- ✅ **热词 API 传入**：热词参数优先从 API 请求中传入，未传入时从 config.py 读取
  - 支持在 `/api/voice/transcribe` 和 `/api/voice/files/{file_id}` 接口中传入 `hotword` 参数
  - 方便工作流工具（如 Dify）动态指定热词
- ✅ **音频预处理优化**：上传时自动预处理音频为 16kHz WAV 格式
  - 提升转写性能和准确率
  - 支持配置开关、GPU 加速、失败降级等选项
  - 自动检测已预处理文件并跳过转换
- ✅ **会议纪要大纲**：会议纪要模板新增"大纲"字段
  - 自动生成约 200 字的会议概要

#### 代码精简
- ✅ **移除热词管理 API**：删除 `GET/POST/DELETE /api/voice/hotwords` 接口
  - 热词直接从 config.py 配置或 API 传入
- ✅ **简化文本处理器**：`text_processor.py` 移除同义词配置文件加载功能
  - 使用内置同义词映射，减少外部依赖

#### 技术改进
- ✅ 优化 `audio_processor.py`：添加格式检查，检测已预处理文件可跳过 FFmpeg 转换
- ✅ 优化 `storage.py`：添加 `preprocess_audio_to_16khz` 方法
- ✅ 简化并发配置：移除基于环境的配置切换，使用固定的生产级配置

---

### v3.1.5-FunASR (2025-12-24)

**健康检查与 Docker 配置优化**

#### 功能修复
- ✅ **健康检查字段名修复**：修复了模型池统计字段名不匹配问题（`available_count` 和 `current_size`）
  - 修复前：使用错误的字段名 `available` 和 `pool_size`，导致健康检查总是返回 503
  - 修复后：使用正确的字段名 `available_count` 和 `current_size`，健康检查正常工作
- ✅ **延迟加载模式优化**：模型未加载不再影响健康检查状态
  - 模型未加载是正常状态（延迟加载），不影响服务健康状态
  - 只有在模型加载后池不可用时才标记为不健康
- ✅ **Dify 服务可选化**：Dify Webhook 服务作为可选服务，不影响整体健康状态
  - Dify 连接失败不会导致服务标记为不健康
  - 添加了明确的提示信息，说明 Dify 是可选服务

#### Docker 配置优化
- ✅ **环境变量加载修复**：修复了 Docker Compose 中 `DIFY_BASE_URL` 环境变量加载问题
  - 修复前：`docker-compose.yml` 中的默认值会覆盖 `.env` 文件中的配置
  - 修复后：`DIFY_BASE_URL` 完全从 `.env` 文件加载，确保配置正确
- ✅ **健康检查配置优化**：调整了 Docker 健康检查参数
  - 检查间隔：30秒 → 1小时（降低检查频率）
  - 启动等待期：60秒 → 120秒（确保存储初始化完成）

#### 技术改进
- ✅ 优化了健康检查逻辑，支持延迟加载模式
- ✅ 改进了 Docker 环境变量配置，确保 `.env` 文件正确加载
- ✅ 增强了错误处理和日志记录

### v3.1.4-FunASR (2025-12-18)

**会议纪要功能增强**

#### 新增功能
- ✅ **会议纪要提示词输入**：支持在 Web 界面中自定义提示词模板
  - 提供提示词输入框，支持自定义生成格式和要求
  - 支持使用 `{transcript}` 占位符，自动替换为转写内容
  - 如果提示词中未包含占位符，系统会自动追加转写内容
  - 自动添加输出格式要求，避免 AI 返回确认消息和引导语句
- ✅ **会议纪要格式化显示**：优化会议纪要的展示效果
  - 自动清理 AI 返回的确认消息、引导语句（如"这是根据您提供的..."、"好的"等）
  - 自动去除 Markdown 格式（标题、粗体、斜体、代码块等）
  - 以纯文本形式在预览区域展示，提升阅读体验
  - 支持实时预览生成的会议纪要内容
- ✅ **多模型支持**：支持在 DeepSeek、Qwen、GLM 等模型间切换
  - 在会议纪要生成界面提供模型选择下拉框
  - 支持为不同文件选择不同的 AI 模型
  - 自动适配不同模型的 API 配置

#### 技术改进
- ✅ 优化了提示词处理逻辑，支持灵活的占位符替换
- ✅ 改进了会议纪要内容清理算法，更准确地识别和去除不需要的格式和文本
- ✅ 增强了前端预览功能，提供更好的用户体验
- ✅ 改进了错误处理和用户提示

### v3.1.3-FunASR (2025-12-04)

**API简化与优化**

#### 接口变更
- ✅ **删除一站式转写接口**：移除 `POST /api/voice/transcribe_all` 接口，统一使用普通转写接口
- ✅ **删除清空Dify生成文件功能**：移除 `DELETE /api/voice/files/_clear_dify` 特殊操作
- ✅ **增强普通转写接口**：优化 `POST /api/voice/transcribe` 接口
  - 当 `wait=true` 时，返回结果包含 `status` 字段和 `transcript` 字段
  - `transcript` 中不包含 `words` 字段，只保留基本转写信息（speaker, text, start_time, end_time）
  - 单个文件时，顶层直接返回 `transcript`，方便 Dify 等工具使用

#### 技术改进
- ✅ 简化了API接口结构，统一使用RESTful风格
- ✅ 优化了转写接口的返回结构，更适合工作流工具集成
- ✅ 清理了代码中的冗余功能，提高代码可维护性

### v3.1.2-FunASR (2025-11-25)

**功能增强**

#### 新增功能
- ✅ **词级别时间戳**：后端自动生成每个词或短语的精确时间戳
  - 优先使用 FunASR 原生词级别时间戳（如果模型支持）
  - 降级方案：使用 Jieba 分词 + 线性插值生成时间戳
  - 确保所有转写结果都包含词级别时间信息
- ✅ **音字同步高亮显示**：前端实现音频播放与转写文字的实时同步
  - 播放音频时自动高亮当前播放位置对应的转写文字
  - 支持点击转写文字跳转到对应音频位置
  - 自动滚动到高亮词，提升阅读体验
  - 支持词级别和句子级别两种模式，向后兼容
- ✅ **进度条细化优化**：避免进度条跳跃显示，提升用户体验
  - 智能进度追踪器：后台线程平滑推进进度，每1%逐步更新
  - WebSocket去重机制：避免发送重复的进度值，减少网络开销
  - 前端防回退保护：确保进度只增不减，忽略网络延迟导致的进度回退
  - 快速追赶机制：任务完成时极速补齐进度，保证视觉连续性

#### 技术改进
- ✅ 优化了词级别时间戳的生成逻辑，确保文本完整性
- ✅ 改进了前端高亮匹配算法，使用左闭右开区间避免相邻词同时高亮
- ✅ 优化了 DOM 元素缓存机制，提升性能
- ✅ 添加了时间戳验证和错误处理，提高健壮性
- ✅ 实现了智能进度追踪器，后台线程平滑推进进度，避免进度条跳跃
- ✅ 优化了 WebSocket 消息发送逻辑，减少重复消息和网络开销

### v3.1.1-FunASR (2025-11-13)

**功能增强与修复**

#### 新增功能
- ✅ **真正的停止转写功能**：支持中断正在进行的转写任务，通过 `_cancelled` 标志和 `InterruptedError` 机制实现
- ✅ **清空所有历史记录**：新增 `DELETE /api/voice/files/_clear_all` 接口，可一键清空所有转写历史记录

#### 功能修复
- ✅ **文件名唯一性修复**：修复了批量转写时文件名冲突问题，使用微秒级时间戳和 `file_id` 确保每个文件生成唯一的转写文档文件名
- ✅ **删除已停止转写文件**：修复了停止转写后无法删除文件的问题，现在可以正常删除已停止的文件
- ✅ **WebSocket进度跳转修复**：修复了转写进度反复跳转的问题，优化了进度更新逻辑，确保进度只增不减
- ✅ **删除后UI立即更新**：修复了删除文件后前端界面不立即更新的问题，现在删除后立即从列表中移除并更新UI
- ✅ **删除错误提示修复**：修复了删除已停止转写文件时出现"删除失败"错误提示的问题，改进了错误处理逻辑

#### 技术改进
- ✅ 改进了转写任务的取消机制，使用 `cancellation_flag` 在转写流程的关键步骤检查取消状态
- ✅ 优化了WebSocket消息处理，防止进度回退和状态不一致
- ✅ 改进了文件删除的错误处理，正确解析FastAPI的HTTPException响应格式

### v3.1.0-FunASR (2025-11-06)

**版本标识**：FunASR一体化模式

#### 技术升级
- ✅ 统一版本号为 3.1.0-FunASR，标识FunASR一体化架构
- ✅ 系统状态接口返回版本信息统一

### v3.0.0 (2025-11-02)

**重大更新**：完整的架构重构

#### 架构变更
- ✅ 采用 DDD（领域驱动设计）三层架构
- ✅ 分离 Domain、Application、Infra 层
- ✅ 提高代码可维护性和扩展性

#### 新增功能
- ✅ RESTful 风格文件资源接口
- ✅ 支持批量文件处理
- ✅ 支持三种返回模式（json/file/both）
- ✅ WebSocket 实时状态推送
- ✅ 历史记录持久化存储
- ✅ AI 会议纪要生成（集成 DeepSeek/Qwen/GLM）
- ✅ 文件管理功能（重新转写、删除等）

#### 优化改进
- ✅ 优化音频处理流程
- ✅ 改进声纹分离准确率
- ✅ 增强热词功能
- ✅ 提升并发处理能力
- ✅ 完善错误处理和日志记录

#### 接口变更
- ⚠️ 移除 `/dify/transcribe` 接口
- ⚠️ 移除 `/v1/audio/transcriptions` 接口
- ✅ 保留向后兼容接口

## 📄 许可证

本项目使用的模型来自 [ModelScope](https://modelscope.cn/)，请遵守相关模型的使用协议。

## 🔗 相关链接

- [ModelScope 模型平台](https://modelscope.cn/)
- [FunASR 项目](https://github.com/alibaba-damo-academy/FunASR)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [DeepSeek API](https://platform.deepseek.com/)
- [Qwen API](https://dashscope.aliyun.com/)
- [GLM API](https://open.bigmodel.cn/)

## 💬 支持与反馈

如有问题或建议，欢迎：
- 提交 Issue
- 发送反馈邮件
- 查看 API 文档：http://localhost:8998/docs

---

**⭐ 如果这个项目对你有帮助，欢迎 Star！**
