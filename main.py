#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频转写系统 - 统一启动入口
基于Domain-Application-Infra三层架构
"""

import os
import sys
import logging
import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ==================== FFmpeg路径配置 ====================
def setup_ffmpeg_path():
    """设置FFmpeg路径"""
    try:
        result = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
        if result.returncode == 0:
            ffmpeg_path = result.stdout.strip()
            print(f"✅ 找到FFmpeg: {ffmpeg_path}")
            return True
    except Exception:
        pass
    
    common_paths = [
        '/usr/bin',
        '/usr/local/bin',
        '/opt/ffmpeg/bin'
    ]
    
    for path in common_paths:
        if os.path.isfile(os.path.join(path, 'ffmpeg')):
            print(f"✅ 找到FFmpeg: {os.path.join(path, 'ffmpeg')}")
            os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
            return True
    
    print("❌ 找不到FFmpeg,请安装FFmpeg:")
    print("  Ubuntu/Debian: sudo apt install ffmpeg")
    return False

# 设置FFmpeg
if not setup_ffmpeg_path():
    print("⚠️  FFmpeg未找到,音频处理功能可能受限")

# ==================== 禁用FunASR表单打印 ====================
import warnings
warnings.filterwarnings('ignore')
os.environ['FUNASR_DISABLE_PRINT_TABLES'] = '1'

# ==================== 导入配置 ====================
from config import FILE_CONFIG, MODEL_CONFIG, AUDIO_PROCESS_CONFIG, CONCURRENCY_CONFIG

# ==================== 初始化日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
logger = logging.getLogger('main')

# ==================== 初始化FastAPI应用 ====================
app = FastAPI(
    title="音频转写系统",
    description="基于AI的实时语音识别与声纹分离系统 (Domain-Application-Infra架构)",
    version="3.1.3-FunASR"
)

# 速率限制
limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ==================== 初始化各层依赖 ====================
from infra.audio_io.storage import AudioStorage
from infra.runners.asr_runner_funasr import ASRRunner  # 使用FunASR版本
from application.voice.pipeline_service_funasr import PipelineService  # 使用FunASR版本
from api.routers import voice_gateway

# 初始化存储
audio_storage = AudioStorage(
    upload_dir=FILE_CONFIG['upload_dir'],
    temp_dir=FILE_CONFIG['temp_dir'],
    output_dir=FILE_CONFIG['output_dir']
)

# 初始化Runner(延迟加载,首次调用时初始化)
# FunASR方式：只需要ASR Runner（已集成说话人识别）
asr_runner = None
pipeline_service = None

def get_pipeline_service():
    """获取Pipeline服务(单例模式 - FunASR版本)"""
    global asr_runner, pipeline_service
    
    if pipeline_service is None:
        logger.info("🔧 正在初始化Pipeline服务（FunASR一体化模式）...")
        
        # 获取并发配置
        use_pool = CONCURRENCY_CONFIG.get('use_model_pool', True)
        asr_pool_size = CONCURRENCY_CONFIG.get('asr_pool_size', 3)
        
        # 初始化ASR Runner（FunASR - 已集成说话人识别）
        if asr_runner is None:
            logger.info(f"🔧 正在初始化FunASR Runner (ASR+说话人识别一体化, 模型池: {use_pool}, 池大小: {asr_pool_size})...")
            asr_runner = ASRRunner(
                MODEL_CONFIG, 
                use_pool=use_pool,
                pool_size=asr_pool_size
            )
        
        # 初始化Pipeline Service（FunASR版本，不需要单独的声纹分离）
        pipeline_service = PipelineService(
            audio_storage=audio_storage,
            asr_runner=asr_runner,
            audio_config=AUDIO_PROCESS_CONFIG
        )
        
        logger.info("✅ Pipeline服务初始化完成（FunASR一体化模式）")
    
    return pipeline_service

# ==================== 配置静态文件和模板 ====================
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if os.path.exists("uploads"):
    app.mount("/uploads", StaticFiles(directory=FILE_CONFIG['upload_dir']), name="uploads")

if os.path.exists("templates"):
    templates = Jinja2Templates(directory="templates")

# ==================== 添加监控中间件 ====================
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """HTTP 请求指标收集中间件"""
    import time
    
    # 尝试导入监控模块（如果不可用则跳过监控）
    try:
        from infra.monitoring import prometheus_metrics, metrics_collector
        monitoring_available = True
    except ImportError:
        monitoring_available = False
        prometheus_metrics = None
        metrics_collector = None
    
    # 记录开始时间
    start_time = time.time()
    
    # 增加活跃请求数
    if monitoring_available:
        try:
            prometheus_metrics.increment_active_requests()
            metrics_collector.increment_active_requests()
        except Exception:
            pass  # 监控失败不影响请求处理
    
    try:
        # 处理请求
        response = await call_next(request)
        
        # 计算耗时
        duration = time.time() - start_time
        
        # 记录指标
        if monitoring_available:
            try:
                # 获取端点和方法
                endpoint = request.url.path
                method = request.method
                status_code = response.status_code
                
                prometheus_metrics.record_http_request(endpoint, method, status_code, duration)
                metrics_collector.record_request(endpoint, method, status_code, duration)
            except Exception:
                pass  # 监控失败不影响请求处理
        
        return response
    except Exception as e:
        # 计算耗时
        duration = time.time() - start_time
        
        # 记录错误请求
        if monitoring_available:
            try:
                endpoint = request.url.path
                method = request.method
                prometheus_metrics.record_http_request(endpoint, method, 500, duration)
                metrics_collector.record_request(endpoint, method, 500, duration)
            except Exception:
                pass  # 监控失败不影响错误处理
        
        raise
    finally:
        # 减少活跃请求数
        if monitoring_available:
            try:
                prometheus_metrics.decrement_active_requests()
                metrics_collector.decrement_active_requests()
            except Exception:
                pass  # 监控失败不影响清理

# ==================== 注册路由 ====================
# 初始化语音网关
voice_gateway.init_voice_gateway(get_pipeline_service(), audio_storage)

# 注册API路由
app.include_router(voice_gateway.router)

# ==================== 基础路由 ====================
@app.get("/")
async def index(request: Request):
    """主页面"""
    if os.path.exists("templates/index.html"):
        return templates.TemplateResponse("index.html", {"request": request})
    return {"message": "音频转写系统API", "version": "3.1.3-FunASR", "docs": "/docs"}

@app.get("/result.html")
async def result_page(request: Request):
    """结果查看页面"""
    from fastapi.responses import FileResponse
    if os.path.exists("templates/result.html"):
        return templates.TemplateResponse("result.html", {"request": request})
    return JSONResponse({"message": "结果页面", "hint": "请从主页面访问"})

@app.get("/healthz")
async def health_check():
    """
    详细健康检查端点
    检查：模型加载状态、存储空间、依赖服务
    """
    import shutil
    import psutil
    from pathlib import Path
    
    health_status = {
        'status': 'healthy',
        'version': '3.1.3-FunASR',
        'checks': {}
    }
    
    overall_healthy = True
    
    # 1. 检查模型加载状态（延迟加载模式，未加载不影响健康状态）
    try:
        model_loaded = asr_runner is not None
        if asr_runner:
            pool_stats = asr_runner.get_pool_stats()
            # 修复：使用正确的字段名 available_count 和 current_size
            available_count = pool_stats.get('available_count', 0) if pool_stats else 0
            current_size = pool_stats.get('current_size', 0) if pool_stats else 0
            model_pool_healthy = pool_stats and available_count > 0
            health_status['checks']['models'] = {
                'status': 'healthy' if model_pool_healthy else 'degraded',
                'loaded': model_loaded,
                'pool_available': available_count,
                'pool_size': current_size
            }
            # 只有在模型加载后池不可用时才标记为不健康
            if not model_pool_healthy:
                overall_healthy = False
        else:
            # 模型未加载是正常状态（延迟加载），不影响健康检查
            health_status['checks']['models'] = {
                'status': 'not_loaded',
                'loaded': False,
                'message': 'Models will be loaded on first request (lazy loading)'
            }
            # 不设置 overall_healthy = False
    except Exception as e:
        health_status['checks']['models'] = {
            'status': 'error',
            'error': str(e)
        }
        overall_healthy = False
    
    # 2. 检查存储空间
    try:
        from config import FILE_CONFIG
        storage_checks = {}
        
        for dir_name, dir_path in [
            ('uploads', FILE_CONFIG.get('upload_dir', 'uploads')),
            ('transcripts', FILE_CONFIG.get('output_dir', 'transcripts')),
            ('temp', FILE_CONFIG.get('temp_dir', 'audio_temp')),
            ('summaries', FILE_CONFIG.get('summary_dir', 'meeting_summaries'))
        ]:
            try:
                path = Path(dir_path)
                if path.exists():
                    # 检查目录可写性
                    test_file = path / '.health_check'
                    try:
                        test_file.touch()
                        test_file.unlink()
                        writable = True
                    except:
                        writable = False
                    
                    # 获取磁盘使用情况
                    disk_usage = shutil.disk_usage(path)
                    total_gb = disk_usage.total / (1024**3)
                    free_gb = disk_usage.free / (1024**3)
                    used_percent = (disk_usage.used / disk_usage.total) * 100
                    
                    storage_checks[dir_name] = {
                        'exists': True,
                        'writable': writable,
                        'total_gb': round(total_gb, 2),
                        'free_gb': round(free_gb, 2),
                        'used_percent': round(used_percent, 2),
                        'status': 'healthy' if writable and free_gb > 1.0 else 'warning'
                    }
                    
                    if not writable or free_gb < 1.0:
                        overall_healthy = False
                else:
                    storage_checks[dir_name] = {
                        'exists': False,
                        'status': 'error'
                    }
                    overall_healthy = False
            except Exception as e:
                storage_checks[dir_name] = {
                    'status': 'error',
                    'error': str(e)
                }
                overall_healthy = False
        
        health_status['checks']['storage'] = storage_checks
    except Exception as e:
        health_status['checks']['storage'] = {
            'status': 'error',
            'error': str(e)
        }
        overall_healthy = False
    
    # 3. 检查系统资源
    try:
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        health_status['checks']['system'] = {
            'cpu_percent': round(cpu_percent, 2),
            'memory_percent': round(memory.percent, 2),
            'memory_available_gb': round(memory.available / (1024**3), 2),
            'status': 'healthy' if memory.percent < 90 and cpu_percent < 95 else 'warning'
        }
        
        if memory.percent >= 90 or cpu_percent >= 95:
            overall_healthy = False
    except Exception as e:
        health_status['checks']['system'] = {
            'status': 'error',
            'error': str(e)
        }
    
    # 4. 检查依赖服务（Dify Webhook - 可选服务）
    try:
        from config import DIFY_CONFIG
        import requests

        if DIFY_CONFIG.get('base_url') and DIFY_CONFIG.get('api_key'):
            if requests:
                try:
                    # 简单连接测试（不发送实际请求）
                    base_url = DIFY_CONFIG['base_url']
                    response = requests.get(
                        f"{base_url}/health" if not base_url.endswith('/health') else base_url,
                        timeout=3
                    )
                    dify_available = response.status_code < 500
                except:
                    # 如果健康检查端点不存在，至少检查配置是否完整
                    dify_available = bool(DIFY_CONFIG.get('api_key'))
            else:
                # requests 不可用，仅检查配置
                dify_available = bool(DIFY_CONFIG.get('api_key'))

            health_status['checks']['dify'] = {
                'configured': True,
                'available': dify_available,
                'status': 'healthy' if dify_available else 'degraded',
                'message': 'Dify is optional - service will work without it'
            }
            # Dify是可选服务，不影响整体健康状态
            # if not dify_available:
            #     overall_healthy = False
        else:
            health_status['checks']['dify'] = {
                'configured': False,
                'status': 'not_configured',
                'message': 'Dify is optional - service will work without it'
            }
    except Exception as e:
        health_status['checks']['dify'] = {
            'status': 'error',
            'error': str(e),
            'message': 'Dify is optional - service will work without it'
        }
    
    # 5. 检查 FFmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              timeout=2)
        ffmpeg_available = result.returncode == 0
        health_status['checks']['ffmpeg'] = {
            'available': ffmpeg_available,
            'status': 'healthy' if ffmpeg_available else 'error'
        }
        if not ffmpeg_available:
            overall_healthy = False
    except Exception as e:
        health_status['checks']['ffmpeg'] = {
            'available': False,
            'status': 'error',
            'error': str(e)
        }
        overall_healthy = False
    
    # 设置总体状态
    health_status['status'] = 'healthy' if overall_healthy else 'degraded'
    
    # 如果关键组件失败，返回 503
    if not overall_healthy:
        from fastapi import status
        return JSONResponse(
            content=health_status,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    return health_status

@app.get("/api/status")
async def get_system_status():
    """获取系统状态"""
    from infra.monitoring import metrics_collector
    from infra.middleware import rate_limiter
    
    status = {
        'success': True,
        'system': 'running',
        'version': '3.1.3-FunASR',  # 标识FunASR版本
        'mode': 'FunASR一体化模式（ASR+说话人识别）',
        'models_loaded': asr_runner is not None
    }
    
    # 添加模型池统计（FunASR只有一个ASR池）
    if asr_runner:
        asr_stats = asr_runner.get_pool_stats()
        if asr_stats:
            status['funasr_pool'] = asr_stats
    
    # 添加限流统计
    if rate_limiter:
        status['rate_limiter'] = rate_limiter.get_stats()
    
    return status

@app.get("/api/metrics")
async def get_metrics():
    """获取性能指标（仅供管理员使用）"""
    try:
        from infra.monitoring import metrics_collector
        
        stats = metrics_collector.get_all_stats()
        return {
            'success': True,
            'metrics': stats
        }
    except ImportError as e:
        logger.warning(f"监控模块不可用: {e}")
        return {
            'success': False,
            'message': '监控模块不可用，请检查依赖（psutil等）是否已安装'
        }
    except Exception as e:
        logger.error(f"获取指标失败: {e}")
        return {
            'success': False,
            'message': str(e)
        }

@app.get("/metrics")
async def get_prometheus_metrics():
    """Prometheus 指标端点（标准格式）"""
    from fastapi.responses import Response
    from infra.monitoring import prometheus_metrics
    import psutil
    
    try:
        # 更新系统指标
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        prometheus_metrics.update_system_metrics(
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used_mb=memory.used / (1024 * 1024),
            threads=threading.active_count()
        )
        
        # 更新模型池指标
        global asr_runner
        if asr_runner:
            pool_stats = asr_runner.get_pool_stats()
            if pool_stats:
                prometheus_metrics.update_model_pool_metrics(
                    pool_size=pool_stats.get('current_size', 0),
                    available=pool_stats.get('available_count', 0)
                )
        
        # 导出 Prometheus 格式
        metrics_text = prometheus_metrics.export_prometheus_format()
        return Response(content=metrics_text, media_type="text/plain; version=0.0.4")
    except Exception as e:
        logger.error(f"导出 Prometheus 指标失败: {e}")
        return Response(content=f"# Error: {e}\n", media_type="text/plain")

# ==================== 异常处理 ====================
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

# ==================== 应用生命周期 ====================
@app.on_event("startup")
async def startup_event():
    """应用启动"""
    import asyncio
    from api.routers import voice_gateway
    
    logger.info("=" * 60)
    logger.info("      音频转写系统启动中 (DDD架构)")
    logger.info("=" * 60)
    logger.info("📁 上传目录: " + FILE_CONFIG['upload_dir'])
    logger.info("📁 临时目录: " + FILE_CONFIG['temp_dir'])
    logger.info("📁 输出目录: " + FILE_CONFIG['output_dir'])
    logger.info("🎧 支持格式: mp3, wav, m4a, flac, aac, ogg, wma")
    logger.info("=" * 60)
    
    # 设置事件循环引用（用于WebSocket消息推送）
    loop = asyncio.get_running_loop()
    voice_gateway.set_main_loop(loop)
    logger.info("✅ 事件循环已配置")
    
    # 可选: 预加载模型
    preload = os.getenv('PRELOAD_MODELS', 'false').lower() == 'true'
    if preload:
        logger.info("开始预加载模型...")
        try:
            get_pipeline_service()
            logger.info("✅ 模型预加载完成")
        except Exception as e:
            logger.error(f"模型预加载失败: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭"""
    logger.info("正在关闭应用...")
    
    # 关闭WebSocket连接管理器
    try:
        from infra.websocket import ws_manager
        await ws_manager.shutdown()
        logger.info("✅ WebSocket连接管理器已关闭")
    except Exception as e:
        logger.error(f"关闭WebSocket连接管理器失败: {e}")
    
    # 关闭模型池
    global asr_runner
    try:
        if asr_runner is not None:
            logger.info("关闭FunASR Runner...")
            asr_runner.shutdown()
    except Exception as e:
        logger.error(f"关闭模型池失败: {e}")
    
    # 清理临时文件
    try:
        audio_storage.cleanup_temp_files()
        logger.info("✅ 临时文件清理完成")
    except Exception as e:
        logger.error(f"清理临时文件失败: {e}")
    
    logger.info("👋 应用已关闭")

# ==================== 主入口 ====================
def main():
    """主函数"""
    import uvicorn
    
    print("\n" + "=" * 60)
    print("       音频转写系统 - 启动中")
    print("       架构: Domain-Application-Infra")
    print("=" * 60)
    print("🌐 访问地址: http://localhost:8998")
    print("📚 API文档: http://localhost:8998/docs")
    print("📚 ReDoc文档: http://localhost:8998/redoc")
    print("=" * 60 + "\n")
    
    try:
        uvicorn.run(
            app,
            host='0.0.0.0',
            port=8998,
            log_level="info",
            access_log=True,
            timeout_keep_alive=30,  # Keep-alive连接超时30秒
            timeout_graceful_shutdown=30,  # 优雅关闭超时30秒
            # ⚠️ 注意：Uvicorn没有请求处理超时参数，需要在应用层控制
        )
    except KeyboardInterrupt:
        print("\n👋 用户中断,程序退出")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

