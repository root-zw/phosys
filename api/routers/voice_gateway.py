"""
API - 语音服务网关 (重构版)
只包含路由定义，业务逻辑已拆分到独立模块
"""

import os
import json
import ast
import asyncio
import logging
import threading
from datetime import datetime
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse

from application.voice.pipeline_service_funasr import PipelineService
from infra.audio_io.storage import AudioStorage
from infra.websocket import ws_manager
from config import FILE_CONFIG, LANGUAGE_CONFIG, AI_MODEL_CONFIG, CONCURRENCY_CONFIG, MODEL_CONFIG
from domain.voice.text_processor import TextProcessor

# 导入拆分后的模块
from .file_manager import ThreadSafeFileManager
from .history_manager import load_history_from_file, save_history_to_file
from .history_manager import HISTORY_FILE
from .utils import set_main_loop, send_ws_message_sync, allowed_file, clean_transcript_words
from .document_generator import save_transcript_to_word, save_meeting_summary_to_word
from .summary_generator import generate_meeting_summary, generate_default_summary
from .transcription_service import TranscriptionService
from .file_handlers import FileHandlers

logger = logging.getLogger(__name__)

# 导入 Dify 报警模块
try:
    from infra.monitoring.dify_webhook_sender import (
        log_success_alarm,
        log_error_alarm,
        log_upload_event,
        log_download_event,
        log_delete_event,
        log_clear_history_event,
        log_stop_transcription_event
    )
    DIFY_ALARM_ENABLED = True
    logger.info("✅ Dify 报警模块已加载 (VoiceGateway)")
except ImportError as e:
    DIFY_ALARM_ENABLED = False
    logger.warning(f"⚠️ Dify 报警模块未找到，报警功能已禁用: {e}")

router = APIRouter(prefix="/api/voice", tags=["voice"])

# ==================== 全局变量和初始化 ====================

# 全局服务实例
pipeline_service: Optional[PipelineService] = None
audio_storage: Optional[AudioStorage] = None

# 线程安全的文件管理器
uploaded_files_manager = ThreadSafeFileManager()

# 线程池用于并发处理转写任务
TRANSCRIPTION_THREAD_POOL = ThreadPoolExecutor(
    max_workers=CONCURRENCY_CONFIG.get('transcription_workers', 5),
    thread_name_prefix='transcribe-worker'
)

# 任务字典：存储 file_id -> Future 的映射，用于取消任务
transcription_tasks = {}  # {file_id: Future}
transcription_tasks_lock = threading.Lock()  # 保护任务字典的锁

# 服务实例
transcription_service: Optional[TranscriptionService] = None
file_handlers: Optional[FileHandlers] = None


def init_voice_gateway(service: PipelineService, storage: AudioStorage):
    """初始化网关服务"""
    global pipeline_service, audio_storage, transcription_service, file_handlers
    
    pipeline_service = service
    audio_storage = storage
    
    # 初始化服务实例
    transcription_service = TranscriptionService(
        pipeline_service=pipeline_service,
        file_manager=uploaded_files_manager,
        thread_pool=TRANSCRIPTION_THREAD_POOL,
        transcription_tasks=transcription_tasks,
        transcription_tasks_lock=transcription_tasks_lock
    )
    
    file_handlers = FileHandlers(
        audio_storage=audio_storage,
        file_manager=uploaded_files_manager,
        allowed_file_func=allowed_file
    )
    
    # 启动时加载历史记录
    load_history_from_file(uploaded_files_manager)


def _extract_user(request: Request, explicit_user: Optional[str] = None, body: Optional[dict] = None) -> Optional[str]:
    """
    提取 user 标识（用于多用户隔离历史记录）
    支持来源优先级：
    - 显式参数（query/form 等）
    - JSON body.user
    - Header: X-User
    - Query: user
    """
    if explicit_user and explicit_user.strip():
        return explicit_user.strip()
    if body and isinstance(body, dict):
        body_user = body.get('user')
        if isinstance(body_user, str) and body_user.strip():
            return body_user.strip()
    header_user = request.headers.get('X-User')
    if header_user and header_user.strip():
        return header_user.strip()
    query_user = request.query_params.get('user')
    if query_user and query_user.strip():
        return query_user.strip()
    return None


def _normalize_user(user: Optional[str]) -> str:
    return (user or '').strip() or 'anonymous'


def _file_belongs_to_user(file_info: dict, user: str) -> bool:
    return _normalize_user(file_info.get('user')) == _normalize_user(user)



# ==================== RESTful文件资源接口 ====================

