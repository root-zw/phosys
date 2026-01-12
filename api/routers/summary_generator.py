"""
会议纪要生成器模块
负责使用 AI 生成会议纪要
"""

import os
import re
import logging
from datetime import datetime
from openai import OpenAI

from config import AI_MODEL_CONFIG

logger = logging.getLogger(__name__)


def generate_meeting_summary(transcript_data, custom_prompt=None, model=None):
    """使用AI生成会议纪要"""
    try:
        if not transcript_data:
            logger.warning("转写数据为空，无法生成会议纪要")
            return None
        
        transcript_text = ""
        for entry in transcript_data:
            speaker = entry.get('speaker', '未知发言人')
            text = entry.get('text', '')
            transcript_text += f"{speaker}: {text}\n\n"
        
        if not transcript_text.strip():
            logger.warning("转写文本为空，无法生成会议纪要")
            return None
        
        logger.info(f"开始生成会议纪要，转写文本长度: {len(transcript_text)} 字符")
        
        # 根据传入的模型选择对应的配置
        model_key = None
        if model:
            model_lower = model.lower()
            if 'deepseek' in model_lower or model_lower == 'deepseek':
                model_key = 'deepseek'
            elif 'qwen' in model_lower or model_lower == 'qwen':
                model_key = 'qwen'
            elif 'glm' in model_lower or model_lower == 'glm':
                model_key = 'glm'
        
        # 如果没有指定模型或模型不在配置中，使用默认的 deepseek
        if not model_key or model_key not in AI_MODEL_CONFIG:
            model_key = 'deepseek'
            logger.info(f"使用默认模型: {model_key}")
        
        # 获取对应模型的配置
        model_config = AI_MODEL_CONFIG.get(model_key, AI_MODEL_CONFIG['deepseek'])
        api_key = model_config.get('api_key')
        api_base = model_config.get('api_base')
        model_name = model_config.get('model')
        
        # 如果配置中没有API KEY，尝试从环境变量读取
        if not api_key:
            api_key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
        if not api_base:
            api_base = os.getenv('DEEPSEEK_API_BASE') or os.getenv('OPENAI_API_BASE', 'https://api.deepseek.com')
        
        if not api_key:
            logger.warning("未配置API KEY，使用默认模板")
            return generate_default_summary(transcript_data)
        
        logger.info(f"使用模型: {model_key} ({model_config.get('display_name', model_key)}), API Base: {api_base}")
        
        client = OpenAI(api_key=api_key, base_url=api_base)
        
        # 使用自定义提示词，如果没有则使用默认提示词
        if custom_prompt:
            # 替换 {transcript} 占位符，如果没有占位符则自动追加转写内容
            if '{transcript}' in custom_prompt:
                prompt = custom_prompt.replace('{transcript}', transcript_text)
                logger.info("使用自定义提示词，已替换 {transcript} 占位符")
            else:
                if '会议转录内容：' in custom_prompt:
                    prompt = custom_prompt.replace('会议转录内容：', f'会议转录内容：\n{transcript_text}')
                else:
                    prompt = f"{custom_prompt}\n\n会议转录内容：\n{transcript_text}"
                logger.info("使用自定义提示词，自动追加转写内容（提示词中未包含 {transcript} 占位符）")
            
            # 为自定义提示词也添加要求（避免确认消息）
            if '不要包含任何确认消息' not in prompt and '不要添加任何前缀说明' not in prompt:
                prompt += "\n\n重要要求：直接输出会议纪要内容，不要包含任何确认消息、引导语句或说明性文字（如'这是根据您提供的会议转录内容生成的会议纪要'、'好的'、'已根据'等）。不要添加任何前缀说明，直接开始输出。"
        else:
            logger.info("使用默认提示词模板")
            prompt = f"""请根据以下会议转录内容，生成一份结构化的会议纪要。

会议转录内容：
{transcript_text}

请严格按照以下格式生成会议纪要：

会议主题：[根据会议内容总结主题]
主持人：[从转录中识别主持人]
参会人数：[统计参与会议的总人数]
关键词：[会议纪要关键词]
大纲:[用200字左右阐述会议概要]

一、会议议题及讨论内容
二、行动清单（待办事项）
三、其他说明

重要要求：
1. 直接输出会议纪要内容，不要包含任何确认消息、引导语句或说明性文字（如"这是根据您提供的会议转录内容生成的会议纪要"、"好的"、"已根据"等）
2. 不要添加任何前缀说明，直接开始输出会议主题
3. 不要使用"为您生成"、"已根据"、"这是"等引导性语句
4. 输出内容应该是纯粹的会议纪要，不包含任何元信息或确认信息
5. 关键词部分应提取会议中的核心专业术语、重要概念、关键议题等，用空格分隔，数量控制在10-20个之间"""
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system", 
                    "content": "你是一个专业的会议纪要助手。重要规则：直接输出会议纪要内容，不要包含任何确认消息、引导语句、说明性文字或元信息（如'这是根据您提供的会议转录内容生成的会议纪要'、'好的'、'已根据'、'为您生成'等）。直接开始输出会议主题，不要添加任何前缀。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        # 去除AI返回内容中的确认消息和markdown格式
        raw_content = response.choices[0].message.content
        
        # 智能去除确认消息和引导消息
        lines = raw_content.split('\n')
        cleaned_lines = []
        skip_until_content = True
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            if not line_stripped:
                if skip_until_content:
                    continue
                else:
                    cleaned_lines.append(line)
                continue
            
            is_confirmation = False
            
            # 确认消息关键词模式
            confirmation_keywords = [
                r'^(好的|明白了|收到|了解)[，,。\s]*',
                r'^(已根据|根据您提供|根据.*?转录|根据.*?内容)',
                r'^(为您生成|为您.*?生成|已.*?生成.*?会议纪要)',
                r'^(这是.*?生成的.*?会议纪要|这是根据.*?生成的)',
                r'^(以下是|下面.*?是|我将.*?为您)',
                r'^(根据.*?内容.*?生成|基于.*?内容.*?生成)',
                r'^(好的[，,]\s*)?(已|已经).*?(生成|为您|根据)',
                r'^.*?(为您|已为您|已经为您).*?(生成|创建|制作).*?(会议纪要|纪要)',
            ]
            
            for pattern in confirmation_keywords:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    is_confirmation = True
                    break
            
            # 检查是否包含确认性短语
            confirmation_phrases = [
                '这是根据您提供的',
                '这是根据.*?生成的',
                '已根据.*?为您生成',
                '为您生成.*?会议纪要',
                '已为您生成',
                '已经为您生成',
                '根据.*?内容.*?生成.*?会议纪要',
            ]
            
            for phrase in confirmation_phrases:
                if re.search(phrase, line_stripped, re.IGNORECASE):
                    is_confirmation = True
                    break
            
            if is_confirmation:
                skip_until_content = True
                continue
            
            # 如果遇到实际内容，停止跳过
            if re.match(r'^(会议主题|会议时间|会议地点|主持人|记录人|参与人员|参会人数|一、|二、|三、)', line_stripped):
                skip_until_content = False
                cleaned_lines.append(line)
            elif not skip_until_content:
                cleaned_lines.append(line)
            elif len(line_stripped) > 20 and not any(keyword in line_stripped for keyword in ['根据', '生成', '为您', '已', '这是']):
                skip_until_content = False
                cleaned_lines.append(line)
        
        raw_content = '\n'.join(cleaned_lines)
        
        # 去除开头可能残留的确认消息
        confirmation_start_patterns = [
            r'^(好的[，,]\s*)?(已根据|根据您提供|根据.*?转录|根据.*?内容).*?',
            r'^(为您生成|已.*?生成.*?会议纪要).*?',
            r'^(这是.*?生成的.*?会议纪要|这是根据.*?生成的).*?',
            r'^(以下是|下面.*?是|我将.*?为您).*?',
        ]
        
        for pattern in confirmation_start_patterns:
            if len(raw_content) > 500:
                prefix = raw_content[:500]
                match = re.match(pattern, prefix, re.IGNORECASE | re.DOTALL)
                if match:
                    content_start = re.search(r'(会议主题|会议时间|会议地点|主持人|记录人|参与人员|参会人数|一、|二、|三、)', raw_content)
                    if content_start:
                        raw_content = raw_content[content_start.start():]
                    else:
                        raw_content = raw_content[match.end():].lstrip()
                    break
            else:
                raw_content = re.sub(pattern, '', raw_content, flags=re.IGNORECASE | re.DOTALL)
                break
        
        # 去除分隔线
        raw_content = re.sub(r'^[-=]{3,}\s*$', '', raw_content, flags=re.MULTILINE)
        
        # 去除markdown标题格式
        raw_content = re.sub(r'^#{1,6}\s*\*{0,2}\s*会议纪要\s*\*{0,2}\s*$', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        raw_content = re.sub(r'^#{1,6}\s+', '', raw_content, flags=re.MULTILINE)
        
        # 去除markdown粗体格式
        raw_content = re.sub(r'\*\*([^*]+)\*\*', r'\1', raw_content)
        
        # 去除单独的"会议纪要"标题行
        raw_content = re.sub(r'^[\s]*会议纪要[\s]*$', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        
        # 去除markdown斜体格式
        raw_content = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', raw_content)
        
        # 去除markdown代码块格式
        raw_content = re.sub(r'```[\s\S]*?```', '', raw_content)
        
        # 去除markdown行内代码格式
        raw_content = re.sub(r'`([^`]+)`', r'\1', raw_content)
        
        # 去除markdown列表标记
        raw_content = re.sub(r'^[\s]*[-*]\s+', '', raw_content, flags=re.MULTILINE)
        raw_content = re.sub(r'^[\s]*\d+\.\s+', '', raw_content, flags=re.MULTILINE)
        
        # 去除多余的空行
        raw_content = re.sub(r'\n{3,}', '\n\n', raw_content)
        
        # 再次去除单独的"会议纪要"标题行
        raw_content = re.sub(r'^[\s]*会议纪要[\s]*\n?', '', raw_content, flags=re.IGNORECASE | re.MULTILINE)
        
        # 去除开头的空白字符和空行
        raw_content = raw_content.strip()
        
        current_time = datetime.now()
        summary = {
            'raw_text': raw_content,
            'generated_at': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'model': model,
            'status': 'success'
        }
        
        return summary
        
    except Exception as e:
        logger.error(f"生成会议纪要失败: {e}")
        return {
            'raw_text': f"生成会议纪要时发生错误: {str(e)}",
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'error',
            'error': str(e)
        }


def generate_default_summary(transcript_data):
    """生成默认会议纪要"""
    speaker_stats = {}
    total_words = 0
    
    for entry in transcript_data:
        speaker = entry.get('speaker', '未知发言人')
        text = entry.get('text', '')
        
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {'count': 0, 'words': 0}
        
        speaker_stats[speaker]['count'] += 1
        speaker_stats[speaker]['words'] += len(text)
        total_words += len(text)
    
    summary_text = f"""## 会议概要
本次会议共有{len(speaker_stats)}位参与者，会议记录共{len(transcript_data)}段发言，总计约{total_words}字。

## 参与人员
"""
    
    for speaker, stats in speaker_stats.items():
        summary_text += f"- {speaker}: 发言{stats['count']}次\n"
    
    return {
        'raw_text': summary_text,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'model': 'default_template',
        'status': 'success'
    }
