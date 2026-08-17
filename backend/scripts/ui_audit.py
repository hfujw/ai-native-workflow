"""无 Key UI 验收——首次打开/空状态/预检/发送禁用（不需要 API Key）。

8 维产品验收框架中"读代码+无 Key 可跑"的部分：
  1. 首次打开：无 Key 时看到什么（placeholder 引导、设置入口）
  2. 空状态：works 页没有历史作品时长什么样
  3. 预检：发送按钮是否禁用、configHint 是否出现
  4. 语义化：核心控件是不是 button/textarea/iframe（非 div 拼）
  5. 焦点：Tab 能否流转到发送按钮

用法（前后端已启动）：
    ../venv/Scripts/python scripts/ui_audit.py
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

FRONTEND_URL = "http://localhost:1420"
OUT_DIR = Path(__file__).resolve().parent.parent.parent / "desktop" / "screenshots" / "audit"

PASS, FAIL = "✅", "❌"
report: list[str] = []


def note(ok: bool, label: str, detail: str = ""):
    mark = PASS if ok else FAIL
    report.append(f"{mark} {label}  {detail}")
    print(f"{mark} {label}  {detail}")


async def run():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--force-light-mode"])
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        print(f"打开 {FRONTEND_URL} …")
        await page.goto(FRONTEND_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)

        # ── 1. 首次打开：Composer 存在？placeholder 引导？ ──
        textarea = page.locator("textarea")
        await textarea.wait_for(state="visible", timeout=8000)
        ph = await textarea.get_attribute("placeholder")
        note(bool(ph), "Composer 输入框存在", f"placeholder={ph!r}")

        # 键盘可达：初始焦点在输入框（autoFocus，任何交互之前测）
        await page.wait_for_timeout(300)  # 等 React 完成 autoFocus
        focused0 = await page.evaluate("() => document.activeElement?.tagName")
        note(focused0 == "TEXTAREA", "初始焦点在输入框（autoFocus）", f"active={focused0}")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(150)
        focused1 = await page.evaluate("() => document.activeElement?.tagName")
        note(focused1 == "BUTTON", "Tab 从输入框流转到按钮", f"active={focused1}")
        # 焦点已移动 → 点回输入框，避免后续步骤失焦干扰
        await textarea.click()
        await page.wait_for_timeout(150)

        # 无 Key 预检提示（computeConfigHint → configHint prop）
        hint = page.locator(".composer-hint")
        hint_visible = await hint.count() > 0 and await hint.is_visible()
        hint_text = (await hint.inner_text()).strip() if hint_visible else ""
        note(hint_visible, "无 Key 预检提示出现", f"文案={hint_text!r}")

        # ── 2. 发送按钮禁用？ ──
        send_btn = page.locator("button.send-btn")
        send_disabled = await send_btn.is_disabled()
        note(send_disabled, "无 Key 时发送按钮禁用")

        # ── 3. 设置入口 discoverability ──
        settings_btn = page.locator("button.settings-btn")
        set_count = await settings_btn.count()
        note(set_count > 0, "设置入口存在", f"匹配 {set_count} 个")
        await page.screenshot(path=str(OUT_DIR / "01-onboarding.png"))

        # ── 4. 打开设置抽屉 → 模型 tab 可见 ──
        await settings_btn.first.click()
        await page.wait_for_timeout(500)
        model_tab = page.locator("text=模型").first
        note(await model_tab.count() > 0, "设置抽屉模型 tab 存在")
        await page.screenshot(path=str(OUT_DIR / "02-settings.png"))
        # 关闭设置
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # ── 5. works 页空状态 ──
        works_btn = page.locator("text=轨迹").first
        if await works_btn.count():
            await works_btn.click()
            await page.wait_for_timeout(600)
            empty = page.locator(".trajectory-empty, text=还没有作品")
            empty_visible = await empty.count() > 0 and await empty.is_visible()
            empty_text = (await empty.inner_text()).strip() if empty_visible else ""
            note(empty_visible, "works 空状态文案存在", f"文案={empty_text!r}")
            await page.screenshot(path=str(OUT_DIR / "03-works-empty.png"))
            # 回 chat
            chat_btn = page.locator("text=对话").first
            if await chat_btn.count():
                await chat_btn.click()
                await page.wait_for_timeout(400)

        # ── 6. 语义化：发送按钮是 button、iframe 有 title（若有） ──
        tag = await send_btn.evaluate("el => el.tagName")
        note(tag == "BUTTON", "发送按钮是 <button>", f"tag={tag}")
        iframe_title = await page.evaluate(
            """() => {
                const ifs = document.querySelectorAll('iframe');
                const missing = [...ifs].filter(f => !f.getAttribute('title'));
                return { count: ifs.length, missingTitle: missing.length };
            }"""
        )
        note(iframe_title["missingTitle"] == 0, "iframe 均有 title",
             f"共 {iframe_title['count']} 个 iframe")

        # ── 8. 空输入时发送禁用（有 Key 场景也要禁） ──
        # 上面已确认无 Key 禁用；这里模拟有 Key（注入 localStorage）后空输入仍禁
        await page.evaluate(
            """() => {
                const creds = JSON.parse(localStorage.getItem('lumen.providerCreds') || '{}');
                creds['DeepSeek'] = { apiKey: 'sk-test', apiBase: 'https://api.deepseek.com' };
                localStorage.setItem('lumen.providerCreds', JSON.stringify(creds));
            }"""
        )
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)
        send2 = page.locator("button.send-btn")
        empty_disabled = await send2.is_disabled()
        note(empty_disabled, "有 Key 但空输入 → 发送仍禁用")

        await browser.close()

    print("\n===== 验收摘要 =====")
    for line in report:
        print(line)
    ok_count = sum(1 for l in report if l.startswith("✅"))
    print(f"\n{ok_count}/{len(report)} 通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
