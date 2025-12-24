"""
Domain - 文本处理领域逻辑
负责热词处理、智能后处理、文本清理等纯业务规则
"""

import re
import os
import json
from typing import List, Dict, Set, Optional
from pathlib import Path


class TextProcessor:
    """文本处理器 - 处理热词、智能后处理等"""
    
    # 热词配置常量
    MAX_HOTWORD_LENGTH = 50  # 单个热词最大长度
    MAX_HOTWORDS_COUNT = 100  # 最大热词数量
    MIN_HOTWORD_LENGTH = 1  # 单个热词最小长度
    
    def __init__(self, hotword_synonym_config_path: Optional[str] = None):
        """
        初始化文本处理器
        
        Args:
            hotword_synonym_config_path: 热词同义词配置文件路径（可选）
                                        如果提供，将从该文件加载自定义同义词映射
        """
        self.hotword_synonym_map = self._load_hotword_synonyms(hotword_synonym_config_path)
    
    def process_hotword(self, hotword: str) -> str:
        """
        智能处理热词,提升识别效果
        
        Args:
            hotword: 原始热词字符串（空格分隔）
            
        Returns:
            处理后的热词字符串（空格分隔）
        """
        if not hotword or not hotword.strip():
            return ''
        
        # 1. 清理和分割热词
        hotwords = self._parse_hotwords(hotword)
        
        # 2. 验证热词
        valid_hotwords = self._validate_hotwords(hotwords)
        
        # 3. 去重（保持顺序）
        unique_hotwords = list(dict.fromkeys(valid_hotwords))
        
        # 4. 扩展热词（如果配置了同义词映射）
        expanded_hotwords = self._expand_hotwords(unique_hotwords)
        
        # 5. 限制数量（避免过多热词影响性能）
        if len(expanded_hotwords) > self.MAX_HOTWORDS_COUNT:
            expanded_hotwords = expanded_hotwords[:self.MAX_HOTWORDS_COUNT]
        
        return ' '.join(expanded_hotwords)
    
    def _load_hotword_synonyms(self, config_path: Optional[str] = None) -> Dict[str, List[str]]:
        """
        加载热词同义词映射配置
        
        Args:
            config_path: 配置文件路径，如果为None则返回空字典
            
        Returns:
            同义词映射字典，格式: {word: [synonym1, synonym2, ...]}
        """
        if not config_path:
            return {}
        
        try:
            config_file = Path(config_path)
            if config_file.exists() and config_file.is_file():
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    else:
                        return {}
        except Exception as e:
            # 静默失败，不影响主功能
            pass
        
        return {}
    
    def _parse_hotwords(self, hotword: str) -> List[str]:
        """
        解析热词字符串，支持多种分隔符
        
        Args:
            hotword: 热词字符串
            
        Returns:
            热词列表
        """
        if not hotword:
            return []
        
        # 支持空格、逗号、分号、换行符作为分隔符
        import re
        # 先替换各种分隔符为空格
        normalized = re.sub(r'[,\n;，；、]+', ' ', hotword)
        # 分割并清理
        hotwords = [word.strip() for word in normalized.split() if word.strip()]
        
        return hotwords
    
    def _validate_hotwords(self, hotwords: List[str]) -> List[str]:
        """
        验证热词的有效性
        
        Args:
            hotwords: 热词列表
            
        Returns:
            有效的热词列表
        """
        valid_hotwords = []
        
        for word in hotwords:
            # 检查长度
            if len(word) < self.MIN_HOTWORD_LENGTH:
                continue
            if len(word) > self.MAX_HOTWORD_LENGTH:
                # 截断过长的热词
                word = word[:self.MAX_HOTWORD_LENGTH]
            
            # 检查是否包含无效字符（只允许中文、英文、数字、常见标点）
            if not self._is_valid_hotword(word):
                continue
            
            valid_hotwords.append(word)
        
        return valid_hotwords
    
    def _is_valid_hotword(self, word: str) -> bool:
        """
        检查热词是否有效
        
        Args:
            word: 热词
            
        Returns:
            是否有效
        """
        if not word:
            return False
        
        # 允许的字符：中文、英文、数字、常见标点（-、_、.）
        import re
        pattern = r'^[\u4e00-\u9fff\w\s\-_\.]+$'
        return bool(re.match(pattern, word))
    
    def format_hotword_for_display(self, hotword: str) -> str:
        """
        格式化热词用于显示
        
        Args:
            hotword: 热词字符串
            
        Returns:
            格式化后的热词字符串
        """
        if not hotword:
            return ''
        
        hotwords = self._parse_hotwords(hotword)
        return ' '.join(hotwords)
    
    def get_hotword_statistics(self, hotword: str) -> Dict:
        """
        获取热词统计信息
        
        Args:
            hotword: 热词字符串
            
        Returns:
            统计信息字典
        """
        if not hotword:
            return {
                'count': 0,
                'total_length': 0,
                'avg_length': 0,
                'words': []
            }
        
        hotwords = self._parse_hotwords(hotword)
        valid_hotwords = self._validate_hotwords(hotwords)
        
        total_length = sum(len(word) for word in valid_hotwords)
        avg_length = total_length / len(valid_hotwords) if valid_hotwords else 0
        
        return {
            'count': len(valid_hotwords),
            'total_length': total_length,
            'avg_length': round(avg_length, 2),
            'words': valid_hotwords
        }
    
    def _expand_hotwords(self, hotwords: List[str]) -> List[str]:
        """
        扩展热词,添加相关词汇和变体（基于配置的同义词映射）
        
        Args:
            hotwords: 原始热词列表
            
        Returns:
            扩展后的热词列表
        """
        expanded = set(hotwords)
        
        # 如果配置了同义词映射，使用配置的映射
        if self.hotword_synonym_map:
            for word in hotwords:
                # 添加配置的同义词
                if word in self.hotword_synonym_map:
                    synonyms = self.hotword_synonym_map[word]
                    if isinstance(synonyms, list):
                        expanded.update(synonyms)
                    elif isinstance(synonyms, str):
                        # 支持字符串格式（空格分隔）
                        expanded.update(synonyms.split())
        
        # 添加大小写变体（仅英文单词）
        for word in hotwords:
            if word.isalpha() and len(word) > 0:
                # 只对纯字母单词添加大小写变体
                expanded.add(word.lower())
                expanded.add(word.upper())
                if len(word) > 1:
                    expanded.add(word.capitalize())
        
        # 保持原始顺序，然后添加扩展词
        result = list(hotwords)
        for word in expanded:
            if word not in result:
                result.append(word)
        
        return result
    
    def intelligent_post_process(self, text: str, speaker_id: int, 
                                 speaker_context: Dict, full_transcript: List) -> str:
        """智能后处理,结合上下文提升内容逻辑性"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 基础文本清理
        processed_text = self.clean_text(text)
        
        # 上下文一致性检查
        processed_text = self._check_context_consistency(
            processed_text, speaker_id, speaker_context, full_transcript
        )
        
        return processed_text
    
    def clean_text(self, text: str) -> str:
        """后处理识别文本,去除多余空格"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 去除中文字符之间的空格
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)
        
        # 去除多个连续空格
        text = re.sub(r'\s+', ' ', text)
        
        # 去除首尾空格
        text = text.strip()
        
        return text
    
    def fix_transcript_text(self, text: str) -> str:
        """
        修复转写文本，确保末尾不是逗号
        
        Args:
            text: 待处理的转写文本
            
        Returns:
            修复后的文本，确保末尾不是逗号等非句末标点
        """
        if not text or text == "[未识别到语音]":
            return text
        
        # 先清理空格
        text = self.clean_text(text)
        
        # 修复末尾标点符号
        text = self._improve_sentence_completeness(text)
        
        return text
    
    def _check_context_consistency(self, text: str, speaker_id: int,
                                   speaker_context: Dict, full_transcript: List) -> str:
        """检查上下文一致性,修正可能的识别错误"""
        if not text or text == "[未识别到语音]":
            return text
        
        # 获取最近几段的内容
        recent_context = []
        for entry in full_transcript[-3:]:
            # 兼容 'speaker' 和 'speaker_id' 两种字段名
            entry_speaker = entry.get('speaker') or entry.get('speaker_id')
            if entry_speaker == speaker_id:
                recent_context.append(entry.get('text', ''))
        
        # 检查重复内容
        if recent_context:
            for prev_text in recent_context:
                if self._calculate_similarity(text, prev_text) > 0.8:
                    return "[重复内容已过滤]"
        
        # 改善句子完整性
        text = self._improve_sentence_completeness(text)
        
        # 修正常见识别错误
        text = self._fix_common_recognition_errors(text)
        
        return text
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        if not text1 or not text2:
            return 0
        
        set1 = set(text1)
        set2 = set(text2)
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0
    
    def _improve_sentence_completeness(self, text: str) -> str:
        """改善句子完整性,添加缺失的标点符号"""
        if not text:
            return text
        
        # 去除末尾空白字符
        text = text.rstrip()
        if not text:
            return text
        
        # 定义所有可能的句末标点符号（中文和英文）
        sentence_end_punctuation = '。！？!?.\n'
        
        # 检查文本末尾是否已有标点符号
        last_char = text[-1]
        
        # 如果末尾已经是句末标点符号，直接返回，不添加（避免重复）
        if last_char in sentence_end_punctuation:
            return text
        
        # 如果末尾是逗号、分号等非句末标点，需要替换为合适的句末标点
        # 发言内容结尾不允许是逗号
        if last_char in '，、；:;':
            # 移除末尾的逗号/分号
            text = text[:-1]
            # 根据内容添加合适的句末标点
            if any(word in text for word in ['吗', '呢', '什么', '怎么', '为什么', '如何']):
                text += '?'
            elif any(word in text for word in ['太', '很', '非常', '真的']):
                text += '!'
            else:
                text += '。'
            return text
        
        # 末尾没有标点符号，根据内容添加合适的标点
        if any(word in text for word in ['吗', '呢', '什么', '怎么', '为什么', '如何']):
            text += '?'
        elif any(word in text for word in ['太', '很', '非常', '真的']):
            text += '!'
        else:
            text += '。'
        
        return text
    
    def _fix_common_recognition_errors(self, text: str) -> str:
        """修正常见的语音识别错误"""
        if not text:
            return text
        
        # 这里可以添加常见的同音字错误修正规则
        # 实际应用中可以使用更复杂的NLP模型
        
        return text
    
    def extract_topics(self, text: str, topic_keywords: Optional[Dict[str, List[str]]] = None) -> Set[str]:
        """
        从文本中提取主题关键词
        
        Args:
            text: 待分析的文本
            topic_keywords: 主题关键词映射（可选），格式: {topic: [keyword1, keyword2, ...]}
                          如果为None，返回空集合（不进行主题提取）
        
        Returns:
            主题集合
        """
        topics = set()
        
        # 如果没有提供主题关键词映射，返回空集合
        if not topic_keywords:
            return topics
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in text for keyword in keywords):
                topics.add(topic)
        
        return topics
    
    def extract_entities(self, text: str) -> Set[str]:
        """从文本中提取实体"""
        entities = set()
        
        # 人名(简单规则)
        names = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        for name in names:
            if len(name) >= 2 and not any(char in name for char in '的了我是在有'):
                entities.add(f"人名:{name}")
        
        # 数字
        numbers = re.findall(r'\d+', text)
        for num in numbers:
            entities.add(f"数字:{num}")
        
        # 时间
        time_patterns = re.findall(r'\d+[年月日时分秒]', text)
        for time_pattern in time_patterns:
            entities.add(f"时间:{time_pattern}")
        
        return entities
    
    def analyze_sentiment(self, text: str, 
                         positive_words: Optional[List[str]] = None,
                         negative_words: Optional[List[str]] = None) -> str:
        """
        分析文本情感倾向
        
        Args:
            text: 待分析的文本
            positive_words: 积极情感词列表（可选），如果为None则不进行情感分析
            negative_words: 消极情感词列表（可选），如果为None则不进行情感分析
        
        Returns:
            情感倾向: 'positive', 'negative', 'neutral' 或 'unknown'（未配置时）
        """
        # 如果未配置情感词，返回未知
        if not positive_words and not negative_words:
            return 'unknown'
        
        positive_count = 0
        negative_count = 0
        
        if positive_words:
            positive_count = sum(1 for word in positive_words if word in text)
        
        if negative_words:
            negative_count = sum(1 for word in negative_words if word in text)
        
        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'
    
    def update_speaker_context(self, current_context: Dict, new_text: str, 
                              start_time: float, end_time: float) -> Dict:
        """更新发言人上下文信息"""
        if not current_context:
            current_context = {
                'recent_texts': [],
                'speaking_pattern': [],
                'vocabulary': set(),
                'topics': set(),
                'entities': set(),
                'sentiment_trend': [],
                'speaking_style': {},
                'last_update': start_time,
                'total_speaking_time': 0
            }
        
        # 更新最近文本
        current_context['recent_texts'].append(new_text)
        if len(current_context['recent_texts']) > 5:
            current_context['recent_texts'].pop(0)
        
        # 更新词汇表
        words = new_text.split()
        current_context['vocabulary'].update(words)
        
        # 提取主题和实体（主题提取需要外部提供关键词映射）
        topics = self.extract_topics(new_text, topic_keywords=None)  # 不进行主题提取，保持通用性
        entities = self.extract_entities(new_text)
        current_context['topics'].update(topics)
        current_context['entities'].update(entities)
        
        # 分析情感趋势
        sentiment = self.analyze_sentiment(new_text)
        current_context['sentiment_trend'].append(sentiment)
        if len(current_context['sentiment_trend']) > 10:
            current_context['sentiment_trend'].pop(0)
        
        # 更新说话模式
        duration = end_time - start_time
        current_context['speaking_pattern'].append(duration)
        current_context['total_speaking_time'] += duration
        if len(current_context['speaking_pattern']) > 10:
            current_context['speaking_pattern'].pop(0)
        
        current_context['last_update'] = start_time
        
        return current_context

