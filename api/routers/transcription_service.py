"""
转写服务模块
负责转写任务的处理逻辑
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, Future

if TYPE_CHECKING:
    from application.voice.pipeline_service_funasr import PipelineService
    from .file_manager import ThreadSafeFileManager
    from .utils import send_ws_message_sync, clean_transcript_words
    from .document_generator import save_transcript_to_word
    from .history_manager import save_history_to_file

logger = logging.getLogger(__name__)

# 导入 Dify 报警模块
try:
    from infra.monitoring.dify_webhook_sender import (
        log_success_alarm,
        log_error_alarm,
        log_stop_transcription_event
    )
    DIFY_ALARM_ENABLED = True
    logger.info("✅ Dify 报警模块已加载 (TranscriptionService)")
except ImportError as e:
    DIFY_ALARM_ENABLED = False
    logger.warning(f"⚠️ Dify 报警模块未找到，报警功能已禁用: {e}")


class TranscriptionService:
    """转写服务"""
    
    def __init__(
        self,
        pipeline_service: 'PipelineService',
        file_manager: 'ThreadSafeFileManager',
        thread_pool: ThreadPoolExecutor,
        transcription_tasks: Dict[str, Future],
        transcription_tasks_lock: threading.Lock
    ):
        self.pipeline_service = pipeline_service
        self.file_manager = file_manager
        self.thread_pool = thread_pool
        self.transcription_tasks = transcription_tasks
        self.transcription_tasks_lock = transcription_tasks_lock
    
    def process_single_file(
        self,
        file_info: dict,
        language: str,
        hotword: str,
        send_ws_message_sync_func,
        save_transcript_to_word_func,
        clean_transcript_words_func,
        save_history_to_file_func
    ):
        """处理单个文件的转写任务"""
        try:
            file_id = file_info['id']
            logger.info(f"[线程池] 开始处理文件: {file_info['original_name']}, 线程: {threading.current_thread().name}")
            
            # 检查是否已被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 已被取消，跳过处理")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                return
            
            # 创建进度回调
            def update_file_progress(step, progress, message="", transcript_entry=None):
                # 检查是否已被取消
                if file_info.get('_cancelled', False):
                    logger.info(f"[线程池] 检测到文件 {file_id} 已被取消，停止处理")
                    raise InterruptedError("转写任务已被取消")
                
                file_info['progress'] = progress
                # WebSocket推送：进度更新
                send_ws_message_sync_func(
                    file_id,
                    'processing',
                    progress,
                    message or f"处理中: {step}"
                )
            
            # 再次检查是否已被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 在开始转写前已被取消")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                return
            
            logger.info(f"[线程池] 开始转写: {file_info['original_name']}")
            
            # 记录开始时间和指标
            import time
            from infra.monitoring import prometheus_metrics, metrics_collector
            transcription_start_time = time.time()
            prometheus_metrics.increment_active_transcriptions()
            
            try:
                transcript, _, _ = self.pipeline_service.execute_transcription(
                    file_info['filepath'],
                    hotword=hotword,
                    language=language,
                    instance_id=file_id,
                    cancellation_flag=lambda: file_info.get('_cancelled', False),
                    callback=update_file_progress
                )
            finally:
                # 计算耗时并记录指标
                transcription_duration = time.time() - transcription_start_time
                prometheus_metrics.decrement_active_transcriptions()
                
                # 获取文件大小和音频时长
                file_size = file_info.get('size', 0)
                # 从转写结果中获取音频时长（如果有的话）
                audio_duration = 0.0
                if transcript and len(transcript) > 0:
                    # 取最后一段的结束时间作为音频时长
                    last_segment = transcript[-1]
                    audio_duration = last_segment.get('end_time', 0.0)
                
                # 记录转写指标
                success = transcript is not None and len(transcript) > 0
                prometheus_metrics.record_transcription(
                    success=success,
                    duration=transcription_duration,
                    file_size=file_size,
                    audio_duration=audio_duration
                )
                metrics_collector.record_transcription(
                    success=success,
                    duration=transcription_duration,
                    file_size=file_size,
                    audio_duration=audio_duration
                )
            
            # 检查是否在转写过程中被取消
            if file_info.get('_cancelled', False):
                logger.info(f"[线程池] 文件 {file_id} 在转写过程中被取消")
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                file_info['error_message'] = '转写已停止'
                send_ws_message_sync_func(
                    file_id,
                    'uploaded',
                    0,
                    '转写已停止'
                )
                
                if DIFY_ALARM_ENABLED:
                    log_stop_transcription_event(
                        file_id=file_id,
                        filename=file_info.get('original_name', 'unknown'),
                        level="SUCCESS",
                        progress=file_info.get('progress', 0)
                    )
                
                return
            
            logger.info(f"[线程池] 转写完成: {file_info['original_name']}")
            
            # 保存转写结果
            if transcript:
                file_info['transcript_data'] = transcript
                logger.info(f"[线程池] 已保存 {len(transcript)} 条转写记录")
                
                # 自动生成Word文档
                filename, filepath = save_transcript_to_word_func(
                    transcript,
                    language=language,
                    audio_filename=file_info['original_name'],
                    file_id=file_id
                )
                if filename:
                    file_info['transcript_file'] = filepath
                    logger.info(f"[线程池] 转写文档已保存: {filename}")
                
                # 更新状态为完成
                file_info['status'] = 'completed'
                file_info['progress'] = 100
                file_info['complete_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 添加到已完成列表
                if file_info['id'] not in self.file_manager.get_completed_files():
                    self.file_manager.add_to_completed(file_info['id'])
                
                # 保存历史记录
                save_history_to_file_func(self.file_manager)
                
                # WebSocket推送：转写完成
                send_ws_message_sync_func(
                    file_info['id'],
                    'completed',
                    100,
                    f"转写完成: {file_info['original_name']}"
                )
                
                logger.info(f"[线程池] 文件处理完成: {file_info['original_name']}")
                
                # 发送 SUCCESS 报警到 Dify
                if DIFY_ALARM_ENABLED:
                    transcript_data = []
                    for entry in transcript:
                        transcript_data.append({
                            'speaker': entry.get('speaker', ''),
                            'text': entry.get('text', ''),
                            'start_time': entry.get('start_time', 0),
                            'end_time': entry.get('end_time', 0)
                        })
                    
                    detail_data = {
                        'file_id': file_id,
                        'filename': file_info['original_name'],
                        'user': file_info.get('user', 'anonymous'),
                        'transcript': transcript_data,
                        'total_chars': sum(len(entry.get('text', '')) for entry in transcript) if transcript else 0,
                        'segment_count': len(transcript) if transcript else 0
                    }
                    success_detail = json.dumps(detail_data, ensure_ascii=False)
                    file_size = file_info.get('size', 0)
                    
                    log_success_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"转写任务成功完成: {file_info['original_name']}",
                        detail=success_detail,
                        file_size=file_size,
                        user=file_info.get('user')
                    )
            else:
                file_info['status'] = 'error'
                file_info['error_message'] = '转写失败'
                
                send_ws_message_sync_func(
                    file_info['id'],
                    'error',
                    0,
                    '转写失败'
                )
                
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"转写失败: {file_info['original_name']} - 转写结果为空",
                        exception=None,
                        user=file_info.get('user')
                    )
                
        except InterruptedError as e:
            file_id = file_info['id']
            logger.info(f"[线程池] 文件 {file_id} 转写被中断: {e}")
            file_info['status'] = 'uploaded'
            file_info['progress'] = 0
            file_info['error_message'] = '转写已停止'
            
            send_ws_message_sync_func(
                file_id,
                'uploaded',
                0,
                '转写已停止'
            )
        except Exception as e:
            file_id = file_info['id']
            logger.error(f"[线程池] 处理文件失败 {file_info['original_name']}: {e}")
            
            if file_info.get('_cancelled', False):
                file_info['status'] = 'uploaded'
                file_info['progress'] = 0
                file_info['error_message'] = '转写已停止'
                send_ws_message_sync_func(
                    file_id,
                    'uploaded',
                    0,
                    '转写已停止'
                )
            else:
                file_info['status'] = 'error'
                file_info['error_message'] = str(e)
                
                send_ws_message_sync_func(
                    file_id,
                    'error',
                    0,
                    f"处理失败: {str(e)}"
                )
                
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=file_id,
                        module="VoiceGateway",
                        message=f"处理文件失败: {file_info['original_name']}",
                        exception=e,
                        user=file_info.get('user')
                    )
            
            import traceback
            traceback.print_exc()
        finally:
            file_id = file_info['id']
            # 从处理列表中移除
            if file_id in self.file_manager.get_processing_files():
                self.file_manager.remove_from_processing(file_id)
            
            # 从任务字典中移除
            with self.transcription_tasks_lock:
                if file_id in self.transcription_tasks:
                    del self.transcription_tasks[file_id]
    
    def start_transcription(
        self,
        file_ids: List[str],
        language: str,
        hotword: str,
        wait_until_complete: bool,
        timeout_seconds: int,
        send_ws_message_sync_func,
        save_transcript_to_word_func,
        clean_transcript_words_func,
        save_history_to_file_func
    ) -> Dict:
        """启动转写任务"""
        # 检查所有文件是否存在且可处理
        files_to_process = []
        for file_id in file_ids:
            file_info = self.file_manager.get_file(file_id)
            if file_info:
                if file_info['status'] == 'processing':
                    return {'success': False, 'message': f'文件 {file_info["original_name"]} 正在处理中'}
                files_to_process.append(file_info)
            else:
                return {'success': False, 'message': f'文件ID {file_id} 不存在'}
        
        if not files_to_process:
            return {'success': False, 'message': '没有可处理的文件'}
        
        # 提前更新所有文件状态为 processing
        for file_info in files_to_process:
            file_info['status'] = 'processing'
            file_info['progress'] = 0
            file_info['language'] = language
            self.file_manager.add_to_processing(file_info['id'])
            logger.info(f"文件 {file_info['original_name']} 状态已更新为 processing")
            
            send_ws_message_sync_func(
                file_info['id'],
                'processing',
                0,
                f"开始转写: {file_info['original_name']}"
            )
        
        # 使用线程池并发处理所有文件
        futures = []
        for file_info in files_to_process:
            file_id = file_info['id']
            file_info['_cancelled'] = False
            
            future = self.thread_pool.submit(
                self.process_single_file,
                file_info,
                language,
                hotword,
                send_ws_message_sync_func,
                save_transcript_to_word_func,
                clean_transcript_words_func,
                save_history_to_file_func
            )
            futures.append((future, file_info))
            
            # 将Future存储到任务字典中，用于取消任务
            with self.transcription_tasks_lock:
                self.transcription_tasks[file_id] = future
        
        logger.info(f"已提交 {len(files_to_process)} 个文件到线程池处理")
        
        # 如果需要阻塞等待至完成，则轮询等待直到完成或超时
        if wait_until_complete:
            deadline = time.time() + timeout_seconds
            pending_ids = set(fi['id'] for _, fi in futures)
            failed_ids = set()
            completed_ids = set()
            
            # 轮询状态直到全部完成或超时
            while time.time() < deadline and pending_ids:
                finished_now = []
                for _, fi in futures:
                    fid = fi['id']
                    if fid not in pending_ids:
                        continue
                    status = fi.get('status')
                    if status in ('completed', 'error'):
                        finished_now.append(fid)
                        if status == 'completed':
                            completed_ids.add(fid)
                        else:
                            failed_ids.add(fid)
                for fid in finished_now:
                    pending_ids.discard(fid)
                if pending_ids:
                    time.sleep(0.5)
            
            if pending_ids:
                # 有未完成任务（超时）
                result = {
                    'success': False,
                    'status': 'timeout',
                    'message': '部分任务未在超时时间内完成',
                    'completed_file_ids': sorted(list(completed_ids)),
                    'failed_file_ids': sorted(list(failed_ids)),
                    'pending_file_ids': sorted(list(pending_ids))
                }
                
                # 收集已完成和失败文件的结果
                all_finished_ids = completed_ids | failed_ids
                if all_finished_ids:
                    results = []
                    for fid in all_finished_ids:
                        file_info = next((f for f in files_to_process if f['id'] == fid), None)
                        if file_info:
                            file_result = {
                                'file_id': fid,
                                'filename': file_info.get('original_name', ''),
                                'status': file_info.get('status', 'completed'),
                                'progress': file_info.get('progress', 100)
                            }
                            
                            if file_info.get('transcript_data'):
                                file_result['transcript'] = clean_transcript_words_func(file_info.get('transcript_data', []))
                            
                            if file_info.get('status') == 'error':
                                file_result['error_message'] = file_info.get('error_message', '转写失败')
                            
                            results.append(file_result)
                    
                    if results:
                        result['results'] = results
                        if len(results) == 1:
                            result['file_id'] = results[0]['file_id']
                            result['filename'] = results[0]['filename']
                            result['status'] = results[0]['status']
                            result['progress'] = results[0]['progress']
                            if 'transcript' in results[0]:
                                result['transcript'] = results[0]['transcript']
                            if 'error_message' in results[0]:
                                result['error_message'] = results[0]['error_message']
                
                return result
            else:
                # 全部完成
                result = {
                    'success': True,
                    'status': 'completed',
                    'message': f'转写完成 {len(completed_ids)} 个文件',
                    'file_ids': sorted(list(completed_ids))
                }
                
                # 收集所有文件的转写结果
                results = []
                all_finished_ids = completed_ids | failed_ids
                
                for fid in all_finished_ids:
                    file_info = next((f for f in files_to_process if f['id'] == fid), None)
                    if file_info:
                        file_result = {
                            'file_id': fid,
                            'filename': file_info.get('original_name', ''),
                            'status': file_info.get('status', 'completed'),
                            'progress': file_info.get('progress', 100),
                            'upload_time': file_info.get('upload_time', ''),
                            'complete_time': file_info.get('complete_time', '')
                        }
                        
                        if file_info.get('transcript_data'):
                            file_result['transcript'] = clean_transcript_words_func(file_info.get('transcript_data', []))
                        
                        if file_info.get('status') == 'error':
                            file_result['error_message'] = file_info.get('error_message', '转写失败')
                            result['success'] = False
                        
                        results.append(file_result)
                
                result['results'] = results
                
                # 单个文件时，直接返回 transcript
                if len(results) == 1:
                    result['file_id'] = results[0]['file_id']
                    result['filename'] = results[0]['filename']
                    result['progress'] = results[0]['progress']
                    result['status'] = results[0]['status']
                    if 'transcript' in results[0]:
                        result['transcript'] = results[0]['transcript']
                    if 'error_message' in results[0]:
                        result['error_message'] = results[0]['error_message']
                        result['success'] = False
                
                return result
        
        # 非阻塞模式：立即返回"已开始转写"
        result = {
            'success': True,
            'status': 'processing',
            'message': f'已开始转写 {len(files_to_process)} 个文件',
            'file_ids': [f['id'] for f in files_to_process],
            'count': len(files_to_process),
            'progress': 0
        }
        
        # 单个文件时，添加 file_id 字段方便使用
        if len(files_to_process) == 1:
            result['file_id'] = files_to_process[0]['id']
            result['filename'] = files_to_process[0].get('original_name', '')
        
        return result
    
    def stop_transcription(self, file_id: str, send_ws_message_sync_func) -> Dict:
        """停止转写任务"""
        file_info = self.file_manager.get_file(file_id)
        
        if not file_info:
            return {'success': False, 'message': '文件不存在'}
        
        if file_info['status'] != 'processing':
            return {'success': False, 'message': '文件未在转写中'}
        
        # 设置中断标志
        file_info['_cancelled'] = True
        logger.info(f"🛑 设置文件 {file_id} 的中断标志")
        
        # 尝试取消Future任务
        with self.transcription_tasks_lock:
            if file_id in self.transcription_tasks:
                future = self.transcription_tasks[file_id]
                cancelled = future.cancel()
                if cancelled:
                    logger.info(f"✅ 成功取消文件 {file_id} 的Future任务")
                else:
                    logger.warning(f"⚠️ 文件 {file_id} 的Future任务无法取消（可能已开始执行）")
                del self.transcription_tasks[file_id]
        
        # 更新文件状态
        file_info['status'] = 'uploaded'
        file_info['progress'] = 0
        file_info['error_message'] = '转写已停止'
        
        if file_id in self.file_manager.get_processing_files():
            self.file_manager.remove_from_processing(file_id)
        
        send_ws_message_sync_func(
            file_id,
            'uploaded',
            0,
            '转写已停止'
        )
        
        if DIFY_ALARM_ENABLED:
            log_stop_transcription_event(
                file_id=file_id,
                filename=file_info.get('original_name', 'unknown'),
                level="SUCCESS",
                progress=file_info.get('progress', 0)
            )
        
        logger.info(f"🛑 已停止文件 {file_id} 的转写任务")
        return {'success': True, 'message': '已停止转写'}

