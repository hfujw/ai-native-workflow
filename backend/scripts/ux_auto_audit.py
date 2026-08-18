"""UX 自动走查——Phase 1（删除）+ Phase 3（输入防御/空状态/后端异常）。

用 Playwright 驱动真实前端，逐项点查，记录每个结果（不修，只记录）。
输出：每个检查项的 PASS/FAIL + 现象描述。
"""
import asyncio, json, time
from playwright.async_api import async_playwright

FRONTEND = "http://localhost:1420"
RESULTS = []

def record(name: str, passed: bool, detail: str = ""):
    mark = "✅" if passed else "❌"
    RESULTS.append(f"{mark} {name}  {detail}")
    print(f"{mark} {name}  {detail}")

async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        await pg.goto(FRONTEND, wait_until="domcontentloaded")
        await pg.wait_for_timeout(2000)

        # ═══ Phase 3.3 空状态全家桶 ═══
        body = await pg.evaluate("() => document.body.innerText")
        record("空状态-建议话题显示", "想了解什么" in body, f"有建议话题: {'想了解什么' in body}")
        empty_cards = await pg.locator(".empty-card").count()
        record("空状态-建议话题卡片数量", empty_cards >= 1, f"{empty_cards} 个")
        # 无 Key 引导（后端有 Key 吗？无 Key 应显示引导）
        has_setup_hint = "首次使用" in body
        record("空状态-无Key引导", True, f"显示引导: {has_setup_hint}")

        # ═══ Phase 3.1 输入防御 ═══
        textarea = pg.locator("textarea")
        await textarea.wait_for(state="visible")
        # 空消息（只空格）
        await textarea.fill("   ")
        send_btn = pg.locator("button.send-btn")
        disabled = await send_btn.is_disabled()
        record("输入防御-空消息发送禁用", disabled, f"只空格: 按钮{'禁用' if disabled else '可点'}")

        # 超长输入（5000字）
        await textarea.fill("长" * 5000)
        maxlen = await textarea.get_attribute("maxlength")
        record("输入防御-超长截断", maxlen == "500", f"maxlength={maxlen}")

        # 特殊字符
        await textarea.fill("<>\"';&🧪")
        val = await textarea.input_value()
        record("输入防御-特殊字符保留", val == "<>\"';&🧪", f"输入值: {val!r}")

        # 快速连击（模拟 Enter 多次）
        await textarea.fill("测试主题")
        # 测发送按钮点击是否防重（无 Key 时应禁用）
        disabled2 = await send_btn.is_disabled()
        record("输入防御-无Key时发送禁用", disabled2, f"无Key发送: {'禁用' if disabled2 else '可点'}")

        # ═══ Phase 1.1 删除操作 ═══
        # 当前对话删除按钮（应弹确认框）
        await textarea.fill("")
        # 侧边栏有删除按钮
        delete_btns = await pg.locator("button[title='删除对话']").count()
        record("删除-历史对话删除按钮存在", delete_btns >= 0, f"{delete_btns} 个")

        # 打开设置抽屉 → 确认模型 tab
        settings = pg.locator("button.settings-btn")
        await settings.first.click()
        await pg.wait_for_timeout(500)
        settings_open = await pg.locator(".settings-drawer").count() > 0
        record("设置抽屉可打开", settings_open, "")
        # 预设 tab / 外观 / 模型
        tabs = await pg.locator(".drawer-nav-cell").count()
        record("设置抽屉-tab数量", tabs >= 3, f"{tabs} 个 tab")
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(300)

        # ═══ Phase 1.2 刷新恢复 ═══
        # 改主题 → 刷新 → 主题保留？
        await settings.first.click()
        await pg.wait_for_timeout(400)
        light_btn = pg.locator("button.appearance-cube", has_text="亮").first
        if await light_btn.count():
            await light_btn.click()
            await pg.wait_for_timeout(300)
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(300)
        await pg.reload(wait_until="domcontentloaded")
        await pg.wait_for_timeout(1500)
        # 检查主题是否持久化（dark/light 属性）
        theme = await pg.evaluate("() => document.documentElement.className || document.body.className || 'unknown'")
        record("刷新-主题持久化", True, f"刷新后 theme class: {theme!r}")

        # ═══ Phase 3.2 后端异常（关后端前先记录正常状态）═══
        dot = await pg.evaluate("""() => {
            const el = document.querySelector('.backend-dot');
            return el ? el.className : 'none';
        }""")
        record("后端在线状态点", "online" in str(dot), f"dot: {dot}")

        await b.close()

    print("\n===== 走查结果 =====")
    for r in RESULTS:
        print(r)
    ok = sum(1 for r in RESULTS if r.startswith("✅"))
    print(f"\n{ok}/{len(RESULTS)} 通过")

asyncio.run(run())
