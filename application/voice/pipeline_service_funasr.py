import os
import logging
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional, Callable

from domain.voice.audio_processor import AudioProcessor
from domain.voice.text_processor import TextProcessor
from domain.voice.diarization import DiarizationProcessor
from infra.audio_io.storage import AudioStorage
from infra.runners.asr_runner_funasr import ASRRunner
from config import MODEL_CONFIG

logger = logging.getLogger(__name__)

# 导入 Dify 报警模块
# 注意：只导入 log_error_alarm，SUCCESS 报警由 VoiceGateway 层统一发送
try:
    from infra.monitoring.dify_webhook_sender import log_error_alarm
    DIFY_ALARM_ENABLED = True
    logger.info("✅ Dify 报警模块已加载")
except ImportError as e:
    DIFY_ALARM_ENABLED = False
    logger.warning(f"⚠️ Dify 报警模块未找到，报警功能已禁用: {e}")

class SmartProgressTracker:
    """
    智能进度追踪器
    功能：后台自动平滑推进进度，任务完成时支持极速追赶，主线程无需sleep等待
    """
    
    def __init__(self, callback: Callable):
        self.callback = callback
        self._current_progress = 0
        self._target_end = 0
        self._stop_event = threading.Event()
        self._thread = None
        self._step_name = ""
        self._step_msg = ""
        self._lock = threading.Lock()

    def start_phase(self, step_name: str, message: str, start_pct: int, end_pct: int, estimated_time: float):
        """
        开始一个新阶段：进度会在 estimated_time 内从 start_pct 平滑走到 end_pct
        """
        self.stop() # 停止旧线程
        
        self._step_name = step_name
        self._step_msg = message
        self._stop_event.clear()
        
        with self._lock:
            self._current_progress = max(self._current_progress, start_pct)
            self._target_end = end_pct
            
        # 立即刷新一次初始状态
        self._emit_progress(self._current_progress)

        self._thread = threading.Thread(
            target=self._background_ticker,
            args=(self._current_progress, end_pct, estimated_time),
            daemon=True
        )
        self._thread.start()

    def complete_phase(self):
        """
        完成当前阶段：
        如果当前进度还没跑完，会以极快速度(不阻塞业务)补齐到目标值
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.2)
            
        # 快速追赶逻辑 (Fast Forward)
        with self._lock:
            start = self._current_progress
            end = self._target_end
            
        if start < end:
            # 极速循环补齐进度，保证视觉连续性但几乎不耗时
            for p in range(start + 1, end + 1):
                self._emit_progress(p)
                time.sleep(0.002) # 2ms 极速间隔
            
            with self._lock:
                self._current_progress = end

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _background_ticker(self, start, end, duration):
        """后台线程：平滑推进"""
        if end <= start: return
        
        total_steps = end - start
        if duration <= 0: duration = 0.5
        
        # 计算每走1%的时间，限制在合理区间 (0.05s - 0.5s)
        interval = max(0.05, min(duration / total_steps, 0.5))

        current = start
        while not self._stop_event.is_set() and current < end:
            time.sleep(interval)
            if self._stop_event.is_set():
                break
                
            current += 1
            with self._lock:
                self._current_progress = current
            self._emit_progress(current)

    def _emit_progress(self, progress):
        if self.callback:
            self.callback(self._step_name, progress, self._step_msg)


class PipelineService:
    """流水线服务 - FunASR一体化转写 (优化版)"""
    
    def __init__(self, 
                 audio_storage: AudioStorage,
                 asr_runner: ASRRunner,
                 audio_config: dict):
        
        self.storage = audio_storage
        self.asr_runner = asr_runner
        
        self.audio_processor = AudioProcessor(
            sample_rate=audio_config.get('sample_rate', 16000),
            use_gpu_accel=True
        )
        self.text_processor = TextProcessor()
        self.diarization_processor = DiarizationProcessor()
    
    def set_callback(self, callback: Callable):
        """
        ⚠️ 已废弃：此方法会导致多任务共享状态冲突
        请直接在 execute_transcription 中传递 callback 参数
        """
        import warnings
        warnings.warn(
            "set_callback() 已废弃，请使用 execute_transcription(callback=...) 参数",
            DeprecationWarning,
            stacklevel=2
        )
        # 保留此方法仅用于向后兼容，但不再使用
    
    def _update_status(self, callback: Optional[Callable], step: str, progress: int, message: str = "", data: Dict = None):
        """发送状态更新"""
        # 终端显示
        bar_len = 20
        filled = int(progress / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r[{progress:3d}%] {bar} | {step}: {message}", end='', flush=True)
        if progress >= 100: print() # 换行

        # WebSocket回调
        if callback:
            callback(step, progress, message, data)
    
    def execute_transcription(self, input_audio_path: str, 
                            hotword: str = '', 
                            language: str = 'zh',
                            instance_id: str = None,
                            cancellation_flag: Optional[Callable] = None,
                            callback: Optional[Callable] = None) -> tuple:
        
        if not instance_id:
            import uuid
            instance_id = str(uuid.uuid4())[:8]
        
        def check_cancelled():
            if cancellation_flag and cancellation_flag():
                raise InterruptedError("任务已取消")

        # ✅ 修复：为每个任务创建独立的 tracker，避免多任务共享状态冲突
        # 创建包装函数，将 callback 传递给 _update_status
        def update_status_wrapper(step: str, progress: int, message: str = "", data: Dict = None):
            self._update_status(callback, step, progress, message, data)
        
        # 为当前任务创建独立的 tracker
        tracker = SmartProgressTracker(update_status_wrapper)

        try:
            check_cancelled()
            self._update_status(callback, "开始", 0, "初始化转写任务...")
            start_time = datetime.now()
            audio_duration = 0.0  # 音频时长，用于计算处理比例
            
            # 1. 准备音频 (0-10%)
            tracker.start_phase("准备音频", "正在处理音频文件...", 0, 10, estimated_time=2.0)
            
            audio_bytes, duration = self.audio_processor.prepare_audio_bytes(input_audio_path)
            audio_duration = duration  # 保存音频时长
            if audio_bytes is None:
                tracker.stop()
                # --- 发送 ERROR 报警：音频准备失败 ---
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=instance_id,
                        module="AudioProcessor",
                        message="音频准备失败，无法读取或处理音频文件",
                        exception=None
                    )
                return None, None, None
                
            tracker.complete_phase() # 瞬间补齐到 10%

            # 2. 准备识别 (10-30%)
            tracker.start_phase("准备识别", "加载模型与资源...", 10, 30, estimated_time=1.0)
            time.sleep(0.1) # 模拟极短耗时
            tracker.complete_phase() # 瞬间补齐到 30%

            # 3. 核心转写 (30-80%)
            # 估算时间：至少5秒，或者音频时长的15%
            est_time = max(duration * 0.15, 5.0)
            tracker.start_phase("语音转录", "正在进行语音识别...", 30, 80, estimated_time=est_time)
            
            # 处理热词：验证、去重、扩展
            processed_hotword = self.text_processor.process_hotword(hotword) if hotword else ''
            if processed_hotword:
                logger.info(f"📝 使用热词: {processed_hotword}")
            
            transcript_list = self.asr_runner.transcribe_with_speaker(audio_bytes, hotword=processed_hotword)
            
            check_cancelled()
            if not transcript_list:
                tracker.stop()
                # --- 发送 ERROR 报警：转写结果为空 ---
                if DIFY_ALARM_ENABLED:
                    log_error_alarm(
                        task_id=instance_id,
                        module="ASR_Core",
                        message="语音转写返回空结果，可能是音频质量问题或模型异常",
                        exception=None
                    )
                return None, None, None
                
            tracker.complete_phase() # 业务完成，瞬间补齐到 80%

            # 4. 合并片段 (80-90%)
            tracker.start_phase("合并片段", f"识别完成，正在整理片段...", 80, 90, estimated_time=1.0)
            merged_transcript = self.diarization_processor.merge_consecutive_segments(transcript_list)
            tracker.complete_phase() # 瞬间补齐到 90%

            # 5. 文本处理 (90-95%)
            tracker.start_phase("文本处理", "正在优化文本内容...", 90, 95, estimated_time=0.5)
            for entry in merged_transcript:
                if 'text' in entry:
                    original_text = entry['text']
                    fixed_text = self.text_processor.fix_transcript_text(original_text)
                    
                    # 如果文本被修改（例如去掉了末尾逗号），需要同步更新words数组
                    if fixed_text != original_text and 'words' in entry and entry['words']:
                        # 重新生成words数组，确保与修复后的文本一致
                        entry['words'] = self.asr_runner._extract_word_timestamps(
                            None, 
                            entry.get('start_time', 0), 
                            entry.get('end_time', 0), 
                            fixed_text
                        )
                    
                    entry['text'] = fixed_text
            tracker.complete_phase() # 瞬间补齐到 95%

            # =================================================
            # 6. 清理与完成 (95-100%) - 关键修改部分
            # =================================================
            # 注意：这里 end_pct 设为 99，而不是 100
            # 我们把 100% 留给最后一步显式调用，确保此时能够计算出准确的耗时
            tracker.start_phase("完成", "正在清理临时文件...", 95, 99, estimated_time=0.5)
            
            self.storage.cleanup_temp_files(instance_id)
            
            # 追赶到 99% (此时 message 还是 "正在清理...")
            tracker.complete_phase()
            
            # --- 计算最终耗时并发送 100% ---
            end_time = datetime.now()
            elapsed = (end_time - start_time).total_seconds()  # 使用 total_seconds() 获取更精确的耗时
            
            # 计算转写字数
            total_chars = sum(len(entry.get('text', '')) for entry in merged_transcript) if merged_transcript else 0
            segment_count = len(merged_transcript) if merged_transcript else 0
            
            final_message = f"转写完成，耗时{elapsed:.1f}秒"
            
            # 显式发送 100% 状态，带上耗时信息
            # 这样前端收到的 {progress: 100} 消息中就会包含准确的耗时
            self._update_status(callback, "完成", 100, final_message)
            
            logger.info(f"✅ {final_message}")
            
            # 注意：SUCCESS 报警由 VoiceGateway 层统一发送，避免重复
            # PipelineService 只负责 ERROR 报警
            
            # 停止追踪器（虽已完成，但也确保清理资源）
            tracker.stop()
            
            return merged_transcript, None, None

        except InterruptedError:
            tracker.stop()
            logger.info(f"任务 {instance_id} 已取消")
            self.storage.cleanup_temp_files(instance_id)
            raise
        except Exception as e:
            tracker.stop()
            logger.error(f"转写流程异常: {e}")
            import traceback
            traceback.print_exc()
            
            # --- 发送 ERROR 报警到 Dify ---
            if DIFY_ALARM_ENABLED:
                log_error_alarm(
                    task_id=instance_id,
                    module="PipelineService",
                    message=f"转写流程异常: {str(e)}",
                    exception=e
                )
            
            self.storage.cleanup_temp_files(instance_id)
            return None, None, None