"""
工具函数模块
包含各种辅助函数
"""

import asyncio
import logging
from typing import Optional

from infra.websocket import ws_manager

logger = logging.getLogger(__name__)

# 保存主事件循环引用
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """设置主事件循环引用"""
    global _main_loop
    _main_loop = loop
    logger.info("主事件循环已设置")


def send_ws_message_sync(file_id: str, status: str, progress: int = 0, message: str = "", **kwargs):
    """
    在同步代码中发送WebSocket消息的辅助函数
    通过asyncio.run_coroutine_threadsafe在事件循环中执行异步任务
    """
    if _main_loop is None:
        logger.warning("主事件循环未设置，无法发送WebSocket消息")
        return
    
    try:
        # 在主事件循环中调度异步任务
        asyncio.run_coroutine_threadsafe(
            ws_manager.send_file_status(file_id, status, progress, message, kwargs),
            _main_loop
        )
    except Exception as e:
        logger.error(f"发送WebSocket消息失败: {e}")


def allowed_file(filename: str) -> bool:
    """检查文件格式"""
    ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg', 'wma'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def clean_transcript_words(transcript_data):
    """
    清理 transcript 中的 words 字段，只保留基本转写信息
    """
    if not transcript_data:
        return transcript_data
    
    cleaned = []
    for entry in transcript_data:
        cleaned_entry = {
            'speaker': entry.get('speaker', ''),
            'text': entry.get('text', ''),
            'start_time': entry.get('start_time', 0),
            'end_time': entry.get('end_time', 0)
        }
        cleaned.append(cleaned_entry)
    
    return cleaned

