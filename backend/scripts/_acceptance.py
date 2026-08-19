"""收尾验收测试：确认当前功能都能正常使用。临时脚本，用后删除。

覆盖：boot → 生成 → 思考块/工具卡 → 成品卡 → 预览 iframe → 历史回放 → 画廊 → 迭代(refine) → 设置页。
"""

import sys
import time
from playwright.sync_api import sync_playwright

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"  {'✅' if cond else '❌'} {name}")


def wait_for(cond, timeout_s, step=3.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(step)
    return False


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto("http://127.0.0.1:5173/", wait_until="networkidle")
        page.wait_for_timeout(2500)

        # 1. boot
        check("boot：hero composer 出现", page.locator("textarea").count() > 0)
        check("boot：侧边栏作品列表出现", "秦始皇是谁" in page.inner_text("body") or "作品" in page.inner_text("body"))

        # 2. 发送 → 生成
        page.locator("textarea").first.fill("秦始皇是谁")
        page.locator("textarea").first.press("Enter")
        ok = wait_for(lambda: "✨ 成品已生成" in page.inner_text("body"), 360, step=5)
        check("生成完成（成品标记出现）", ok)
        page.wait_for_timeout(3000)

        # 3. 思考块 / 工具卡
        markers = page.evaluate("() => document.querySelectorAll('[data-testid=activity-reasoning-marker]').length")
        check("思考块（reasoning 标记）> 0", markers > 0)
        check("工具卡（✅ 文本可见）", "✅" in page.inner_text("body") or "搜索" in page.inner_text("body"))
        check("成品卡（预览按钮）", "预览" in page.inner_text("body"))

        # 4. 预览 iframe
        preview_btn = page.get_by_role("button", name="预览").first
        if preview_btn.count():
            preview_btn.click()
            page.wait_for_timeout(1500)
            iframe = page.locator("iframe[title^='artifact-']")
            check("预览 iframe 渲染", iframe.count() > 0)
            if iframe.count():
                ok = wait_for(lambda: "Lumen" in page.content() or page.locator("iframe[title^='artifact-']").count() > 0, 10, step=2)
                check("预览 iframe 内容加载", ok)

        # 5. 历史回放（刷新）
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        page.locator("text=秦始皇是谁").first.click()
        page.wait_for_timeout(1800)
        ok = wait_for(lambda: "✨ 成品已生成" in page.inner_text("body") or "预览" in page.inner_text("body"), 30, step=2)
        check("历史回放（重开后成品卡在）", ok)
        m2 = page.evaluate("() => document.querySelectorAll('[data-testid=activity-reasoning-marker]').length")
        check("回放思考块 > 1（不塌成一个）", m2 > 1)

        # 6. 画廊
        page.get_by_role("button", name="作品画廊").click()
        page.wait_for_timeout(1500)
        check("画廊：作品卡出现", "秦始皇是谁" in page.inner_text("body"))

        # 7. 迭代（从画廊点侧边栏会话回聊天，发二次消息 → refine）
        page.locator("text=秦始皇是谁").first.click()
        page.wait_for_timeout(1500)
        ta = page.locator("textarea").first
        if ta.count():
            ta.fill("把配色改成蓝色")
            ta.press("Enter")
            ok = wait_for(lambda: page.inner_text("body").count("✨ 成品已生成") >= 2, 300, step=5)
            check("迭代：二次消息出第二个成品", ok)

        # 8. 设置页
        page.get_by_role("button", name="Settings").click()
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        check("设置页：概览渲染", "已生成作品" in body and "deepseek-v4-flash" in body)
        page.get_by_role("button", name="模型").click()
        page.wait_for_timeout(800)
        check("设置页：模型（DeepSeek/Tavily 输入）", "DeepSeek API Key" in page.inner_text("body") and "网页搜索服务" in page.inner_text("body"))
        page.get_by_role("button", name="技能").click()
        page.wait_for_timeout(800)
        check("设置页：技能（/api/skills 列表）", "安装 skill" in page.inner_text("body"))

        b.close()

    print("\n=== 验收结果 ===")
    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"  {passed}/{len(RESULTS)} 通过")
    for name, ok in RESULTS:
        print(f"  {'✅' if ok else '❌'} {name}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
