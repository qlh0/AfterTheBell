"""模型配置与 JSON 调用；密钥保存在同目录 .env。"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))
MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-flash"


def generate(system_prompt, data):
    correction = data.get("format_correction") or data.get("context", {}).get("format_correction")
    if correction:
        system_prompt += "\n格式纠正（优先执行）：" + correction + (
            '\n对白示例："lines":[{"speaker":"小美","emotion":"平静","text":"知道了。"}]。'
            '保留当前任务其他字段，speaker必须为当前在场人物。')
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        timeout=90,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
        max_tokens=3000,
    )
    return json.loads(response.choices[0].message.content)
