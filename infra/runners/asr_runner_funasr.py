"""
Infra - ASR执行器（FunASR AutoModel版本）
使用FunASR的AutoModel实现ASR和说话人识别一体化
与demo.py保持一致
"""

import os
import logging
import torch
from typing import Optional, List, Dict

# 禁用FunASR的表单打印
os.environ['FUNASR_CACHE_DIR'] = os.path.expanduser('~/.cache/modelscope')
import warnings
warnings.filterwarnings('ignore')

from funasr import AutoModel

from .model_pool import ModelPool

logger = logging.getLogger(__name__)


class FunASRModelWrapper:
    """FunASR AutoModel包装器，用于池化管理"""
    
    def __init__(self, model_config: dict):
        logger.info("正在创建FunASR AutoModel实例...")
        
        # 检测设备和硬件资源（与demo.py一致）
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        ngpu = 1 if self.device == "cuda" else 0
        
        # 获取CPU核心数（限制最大值，避免超大服务器导致内存问题）
        try:
            import psutil
            ncpu = psutil.cpu_count()
        except:
            import multiprocessing
            ncpu = multiprocessing.cpu_count()
        
        # ⚠️ 限制CPU核心数，避免在大型服务器上分配过多内存
        # FunASR每个核心会分配一定内存，112核可能导致OOM
        ncpu = min(ncpu, 16)  # 最多使用16个核心
        
        logger.info(f"使用设备: {self.device}, GPU数: {ngpu}, CPU核心数: {ncpu}")
        
        # 创建AutoModel（集成ASR、VAD、PUNC、说话人识别）
        # 参数与demo.py完全一致
        self.model = AutoModel(
            model=model_config['asr']['model_id'],
            model_revision=model_config['asr']['model_revision'],
            vad_model=model_config['vad']['model_id'],
            vad_model_revision=model_config['vad']['model_revision'],
            punc_model=model_config['punc']['model_id'],
            punc_model_revision=model_config['punc']['model_revision'],
            spk_model=model_config['diarization']['model_id'],  # 说话人识别模型
            spk_model_revision=model_config['diarization']['revision'],
            ngpu=ngpu,  # GPU数量
            ncpu=ncpu,  # CPU核心数
            device=self.device,
            disable_pbar=True,
            disable_log=True,  # 禁用日志，防止打印表单
            disable_update=True
        )
        
        logger.info("FunASR AutoModel实例创建成功")
    
    def transcribe_with_speaker(self, audio_input, hotword: str = '') -> Dict:
        """
        执行ASR和说话人识别（一体化）
        
        Args:
            audio_input: 音频输入（字节流或文件路径）
            hotword: 热词
            
        Returns:
            包含文本和说话人信息的结果
        """
        try:
            # 准备generate参数
            generate_kwargs = {
                'input': audio_input,
                'use_itn': True,
                'batch_size_s': 60,
                'is_final': True,
                'sentence_timestamp': True
            }
            
            # 只有当hotword非空时才传递（避免空字符串被解析为['<s>']）
            if hotword and hotword.strip():
                generate_kwargs['hotword'] = hotword
            
            # 调用FunASR生成
            res = self.model.generate(**generate_kwargs)
            
            if not res or len(res) == 0:
                return None
            
            return res[0]  # 返回第一个结果
            
        except Exception as e:
            logger.error(f"FunASR转写失败: {e}")
            raise
    
    def cleanup(self):
        """清理模型资源"""
        try:
            if hasattr(self, 'model'):
                del self.model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.error(f"清理FunASR模型资源失败: {e}")


