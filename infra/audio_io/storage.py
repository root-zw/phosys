"""
Infra - 音频文件存储
负责音频文件的保存、加载、清理等操作
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class AudioStorage:
    """音频存储管理器"""
    
    def __init__(self, upload_dir: str, temp_dir: str, output_dir: str):
        self.upload_dir = upload_dir
        self.temp_dir = temp_dir
        self.output_dir = output_dir
        
        # 确保目录存在
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
    
    def save_uploaded_file(self, file_content: bytes, filename: str) -> str:
        """保存上传的文件"""
        filepath = os.path.join(self.upload_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(file_content)
        return filepath
    
    def get_temp_path(self, filename: str) -> str:
        """获取临时文件路径"""
        return os.path.join(self.temp_dir, filename)
    
    def get_output_path(self, filename: str) -> str:
        """获取输出文件路径"""
        return os.path.join(self.output_dir, filename)
    
    def cleanup_temp_files(self, instance_id: str = None):
        """清理临时文件"""
        try:
            if instance_id:
                # 只清理特定实例的临时文件
                for file in os.listdir(self.temp_dir):
                    if instance_id in file:
                        try:
                            os.remove(os.path.join(self.temp_dir, file))
                        except Exception as e:
                            print(f"删除文件 {file} 失败: {e}")
            else:
                # 清理所有临时文件
                for file in os.listdir(self.temp_dir):
                    try:
                        os.remove(os.path.join(self.temp_dir, file))
                    except Exception as e:
                        print(f"删除文件 {file} 失败: {e}")
        except Exception as e:
            print(f"清理临时文件失败: {e}")
    
    def file_exists(self, filepath: str) -> bool:
        """检查文件是否存在"""
        return os.path.exists(filepath)
    
    def get_file_size(self, filepath: str) -> int:
        """获取文件大小(字节)"""
        if self.file_exists(filepath):
            return os.path.getsize(filepath)
        return 0
    
    def list_output_files(self, extension: str = None) -> list:
        """列出输出目录中的文件"""
        files = []
        if os.path.exists(self.output_dir):
            for filename in os.listdir(self.output_dir):
                if extension is None or filename.endswith(extension):
                    filepath = os.path.join(self.output_dir, filename)
                    files.append({
                        'filename': filename,
                        'filepath': filepath,
                        'size': os.path.getsize(filepath)
                    })
        return files

    def preprocess_audio_to_16khz(
        self,
        filepath: str,
        target_sample_rate: int = 16000,
        target_channels: int = 1,
        output_codec: str = "pcm_s16le",
        use_gpu_accel: bool = False
    ) -> Tuple[bool, str, str]:
        """
        使用FFmpeg将音频预处理为16kHz WAV格式

        Args:
            filepath: 原始音频文件路径
            target_sample_rate: 目标采样率（默认16000）
            target_channels: 目标声道数（默认1=单声道）
            output_codec: 输出编码（默认pcm_s16le=16位PCM）
            use_gpu_accel: 是否使用GPU加速（默认False）

        Returns:
            Tuple[bool, str, str]: (是否成功, 新文件路径, 错误信息)
        """
        if not os.path.exists(filepath):
            error_msg = f"文件不存在: {filepath}"
            logger.error(error_msg)
            return False, filepath, error_msg

        try:
            # 生成临时输出文件路径（先输出到临时文件，成功后替换原文件）
            temp_output = filepath + ".preprocessing.wav"

            logger.info(f"🔧 开始预处理音频: {os.path.basename(filepath)} -> 16kHz WAV")

            # 构建FFmpeg命令
            ffmpeg_cmd = [
                'ffmpeg',
                '-nostdin',  # 禁用stdin交互
                '-threads', '0',  # 自动多线程
            ]

            # 添加GPU硬件加速（如果启用且可用）
            if use_gpu_accel:
                ffmpeg_cmd.extend(['-hwaccel', 'cuda'])

            ffmpeg_cmd.extend([
                '-i', filepath,
                '-acodec', output_codec,  # 16位PCM编码
                '-ac', str(target_channels),  # 声道数
                '-ar', str(target_sample_rate),  # 采样率
                '-f', 'wav',  # WAV格式
                '-y',  # 覆盖输出文件
                temp_output
            ])

            # 执行FFmpeg转换
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                timeout=300  # 5分钟超时
            )

            if result.returncode != 0:
                error_msg = f"FFmpeg转换失败: {result.stderr.decode('utf-8', errors='ignore')}"
                logger.error(error_msg)
                # 清理临时文件
                if os.path.exists(temp_output):
                    os.remove(temp_output)
                return False, filepath, error_msg

            # 检查输出文件
            if not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
                error_msg = "FFmpeg生成的文件为空或不存在"
                logger.error(error_msg)
                if os.path.exists(temp_output):
                    os.remove(temp_output)
                return False, filepath, error_msg

            # 获取原文件和新文件大小
            original_size = os.path.getsize(filepath)
            new_size = os.path.getsize(temp_output)

            # 替换原文件
            # 先备份原文件路径（用于生成新文件名）
            original_name, original_ext = os.path.splitext(filepath)
            new_filepath = original_name + ".wav"

            # 如果原文件就是.wav，直接替换；否则生成新文件名
            if filepath.lower().endswith('.wav'):
                os.remove(filepath)
                os.rename(temp_output, filepath)
                final_filepath = filepath
            else:
                # 删除原文件，重命名临时文件
                os.remove(filepath)
                os.rename(temp_output, new_filepath)
                final_filepath = new_filepath

            logger.info(
                f"✅ 音频预处理完成: {os.path.basename(filepath)} "
                f"({original_size / 1024 / 1024:.2f}MB) -> "
                f"{os.path.basename(final_filepath)} ({new_size / 1024 / 1024:.2f}MB)"
            )

            return True, final_filepath, ""

        except subprocess.TimeoutExpired:
            error_msg = "FFmpeg处理超时（超过5分钟）"
            logger.error(error_msg)
            # 清理临时文件
            temp_output = filepath + ".preprocessing.wav"
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass
            return False, filepath, error_msg

        except Exception as e:
            error_msg = f"音频预处理失败: {str(e)}"
            logger.error(error_msg)
            import traceback
            traceback.print_exc()
            # 清理临时文件
            temp_output = filepath + ".preprocessing.wav"
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass
            return False, filepath, error_msg

