"""LLM 连接诊断脚本——一次跑清"模型名到底该填什么"。

用法：
    cd backend
    ..\venv\Scripts\python scripts/check_llm.py --key sk-你的key [--base https://api.deepseek.com]

它会对每个候选模型名发一个最小请求，打印 API 的真实响应：
  ✅ 200 = 这个名字能用（照抄这个）
  ❌ 400 = 这个名字被拒（原因会打出来）
  🔒 401 = key 有问题（不是名字问题）

跑完你就知道：后端归一化后实际发送的名字（deepseek-v4-flash / deepseek-v4-pro）
是否被你的 API 接受。
"""

import argparse
import sys

from openai import OpenAI


def main():
    parser = argparse.ArgumentParser(description="测试 DeepSeek API 接受的模型名")
    parser.add_argument("--key", required=True, help="API Key")
    parser.add_argument("--base", default="https://api.deepseek.com", help="API Base URL")
    args = parser.parse_args()

    client = OpenAI(api_key=args.key, base_url=args.base, timeout=30)

    candidates = [
        # 后端归一化后实际发送的名字（官方现行名）
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        # 用户可能填的变体（归一化会映射到上面两个）
        "deepseek-Flash",
        "deepseek-Pro",
        "deepseek",
        "deepseek-chat",
        "deepseek-reasoner",
    ]

    print(f"Base: {args.base}")
    print(f"Key:  {args.key[:8]}***（长度 {len(args.key)}）")
    print("=" * 60)
    ok_count = 0
    for name in candidates:
        try:
            resp = client.chat.completions.create(
                model=name,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            content = resp.choices[0].message.content or ""
            print(f"  ✅ {name!r:28} → 200 可用（返回: {content[:20]!r}）")
            ok_count += 1
        except Exception as e:
            status = getattr(e, "status_code", "?")
            msg = str(e).split("'message': ")[-1][:120] if "'message':" in str(e) else str(e)[:120]
            print(f"  ❌ {name!r:28} → HTTP {status} | {msg}")

    print("=" * 60)
    if ok_count:
        print(f"结论：{ok_count} 个模型名可用。后端会把所有 deepseek 开头的名字")
        print("归一化为 deepseek-v4-flash / deepseek-v4-pro——只要这两个里有 ✅ 就能跑通。")
    else:
        print("结论：没有一个名字可用——请检查 key 是否有效、账号是否开通 API、")
        print("或 base 地址是否填对（DeepSeek 官方是 https://api.deepseek.com）。")
        sys.exit(1)


if __name__ == "__main__":
    main()