@router.get("/files")
async def list_all_files(
    request: Request,
    filepath: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    include_history: bool = False,
    download: int = 0,
    user: Optional[str] = None
):
    """
    📋 列出所有文件（RESTful风格，方案2优化）
    
    查询参数：
    - filepath: 可选，如果提供则直接返回该路径的音频文件（类似 /api/voice/files/{file_id}）
    - status: 过滤状态 (uploaded/processing/completed/error)
    - limit: 返回数量限制
    - offset: 分页偏移量
    - include_history: 是否包含历史记录，默认False
    - download: 当提供filepath时，是否下载（0=预览，1=下载）
    
    返回：文件列表及统计信息，或音频文件（当提供filepath时）
    """
    try:
        # 如果提供了filepath，直接返回音频文件
        if filepath:
            # 安全检查：防止路径遍历攻击
            # 规范化路径并确保在允许的目录内
            normalized_path = os.path.normpath(filepath)
            
            # 检查路径是否在uploads目录内
            upload_dir = os.path.abspath(FILE_CONFIG['upload_dir'])
            file_full_path = os.path.abspath(normalized_path)
            
            # 确保文件路径在uploads目录内
            if not file_full_path.startswith(upload_dir):
                raise HTTPException(status_code=403, detail="文件路径不在允许的目录内")
            
            # 检查文件是否存在
            if not os.path.exists(file_full_path):
                raise HTTPException(status_code=404, detail="音频文件不存在")
            
            # 检查是否为文件（不是目录）
            if not os.path.isfile(file_full_path):
                raise HTTPException(status_code=400, detail="指定路径不是文件")
            
            # 获取文件名（用于下载时的文件名）
            filename = os.path.basename(file_full_path)
            
            if download == 1:
                return FileResponse(
                    file_full_path,
                    media_type='application/octet-stream',
                    filename=filename
                )
            else:
                return FileResponse(
                    file_full_path,
                    media_type='audio/mpeg'
                )
        
        # 如果需要历史记录，从文件加载
        if include_history:
            load_history_from_file(uploaded_files_manager)
        
        effective_user = _extract_user(request, explicit_user=user)

        # 获取所有文件
        all_files = uploaded_files_manager.get_all_files()
        # 传了 user 才按 user 隔离；不传保持原行为（返回所有）
        if effective_user:
            all_files = [f for f in all_files if _file_belongs_to_user(f, effective_user)]
        
        # 根据状态过滤
        if status:
            filtered_files = [f for f in all_files if f['status'] == status]
        else:
            filtered_files = all_files
        
        # 排序：processing > uploaded > completed > error
        status_priority = {'processing': 0, 'uploaded': 1, 'completed': 2, 'error': 3}
        filtered_files.sort(key=lambda x: (
            status_priority.get(x['status'], 999),
            x.get('upload_time', '')
        ), reverse=True)
        
        # 分页
        total_count = len(filtered_files)
        if limit:
            filtered_files = filtered_files[offset:offset+limit]
        else:
            filtered_files = filtered_files[offset:]
        
        # 🔧 为每个文件添加可访问的下载URL
        for file_info in filtered_files:
            # 添加音频下载链接
            if 'download_urls' not in file_info:
                file_info['download_urls'] = {}
            file_info['download_urls']['audio'] = f"/api/voice/audio/{file_info['id']}?download=1"
            
            # 添加转写文档下载链接（如果存在）
            if file_info.get('transcript_file'):
                file_info['download_urls']['transcript'] = f"/api/voice/download_transcript/{file_info['id']}"
            
            # 添加会议纪要下载链接（如果存在）
            if file_info.get('meeting_summary'):
                file_info['download_urls']['summary'] = f"/api/voice/download_summary/{file_info['id']}"
        
        # 统计信息
        status_counts = {
            'uploaded': len([f for f in all_files if f['status'] == 'uploaded']),
            'processing': len([f for f in all_files if f['status'] == 'processing']),
            'completed': len([f for f in all_files if f['status'] == 'completed']),
            'error': len([f for f in all_files if f['status'] == 'error'])
        }
        
        return {
            'success': True,
            'files': filtered_files,
            'pagination': {
                'total': total_count,
                'limit': limit,
                'offset': offset,
                'returned': len(filtered_files)
            },
            'statistics': status_counts
        }
        
    except Exception as e:
        logger.error(f"列出文件失败: {e}")
        return JSONResponse({
            'success': False,
            'message': f'获取文件列表失败: {str(e)}'
        }, status_code=500)


@router.get("/files/{file_id}")
async def get_file_detail(
    file_id: str,
    request: Request,
    include_transcript: bool = False,
    include_summary: bool = False,
    user: Optional[str] = None
):
    """
    📄 获取文件详情（RESTful风格，方案2优化）
    
    路径参数：
    - file_id: 文件ID
    
    查询参数：
    - include_transcript: 是否包含转写结果，默认False
    - include_summary: 是否包含会议纪要，默认False
    
    返回：文件详细信息
    """
    try:
        file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
        
        if not file_info:
            raise HTTPException(status_code=404, detail='文件不存在')

        # 传了 user 时才做鉴权（不传 user 保持旧行为）
        effective_user = _extract_user(request, explicit_user=user)
        if effective_user and not _file_belongs_to_user(file_info, effective_user):
            raise HTTPException(status_code=403, detail='无权访问该文件')
        
        # 构建基本响应
        result = {
            'success': True,
            'file': {
                'id': file_info['id'],
                'filename': file_info.get('original_name', file_info.get('filename')),
                'size': file_info.get('size', 0),
                'status': file_info['status'],
                'progress': file_info.get('progress', 0),
                'language': file_info.get('language', 'zh'),
                'upload_time': file_info.get('upload_time'),
                'complete_time': file_info.get('complete_time'),
                'error_message': file_info.get('error_message', '')
            }
        }
        
        # 添加下载链接
        result['file']['download_urls'] = {
            'audio': f"/api/voice/audio/{file_id}?download=1"
        }
        
        if file_info.get('transcript_file'):
            result['file']['download_urls']['transcript'] = f"/api/voice/download_transcript/{file_id}"
        
        if file_info.get('meeting_summary'):
            result['file']['download_urls']['summary'] = f"/api/voice/download_summary/{file_id}"
        
        # 可选：包含转写结果
        if include_transcript and file_info['status'] == 'completed':
            transcript_data = file_info.get('transcript_data', [])
            result['transcript'] = transcript_data
            
            # 添加统计信息
            if transcript_data:
                speakers = set(t.get('speaker', '') for t in transcript_data if t.get('speaker'))
                result['statistics'] = {
                    'speakers_count': len(speakers),
                    'segments_count': len(transcript_data),
                    'total_characters': sum(len(t.get('text', '')) for t in transcript_data),
                    'speakers': list(speakers)
                }
        
        # 可选：包含会议纪要
        if include_summary and file_info.get('meeting_summary'):
            result['summary'] = file_info['meeting_summary']
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件详情失败: {e}")
        raise HTTPException(status_code=500, detail=f'获取文件详情失败: {str(e)}')


