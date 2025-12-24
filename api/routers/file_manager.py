"""
文件管理器模块
负责文件信息的线程安全管理
"""

import threading
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class ThreadSafeFileManager:
    """线程安全的文件管理器"""
    
    def __init__(self):
        self._files = []
        self._processing_files = []
        self._completed_files = []
        self._lock = threading.RLock()  # 递归锁，支持同一线程多次获取
    
    def add_file(self, file_info: dict):
        """添加文件"""
        with self._lock:
            self._files.append(file_info)
    
    def get_file(self, file_id: str) -> Optional[dict]:
        """获取文件信息"""
        with self._lock:
            for f in self._files:
                if f['id'] == file_id:
                    return f
            return None
    
    def get_all_files(self) -> List[dict]:
        """获取所有文件（返回副本）"""
        with self._lock:
            return self._files.copy()
    
    def update_file(self, file_id: str, updates: dict):
        """更新文件信息"""
        with self._lock:
            for f in self._files:
                if f['id'] == file_id:
                    f.update(updates)
                    return True
            return False
    
    def remove_file(self, file_id: str) -> bool:
        """移除文件"""
        with self._lock:
            for i, f in enumerate(self._files):
                if f['id'] == file_id:
                    self._files.pop(i)
                    self._processing_files = [fid for fid in self._processing_files if fid != file_id]
                    self._completed_files = [fid for fid in self._completed_files if fid != file_id]
                    return True
            return False
    
    def add_to_processing(self, file_id: str):
        """添加到处理队列"""
        with self._lock:
            if file_id not in self._processing_files:
                self._processing_files.append(file_id)
    
    def remove_from_processing(self, file_id: str):
        """从处理队列移除"""
        with self._lock:
            self._processing_files = [fid for fid in self._processing_files if fid != file_id]
    
    def add_to_completed(self, file_id: str):
        """添加到已完成队列"""
        with self._lock:
            if file_id not in self._completed_files:
                self._completed_files.append(file_id)
    
    def get_processing_files(self) -> List[str]:
        """获取处理中的文件ID列表"""
        with self._lock:
            return self._processing_files.copy()
    
    def get_completed_files(self) -> List[str]:
        """获取已完成的文件ID列表"""
        with self._lock:
            return self._completed_files.copy()
    
    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        with self._lock:
            return {
                'files': self._files.copy(),
                'processing_files': self._processing_files.copy(),
                'completed_files': self._completed_files.copy()
            }

