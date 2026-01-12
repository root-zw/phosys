"""
Domain - 音频处理领域逻辑
负责音频格式转换等纯函数处理
"""

import os
import subprocess
import logging

logger = logging.getLogger(__name__)


class AudioProcessor:
    """音频处理器 - 纯领域逻辑,不依赖外部基础设施"""

    def __init__(self, sample_rate=16000, use_gpu_accel=True):
        self.sample_rate = sample_rate
        self.use_gpu_accel = use_gpu_accel

    def _check_audio_format(self, input_path: str) -> dict:
        """
        检查音频文件格式和参数

        Returns:
            dict: {'sample_rate': int, 'channels': int, 'codec': str, 'format': str}
                 失败时返回空字典
        """
        try:
            # 使用ffprobe获取音频信息
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'a:0',
                    '-show_entries', 'stream=codec_name,sample_rate,channels',
                    '-of', 'default=noprint_wrappers=1',
                    input_path
                ],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return {}

            # 解析输出
            info = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key] = value

            # 转换为标准格式
            return {
                'sample_rate': int(info.get('sample_rate', 0)),
                'channels': int(info.get('channels', 0)),
                'codec': info.get('codec_name', ''),
            }
        except Exception as e:
            logger.warning(f"检查音频格式失败: {e}")
            return {}

    def prepare_audio_bytes(self, input_path: str) -> tuple:
        """
        准备音频为内存字节流（优化版：检测已预处理文件）

        Args:
            input_path: 输入音频文件路径

        Returns:
            tuple: (音频字节流, 音频时长秒数) 或 (None, 0) 失败时
        """
        if not os.path.exists(input_path):
            logger.error(f"找不到输入文件: {input_path}")
            return None, 0

        try:
            # 检查文件格式
            audio_info = self._check_audio_format(input_path)

            # 如果已经是16kHz单声道PCM WAV，直接读取文件（无需转换）
            is_already_processed = (
                audio_info.get('sample_rate') == self.sample_rate and
                audio_info.get('channels') == 1 and
                audio_info.get('codec') == 'pcm_s16le' and
                input_path.lower().endswith('.wav')
            )

            if is_already_processed:
                logger.info("✅ 检测到已预处理的16kHz WAV文件，直接读取（跳过转换）")
                try:
                    # 直接读取文件到字节流
                    with open(input_path, 'rb') as f:
                        audio_bytes = f.read()

                    if not audio_bytes or len(audio_bytes) < 44:
                        logger.error("文件内容无效或过小")
                        return None, 0

                    # 计算音频时长（WAV格式，16位，单声道）
                    # WAV头部44字节，之后是PCM数据
                    data_size = len(audio_bytes) - 44
                    duration = data_size / (self.sample_rate * 2)  # 2字节/样本

                    logger.info(f"✅ 文件读取完成: {len(audio_bytes) / 1024 / 1024:.2f} MB, 时长: {duration:.2f}秒")
                    return audio_bytes, duration

                except Exception as e:
                    logger.warning(f"直接读取失败，降级使用FFmpeg转换: {e}")
                    # 继续执行FFmpeg转换

            # 使用FFmpeg转换
            logger.info("🔧 使用FFmpeg转换音频为内存字节流（GPU加速）...")

            # 构建FFmpeg命令（与demo.py一致）
            ffmpeg_cmd = [
                'ffmpeg',
                '-nostdin',  # 禁用stdin交互
                '-threads', '0',  # 自动多线程
            ]

            # 添加GPU硬件加速（如果可用）
            if self.use_gpu_accel:
                ffmpeg_cmd.extend(['-hwaccel', 'cuda'])

            ffmpeg_cmd.extend([
                '-i', input_path,
                '-acodec', 'pcm_s16le',  # 16位PCM编码
                '-ac', '1',  # 单声道
                '-ar', str(self.sample_rate),  # 采样率
                '-f', 'wav',  # WAV格式
                '-'  # 输出到stdout
            ])

            # 执行FFmpeg，捕获输出字节流
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                check=False
            )

            if result.returncode != 0:
                logger.error(f"FFmpeg转换失败: {result.stderr.decode('utf-8', errors='ignore')}")
                return None, 0

            audio_bytes = result.stdout
            if not audio_bytes or len(audio_bytes) == 0:
                logger.error("FFmpeg返回空字节流")
                return None, 0

            # 计算音频时长（WAV格式，16位，单声道）
            # WAV头部44字节，之后是PCM数据
            data_size = len(audio_bytes) - 44
            duration = data_size / (self.sample_rate * 2)  # 2字节/样本

            logger.info(f"✅ 音频转换完成: {len(audio_bytes) / 1024 / 1024:.2f} MB, 时长: {duration:.2f}秒")

            return audio_bytes, duration

        except Exception as e:
            logger.error(f"音频处理失败: {e}")
            import traceback
            traceback.print_exc()
            return None, 0

