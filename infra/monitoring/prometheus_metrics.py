"""
Prometheus 指标导出模块
提供标准的 Prometheus 格式指标，便于监控系统抓取
"""

import time
import logging
import threading
from typing import Dict, List
from collections import defaultdict, deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionMetrics:
    """转写任务指标"""
    duration: float  # 耗时（秒）
    success: bool
    file_size: int  # 文件大小（字节）
    audio_duration: float  # 音频时长（秒）
    timestamp: float


class PrometheusMetrics:
    """Prometheus 指标收集器"""
    
    def __init__(self):
        # 计数器（Counter）- 只增不减
        self.counters = {
            'http_requests_total': defaultdict(int),  # {endpoint: {method: {status: count}}}
            'transcriptions_total': 0,
            'transcriptions_success_total': 0,
            'transcriptions_failed_total': 0,
            'files_uploaded_total': 0,
            'files_deleted_total': 0,
        }
        
        # 直方图（Histogram）- 用于统计分布
        self.histograms = {
            'http_request_duration_seconds': deque(maxlen=1000),  # 请求耗时
            'transcription_duration_seconds': deque(maxlen=1000),  # 转写耗时
            'transcription_processing_ratio': deque(maxlen=1000),  # 处理比例（实际耗时/音频时长）
        }
        
        # 仪表盘（Gauge）- 当前值
        self.gauges = {
            'active_transcriptions': 0,  # 正在进行的转写任务数
            'active_requests': 0,  # 正在处理的请求数
            'system_cpu_percent': 0.0,
            'system_memory_percent': 0.0,
            'system_memory_used_mb': 0.0,
            'system_threads': 0,
            'model_pool_size': 0,  # 模型池大小
            'model_pool_available': 0,  # 可用模型数
        }
        
        # 转写任务详细指标
        self.transcription_metrics: deque = deque(maxlen=1000)
        
        self._lock = threading.Lock()
    
    def record_http_request(self, endpoint: str, method: str, status_code: int, duration: float):
        """记录 HTTP 请求"""
        with self._lock:
            # 更新计数器
            if endpoint not in self.counters['http_requests_total']:
                self.counters['http_requests_total'][endpoint] = defaultdict(int)
            if method not in self.counters['http_requests_total'][endpoint]:
                self.counters['http_requests_total'][endpoint][method] = defaultdict(int)
            
            status_str = str(status_code)
            self.counters['http_requests_total'][endpoint][method][status_str] += 1
            
            # 记录耗时
            self.histograms['http_request_duration_seconds'].append(duration)
    
    def record_transcription(
        self, 
        success: bool, 
        duration: float,
        file_size: int = 0,
        audio_duration: float = 0.0
    ):
        """记录转写任务"""
        with self._lock:
            # 更新计数器
            self.counters['transcriptions_total'] += 1
            if success:
                self.counters['transcriptions_success_total'] += 1
            else:
                self.counters['transcriptions_failed_total'] += 1
            
            # 记录耗时
            self.histograms['transcription_duration_seconds'].append(duration)
            
            # 计算处理比例（实际耗时/音频时长）
            if audio_duration > 0:
                ratio = duration / audio_duration
                self.histograms['transcription_processing_ratio'].append(ratio)
            
            # 保存详细指标
            self.transcription_metrics.append(
                TranscriptionMetrics(
                    duration=duration,
                    success=success,
                    file_size=file_size,
                    audio_duration=audio_duration,
                    timestamp=time.time()
                )
            )
    
    def increment_active_transcriptions(self):
        """增加活跃转写任务数"""
        with self._lock:
            self.gauges['active_transcriptions'] += 1
    
    def decrement_active_transcriptions(self):
        """减少活跃转写任务数"""
        with self._lock:
            self.gauges['active_transcriptions'] = max(0, self.gauges['active_transcriptions'] - 1)
    
    def increment_active_requests(self):
        """增加活跃请求数"""
        with self._lock:
            self.gauges['active_requests'] += 1
    
    def decrement_active_requests(self):
        """减少活跃请求数"""
        with self._lock:
            self.gauges['active_requests'] = max(0, self.gauges['active_requests'] - 1)
    
    def record_file_upload(self):
        """记录文件上传"""
        with self._lock:
            self.counters['files_uploaded_total'] += 1
    
    def record_file_delete(self):
        """记录文件删除"""
        with self._lock:
            self.counters['files_deleted_total'] += 1
    
    def update_system_metrics(self, cpu_percent: float, memory_percent: float, 
                              memory_used_mb: float, threads: int):
        """更新系统指标"""
        with self._lock:
            self.gauges['system_cpu_percent'] = cpu_percent
            self.gauges['system_memory_percent'] = memory_percent
            self.gauges['system_memory_used_mb'] = memory_used_mb
            self.gauges['system_threads'] = threads
    
    def update_model_pool_metrics(self, pool_size: int, available: int):
        """更新模型池指标"""
        with self._lock:
            self.gauges['model_pool_size'] = pool_size
            self.gauges['model_pool_available'] = available
    
    def _calculate_histogram_buckets(self, values: deque, buckets: List[float] = None) -> Dict[str, int]:
        """计算直方图分桶"""
        if buckets is None:
            # 默认分桶：0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, +Inf
            buckets = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
        
        if not values:
            return {}
        
        bucket_counts = {str(b): 0 for b in buckets}
        bucket_counts['+Inf'] = 0
        
        for value in values:
            placed = False
            for bucket in buckets:
                if value <= bucket:
                    bucket_counts[str(bucket)] += 1
                    placed = True
                    break
            if not placed:
                bucket_counts['+Inf'] += 1
        
        return bucket_counts
    
    def _calculate_summary(self, values: deque) -> Dict[str, float]:
        """计算摘要统计（总和、计数、分位数）"""
        if not values:
            return {'sum': 0.0, 'count': 0, 'avg': 0.0}
        
        sorted_values = sorted(values)
        count = len(sorted_values)
        total = sum(sorted_values)
        
        # 计算分位数
        def percentile(data, p):
            if not data:
                return 0.0
            k = (len(data) - 1) * p
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] + c * (data[f + 1] - data[f])
            return data[f]
        
        return {
            'sum': total,
            'count': count,
            'avg': total / count,
            'min': sorted_values[0],
            'max': sorted_values[-1],
            'p50': percentile(sorted_values, 0.5),
            'p95': percentile(sorted_values, 0.95),
            'p99': percentile(sorted_values, 0.99),
        }
    
    def get_transcription_stats(self) -> Dict:
        """获取转写统计信息"""
        with self._lock:
            total = self.counters['transcriptions_total']
            success = self.counters['transcriptions_success_total']
            failed = self.counters['transcriptions_failed_total']
            
            duration_stats = self._calculate_summary(self.histograms['transcription_duration_seconds'])
            
            # 计算成功率
            success_rate = (success / total * 100) if total > 0 else 0.0
            
            # 计算平均处理比例
            ratio_stats = self._calculate_summary(self.histograms['transcription_processing_ratio'])
            
            return {
                'total': total,
                'success': success,
                'failed': failed,
                'success_rate': success_rate,
                'duration': duration_stats,
                'processing_ratio': ratio_stats,  # 实际耗时/音频时长的比例
            }
    
    def export_prometheus_format(self) -> str:
        """导出 Prometheus 格式的指标"""
        lines = []
        
        with self._lock:
            # 导出计数器
            for metric_name, counters in self.counters.items():
                if isinstance(counters, dict):
                    # 嵌套字典结构（如 http_requests_total）
                    for endpoint, methods in counters.items():
                        for method, statuses in methods.items():
                            for status, count in statuses.items():
                                lines.append(
                                    f'{metric_name}{{endpoint="{endpoint}",method="{method}",status="{status}"}} {count}'
                                )
                else:
                    # 简单计数器
                    lines.append(f'{metric_name} {counters}')
            
            # 导出仪表盘
            for metric_name, value in self.gauges.items():
                lines.append(f'{metric_name} {value}')
            
            # 导出直方图（使用 summary 格式，因为 Prometheus 的 histogram 需要更复杂的实现）
            # HTTP 请求耗时
            http_duration = self._calculate_summary(self.histograms['http_request_duration_seconds'])
            if http_duration['count'] > 0:
                lines.append(f'http_request_duration_seconds_sum {http_duration["sum"]}')
                lines.append(f'http_request_duration_seconds_count {http_duration["count"]}')
                lines.append(f'http_request_duration_seconds_avg {http_duration["avg"]}')
                lines.append(f'http_request_duration_seconds_p95 {http_duration["p95"]}')
            
            # 转写耗时
            transcription_duration = self._calculate_summary(self.histograms['transcription_duration_seconds'])
            if transcription_duration['count'] > 0:
                lines.append(f'transcription_duration_seconds_sum {transcription_duration["sum"]}')
                lines.append(f'transcription_duration_seconds_count {transcription_duration["count"]}')
                lines.append(f'transcription_duration_seconds_avg {transcription_duration["avg"]}')
                lines.append(f'transcription_duration_seconds_p95 {transcription_duration["p95"]}')
                lines.append(f'transcription_duration_seconds_p99 {transcription_duration["p99"]}')
            
            # 处理比例
            processing_ratio = self._calculate_summary(self.histograms['transcription_processing_ratio'])
            if processing_ratio['count'] > 0:
                lines.append(f'transcription_processing_ratio_sum {processing_ratio["sum"]}')
                lines.append(f'transcription_processing_ratio_count {processing_ratio["count"]}')
                lines.append(f'transcription_processing_ratio_avg {processing_ratio["avg"]}')
        
        return '\n'.join(lines) + '\n'


# 全局 Prometheus 指标实例
prometheus_metrics = PrometheusMetrics()