class ASRRunner:
    """ASR执行器 - 使用FunASR AutoModel（支持模型池）"""
    
    def __init__(self, model_config: dict, use_pool: bool = True, pool_size: int = 3):
        """
        初始化ASR运行器（FunASR方式）
        
        Args:
            model_config: 模型配置
            use_pool: 是否使用模型池（生产环境推荐开启）
            pool_size: 模型池大小
        """
        self.model_config = model_config
        self.use_pool = use_pool
        
        # 加载时间戳校正配置
        try:
            from config import TIMESTAMP_CORRECTION_CONFIG
            self.ts_correction_enabled = TIMESTAMP_CORRECTION_CONFIG.get('enabled', False)
            self.ts_correction_factor = TIMESTAMP_CORRECTION_CONFIG.get('correction_factor', 1.0)
            if self.ts_correction_enabled and self.ts_correction_factor != 1.0:
                logger.info(f"📐 时间戳校正已启用，校正因子: {self.ts_correction_factor}")
        except ImportError:
            self.ts_correction_enabled = False
            self.ts_correction_factor = 1.0
        
        if use_pool:
            logger.info(f"使用FunASR AutoModel + 模型池模式，池大小: {pool_size}")
            # 创建模型工厂函数
            def funasr_factory():
                return FunASRModelWrapper(model_config)
            
            # 创建模型池
            self.model_pool = ModelPool(
                model_factory=funasr_factory,
                initial_size=min(pool_size, 2),  # 初始创建较少实例
                max_size=pool_size,
                min_size=1,
                max_idle_time=600,  # 10分钟
                health_check_interval=300  # 5分钟，降低日志频率
            )
            self.model = None
        else:
            logger.info("使用FunASR AutoModel单例模式")
            self.model_pool = None
            self.model = FunASRModelWrapper(model_config)
    
    def transcribe_with_speaker(self, audio_input, hotword: str = '') -> Optional[List[Dict]]:
        """
        执行语音识别和说话人识别（FunASR一体化方式）
        
        Args:
            audio_input: 音频输入（字节流bytes或文件路径str）
            hotword: 热词
            
        Returns:
            List[Dict]: 转写结果列表，每项包含：
                - text: 文本内容
                - start: 开始时间(毫秒)
                - end: 结束时间(毫秒)
                - spk: 说话人ID
        """
        try:
            input_type = "字节流" if isinstance(audio_input, bytes) else "文件"
            logger.info(f"🎙️ 开始FunASR一体化转写 (输入类型: {input_type})")
            if hotword and hotword.strip():
                logger.info(f"📝 使用热词: {hotword}")
            else:
                logger.info("📝 无热词")
            
            # 根据模式选择执行方式
            if self.use_pool and self.model_pool:
                # 使用模型池
                logger.info("⏳ 正在从模型池获取模型实例...")
                with self.model_pool.acquire(timeout=60.0) as model:
                    logger.info("✅ 模型获取成功，开始转录...")
                    result = model.transcribe_with_speaker(audio_input, hotword)
            else:
                # 使用单例模型
                logger.info("🔄 使用单例模型进行转录...")
                result = self.model.transcribe_with_speaker(audio_input, hotword)
            
            if not result:
                logger.warning("⚠️ FunASR返回空结果")
                return None
            
            # 解析FunASR结果格式
            transcript_list = []
            
            if 'sentence_info' in result:
                # 有说话人信息的结果
                sentence_count = len(result['sentence_info'])
                
                # 创建说话人ID映射表（按出现顺序重新编号）
                speaker_id_map = {}  # 原始spk -> 连续编号
                next_speaker_number = 1
                
                # 统计时间戳使用情况
                ts_stats = {'native': 0, 'mapped': 0, 'interpolated': 0}
                
                for sentence in result['sentence_info']:
                    original_spk = sentence.get('spk', 0)
                    
                    # 第一次遇到这个说话人时，分配新的连续编号
                    if original_spk not in speaker_id_map:
                        speaker_id_map[original_spk] = next_speaker_number
                        next_speaker_number += 1
                    
                    # 使用映射后的连续编号
                    speaker_number = speaker_id_map[original_spk]
                    
                    text = sentence.get('text', '')
                    start_time = sentence.get('start', 0) / 1000.0  # 转为秒
                    end_time = sentence.get('end', 0) / 1000.0
                    
                    # 应用时间戳校正
                    if self.ts_correction_enabled:
                        start_time *= self.ts_correction_factor
                        end_time *= self.ts_correction_factor
                    
                    # 提取词级别时间戳（校正因子会在内部方法中应用）
                    words, ts_method = self._extract_word_timestamps_with_stats(sentence, start_time, end_time, text)
                    ts_stats[ts_method] = ts_stats.get(ts_method, 0) + 1
                    
                    transcript_list.append({
                        'text': text,
                        'start_time': start_time,
                        'end_time': end_time,
                        'speaker': f"发言人{speaker_number}",  # 使用连续编号
                        'words': words  # 词级别时间戳
                    })
                
                # 输出时间戳统计
                logger.info(f"✅ 识别完成: 共{sentence_count}个句子, {len(speaker_id_map)}位说话人")
                logger.info(f"📊 时间戳来源: 原生={ts_stats.get('native', 0)}, 映射={ts_stats.get('mapped', 0)}, 插值={ts_stats.get('interpolated', 0)}")
            elif 'text' in result:
                # 只有文本，没有说话人信息
                logger.warning("⚠️ 结果中无说话人信息，作为单人处理")
                text = result['text']
                words = self._extract_word_timestamps(None, 0, 0, text)
                transcript_list.append({
                    'text': text,
                    'start_time': 0,
                    'end_time': 0,
                    'speaker': '发言人1',  # 单人时默认为发言人1
                    'words': words
                })
            
            return transcript_list
            
        except Exception as e:
            logger.error(f"❌ FunASR转写失败: {e}")
            raise
    
    def _extract_word_timestamps_with_stats(self, sentence: Dict, start_time: float, end_time: float, text: str) -> tuple:
        """
        提取词级别时间戳，并返回使用的方法
        
        Returns:
            tuple: (词列表, 方法名称) - 方法名称为 'native', 'mapped', 'interpolated'
        """
        words, method = self._extract_word_timestamps_internal(sentence, start_time, end_time, text)
        return words, method
    
    def _extract_word_timestamps(self, sentence: Dict, start_time: float, end_time: float, text: str) -> List[Dict]:
        """提取词级别时间戳（兼容旧接口）"""
        words, _ = self._extract_word_timestamps_internal(sentence, start_time, end_time, text)
        return words
    
    def _extract_word_timestamps_internal(self, sentence: Dict, start_time: float, end_time: float, text: str) -> tuple:
        """
        提取词级别时间戳（智能版：超长句子按句号拆分子句，每个子句独立计算时间戳）
        
        Returns:
            tuple: (词列表, 方法名称)
        """
        import jieba
        import re
        
        words = []
        
        # 获取时间戳校正因子
        ts_factor = self.ts_correction_factor if self.ts_correction_enabled else 1.0
        
        # 方法1: 尝试从FunASR结果中提取 timestamp 字段（字级别时间戳）
        if sentence and 'timestamp' in sentence:
            timestamp_list = sentence.get('timestamp', [])
            text_chars = list(text) if text else []
            
            if timestamp_list and len(timestamp_list) == len(text_chars):
                # 时间戳数量与字符数量匹配，直接使用
                for i, (char, ts) in enumerate(zip(text_chars, timestamp_list)):
                    if isinstance(ts, (list, tuple)) and len(ts) >= 2:
                        char_start = (ts[0] / 1000.0) * ts_factor
                        char_end = (ts[1] / 1000.0) * ts_factor
                        words.append({'text': char, 'start': char_start, 'end': char_end})
                
                if words:
                    return words, 'native'
                    
            elif timestamp_list:
                # FunASR的timestamp不包含标点符号，需要映射
                PUNCTUATION_SET = set('，。！？、；：""''（）【】《》—…·,.!?;:\'"()[]<>-–—')
                
                char_info = []
                ts_idx = 0
                for char in text_chars:
                    is_punct = char in PUNCTUATION_SET
                    if is_punct:
                        char_info.append((char, True, -1))
                    else:
                        char_info.append((char, False, ts_idx))
                        ts_idx += 1
                
                non_punct_count = sum(1 for c in char_info if not c[1])
                
                if non_punct_count == len(timestamp_list):
                    for i, (char, is_punct, ts_idx) in enumerate(char_info):
                        if is_punct:
                            if words:
                                punct_time = words[-1]['end']
                                words.append({'text': char, 'start': punct_time, 'end': punct_time})
                        else:
                            ts = timestamp_list[ts_idx]
                            if isinstance(ts, (list, tuple)) and len(ts) >= 2:
                                words.append({'text': char, 'start': (ts[0] / 1000.0) * ts_factor, 'end': (ts[1] / 1000.0) * ts_factor})
                    
                    if words:
                        return words, 'native'
        
        # 方法1b: 尝试从 words 字段提取
        if sentence and 'words' in sentence:
            for word_info in sentence['words']:
                word_text = word_info.get('text', '')
                word_start = (word_info.get('start', 0) / 1000.0) * ts_factor
                word_end = (word_info.get('end', 0) / 1000.0) * ts_factor
                if word_text:
                    words.append({'text': word_text, 'start': word_start, 'end': word_end})
            if words:
                return words, 'native'
        
        # 方法2: 分词+timestamp映射
        if sentence and 'timestamp' in sentence:
            timestamp_list = sentence.get('timestamp', [])
            if timestamp_list and text:
                words = self._map_timestamps_to_words(text, timestamp_list, ts_factor)
                if words:
                    return words, 'mapped'
        
        # 方法3: 智能分词+子句插值（降级方案）
        if not text or not text.strip():
            return words, 'interpolated'
        
        try:
            # 中英文标点符号集合
            PUNCTUATION_SET = set('，。！？、；：""''（）【】《》—…·,.!?;:\'"()[]<>-–—')
            # 句子结束标点（用于拆分子句）
            SENTENCE_END_PUNCT = set('。！？.!?')
            
            def is_punctuation(word: str) -> bool:
                """判断是否为纯标点符号"""
                return all(c in PUNCTUATION_SET or c.isspace() for c in word)
            
            def is_sentence_end(word: str) -> bool:
                """判断是否为句子结束标点"""
                return word in SENTENCE_END_PUNCT
            
            def estimate_syllables(word: str) -> int:
                """估算词的音节数"""
                if is_punctuation(word):
                    return 0
                chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', word))
                english_part = re.sub(r'[\u4e00-\u9fff\d]', '', word)
                english_syllables = 0
                if english_part.strip():
                    vowel_groups = re.findall(r'[aeiouAEIOU]+', english_part)
                    english_syllables = max(1, len(vowel_groups)) if re.search(r'[a-zA-Z]', english_part) else 0
                digits = len(re.findall(r'\d', word))
                total = chinese_chars + english_syllables + digits
                return max(1, total) if total > 0 else 1
            
            def process_clause(word_list: list, clause_start: float, clause_end: float) -> list:
                """处理单个子句，返回带时间戳的词列表"""
                if not word_list:
                    return []
                
                clause_words = []
                duration = clause_end - clause_start
                if duration <= 0:
                    duration = max(len(word_list), 1) * 0.2
                    clause_end = clause_start + duration
                
                syllable_counts = [estimate_syllables(w) for w in word_list]
                total_syllables = sum(syllable_counts)
                
                if total_syllables == 0:
                    total_syllables = max(sum(1 for w in word_list if not is_punctuation(w)), 1)
                    syllable_counts = [1 if not is_punctuation(w) else 0 for w in word_list]
                
                current_time = clause_start
                for word, syllables in zip(word_list, syllable_counts):
                    if syllables == 0:
                        clause_words.append({'text': word, 'start': current_time, 'end': current_time})
                    else:
                        word_duration = (syllables / total_syllables) * duration
                        clause_words.append({'text': word, 'start': current_time, 'end': current_time + word_duration})
                        current_time += word_duration
                
                # 确保最后一个非标点词的结束时间等于子句结束时间
                for w in reversed(clause_words):
                    if w['start'] != w['end']:
                        w['end'] = clause_end
                        break
                
                return clause_words
            
            # 使用jieba进行中文分词
            word_segments = list(jieba.cut(text, cut_all=False))
            word_list = [w for w in word_segments if w]
            
            if not word_list:
                return words, 'interpolated'
            
            duration = end_time - start_time
            if duration <= 0:
                non_punct_count = sum(1 for w in word_list if not is_punctuation(w))
                duration = max(non_punct_count, 1) * 0.3
                end_time = start_time + duration
            
            # ===== 核心改进：按句号拆分子句 =====
            # 只有当句子较长时才拆分（超过20秒或超过50个词）
            should_split = duration > 20 or len(word_list) > 50
            
            if should_split:
                # 拆分成多个子句
                clauses = []  # 每个元素是 (word_list, syllable_count)
                current_clause = []
                current_syllables = 0
                
                for word in word_list:
                    current_clause.append(word)
                    current_syllables += estimate_syllables(word)
                    
                    if is_sentence_end(word) and len(current_clause) > 1:
                        # 遇到句号，结束当前子句
                        clauses.append((current_clause, current_syllables))
                        current_clause = []
                        current_syllables = 0
                
                # 处理最后一个子句（可能没有句号结尾）
                if current_clause:
                    clauses.append((current_clause, current_syllables))
                
                # 按子句音节数比例分配时间
                total_syllables = sum(c[1] for c in clauses)
                if total_syllables == 0:
                    total_syllables = len(clauses)
                
                current_time = start_time
                for clause_words, clause_syllables in clauses:
                    # 计算子句时长
                    if clause_syllables == 0:
                        clause_syllables = max(sum(1 for w in clause_words if not is_punctuation(w)), 1)
                    clause_duration = (clause_syllables / total_syllables) * duration
                    clause_end = current_time + clause_duration
                    
                    # 处理子句
                    clause_result = process_clause(clause_words, current_time, clause_end)
                    words.extend(clause_result)
                    
                    current_time = clause_end
                
                # 确保最后一个词的结束时间等于句子结束时间
                if words:
                    for w in reversed(words):
                        if w['start'] != w['end']:
                            w['end'] = end_time
                            break
                
                logger.debug(f"超长句子拆分: {len(clauses)} 个子句, {len(words)} 个词")
            else:
                # 短句子直接处理
                words = process_clause(word_list, start_time, end_time)
                logger.debug(f"使用分词+音节插值: {len(words)} 个词")
            
            # 验证文本完整性
            reconstructed_text = ''.join([w['text'] for w in words])
            if reconstructed_text.replace(' ', '') != text.replace(' ', ''):
                logger.warning(f"⚠️ 分词后文本不匹配，原文本长度: {len(text)}, 重建长度: {len(reconstructed_text)}")
            
        except Exception as e:
            logger.warning(f"⚠️ 词级别时间戳提取失败: {e}，将使用句子级别时间戳")
            if text.strip():
                words.append({
                    'text': text.strip(),
                    'start': start_time,
                    'end': end_time
                })
        
        return words, 'interpolated'
    
    def _map_timestamps_to_words(self, text: str, timestamp_list: List, ts_factor: float = 1.0) -> List[Dict]:
        """
        将FunASR的字级别timestamp映射到词级别
        FunASR的timestamp不包含标点符号，需要特殊处理
        
        Args:
            text: 文本内容
            timestamp_list: FunASR返回的timestamp列表 [[start, end], ...]
            ts_factor: 时间戳校正因子
            
        Returns:
            词级别时间戳列表
        """
        import jieba
        
        words = []
        PUNCTUATION_SET = set('，。！？、；：""''（）【】《》—…·,.!?;:\'"()[]<>-–—')
        
        try:
            # 使用jieba分词
            word_segments = list(jieba.cut(text, cut_all=False))
            word_list = [w for w in word_segments if w]
            
            # 为每个词计算时间戳
            # timestamp只对应非标点字符，所以需要跟踪ts_index
            ts_index = 0
            
            for word in word_list:
                # 检查这个词是否是纯标点
                is_pure_punct = all(c in PUNCTUATION_SET for c in word)
                
                if is_pure_punct:
                    # 标点使用前一个词的结束时间
                    if words:
                        punct_time = words[-1]['end']
                        words.append({
                            'text': word,
                            'start': punct_time,
                            'end': punct_time
                        })
                else:
                    # 计算这个词中的非标点字符数
                    non_punct_chars = [c for c in word if c not in PUNCTUATION_SET]
                    num_non_punct = len(non_punct_chars)
                    
                    if ts_index + num_non_punct > len(timestamp_list):
                        # 时间戳不够了，跳出
                        break
                    
                    # 获取该词的起始和结束时间
                    word_start_ts = timestamp_list[ts_index]
                    word_end_ts = timestamp_list[ts_index + num_non_punct - 1]
                    
                    if isinstance(word_start_ts, (list, tuple)) and isinstance(word_end_ts, (list, tuple)):
                        word_start = (word_start_ts[0] / 1000.0) * ts_factor  # 毫秒转秒，并应用校正
                        word_end = (word_end_ts[1] / 1000.0) * ts_factor
                        
                        words.append({
                            'text': word,
                            'start': word_start,
                            'end': word_end
                        })
                    
                    ts_index += num_non_punct
            
            return words
            
        except Exception as e:
            logger.warning(f"⚠️ timestamp映射异常: {e}")
            return words
    
    def get_pool_stats(self) -> Optional[dict]:
        """获取模型池统计信息"""
        if self.use_pool and self.model_pool:
            return self.model_pool.get_stats()
        return None
    
    def shutdown(self):
        """关闭运行器，清理资源"""
        if self.use_pool and self.model_pool:
            self.model_pool.shutdown()
        elif self.model:
            self.model.cleanup()

