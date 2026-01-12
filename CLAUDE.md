# 🎙️ Audio Transcription System - Project Guide for Claude

This document provides essential information for Claude instances to understand and work with this audio transcription system effectively.

## Project Overview

**Audio Transcription System** - An AI-powered real-time speech recognition and speaker diarization system built with Domain-Driven Design (DDD) architecture.

- **Technology Stack**: FastAPI + ModelScope + FunASR + Python 3.8+
- **Main Function**: Convert audio files to text with multi-speaker identification
- **Architecture**: DDD三层架构 (Domain-Application-Infra)
- **AI Models**: SeACo-Paraformer (ASR) + CAM++ (Speaker Diarization) + VAD + PUNC

## 🏗️ Project Architecture

### Directory Structure

```
phosys/
├── domain/                    # 领域层 - 核心业务逻辑
│   └── voice/
│       ├── audio_processor.py    # 音频处理逻辑
│       ├── text_processor.py     # 文本处理逻辑  
│       ├── diarization.py       # 声纹分离业务规则
│       └── __init__.py
│
├── application/              # 应用层 - 业务流程编排
│   └── voice/
│       ├── pipeline_service_funasr.py  # 转写流水线服务
│       └── __init__.py
│
├── infra/                    # 基础设施层 - 技术实现
│   ├── audio_io/             # 音频存储管理
│   │   └── storage.py
│   ├── runners/              # 模型运行器
│   │   ├── asr_runner_funasr.py      # ASR执行器(FunASR)
│   │   └── model_pool.py              # 模型池管理
│   ├── websocket/            # WebSocket管理
│   │   └── connection_manager.py
│   ├── monitoring/           # 监控和指标
│   │   ├── dify_webhook_sender.py    # Dify Webhook 报警
│   │   ├── metrics.py                # 系统指标
│   │   └── prometheus_metrics.py     # Prometheus 指标
│   ├── middleware/           # 中间件
│   │   └── rate_limiter.py
│   ├── cache/                # 缓存
│   └── repos/                # 数据仓库（预留）
│
├── api/                      # API层 - 对外接口
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
├── templates/                # 前端模板
│   ├── index.html
│   └── result.html
├── static/                   # 静态资源
│   ├── css/
│   └── js/
├── uploads/                  # 上传文件目录
├── transcripts/              # 转写结果目录
├── audio_temp/               # 临时音频文件
├── meeting_summaries/         # 会议纪要存储目录
├── main.py                   # 应用入口
├── config.py                 # 配置文件
├── requirements.txt          # 依赖包
├── README.md                 # 项目文档
├── app.log                   # 应用日志
└── CLAUDE.md                 # 本文件
```

### Key Architectural Components

#### 1. Domain Layer (业务领域层)
- **Purpose**: Core business logic, independent of external frameworks
- **Key Files**:
  - `domain/voice/audio_processor.py` - Audio format conversion and preprocessing
  - `domain/voice/diarization.py` - Speaker diarization business rules and post-processing
  - `domain/voice/text_processor.py` - Text processing and formatting

#### 2. Application Layer (应用层)  
- **Purpose**: Business process orchestration, coordinates domain objects
- **Key Files**:
  - `application/voice/pipeline_service_funasr.py` - Main transcription pipeline using FunASR

#### 3. Infrastructure Layer (基础设施层)
- **Purpose**: Technical implementation support
- **Key Files**:
  - `infra/audio_io/storage.py` - File storage and management
  - `infra/runners/asr_runner_funasr.py` - ASR model execution with FunASR
  - `infra/runners/model_pool.py` - Model pooling for concurrent processing
  - `infra/websocket/connection_manager.py` - WebSocket real-time communication
  - `infra/monitoring/dify_webhook_sender.py` - Dify Webhook event notifications
  - `infra/monitoring/prometheus_metrics.py` - Prometheus metrics collection
  - `infra/middleware/rate_limiter.py` - API rate limiting

#### 4. API Layer (接口层)
- **Purpose**: HTTP request handling and response generation
- **Key Files**:
  - `api/routers/voice_gateway.py` - Main API router with route definitions
  - `api/routers/file_handlers.py` - File upload, download, and deletion handlers
  - `api/routers/file_manager.py` - Thread-safe file information management
  - `api/routers/transcription_service.py` - Transcription task management and execution
  - `api/routers/history_manager.py` - History record loading and saving
  - `api/routers/summary_generator.py` - Meeting summary generation using AI models
  - `api/routers/document_generator.py` - Word document generation for transcripts and summaries
  - `api/routers/utils.py` - Utility functions (WebSocket, file validation, etc.)

## 🔧 Configuration

### Main Configuration (config.py)