@router.patch("/files/{file_id}")
async def update_file(file_id: str, request: Request):
    """
    🔄 更新文件（RESTful风格，方案2优化）
    
    路径参数：
    - file_id: 文件ID
    
    请求体：
    - action: 操作类型 (retranscribe)
    - language: 语言（重新转写时）
    - hotword: 热词（重新转写时）
    
    返回：更新后的文件信息
    """
    try:
        body = await request.json()
        action = body.get('action')
        
        file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
        
        if not file_info:
            raise HTTPException(status_code=404, detail='文件不存在')
        
        if action == 'retranscribe':
            # 重新转写
            if file_info['status'] == 'processing':
                raise HTTPException(status_code=400, detail='文件正在处理中')
            
            language = body.get('language', file_info.get('language', 'zh'))
            # 热词优先从API传入，未传入时从config.py读取
            hotword = body.get('hotword', MODEL_CONFIG.get('hotword', ''))
            
            # 重置状态
            file_info['status'] = 'processing'
            file_info['progress'] = 0
            file_info['language'] = language
            
            # 提交转写任务
            def retranscribe_task():
                try:
                    def update_progress(step, progress, message="", transcript_entry=None):
                        file_info['progress'] = progress
                        send_ws_message_sync(file_id, 'processing', progress, message)
                    
                    # ✅ 执行转写（不再需要全局锁）
                    # ✅ 修复：直接传递 callback，避免多任务共享状态冲突
                    transcript, _, _ = pipeline_service.execute_transcription(
                        file_info['filepath'],
                        hotword=hotword,
                        language=language,
                        instance_id=file_id,
                        callback=update_progress  # 直接传递 callback，每个任务有独立的 tracker
                    )
                    
                    if transcript:
                        file_info['transcript_data'] = transcript
                        # ✅ 修复：传入 file_id 确保每个文件生成唯一的转写文档文件名
                        filename, filepath = save_transcript_to_word(
                            transcript, language=language,
                            audio_filename=file_info['original_name'],
                            file_id=file_id
                        )
                        if filename:
                            file_info['transcript_file'] = filepath
                        
                        file_info['status'] = 'completed'
                        file_info['progress'] = 100
                        file_info['complete_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        save_history_to_file(uploaded_files_manager)
                        send_ws_message_sync(file_id, 'completed', 100, '重新转写完成')
                    else:
                        file_info['status'] = 'error'
                        file_info['error_message'] = '重新转写失败'
                        send_ws_message_sync(file_id, 'error', 0, '重新转写失败')
                        
                except Exception as e:
                    logger.error(f"重新转写失败: {e}")
                    file_info['status'] = 'error'
                    file_info['error_message'] = str(e)
                    send_ws_message_sync(file_id, 'error', 0, f"重新转写失败: {str(e)}")
            
            TRANSCRIPTION_THREAD_POOL.submit(retranscribe_task)
            
            return {
                'success': True,
                'message': '已开始重新转写',
                'file_id': file_id,
                'status': 'processing'
            }
        
        else:
            raise HTTPException(status_code=400, detail=f'不支持的操作: {action}')
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新文件失败: {e}")
        raise HTTPException(status_code=500, detail=f'更新文件失败: {str(e)}')


# ==================== 原有接口（保持向后兼容） ====================

@router.post("/upload")
async def upload_audio(
    request: Request,
    audio_files: List[UploadFile] = File(..., alias="audio_file"),
    user: Optional[str] = Form(None)
):
    """
    上传音频文件（支持单个或多个文件）
    
    参数：
    - audio_files: 文件列表（表单字段名：audio_file，支持多个同名字段）
    
    使用方式：
    - 单个文件：form-data 中一个 audio_file 字段
    - 多个文件：form-data 中多个 audio_file 字段
    
    返回：
    - 单个文件：保持向后兼容，返回 {success, message, file, file_id}
    - 多个文件：返回 {success, message, files, file_ids, failed_files}
    """
    if not file_handlers:
        raise HTTPException(status_code=500, detail="文件处理器未初始化")

    effective_user = _extract_user(request, explicit_user=user)
    result = await file_handlers.upload_files(audio_files, user=effective_user)
    
    # 根据结果返回适当的 HTTP 状态码
    if not result.get('success'):
        status_code = 400 if '格式不支持' in result.get('message', '') else 500
        return JSONResponse(result, status_code=status_code)
    
    return JSONResponse(result, status_code=200)


@router.post("/transcribe")
async def transcribe(request: Request):
    """开始转写（支持批量和并发处理；支持等待完成再返回）"""
    global TRANSCRIPTION_THREAD_POOL
    
    try:
        body = await request.json()
        effective_user = _extract_user(request, body=body)
        
        # ✅ 兼容模式：同时支持 file_id (单个) 和 file_ids (数组)
        file_ids = body.get('file_ids', [])
        file_id = body.get('file_id', '')
        
        # 如果提供了单个 file_id，转换为数组
        if file_id and not file_ids:
            file_ids = [file_id]
        # 如果 file_ids 是字符串，尝试解析（可能是 JSON 字符串、Python 列表字符串或单个 ID）
        elif isinstance(file_ids, str):
            # 先尝试解析 JSON 字符串（Dify 模板转换可能输出 JSON 字符串）
            try:
                parsed = json.loads(file_ids)
                if isinstance(parsed, list):
                    file_ids = parsed
                else:
                    file_ids = [parsed]
            except (json.JSONDecodeError, TypeError):
                # 如果不是 JSON，尝试解析 Python 列表字符串格式（如 "['id1', 'id2']"）
                try:
                    # 使用 ast.literal_eval 安全解析 Python 字面量
                    import ast
                    parsed = ast.literal_eval(file_ids)
                    if isinstance(parsed, list):
                        file_ids = parsed
                    else:
                        file_ids = [parsed]
                except (ValueError, SyntaxError):
                    # 如果都解析失败，当作单个 ID 处理
                    file_ids = [file_ids]
        
        language = body.get('language', 'zh')
        # 热词优先从API传入，未传入时从config.py读取
        hotword = body.get('hotword', MODEL_CONFIG.get('hotword', ''))
        # 新增：是否等待完成以及超时时间（秒）
        wait_until_complete = body.get('wait', True)
        timeout_seconds = int(body.get('timeout', 3600))  # 默认最多等待1小时
    except:
        return {'success': False, 'message': '请求参数错误'}
    
    if not file_ids:
        return {'success': False, 'message': '请选择要转写的文件（file_id 或 file_ids）'}
    
    # 确保 file_ids 是列表，且每个元素都是字符串
    if not isinstance(file_ids, list):
        logger.error(f"file_ids 不是列表类型: {type(file_ids)}, 值: {file_ids}")
        return {'success': False, 'message': f'file_ids 格式错误，期望数组，实际类型: {type(file_ids).__name__}'}
    
    # 规范化 file_ids：确保所有元素都是字符串
    normalized_file_ids = []
    for item in file_ids:
        if isinstance(item, str):
            normalized_file_ids.append(item)
        elif isinstance(item, (list, tuple)):
            # 如果元素本身是列表，展开它
            normalized_file_ids.extend([str(x) for x in item])
        else:
            normalized_file_ids.append(str(item))
    
    file_ids = normalized_file_ids
    logger.info(f"解析后的 file_ids: {file_ids}, 类型: {type(file_ids)}, 长度: {len(file_ids)}")
    
    if not transcription_service:
        raise HTTPException(status_code=500, detail="转写服务未初始化")

    # 传了 user 时才做鉴权（不传 user 保持旧行为）
    if effective_user:
        for fid in file_ids:
            fi = uploaded_files_manager.get_file(fid)
            if not fi:
                return JSONResponse({'success': False, 'message': f'文件ID {fid} 不存在'}, status_code=404)
            if not _file_belongs_to_user(fi, effective_user):
                return JSONResponse({'success': False, 'message': '无权操作该文件'}, status_code=403)
    
    # 调用转写服务
    result = transcription_service.start_transcription(
        file_ids=file_ids,
        language=language,
        hotword=hotword,
        wait_until_complete=wait_until_complete,
        timeout_seconds=timeout_seconds,
        send_ws_message_sync_func=send_ws_message_sync,
        save_transcript_to_word_func=save_transcript_to_word,
        clean_transcript_words_func=clean_transcript_words,
        save_history_to_file_func=lambda fm: save_history_to_file(fm)
    )
    
    # 根据结果返回适当的 HTTP 状态码
    if result.get('status') == 'timeout':
        return JSONResponse(result, status_code=202)  # 202 Accepted for partial completion
    elif result.get('success'):
        return JSONResponse(result, status_code=200)
    else:
        status_code = 400 if '不存在' in result.get('message', '') or '格式错误' in result.get('message', '') else 500
        return JSONResponse(result, status_code=status_code)
@router.post("/stop/{file_id}")
async def stop_transcription(file_id: str):
    """
    ⏹️ 停止转写（向后兼容接口）
    
    实现真正的任务中断：取消Future并设置中断标志
    """
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        return {'success': False, 'message': '文件不存在'}
    
    if file_info['status'] != 'processing':
        return {'success': False, 'message': '文件未在转写中'}
    
    # 设置中断标志
    file_info['_cancelled'] = True
    logger.info(f"🛑 设置文件 {file_id} 的中断标志")
    
    # 尝试取消Future任务
    with transcription_tasks_lock:
        if file_id in transcription_tasks:
            future = transcription_tasks[file_id]
            cancelled = future.cancel()
            if cancelled:
                logger.info(f"✅ 成功取消文件 {file_id} 的Future任务")
            else:
                logger.warning(f"⚠️ 文件 {file_id} 的Future任务无法取消（可能已开始执行）")
            # 从任务字典中移除
            del transcription_tasks[file_id]
    
    # 更新文件状态
    file_info['status'] = 'uploaded'
    file_info['progress'] = 0
    file_info['error_message'] = '转写已停止'
    
    if file_id in uploaded_files_manager.get_processing_files():
        uploaded_files_manager.remove_from_processing(file_id)
    
    # 🔔 WebSocket推送：转写已停止
    send_ws_message_sync(
        file_id,
        'uploaded',
        0,
        '转写已停止'
    )
    
    # --- 发送停止转写成功事件到 Dify ---
    if DIFY_ALARM_ENABLED:
        log_stop_transcription_event(
            file_id=file_id,
            filename=file_info.get('original_name', 'unknown'),
            level="SUCCESS",
            progress=file_info.get('progress', 0)
        )
    
    logger.info(f"🛑 已停止文件 {file_id} 的转写任务")
    return {'success': True, 'message': '已停止转写'}


@router.get("/status/{file_id}")
async def get_status(file_id: str):
    """
    📊 获取转写状态（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files/{file_id}
    """
    for f in uploaded_files_manager.get_all_files():
        if f['id'] == file_id:
            return {
                'success': True,
                'status': f['status'],
                'progress': f['progress'],
                'error_message': f.get('error_message', '')
            }
    
    return {'success': False, 'message': '文件不存在'}


@router.get("/result/{file_id}")
async def get_result(file_id: str):
    """
    📄 获取转写结果（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files/{file_id}?include_transcript=true&include_summary=true
    """
    for f in uploaded_files_manager.get_all_files():
        if f['id'] == file_id:
            if f['status'] != 'completed':
                return {'success': False, 'message': '文件转写未完成'}
            
            return {
                'success': True,
                'file_info': {
                    'id': f['id'],
                    'original_name': f['original_name'],
                    'upload_time': f['upload_time']
                },
                'transcript': f.get('transcript_data', []),
                'summary': f.get('meeting_summary')
            }
    
    return {'success': False, 'message': '文件不存在'}


@router.get("/history")
async def list_history(request: Request, user: Optional[str] = None):
    """
    📜 获取历史记录（向后兼容接口）
    
    推荐使用新接口: GET /api/voice/files?status=completed&include_history=true
    """
    # 从文件加载历史记录
    load_history_from_file(uploaded_files_manager)

    effective_user = _extract_user(request, explicit_user=user)
    
    history_records = []
    for f in uploaded_files_manager.get_all_files():
        if f['status'] == 'completed' and (not effective_user or _file_belongs_to_user(f, effective_user)):
            transcript_data = f.get('transcript_data', [])
            speakers = set(t.get('speaker', '') for t in transcript_data if t.get('speaker'))
            
            details = f"{len(speakers)}位发言人, {len(transcript_data)}段对话"
            
            history_records.append({
                'file_id': f['id'],
                'filename': f['original_name'],
                'transcribe_time': f.get('complete_time', f.get('upload_time', '-')),
                'status': 'completed',
                'details': details
            })
    
    history_records.sort(key=lambda x: x['transcribe_time'], reverse=True)
    
    logger.info(f"返回 {len(history_records)} 条历史记录")
    
    return {
        'success': True,
        'records': history_records,
        'total': len(history_records)
    }


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request, user: Optional[str] = None):
    """
    🗑️ 删除文件（RESTful标准接口）
    
    删除音频文件、转写结果和相关文档
    
    特殊操作：
    - file_id = "_clear_all": 清空所有历史记录，包括所有转写文件以及所有音频
    """
    effective_user = _extract_user(request, explicit_user=user)

    # 特殊操作：清空所有历史记录
    if file_id == "_clear_all":
        try:
            # 如果提供 user：只清空该 user 的历史（不影响其他用户）
            if effective_user:
                deleted_count = 0
                deleted_audio_count = 0
                deleted_transcript_count = 0
                deleted_summary_count = 0

                all_files = uploaded_files_manager.get_all_files()
                for file_info in all_files:
                    # 只处理该用户的文件
                    if not _file_belongs_to_user(file_info, effective_user):
                        continue
                    # 跳过正在处理中的文件
                    if file_info['status'] == 'processing':
                        continue
                    try:
                        # 删除音频文件
                        if 'filepath' in file_info and os.path.exists(file_info['filepath']):
                            os.remove(file_info['filepath'])
                            deleted_audio_count += 1
                        # 删除转写文档
                        if file_info.get('transcript_file') and os.path.exists(file_info['transcript_file']):
                            os.remove(file_info['transcript_file'])
                            deleted_transcript_count += 1
                        # 删除会议纪要文档
                        if file_info.get('summary_file') and os.path.exists(file_info['summary_file']):
                            os.remove(file_info['summary_file'])
                            deleted_summary_count += 1

                        uploaded_files_manager.remove_file(file_info['id'])
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"删除用户历史文件失败 {file_info.get('original_name', 'unknown')}: {e}")

                # 保存更新后的历史记录到磁盘（只保存 remaining completed）
                save_history_to_file(uploaded_files_manager)

                return {
                    'success': True,
                    'message': '清空用户历史记录成功',
                    'deleted': {
                        'audio_files': deleted_audio_count,
                        'transcript_files': deleted_transcript_count,
                        'summary_files': deleted_summary_count,
                        'records': deleted_count
                    }
                }

            deleted_count = 0
            deleted_audio_count = 0
            deleted_transcript_count = 0
            deleted_summary_count = 0
            
            # 获取所有文件
            all_files = uploaded_files_manager.get_all_files()
            
            for file_info in all_files:
                # 跳过正在处理中的文件
                if file_info['status'] == 'processing':
                    continue
                
                try:
                    # 删除音频文件
                    if 'filepath' in file_info and os.path.exists(file_info['filepath']):
                        os.remove(file_info['filepath'])
                        deleted_audio_count += 1
                        logger.info(f"已删除音频文件: {file_info['filepath']}")
                    
                    # 删除转写文档
                    if 'transcript_file' in file_info and os.path.exists(file_info['transcript_file']):
                        os.remove(file_info['transcript_file'])
                        deleted_transcript_count += 1
                        logger.info(f"已删除转写文档: {file_info['transcript_file']}")
                    
                    # 删除会议纪要文档
                    if 'summary_file' in file_info and os.path.exists(file_info['summary_file']):
                        os.remove(file_info['summary_file'])
                        deleted_summary_count += 1
                        logger.info(f"已删除会议纪要文档: {file_info['summary_file']}")
                    
                    # 从内存中删除
                    uploaded_files_manager.remove_file(file_info['id'])
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"删除文件失败 {file_info.get('original_name', 'unknown')}: {e}")
            
            # 清空output_dir目录下的所有文件（包括.zip和.docx，但不包括会议纪要）
            output_dir = FILE_CONFIG['output_dir']
            if os.path.exists(output_dir):
                for filename in os.listdir(output_dir):
                    # 跳过history_records.json文件
                    if filename == 'history_records.json':
                        continue
                    file_path = os.path.join(output_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            logger.info(f"已删除输出文件: {filename}")
                    except Exception as e:
                        logger.error(f"删除输出文件失败 {filename}: {e}")
            
            # 清空会议纪要目录下的所有文件
            summary_dir = FILE_CONFIG.get('summary_dir', 'meeting_summaries')
            if os.path.exists(summary_dir):
                for filename in os.listdir(summary_dir):
                    file_path = os.path.join(summary_dir, filename)
                    try:
                        if os.path.isfile(file_path) and filename.endswith('.docx'):
                            os.remove(file_path)
                            deleted_summary_count += 1
                            logger.info(f"已删除会议纪要文档: {filename}")
                    except Exception as e:
                        logger.error(f"删除会议纪要文档失败 {filename}: {e}")
            
            # 清空历史记录文件（保留文件但清空内容）
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'files': [], 'completed_files': []}, f, ensure_ascii=False, indent=2)
                logger.info("已清空历史记录文件")
            except Exception as e:
                logger.error(f"清空历史记录文件失败: {e}")
            
            logger.info(f"清空所有历史记录完成: 删除 {deleted_audio_count} 个音频文件, {deleted_transcript_count} 个转写文档, {deleted_summary_count} 个会议纪要文档, {deleted_count} 条历史记录")
            
            # --- 发送清空历史记录成功事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_clear_history_event(
                    level="SUCCESS",
                    deleted_records=deleted_count,
                    deleted_audio_files=deleted_audio_count,
                    deleted_transcript_files=deleted_transcript_count
                )
            
            return {
                'success': True, 
                'message': f'清空所有历史记录成功',
                'deleted': {
                    'audio_files': deleted_audio_count,
                    'transcript_files': deleted_transcript_count,
                    'summary_files': deleted_summary_count,
                    'records': deleted_count
                }
            }
        except Exception as e:
            logger.error(f"清空所有历史记录失败: {e}")
            
            # --- 发送清空历史记录失败事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_clear_history_event(
                    level="ERROR",
                    deleted_records=0,
                    deleted_audio_files=0,
                    deleted_transcript_files=0,
                    error=e
                )
            
            raise HTTPException(status_code=500, detail=f'清空所有历史记录失败: {str(e)}')
    
    # 正常删除单个文件
    file_info = uploaded_files_manager.get_file(file_id)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')

    # 传了 user 时才做鉴权（不传 user 保持旧行为）
    if effective_user and not _file_belongs_to_user(file_info, effective_user):
        raise HTTPException(status_code=403, detail='无权删除该文件')
    
    # ✅ 修复：如果文件正在处理中，但已设置取消标志（停止转写），允许删除
    if file_info['status'] == 'processing' and not file_info.get('_cancelled', False):
        raise HTTPException(status_code=400, detail='文件正在处理中，无法删除')
    
    try:
        # 删除音频文件
        if os.path.exists(file_info['filepath']):
            os.remove(file_info['filepath'])
            logger.info(f"已删除音频文件: {file_info['filepath']}")
        
        # 删除转写文档（如果存在）
        if 'transcript_file' in file_info and os.path.exists(file_info['transcript_file']):
            os.remove(file_info['transcript_file'])
            logger.info(f"已删除转写文档: {file_info['transcript_file']}")
        
        # 删除会议纪要文档（如果存在）
        if 'summary_file' in file_info and os.path.exists(file_info['summary_file']):
            os.remove(file_info['summary_file'])
            logger.info(f"已删除会议纪要文档: {file_info['summary_file']}")
        
        # 从内存中删除（使用线程安全方法）
        uploaded_files_manager.remove_file(file_id)
        
        # 保存更新后的历史记录到磁盘
        save_history_to_file(uploaded_files_manager)
        
        # --- 发送删除成功事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            # 检查文件是否是被停止的转写
            was_stopped = (
                file_info.get('_cancelled', False) or 
                file_info.get('error_message') == '转写已停止'
            )
            log_delete_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown'),
                level="SUCCESS",
                was_stopped=was_stopped
            )
        
        # 🔔 WebSocket推送：文件已删除
        send_ws_message_sync(
            file_id,
            'deleted',
            0,
            f"文件已删除: {file_info['original_name']}"
        )
        
        logger.info(f"文件删除成功: {file_info['original_name']}, ID: {file_id}")
        
        return {'success': True, 'message': '文件删除成功'}
        
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        
        # --- 发送删除失败事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            filename = file_info.get('original_name', 'unknown') if file_info else 'unknown'
            # 检查文件是否是被停止的转写
            was_stopped = False
            if file_info:
                was_stopped = (
                    file_info.get('_cancelled', False) or 
                    file_info.get('error_message') == '转写已停止'
                )
            log_delete_event(
                file_id=file_id,
                filename=filename,
                level="ERROR",
                error=e,
                was_stopped=was_stopped
            )
        
        raise HTTPException(status_code=500, detail=f'删除文件失败: {str(e)}')


