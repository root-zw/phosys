"""
文件处理模块
负责文件上传、下载等处理
"""

import os
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional, TYPE_CHECKING
from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse
from werkzeug.utils import secure_filename

if TYPE_CHECKING:
    from infra.audio_io.storage import AudioStorage
    from .file_manager import ThreadSafeFileManager
    from .utils import allowed_file

logger = logging.getLogger(__name__)

# 导入 Dify 报警模块
try:
    from infra.monitoring.dify_webhook_sender import (
        log_upload_event,
        log_download_event,
        log_delete_event,
        log_clear_history_event
    )
    DIFY_ALARM_ENABLED = True
    logger.info("✅ Dify 报警模块已加载 (FileHandlers)")
except ImportError as e:
    DIFY_ALARM_ENABLED = False
    logger.warning(f"⚠️ Dify 报警模块未找到，报警功能已禁用: {e}")


class FileHandlers:
    """文件处理器"""
    
    def __init__(
        self,
        audio_storage: 'AudioStorage',
        file_manager: 'ThreadSafeFileManager',
        allowed_file_func
    ):
        self.audio_storage = audio_storage
        self.file_manager = file_manager
        self.allowed_file = allowed_file_func
    
    async def upload_files(
        self,
        audio_files: List[UploadFile]
    ) -> Dict:
        """上传音频文件（支持单个或多个文件）"""
        if not audio_files:
            return {'success': False, 'message': '没有选择文件'}
        
        # 验证所有文件格式
        for audio_file in audio_files:
            if not audio_file.filename:
                return {'success': False, 'message': '存在空文件名的文件'}
            if not self.allowed_file(audio_file.filename):
                return {
                    'success': False,
                    'message': f'文件 {audio_file.filename} 格式不支持，支持的格式：mp3, wav, m4a, flac, aac, ogg, wma'
                }
        
        uploaded_files = []
        failed_files = []
        
        for audio_file in audio_files:
            try:
                filename = secure_filename(audio_file.filename)
                # 使用微秒级时间戳确保批量上传时文件名唯一
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                name, ext = os.path.splitext(filename)
                safe_filename = f"{name}_{timestamp}{ext}"
                
                contents = await audio_file.read()
                file_size = len(contents)
                filepath = self.audio_storage.save_uploaded_file(contents, safe_filename)
                
                file_id = str(uuid.uuid4())
                
                file_info = {
                    'id': file_id,
                    'filename': safe_filename,
                    'original_name': audio_file.filename,
                    'filepath': filepath,
                    'size': file_size,
                    'upload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'uploaded',
                    'progress': 0,
                    'error_message': ''
                }
                
                self.file_manager.add_file(file_info)
                uploaded_files.append(file_info)
                logger.info(f"文件上传成功: {audio_file.filename}, ID: {file_id}")
                
                # 记录文件上传指标
                try:
                    from infra.monitoring import prometheus_metrics
                    prometheus_metrics.record_file_upload()
                except Exception:
                    pass  # 指标记录失败不影响主流程
                
                if DIFY_ALARM_ENABLED:
                    log_upload_event(
                        file_id=file_id,
                        filename=audio_file.filename,
                        file_size=file_size,
                        level="SUCCESS"
                    )
                
            except Exception as e:
                logger.error(f"文件上传失败 {audio_file.filename}: {e}")
                failed_files.append({
                    'filename': audio_file.filename,
                    'error': str(e)
                })
                
                if DIFY_ALARM_ENABLED:
                    try:
                        file_id_temp = str(uuid.uuid4())
                        log_upload_event(
                            file_id=file_id_temp,
                            filename=audio_file.filename,
                            file_size=0,
                            level="ERROR",
                            error=e
                        )
                    except:
                        pass
        
        # 返回结果
        if not uploaded_files:
            return {
                'success': False,
                'message': '所有文件上传失败',
                'failed_files': failed_files
            }
        
        # 统一返回格式
        result = {
            'success': True,
            'message': f'成功上传 {len(uploaded_files)} 个文件' if len(uploaded_files) > 1 else '文件上传成功',
            'files': uploaded_files,
            'file_ids': [f['id'] for f in uploaded_files]
        }
        
        # 单个文件时，添加向后兼容字段
        if len(uploaded_files) == 1:
            result['file'] = uploaded_files[0]
            result['file_id'] = uploaded_files[0]['id']
        
        # 如果有失败的文件，添加失败信息
        if failed_files:
            result['failed_files'] = failed_files
        
        return result
    
    def get_audio_file(self, file_id: str, download: int = 0) -> FileResponse:
        """获取音频文件"""
        file_info = self.file_manager.get_file(file_id)
        
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
    
    def download_transcript_file(
        self,
        file_id: str,
        save_transcript_to_word_func
    ) -> FileResponse:
        """下载转写结果"""
        file_info = self.file_manager.get_file(file_id)
        
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
            
            # 重新生成文件
            filename, filepath = save_transcript_to_word_func(
                transcript_data,
                language=file_info.get('language', 'zh'),
                audio_filename=file_info.get('original_name'),
                file_id=file_id
            )
            
            if filename and os.path.exists(filepath):
                file_info['transcript_file'] = filepath
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
            if DIFY_ALARM_ENABLED:
                log_download_event(
                    file_id=file_id,
                    filename=file_info.get('original_name', 'unknown') if file_info else 'unknown',
                    level="ERROR",
                    error=e
                )
            raise HTTPException(status_code=500, detail=f'下载失败: {str(e)}')
    
    def download_summary_file(
        self,
        file_id: str,
        save_meeting_summary_to_word_func
    ) -> FileResponse:
        """下载会议纪要"""
        file_info = self.file_manager.get_file(file_id)
        
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
            
            filename, filepath = save_meeting_summary_to_word_func(
                transcript_data,
                summary,
                "meeting_summary",
                file_id,
                file_info.get('original_name'),
                audio_duration
            )
            
            if filename and os.path.exists(filepath):
                file_info['summary_file'] = filepath
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
    
    def delete_file(
        self,
        file_id: str,
        save_history_to_file_func,
        send_ws_message_sync_func
    ) -> Dict:
        """删除文件"""
        from config import FILE_CONFIG
        
        # 特殊操作：清空所有历史记录
        if file_id == "_clear_all":
            try:
                deleted_count = 0
                deleted_audio_count = 0
                deleted_transcript_count = 0
                deleted_summary_count = 0
                
                all_files = self.file_manager.get_all_files()
                
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
                            
                            # 记录文件删除指标
                            try:
                                from infra.monitoring import prometheus_metrics
                                prometheus_metrics.record_file_delete()
                            except Exception:
                                pass  # 指标记录失败不影响主流程
                        
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
                        self.file_manager.remove_file(file_info['id'])
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"删除文件失败 {file_info.get('original_name', 'unknown')}: {e}")
                
                # 清空output_dir目录下的所有文件
                output_dir = FILE_CONFIG['output_dir']
                if os.path.exists(output_dir):
                    for filename in os.listdir(output_dir):
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
                
                # 清空历史记录文件
                from .history_manager import HISTORY_FILE
                try:
                    import json
                    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                        json.dump({'files': [], 'completed_files': []}, f, ensure_ascii=False, indent=2)
                    logger.info("已清空历史记录文件")
                except Exception as e:
                    logger.error(f"清空历史记录文件失败: {e}")
                
                logger.info(f"清空所有历史记录完成: 删除 {deleted_audio_count} 个音频文件, {deleted_transcript_count} 个转写文档, {deleted_summary_count} 个会议纪要文档, {deleted_count} 条历史记录")
                
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
        file_info = self.file_manager.get_file(file_id)
        
        if not file_info:
            raise HTTPException(status_code=404, detail='文件不存在')
        
        # 如果文件正在处理中，但已设置取消标志（停止转写），允许删除
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
            
            # 从内存中删除
            self.file_manager.remove_file(file_id)
            
            # 保存更新后的历史记录到磁盘
            save_history_to_file_func(self.file_manager)
            
            if DIFY_ALARM_ENABLED:
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
            
            send_ws_message_sync_func(
                file_id,
                'deleted',
                0,
                f"文件已删除: {file_info['original_name']}"
            )
            
            logger.info(f"文件删除成功: {file_info['original_name']}, ID: {file_id}")
            
            return {'success': True, 'message': '文件删除成功'}
            
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            
            if DIFY_ALARM_ENABLED:
                filename = file_info.get('original_name', 'unknown') if file_info else 'unknown'
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