```python
# File paths
FILE_CONFIG = {
    "output_dir": "transcripts",     # 转写结果目录
    "temp_dir": "audio_temp",       # 临时文件目录  
    "upload_dir": "uploads"         # 上传文件目录
}

# AI Models
MODEL_CONFIG = {
    "diarization": {
        "model_id": 'iic/speech_campplus_sv_zh-cn_16k-common',
        "revision": 'v2.0.2'
    },
    "asr": {
        "model_id": 'iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        "model_revision": 'v2.0.4'
    },
    "vad": {
        "model_id": 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        "model_revision": 'v2.0.4'
    },
    "punc": {
        "model_id": 'iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch', 
        "model_revision": 'v2.0.4'
    }
}

# Concurrency settings
CONCURRENCY_CONFIG = {
    "use_model_pool": True,
    "asr_pool_size": 6,              # ASR模型池大小
    "transcription_workers": 12,     # 转写任务并发数
    "max_memory_mb": 8192,          # 内存限制
}

# Audio preprocessing (optional)
AUDIO_PREPROCESS_CONFIG = {
    "enabled": True,              # Enable preprocessing on upload
    "replace_original": True,      # Replace original file
    "target_sample_rate": 16000,  # Target sample rate
    "target_channels": 1,         # Target channels
    "output_format": "wav",      # Output format
    "output_codec": "pcm_s16le", # Output codec
    "use_gpu_accel": False,      # Use GPU acceleration
    "fallback_on_error": True    # Keep original on error
}
```

### Environment Variables

```bash
# AI API Keys (optional for meeting summaries)
# 支持 DeepSeek、Qwen、GLM 三种模型，在 config.py 中配置
export DEEPSEEK_API_KEY="your-api-key"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"

# Qwen 模型配置（可选）
export QWEN_API_KEY="your-api-key"
export QWEN_API_BASE="https://dashscope.aliyuncs.com/compatible-mode/v1"

# GLM 模型配置（可选）
export GLM_API_KEY="your-api-key"
export GLM_API_BASE="https://open.bigmodel.cn/api/paas/v4"

# Optional settings
export PRELOAD_MODELS="true"           # 预加载模型
export TRANSCRIBE_WORKERS="12"         # 转写线程数
export AUDIO_PREPROCESS_ENABLED="true" # 启用上传时音频预处理
export AUDIO_PREPROCESS_GPU="false"    # 使用GPU加速预处理

# Dify Webhook (optional)
export DIFY_API_KEY="your-api-key"
export DIFY_BASE_URL="http://your-dify:5001"
export DIFY_WORKFLOW_ID="optional-workflow-id"
export DIFY_USER_ID="your-user-id"
```

## 🚀 Running the System

### Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Check FFmpeg installation
which ffmpeg

# 3. Start the service
python main.py

# Service will be available at:
# Main page: http://localhost:8998
# API docs: http://localhost:8998/docs
# Health check: http://localhost:8998/healthz
```

### Development Mode

```bash
# With auto-reload
uvicorn main:app --host 0.0.0.0 --port 8998 --reload

# Background mode
nohup python main.py > app.log 2>&1 &
```

## 📡 API Usage Guide

### Primary Interface: Transcription API

```bash
# 1. Upload audio file
FILE_ID=$(curl -X POST "http://localhost:8998/api/voice/upload" \
  -F "audio_file=@meeting.mp3" | jq -r '.file.id')

# 2. Start transcription (wait for completion)
curl -X POST "http://localhost:8998/api/voice/transcribe" \
  -H "Content-Type: application/json" \
  -d "{\"file_id\": \"$FILE_ID\", \"language\": \"zh\", \"wait\": true}"

# 3. Get result
curl "http://localhost:8998/api/voice/result/$FILE_ID"
```

### RESTful File Management

```bash
# List all files (returns files with download_urls field)
curl "http://localhost:8998/api/voice/files"

# List completed files
curl "http://localhost:8998/api/voice/files?status=completed"

# List files with history
curl "http://localhost:8998/api/voice/files?include_history=true"

# Pagination (page 2, 20 items per page)
curl "http://localhost:8998/api/voice/files?limit=20&offset=20"

# Get file details with transcript
curl "http://localhost:8998/api/voice/files/{file_id}?include_transcript=true"

# Retranscribe file
curl -X PATCH "http://localhost:8998/api/voice/files/{file_id}" \
  -H "Content-Type: application/json" \
  -d '{"action": "retranscribe", "language": "zh"}'

