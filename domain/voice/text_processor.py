"""
Domain - 文本处理领域逻辑
负责热词处理、智能后处理、文本清理等纯业务规则
"""

import re
from typing import List, Dict, Set, Optional, Tuple


class TextProcessor:
    """文本处理器 - 处理热词、智能后处理等"""

    def process_hotword(self, hotword: str) -> str:
        """智能处理热词,提升识别效果"""
        if not hotword or not hotword.strip():
            return ''

        hotwords = [word.strip() for word in hotword.split() if word.strip()]
        unique_hotwords = list(dict.fromkeys(hotwords))
        expanded_hotwords = self._expand_hotwords(unique_hotwords)

        return ' '.join(expanded_hotwords)
    
    def _expand_hotwords(self, hotwords: List[str]) -> List[str]:
        """扩展热词,添加相关词汇"""
        expanded = set(hotwords)

        synonym_map = {
            'AI': ['人工智能', '机器学习', '深度学习'],
            '人工智能': ['AI', '机器学习', '深度学习'],
            '会议': ['开会', '讨论', '商议'],
            '项目': ['工程', '任务', '计划'],
            '技术': ['科技', '工程', '研发'],
            '产品': ['商品', '服务', '方案'],
            '市场': ['销售', '营销', '推广'],
            '客户': ['用户', '消费者', '买家'],
            '团队': ['小组', '部门', '组织'],
            '预算': ['费用', '成本', '资金']
        }

        for word in hotwords:
            if word in synonym_map:
                expanded.update(synonym_map[word])

        return list(expanded)
    
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

    def post_process_text(
        self,
        text: str,
        *,
        remove_repetitions: bool = True,
        profanity_words: Optional[List[str]] = None,
        profanity_action: str = "mask",
        profanity_mask_char: str = "*",
        profanity_replacement: str = "[不当内容已处理]",
        profanity_match_mode: str = "substring",
    ) -> Tuple[str, Dict]:
        """
        文本后处理（可用于展示/导出），包含：
        - 明显叠词/口吃式重复清理（中英文）
        - 不当词汇过滤（可配置词表 + 行为）

        Returns:
            (processed_text, meta)
            meta: {'changed': bool, 'removed_repetitions': bool, 'profanity_hit': bool}
        """
        if not text or text == "[未识别到语音]":
            return text, {"changed": False, "removed_repetitions": False, "profanity_hit": False}

        original = text
        removed_repetitions_flag = False
        profanity_hit = False

        # 基础空白清理
        processed = self.clean_text(text)

        # 1) 明显叠词/重复（尽量保守，避免误伤正常词汇）
        if remove_repetitions:
            processed2, removed_repetitions_flag = self._remove_obvious_repetitions(processed)
            processed = processed2

        # 2) 不当词汇过滤（默认不内置词库，只按配置词表处理）
        if profanity_words:
            processed2, profanity_hit = self._filter_profanity(
                processed,
                profanity_words=profanity_words,
                action=profanity_action,
                mask_char=profanity_mask_char,
                replacement=profanity_replacement,
                match_mode=profanity_match_mode,
            )
            processed = processed2

        changed = processed != original
        return processed, {"changed": changed, "removed_repetitions": removed_repetitions_flag, "profanity_hit": profanity_hit}
    
    def fix_transcript_text(self, text: str, *, remove_repetitions: bool = True) -> str:
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

        # ✅ 轻量文本质量修复：明显叠词/口吃重复
        # 注意：如果需要保证 words 与 text 对齐（逐词高亮），上层应在有 words 时关闭该选项，
        # 或者使用基于 words 的过滤方式来保持一致性。
        if remove_repetitions:
            text, _ = self._remove_obvious_repetitions(text)
        
        # 修复末尾标点符号
        text = self._improve_sentence_completeness(text)
        
        return text

    def filter_profanity_in_words(
        self,
        words: List[Dict],
        *,
        profanity_words: List[str],
        action: str = "mask",
        mask_char: str = "*",
        replacement: str = "[不当内容已处理]",
        match_mode: str = "substring",
    ) -> Tuple[List[Dict], bool]:
        """
        在 words 粒度做不当词过滤，保持时间戳不变，并确保最终 entry.text == ''.join(words.text)。
        这比“直接改整句 text”更适合逐词高亮场景。

        说明：
        - action=mask：按命中长度打码（推荐，最稳）
        - action=replace：用 replacement 替换，但会按命中长度做截断/重复以贴合跨度（保证不跨词错位）
        - action=remove：删除命中文字（会让该 word 文字变短/为空，但时间戳仍保留）
        """
        if not words or not profanity_words:
            return words, False

        # 复制，避免原地修改带来副作用
        new_words = [dict(w) for w in words]
        texts = [w.get("text", "") or "" for w in new_words]

        full = "".join(texts)
        if not full:
            return new_words, False

        action = (action or "mask").lower().strip()
        match_mode = (match_mode or "substring").lower().strip()

        # 预计算每个 word 在 full 中的起始偏移
        starts: List[int] = []
        pos = 0
        for t in texts:
            starts.append(pos)
            pos += len(t)

        def _normalize_replace(seg_len: int) -> str:
            if seg_len <= 0:
                return ""
            if not replacement:
                return mask_char * seg_len
            if len(replacement) == seg_len:
                return replacement
            if len(replacement) > seg_len:
                return replacement[:seg_len]
            # repeat to fill
            times = (seg_len + len(replacement) - 1) // len(replacement)
            return (replacement * times)[:seg_len]

        # 收集所有 match span（start,end），基于原始 full 计算
        spans: List[Tuple[int, int]] = []
        rule_list = [w.strip() for w in profanity_words if w and w.strip()]
        rule_list.sort(key=len, reverse=True)

        for rule in rule_list:
            # /regex/ or /regex/i
            if len(rule) >= 2 and rule.startswith("/") and rule.count("/") >= 2:
                last_slash = rule.rfind("/")
                pattern = rule[1:last_slash]
                flags_part = rule[last_slash + 1 :].strip()
                flags = 0
                if "i" in flags_part.lower():
                    flags |= re.IGNORECASE
                try:
                    for m in re.finditer(pattern, full, flags):
                        if m and m.start() < m.end():
                            spans.append((m.start(), m.end()))
                except re.error:
                    continue
                continue

            # 英文/数字词默认按单词边界匹配
            if re.fullmatch(r"[A-Za-z0-9_]+", rule):
                for m in re.finditer(rf"\b{re.escape(rule)}\b", full, flags=re.IGNORECASE):
                    if m and m.start() < m.end():
                        spans.append((m.start(), m.end()))
                continue

            if match_mode == "word":
                pat = rf"(?<![A-Za-z0-9_]){re.escape(rule)}(?![A-Za-z0-9_])"
            else:
                pat = re.escape(rule)
            for m in re.finditer(pat, full):
                if m and m.start() < m.end():
                    spans.append((m.start(), m.end()))

        if not spans:
            return new_words, False

        # 合并重叠 spans（避免重复处理）
        spans.sort()
        merged: List[Tuple[int, int]] = []
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))

        # 将 spans 按 word 切分为局部替换（按原始偏移），并在每个 word 内“从后往前”应用避免位移问题
        per_word_ops: Dict[int, List[Tuple[int, int, str]]] = {}
        hit = False

        for s, e in merged:
            if s >= e:
                continue
            hit = True
            # 找到覆盖的 word 范围
            for i, w_start in enumerate(starts):
                w_text = texts[i]
                w_end = w_start + len(w_text)
                if w_end <= s:
                    continue
                if w_start >= e:
                    break
                # 相交
                local_s = max(0, s - w_start)
                local_e = min(len(w_text), e - w_start)
                if local_s >= local_e:
                    continue
                seg_len = local_e - local_s
                if action == "remove":
                    repl = ""
                elif action == "replace":
                    repl = _normalize_replace(seg_len)
                else:
                    repl = mask_char * seg_len
                per_word_ops.setdefault(i, []).append((local_s, local_e, repl))

        for idx, ops in per_word_ops.items():
            t = texts[idx]
            # 从后往前应用
            ops.sort(key=lambda x: x[0], reverse=True)
            for local_s, local_e, repl in ops:
                t = t[:local_s] + repl + t[local_e:]
            texts[idx] = t
            new_words[idx]["text"] = t

        return new_words, hit

    def remove_repetitions_in_words(self, words: List[Dict]) -> Tuple[List[Dict], bool]:
        """
        在 words 粒度做“明显口吃/叠词重复”清理，保持时间戳不变，并确保 text 可由 words 重建且对齐高亮。
        覆盖：
        - 中文 2~6 字短语连续重复：'这是这是' -> '这是'
        - 中文短语带空格重复：'这是 这是' -> '这是'
        - 英文连续重复单词：'the the' -> 'the'
        - 常见填充词连续重复：'嗯嗯嗯'/'啊 啊' -> 收敛为 1 个
        """
        if not words:
            return words, False

        new_words = [dict(w) for w in words]
        texts = [w.get("text", "") or "" for w in new_words]
        full = "".join(texts)
        if not full:
            return new_words, False

        # 预计算每个 word 在 full 的起始偏移
        starts: List[int] = []
        pos = 0
        for t in texts:
            starts.append(pos)
            pos += len(t)

        # 收集要删除的 spans（start,end），基于 full 偏移
        spans: List[Tuple[int, int]] = []

        # 1) 填充词连续重复：保留第一个，删除后续
        fillers = r"(嗯|呃|额|啊|唉|哎|诶)"
        for m in re.finditer(rf"(?:{fillers})(?:[\s,，、]*{fillers})+", full):
            if not m:
                continue
            spans.append((m.start() + 1, m.end()))

        # 2) 中文短语连续重复（2~6字）
        for m in re.finditer(r"([\u4e00-\u9fff]{2,6})\1{1,}", full):
            if not m:
                continue
            g = m.group(1)
            spans.append((m.start() + len(g), m.end()))

        # 3) 中文短语带空格重复
        for m in re.finditer(r"([\u4e00-\u9fff]{2,6})(?:\s+\1){1,}", full):
            if not m:
                continue
            g = m.group(1)
            spans.append((m.start() + len(g), m.end()))

        # 4) 英文连续重复单词（忽略大小写）
        for m in re.finditer(r"\b([A-Za-z]{2,})\b(?:\s+\1\b)+", full, flags=re.IGNORECASE):
            if not m:
                continue
            g = m.group(1)
            spans.append((m.start() + len(g), m.end()))

        if not spans:
            return new_words, False

        # 合并 spans
        spans.sort()
        merged: List[Tuple[int, int]] = []
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))

        # 按 word 切分删除操作（从后往前应用）
        per_word_ops: Dict[int, List[Tuple[int, int]]] = {}
        changed = False

        for s, e in merged:
            if s >= e:
                continue
            changed = True
            for i, w_start in enumerate(starts):
                w_text = texts[i]
                w_end = w_start + len(w_text)
                if w_end <= s:
                    continue
                if w_start >= e:
                    break
                local_s = max(0, s - w_start)
                local_e = min(len(w_text), e - w_start)
                if local_s >= local_e:
                    continue
                per_word_ops.setdefault(i, []).append((local_s, local_e))

        for idx, ops in per_word_ops.items():
            t = texts[idx]
            ops.sort(key=lambda x: x[0], reverse=True)
            for local_s, local_e in ops:
                t = t[:local_s] + "" + t[local_e:]
            texts[idx] = t
            new_words[idx]["text"] = t

        return new_words, changed

    def is_tail_only_change(self, original: str, modified: str) -> bool:
        """
        判断改动是否仅发生在文本末尾（典型：补句号/替换末尾逗号），用于决定是否可以安全地保留 words。
        这是保守判定：只要有明显句中改动，就返回 False。
        """
        if original == modified:
            return True
        if not original or not modified:
            return False

        a = original.rstrip()
        b = modified.rstrip()

        # 允许：在末尾新增 1 个句末标点
        if b.startswith(a) and len(b) - len(a) <= 1:
            return True

        # 允许：末尾 1 个字符替换（逗号->句号/问号/叹号）
        if len(a) == len(b) and len(a) >= 1 and a[:-1] == b[:-1]:
            return True

        # 允许：末尾 2 个字符以内的轻微变化（比如 ", " -> "。"）
        # 但必须保持绝大部分前缀一致
        min_len = min(len(a), len(b))
        prefix_len = 0
        for i in range(min_len):
            if a[i] != b[i]:
                break
            prefix_len += 1
        # 只要差异点出现在最后 2 个字符内，就认为是尾部改动
        return prefix_len >= min_len - 2

    def _remove_obvious_repetitions(self, text: str) -> Tuple[str, bool]:
        """
        清理明显的重复（叠词/口吃式重复）。
        目标是“明显错误”而不是“语气重复”，所以策略偏保守：
        - 中文：2~6字短语连续重复 -> 保留一次（例如：'这是这是' -> '这是'；'我们我们我们'->'我们'）
        - 英文：连续重复单词 -> 保留一次（'the the' -> 'the'）
        - 口头语填充：'嗯嗯'/'啊啊' 连续重复 -> 收敛为 1 个
        """
        if not text:
            return text, False

        original = text

        # 1) 常见口头语填充词：连续重复 -> 收敛为一个
        fillers = r"(嗯|呃|额|啊|唉|哎|诶)"
        text = re.sub(rf"(?:{fillers})(?:[\s,，、]*{fillers})+", r"\1", text)

        # 2) 中文短语重复（连续）
        #    - 用 2~6 字，避免误伤“人人/看看”这类单字叠字（单字叠字不在这里处理）
        text = re.sub(r"([\u4e00-\u9fff]{2,6})\1{1,}", r"\1", text)

        # 3) 中英文混合场景：带空格的中文短语重复（ASR偶尔会插空格）
        text = re.sub(r"([\u4e00-\u9fff]{2,6})(?:\s+\1){1,}", r"\1", text)

        # 4) 英文连续重复单词（忽略大小写）
        text = re.sub(r"\b([A-Za-z]{2,})\b(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

        # 5) 多余空格再收敛一次
        text = re.sub(r"\s+", " ", text).strip()

        return text, (text != original)

    def _filter_profanity(
        self,
        text: str,
        *,
        profanity_words: List[str],
        action: str = "mask",
        mask_char: str = "*",
        replacement: str = "[不当内容已处理]",
        match_mode: str = "substring",
    ) -> Tuple[str, bool]:
        """
        基于词表的不当词过滤。
        action:
          - 'mask': 用 mask_char 按长度打码（默认）
          - 'replace': 统一替换为 replacement
          - 'remove': 直接移除
        规则：
          - 普通词条：中文按子串匹配；英文/数字按单词边界匹配（忽略大小写）
          - /regex/ 或 /regex/i：按正则匹配（高级用法）
        """
        if not text or not profanity_words:
            return text, False

        action = (action or "mask").lower().strip()
        match_mode = (match_mode or "substring").lower().strip()
        hit = False

        # 词表去重、去空
        words = [w.strip() for w in profanity_words if w and w.strip()]
        if not words:
            return text, False

        # 先长词后短词，避免短词抢占
        words.sort(key=len, reverse=True)

        def repl(m: re.Match) -> str:
            nonlocal hit
            hit = True
            s = m.group(0)
            if action == "remove":
                return ""
            if action == "replace":
                return replacement
            # mask
            return mask_char * max(len(s), 1)

        # 对英文词做边界匹配，对中文/其他做普通子串匹配（尽量简单且可控）
        for w in words:
            # /regex/ 或 /regex/i（可选 i 标志）
            if len(w) >= 2 and w.startswith("/") and w.count("/") >= 2:
                # 取最后一个 / 作为结束
                last_slash = w.rfind("/")
                pattern = w[1:last_slash]
                flags_part = w[last_slash + 1 :].strip()
                flags = 0
                if "i" in flags_part.lower():
                    flags |= re.IGNORECASE
                try:
                    text = re.sub(pattern, repl, text, flags=flags)
                except re.error:
                    # 正则有误则跳过
                    continue
                continue

            if re.fullmatch(r"[A-Za-z0-9_]+", w):
                text = re.sub(rf"\b{re.escape(w)}\b", repl, text, flags=re.IGNORECASE)
            else:
                if match_mode == "word":
                    # 尝试用“非字母数字下划线”作为边界（对中英混合更稳一点）
                    text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(w)}(?![A-Za-z0-9_])", repl, text)
                else:
                    text = re.sub(re.escape(w), repl, text)

        # 清理多余空格
        text = re.sub(r"\s+", " ", text).strip()
        return text, hit
    
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
    
    def extract_topics(self, text: str) -> Set[str]:
        """从文本中提取主题关键词"""
        topics = set()

        topic_keywords = {
            '技术': ['技术', '开发', '编程', '代码', '系统', '软件', '硬件'],
            '产品': ['产品', '功能', '特性', '设计', '界面', '用户体验'],
            '市场': ['市场', '销售', '客户', '用户', '推广', '营销'],
            '管理': ['管理', '团队', '项目', '计划', '目标', '策略'],
            '财务': ['预算', '成本', '费用', '收入', '利润', '投资'],
            '会议': ['会议', '讨论', '决策', '意见', '建议', '方案']
        }

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
    
    def analyze_sentiment(self, text: str) -> str:
        """分析文本情感倾向"""
        positive_words = ['好', '棒', '优秀', '成功', '满意', '喜欢', '支持', '同意']
        negative_words = ['差', '糟糕', '失败', '不满', '反对', '问题', '错误', '困难']

        positive_count = sum(1 for word in positive_words if word in text)
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

        # 提取主题和实体
        topics = self.extract_topics(new_text)
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

