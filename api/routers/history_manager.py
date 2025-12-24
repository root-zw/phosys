"""
历史记录管理模块
负责历史记录的加载和保存
"""

import os
import json
import logging
from typing import TYPE_CHECKING

from config import FILE_CONFIG

if TYPE_CHECKING:
    from .file_manager import ThreadSafeFileManager

logger = logging.getLogger(__name__)

# 历史记录文件路径
HISTORY_FILE = os.path.join(FILE_CONFIG['output_dir'], 'history_records.json')


def load_history_from_file(uploaded_files_manager: 'ThreadSafeFileManager'):
    """
    从文件加载历史记录（只加载已完成的，不影响当前正在处理的文件）
    
    Args:
        uploaded_files_manager: 文件管理器实例
    """
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                completed_files_from_disk = data.get('files', [])
                
                # 保留当前内存中未完成的文件
                all_files = uploaded_files_manager.get_all_files()
                current_incomplete_files = [f for f in all_files 
                                           if f['status'] in ['uploaded', 'processing', 'error']]
                
                # 合并：未完成的文件 + 磁盘上的已完成文件
                # 使用字典去重，以file_id为key
                files_dict = {}
                
                # 先添加未完成的文件
                for f in current_incomplete_files:
                    files_dict[f['id']] = f
                
                # 再添加已完成的文件（如果有重复，已完成的会覆盖）
                for f in completed_files_from_disk:
                    files_dict[f['id']] = f
                
                # 重新构建管理器（需要在锁内完成）
                uploaded_files_manager._lock.acquire()
                try:
                    uploaded_files_manager._files = list(files_dict.values())
                    uploaded_files_manager._completed_files = data.get('completed_files', [])
                finally:
                    uploaded_files_manager._lock.release()
                
                logger.info(f"已加载 {len(completed_files_from_disk)} 条历史记录，当前总文件数: {len(files_dict)}")
    except Exception as e:
        logger.error(f"加载历史记录失败: {e}")


def save_history_to_file(uploaded_files_manager: 'ThreadSafeFileManager'):
    """
    保存历史记录到文件
    
    Args:
        uploaded_files_manager: 文件管理器实例
    """
    try:
        # 只保存已完成的文件记录
        all_files = uploaded_files_manager.get_all_files()
        completed_files = [f for f in all_files if f['status'] == 'completed']
        data = {
            'files': completed_files,
            'completed_files': uploaded_files_manager.get_completed_files()
        }
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(completed_files)} 条历史记录")
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")