@router.get("/audio/{file_id}")
async def get_audio(file_id: str, download: int = 0):
    """获取音频文件"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    if not os.path.exists(file_info['filepath']):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    
    if download == 1:
        return FileResponse(
            file_info['filepath'],
            media_type='application/octet-stream',
            filename=file_info['original_name']
        )
    else:
        return FileResponse(
            file_info['filepath'],
            media_type='audio/mpeg'
        )


@router.get("/download_transcript/{file_id}")
async def download_transcript(file_id: str):
    """下载转写结果"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename="unknown",
                level="ERROR"
            )
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown'),
                level="ERROR"
            )
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    try:
        if 'transcript_file' in file_info and file_info['transcript_file']:
            filepath = file_info['transcript_file']
            if os.path.exists(filepath):
                # --- 发送下载成功事件到 Dify ---
                if DIFY_ALARM_ENABLED:
                    log_download_event(
                        file_id=file_id,
                        filename=file_info.get('original_name', os.path.basename(filepath)),
                        level="SUCCESS"
                    )
                return FileResponse(
                    path=filepath,
                    filename=os.path.basename(filepath),
                    media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
        
        transcript_data = file_info.get('transcript_data', [])
        if not transcript_data:
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', 'unknown'),
                    level="ERROR"
                )
            raise HTTPException(status_code=400, detail='没有转写结果')
        
        # ✅ 修复：传入 file_id 确保每个文件生成唯一的转写文档文件名
        filename, filepath = save_transcript_to_word(
            transcript_data,
            language=file_info.get('language', 'zh'),
            audio_filename=file_info.get('original_name'),
            file_id=file_id
        )
        
        if filename and os.path.exists(filepath):
            file_info['transcript_file'] = filepath
            # --- 发送下载成功事件到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', filename),
                    level="SUCCESS"
                )
            return FileResponse(
                path=filepath,
                filename=filename,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', 'unknown'),
                    level="ERROR"
                )
            raise HTTPException(status_code=500, detail='生成Word文档失败')
    except HTTPException:
        raise
    except Exception as e:
        # --- 发送下载失败事件到 Dify ---
        if DIFY_ALARM_ENABLED:
            log_download_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown') if file_info else 'unknown',
                level="ERROR",
                error=e
            )
        raise HTTPException(status_code=500, detail=f'下载失败: {str(e)}')