# Delete file
curl -X DELETE "http://localhost:8998/api/voice/files/{file_id}"
```

**Note**: The `/api/voice/files` endpoint returns files with `download_urls` field. Use `download_urls.audio` to access audio files, not the `filepath` field (which is a server local path).

## 🔑 Key Classes and Their Responsibilities

### Domain Classes

- **`DiarizationProcessor`** (`domain/voice/diarization.py`): Handles speaker diarization business logic, post-processing of segments, merging nearby segments
- **`AudioProcessor`** (`domain/voice/audio_processor.py`): Audio format conversion and preprocessing with GPU acceleration
- **`TextProcessor`** (`domain/voice/text_processor.py`): Text processing and formatting logic

### Application Classes

- **`PipelineService`** (`application/voice/pipeline_service_funasr.py`): Main orchestration service that coordinates the entire transcription workflow using FunASR

### Infrastructure Classes

- **`AudioStorage`** (`infra/audio_io/storage.py`): Manages file upload, temporary storage, and cleanup
- **`ASRRunner`** (`infra/runners/asr_runner_funasr.py`): ASR model execution with FunASR AutoModel and model pooling
- **`ModelPool`** (`infra/runners/model_pool.py`): Advanced object pooling for concurrent model instances
- **`ConnectionManager`** (`infra/websocket/connection_manager.py`): WebSocket real-time communication

### API Classes

- **`voice_gateway`** (`api/routers/voice_gateway.py`): Main API router with route definitions
- **`FileHandlers`** (`api/routers/file_handlers.py`): Handles file upload, download, and deletion operations
- **`ThreadSafeFileManager`** (`api/routers/file_manager.py`): Thread-safe file information management
- **`TranscriptionService`** (`api/routers/transcription_service.py`): Manages transcription tasks and execution
- **`history_manager`** (`api/routers/history_manager.py`): Loads and saves transcription history
- **`summary_generator`** (`api/routers/summary_generator.py`): Generates meeting summaries using AI models
- **`document_generator`** (`api/routers/document_generator.py`): Generates Word documents for transcripts and summaries
- **`utils`** (`api/routers/utils.py`): Utility functions for WebSocket, file validation, etc.

## 🧪 Development Tasks

### Common Development Activities

1. **Adding New Audio Formats**: Update `domain/voice/audio_processor.py` and the `allowed_file()` function in `voice_gateway.py`

2. **Extending AI Models**: Update `MODEL_CONFIG` in `config.py` and modify the corresponding runner in `infra/runners/`

3. **Adding New API Endpoints**: Add new routes to `api/routers/voice_gateway.py` following the existing patterns

4. **Modifying Business Logic**: Changes to core business rules should go in the `domain/` layer

5. **Performance Tuning**: Adjust `CONCURRENCY_CONFIG` in `config.py` and modify model pool settings in `infra/runners/model_pool.py`

### Testing and Debugging

```bash
# Check system status
curl "http://localhost:8998/api/status"

# View application logs
tail -f app.log

