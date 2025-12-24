"""监控模块"""

# 延迟导入 metrics，避免 psutil 依赖问题
try:
    from .metrics import metrics_collector, MetricsCollector
    __all__ = ['metrics_collector', 'MetricsCollector']
except ImportError as e:
    # 如果 metrics 模块导入失败（例如缺少 psutil），不影响其他模块
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"监控模块 metrics 导入失败: {e}，某些监控功能可能不可用")
    __all__ = []

# 导入 Prometheus 指标
try:
    from .prometheus_metrics import prometheus_metrics, PrometheusMetrics
    if 'prometheus_metrics' not in __all__:
        __all__.extend(['prometheus_metrics', 'PrometheusMetrics'])
except ImportError as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Prometheus 指标模块导入失败: {e}")