@router.post("/generate_summary/{file_id}")
async def generate_summary_legacy(file_id: str, request: Request = None):
    """
    📝 生成会议纪要（向后兼容接口）
    
    支持自定义提示词和模型选择：
    - prompt: 自定义提示词模板（可选，使用 {transcript} 作为占位符）
    - model: 模型名称（可选，默认使用配置的模型）
    
    推荐使用新接口: PATCH /api/voice/files/{file_id} with action=generate_summary
    """
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    transcript_data = file_info.get('transcript_data', [])
    if not transcript_data:
        raise HTTPException(status_code=400, detail='没有转写结果')
    
    # 获取请求参数（自定义提示词和模型）
    custom_prompt = None
    model = None
    
    if request:
        try:
            body = await request.json()
            custom_prompt = body.get('prompt')
            model = body.get('model')
        except:
            # 如果不是JSON请求，使用默认值
            pass
    
    try:
        # 使用线程池异步执行生成会议纪要（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            TRANSCRIPTION_THREAD_POOL,
            generate_meeting_summary,
            transcript_data,
            custom_prompt,
            model
        )
        
        if summary:
            file_info['meeting_summary'] = summary
            
            # 计算音频时长
            audio_duration = None
            if transcript_data:
                last_entry = transcript_data[-1] if transcript_data else None
                if last_entry and 'end_time' in last_entry:
                    audio_duration = last_entry['end_time']
            
            # 使用线程池异步执行Word文档生成（避免阻塞事件循环）
            filename, filepath = await loop.run_in_executor(
                TRANSCRIPTION_THREAD_POOL,
                save_meeting_summary_to_word,
                transcript_data, 
                summary, 
                "meeting_summary",  # filename_prefix
                file_id,
                file_info.get('original_name'),
                audio_duration
            )
            
            if filename and filepath:
                file_info['summary_file'] = filepath
                # 保存历史记录也在线程池中执行
                await loop.run_in_executor(
                    TRANSCRIPTION_THREAD_POOL,
                    save_history_to_file,
                    uploaded_files_manager
                )
                return {
                    'success': True, 
                    'message': '会议纪要生成成功',
                    'summary': summary
                }
            else:
                # 即使保存文件失败，也保存摘要数据
                await loop.run_in_executor(
                    TRANSCRIPTION_THREAD_POOL,
                    save_history_to_file,
                    uploaded_files_manager
                )
                return {
                    'success': True, 
                    'message': '会议纪要生成成功，但保存文件失败',
                    'summary': summary
                }
        else:
            raise HTTPException(status_code=500, detail='生成会议纪要失败')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'生成会议纪要失败: {str(e)}')