# Monitor model pool stats
curl "http://localhost:8998/api/metrics"
```

### Adding Dependencies

```bash
# Add to requirements.txt
echo "new-package==1.0.0" >> requirements.txt
pip install new-package==1.0.0
```

## 🚨 Important Notes for Claude Instances

### Architecture Principles

1. **DDD Strictly**: Always follow the DDD layers - Domain should not depend on Application or Infrastructure
2. **FunASR Integration**: The system uses FunASR AutoModel for integrated ASR + speaker diarization
3. **Model Pooling**: Production uses model pooling for concurrency - avoid global locks
4. **WebSocket Support**: Real-time progress updates via WebSocket (`/api/voice/ws`)

### Code Patterns to Follow

- **Error Handling**: Use try-catch blocks with detailed logging
- **File Management**: Use `AudioStorage` class for all file operations
- **Concurrency**: Use the thread pool pattern with `TRANSCRIPTION_THREAD_POOL`
- **Progress Callbacks**: Use the progress callback pattern for real-time updates
- **Configuration**: Use `config.py` for all configuration, avoid hard-coded values
- **Module Separation**: Keep business logic in separate modules (file_handlers, transcription_service, etc.)
- **Thread Safety**: Use `ThreadSafeFileManager` for file information management
- **WebSocket**: Use `send_ws_message_sync` from utils for sending messages from sync code

### Common Pitfalls to Avoid

1. **Global State**: Use the `ThreadSafeFileManager` instead of global variables
2. **Model Loading**: Let the model pool handle model loading - don't load models directly
3. **Memory Management**: Monitor memory usage in `CONCURRENCY_CONFIG`
4. **File Paths**: Use absolute paths consistently
5. **Async/Sync Mixing**: Be careful when mixing async and sync code - use `asyncio.run_coroutine_threadsafe` for WebSocket from sync threads
6. **Health Check Fields**: Use correct field names (`available_count`, `current_size`) when checking model pool stats
7. **Docker Environment Variables**: Ensure `.env` file is in project root and run Docker Compose from root directory
8. **Lazy Loading**: Model not loaded is normal state - don't mark service as unhealthy
9. **Module Dependencies**: Don't create circular imports between API modules - use TYPE_CHECKING for type hints
10. **Thread Safety**: Always use `ThreadSafeFileManager` methods with lock protection when accessing file information

### Performance Considerations

- The system is optimized for batch processing with high concurrency
- Model pooling reduces initialization overhead for repeated tasks  
- GPU acceleration is enabled for audio processing when available
- Memory limits prevent system overload on large servers

## 🔄 Version Information

- **Current Version**: 3.1.6-FunASR
- **Architecture**: DDD with FunASR integration
- **Last Updated**: 2025-12-29
- **Python Version**: 3.8+
- **Framework**: FastAPI 0.120.4

### Recent Updates (v3.1.6-FunASR, 2025-12-29)

#### Configuration Simplification
- ✅ **Removed Environment Distinction**: Removed development/staging/production environment switching
  - `config.py` no longer loads different configs based on `ENVIRONMENT`
  - Docker config removed `ENVIRONMENT` variable
- ✅ **Simplified Config Loading**: Direct `load_dotenv()` without environment-based file selection
- ✅ **AI Model Config Optimization**: Added default API base URLs and model names for DeepSeek/Qwen/GLM

#### New Features
- ✅ **Hotword API Parameter**: Hotword can now be passed via API, falls back to config.py if not provided
- ✅ **Audio Preprocessing**: Auto-convert uploaded audio to 16kHz WAV for better performance
- ✅ **Meeting Summary Outline**: Added "大纲" (outline) field to meeting summary template

#### Code Cleanup
- ✅ **Removed Hotword Management API**: Deleted `GET/POST/DELETE /api/voice/hotwords` endpoints
- ✅ **Simplified TextProcessor**: Removed synonym config file loading, using built-in mappings

#### Technical Improvements
- ✅ Optimized `audio_processor.py`: Added format check, skip FFmpeg for pre-processed files
- ✅ Added `preprocess_audio_to_16khz` method to `storage.py`
- ✅ Simplified concurrency config: Removed environment-based switching

### Previous Updates (v3.1.5-FunASR, 2025-12-24)

#### Health Check & Docker Configuration Fixes
- ✅ **Health Check Field Name Fix**: Fixed model pool stats field name mismatch (`available_count` and `current_size`)
- ✅ **Lazy Loading Mode Optimization**: Model not loaded no longer affects health status
- ✅ **Dify Service Optional**: Dify Webhook is now optional and doesn't affect overall health status
- ✅ **Docker Environment Variable Fix**: Fixed `DIFY_BASE_URL` loading from `.env` file in Docker Compose
- ✅ **Health Check Configuration**: Optimized Docker health check parameters (interval: 1h, start_period: 120s)

### Previous Updates (v3.1.3-FunASR, 2025-12-04)

#### API Simplification
- ✅ **Removed One-Stop Transcription Interface**: Deleted `/api/voice/transcribe_all` endpoint
- ✅ **Removed Clear Dify Files Feature**: Deleted `_clear_dify` special operation
- ✅ **Enhanced Transcription API**: Improved `POST /api/voice/transcribe` with `wait=true` to return transcript directly without words field

### Previous Updates (v3.1.1-FunASR, 2025-11-13)

#### New Features
- ✅ **True Stop Transcription**: Implemented real task interruption using `_cancelled` flag and `InterruptedError` mechanism
- ✅ **Clear All History**: New endpoint `DELETE /api/voice/files/_clear_all` to clear all transcription history

#### Bug Fixes
- ✅ **Filename Uniqueness**: Fixed filename conflicts in batch transcription by using microsecond timestamps and `file_id`
- ✅ **Delete Stopped Files**: Fixed issue where stopped transcription files couldn't be deleted
- ✅ **WebSocket Progress Jump**: Fixed progress jumping issue, ensuring progress only increases
- ✅ **UI Update After Delete**: Fixed issue where UI didn't update immediately after file deletion
- ✅ **Delete Error Message**: Fixed incorrect "deletion failed" message when deleting stopped transcription files

#### Technical Improvements
- ✅ Improved cancellation mechanism using `cancellation_flag` to check cancellation status at key steps
- ✅ Optimized WebSocket message handling to prevent progress regression
- ✅ Improved error handling for file deletion, correctly parsing FastAPI HTTPException responses

## 📚 Related Documentation

- [API Documentation](http://localhost:8998/docs) - Auto-generated FastAPI docs
- [README.md](README.md) - Complete project documentation and usage guide
- [ModelScope Models](https://modelscope.cn/) - AI model platform documentation
- [FunASR](https://github.com/alibaba-damo-academy/FunASR) - Speech recognition framework

---

This guide should provide Claude instances with the essential context needed to understand and work effectively with this audio transcription system. Always refer to the actual code files for the most current implementation details.
