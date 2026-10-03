import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.llm_client import LLMClient


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    llm = LLMClient()
    print(f"model={llm.model} available={llm.available} cache={llm.cache_enabled}")

    out = llm.chat([{"role": "user", "content": "只回复两个字：正常"}], max_tokens=10)
    print(f"chat_reply={out['content'].strip()!r} cached={out['cached']} usage={out['usage']}")

    tools = [{
        "type": "function",
        "function": {
            "name": "get_fact",
            "description": "查询年报中的财务事实",
            "parameters": {"type": "object", "properties": {"metric": {"type": "string"}}, "required": ["metric"]},
        },
    }]
    out2 = llm.chat([{"role": "user", "content": "请调用工具查询营业收入"}], tools=tools, max_tokens=200)
    tc = out2.get("tool_calls")
    if tc:
        print(f"tool_call=支持 name={tc[0]['function']['name']} args={tc[0]['function']['arguments']}")
    else:
        print(f"tool_call=未触发 content={out2['content'][:120]}")

    out3 = llm.chat_json([{"role": "user", "content": "输出JSON：{\"ok\": true, \"msg\": \"你好\"}"}], max_tokens=512)
    print(f"json_parse=OK {out3[0]}")

    print(f"stats={llm.stats}")


if __name__ == "__main__":
    main()