@router.get("/download_summary/{file_id}")
async def download_summary(file_id: str):
    """下载会议纪要"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if file_info['status'] != 'completed':
        raise HTTPException(status_code=400, detail='文件转写未完成')
    
    if not file_info.get('meeting_summary'):
        raise HTTPException(status_code=400, detail='请先生成会议纪要')
    
    try:
        # 如果已有保存的文件，直接返回
        if 'summary_file' in file_info and file_info['summary_file']:
            filepath = file_info['summary_file']
            if os.path.exists(filepath):
                return FileResponse(
                    path=filepath,
                    filename=os.path.basename(filepath),
                    media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
        
        # 否则重新生成文件
        transcript_data = file_info.get('transcript_data', [])
        summary = file_info['meeting_summary']
        
        # 计算音频时长
        audio_duration = None
        if transcript_data:
            last_entry = transcript_data[-1] if transcript_data else None
            if last_entry and 'end_time' in last_entry:
                audio_duration = last_entry['end_time']
        
        # 使用线程池异步执行Word文档生成（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        filename, filepath = await loop.run_in_executor(
            TRANSCRIPTION_THREAD_POOL,
            save_meeting_summary_to_word,
            transcript_data, 
            summary, 
            "meeting_summary",  # filename_prefix
            file_id,
            file_info.get('original_name'),
            audio_duration
        )
        
        if filename and os.path.exists(filepath):
            # 保存文件路径到 file_info
            file_info['summary_file'] = filepath
            # 保存历史记录也在线程池中执行
            await loop.run_in_executor(
                TRANSCRIPTION_THREAD_POOL,
                save_history_to_file,
                uploaded_files_manager
            )
            
            return FileResponse(
                path=filepath,
                filename=filename,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            raise HTTPException(status_code=500, detail='生成Word文档失败')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'下载失败: {str(e)}')


@router.delete("/summary/{file_id}")
async def delete_summary(file_id: str):
    """删除会议纪要"""
    file_info = next((f for f in uploaded_files_manager.get_all_files() if f['id'] == file_id), None)
    
    if not file_info:
        raise HTTPException(status_code=404, detail='文件不存在')
    
    if not file_info.get('meeting_summary'):
        raise HTTPException(status_code=400, detail='没有会议纪要可删除')
    
    try:
        # 删除会议纪要数据
        if 'meeting_summary' in file_info:
            del file_info['meeting_summary']
        
        # 删除该转写结果对应的所有会议纪要文件
        deleted_files = []
        summary_dir = FILE_CONFIG.get('summary_dir', 'meeting_summaries')
        
        # 生成 file_id 的短标识（与保存文件时使用的格式一致）
        file_id_short = file_id.replace('-', '')[:8]  # 移除连字符，取前8位
        
        # 扫描 summary_dir 目录，查找所有匹配该 file_id 的会议纪要文件
        if os.path.exists(summary_dir):
            for filename in os.listdir(summary_dir):
                # 匹配格式：meeting_summary_*_{file_id_short}.docx
                if filename.startswith('meeting_summary_') and filename.endswith(f'_{file_id_short}.docx'):
                    filepath = os.path.join(summary_dir, filename)
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                            deleted_files.append(filename)
                            logger.info(f"已删除会议纪要文档: {filepath}")
                    except Exception as e:
                        logger.warning(f"删除会议纪要文档失败 {filepath}: {e}")
        
        # 删除 file_info 中保存的文件路径（如果存在）
        if 'summary_file' in file_info:
            del file_info['summary_file']
        
        # 保存更改
        save_history_to_file(uploaded_files_manager)
        
        message = f'会议纪要删除成功'
        if deleted_files:
            message += f'，共删除 {len(deleted_files)} 个文件'
        
        return {
            'success': True,
            'message': message,
            'deleted_files_count': len(deleted_files)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会议纪要失败: {e}")
        raise HTTPException(status_code=500, detail=f'删除会议纪要失败: {str(e)}')


@router.get("/languages")
async def get_languages():
    """获取支持的语言列表"""
    return {
        'success': True,
        'languages': [
            {'value': key, 'name': value['name'], 'description': value['description']}
            for key, value in LANGUAGE_CONFIG.items()
        ]
    }


@router.get("/transcript_files")
async def list_transcript_files():
    """列出所有转写文件"""
    try:
        files = audio_storage.list_output_files('.docx')
        for f in files:
            stat = os.stat(f['filepath'])
            f['modified'] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            f['type'] = 'Word文档'
        
        files.sort(key=lambda x: x['modified'], reverse=True)
        return {'success': True, 'files': files}
    except Exception as e:
        return {'success': False, 'message': str(e)}


@router.get("/download_file/{filename}")
async def download_file(filename: str):
    """
    📥 下载输出文件（Word文档、ZIP压缩包等）
    
    路径参数：
    - filename: 文件名（例如：transcript_20251101_203654.docx）
    
    用途：
    - 下载单独的 Word 转写文档
    - 下载其他输出文件
    
    返回：文件流
    """
    try:
        filepath = os.path.join(FILE_CONFIG['output_dir'], filename)
        if os.path.exists(filepath):
            # 根据文件扩展名确定 MIME 类型
            if filename.endswith('.zip'):
                media_type = 'application/zip'
            elif filename.endswith('.docx'):
                media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                media_type = 'application/octet-stream'
            
            return FileResponse(
                filepath,
                media_type=media_type,
                filename=filename
            )
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete_file/{filename}")
async def delete_output_file(filename: str):
    """删除输出文件"""
    try:
        filepath = os.path.join(FILE_CONFIG['output_dir'], filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'message': '文件删除成功'}
        else:
            return {'success': False, 'message': '文件不存在'}
    except Exception as e:
        return {'success': False, 'message': f'删除失败: {str(e)}'}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点 - 实时推送文件状态更新
    
    客户端可以通过此WebSocket连接接收：
    - 文件上传状态
    - 转写进度更新
    - 转写完成通知
    - 错误提示
    """
    await ws_manager.connect(websocket)
    
    try:
        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket连接已建立"
        })
        
        # 保持连接并处理客户端消息
        while True:
            data = await websocket.receive_text()
            # 可以处理客户端发送的消息（如订阅特定文件）
            try:
                message = json.loads(data)
                if message.get('type') == 'subscribe':
                    file_id = message.get('file_id')
                    if file_id:
                        ws_manager.subscribe_file(websocket, file_id)
                        await websocket.send_json({
                            "type": "subscribed",
                            "file_id": file_id,
                            "message": f"已订阅文件 {file_id} 的状态更新"
                        })
            except json.JSONDecodeError:
                pass
            
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("WebSocket客户端断开连接")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        ws_manager.disconnect(websocket)


