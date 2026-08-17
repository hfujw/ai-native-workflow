"""task 4 · README 截图自动化脚本（Playwright 驱动前端，全本地）。

流程（对应 docs/error-states.md 与 docs/ROADMAP 的产品验收）：
  1. 打开前端 localhost:1420（默认）或 Tauri 窗口
  2. 选「知识探险家」预设，输入主题，点发送
  3. 等生成完成（complete 事件）——期间 thinking 卡片流留作截图素材
  4. 产物质量自动打分（artifact_quality），≥4/5 才截"产物预览"图
  5. 截 3 张图：
     01-composer.webp   创作区（含 thinking 卡片流 + Composer）
     02-preview.webp    产物首屏（窗口级，滚动到首个 section）
     03-trace.webp      思考回放抽屉（展开一个阶段）
  6. 全部本地：只操作 localhost，截图存 desktop/screenshots/，不经过任何第三方服务

用法（先手动启动后端 8001 + 前端 1420，再跑）：
    ../venv/Scripts/python scripts/capture_demo.py "恐龙为什么灭绝"
 环境变量：
   LUMEN_FRONTEND_URL  前端地址（默认 http://localhost:1420）
   LUMEN_OUT_DIR       截图输出目录（默认 desktop/screenshots）
   LUMEN_TIMEOUT       生成超时秒（默认 180）
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

# 确保 backend 可导入（artifact_quality）
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.observability.artifact_quality import assess_artifact  # noqa: E402

FRONTEND_URL = os.getenv("LUMEN_FRONTEND_URL", "http://localhost:1420")
OUT_DIR = Path(os.getenv("LUMEN_OUT_DIR", BACKEND_ROOT.parent / "desktop" / "screenshots"))
TIMEOUT_MS = int(os.getenv("LUMEN_TIMEOUT", "180")) * 1000
# Key 注入（可选）：设了就用 JS 写入 localStorage（浏览器源 localhost:1420 与 Playwright 共享）；
# 不设则要求用户已在浏览器设置里手动填过。二者选一。
LUMEN_LLM_KEY = os.getenv("LUMEN_LLM_KEY", "").strip()
LUMEN_TAVILY_KEY = os.getenv("LUMEN_TAVILY_KEY", "").strip()


async def _inject_keys(page) -> None:
    """把环境变量里的 Key 写入前端 localStorage（与设置页同名 key，刷新即生效）。"""
    if not (LUMEN_LLM_KEY or LUMEN_TAVILY_KEY):
        return
    await page.evaluate(
        """([llmKey, tavilyKey]) => {
            const creds = JSON.parse(localStorage.getItem('lumen.providerCreds') || '{}');
            if (llmKey) {
                creds['DeepSeek'] = { ...(creds['DeepSeek'] || {}), apiKey: llmKey,
                                      apiBase: 'https://api.deepseek.com' };
            }
            localStorage.setItem('lumen.providerCreds', JSON.stringify(creds));
            if (tavilyKey) {
                const svcs = JSON.parse(localStorage.getItem('lumen.searchServices') || '[]');
                const t = svcs.find((s) => s.id === 'tavily');
                if (t) { t.apiKey = tavilyKey; localStorage.setItem('lumen.searchServices', JSON.stringify(svcs)); }
            }
        }"""
        , [LUMEN_LLM_KEY, LUMEN_TAVILY_KEY])
    await page.reload(wait_until="domcontentloaded")
    await page.wait_for_timeout(800)

# ── Q1 决策：截图等稳定，不等固定 sleep ──
# 抽屉 200ms 动画 → 等 transitionend；产物 iframe → 等 h1 存在 + readyState complete
DRAWER_ANIM_MS = 400      # traceIn 0.2s + 余量
IFRAME_SETTLE_MS = 600    # srcDoc 注入 + 内部资源 100ms 级


async def _screenshot(page, path: Path):
    """截图（WebP，GitHub 渲染友好）+ 净化滚动条。"""
    # Q4 决策：截图前隐藏滚动条 + 等 toast 消失 + 输入框失焦
    await page.evaluate(
        """() => {
            const css = document.createElement('style');
            css.textContent = '*::-webkit-scrollbar{display:none} *{scrollbar-width:none}';
            document.head.appendChild(css);
            document.activeElement?.blur();
        }"""
    )
    await page.wait_for_timeout(150)  # toast 淡出
    await page.screenshot(path=str(path), type="webp", full_page=False)
    print(f"  📸 {path.relative_to(BACKEND_ROOT.parent)}")


async def _wait_drawer_settled(page) -> None:
    """Q1 决策：等抽屉 transform 动画结束，再等 100ms 余量。"""
    await page.wait_for_timeout(DRAWER_ANIM_MS)


def _quality_badge(html: str) -> str:
    """产物质量打分，返回 '4/5' 之类。"""
    r = assess_artifact(html)
    return f"{r['score']}/5"


async def run(topic: str) -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        # Q5 决策：强制浅色（产物浅色杂志风，三图风格统一）
        browser = await p.chromium.launch(
            args=["--force-light-mode", "--disable-features=WebContentsForceDark"],
        )
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        print(f"打开前端 {FRONTEND_URL} …")
        await page.goto(FRONTEND_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(800)
        await _inject_keys(page)

        # ── 1. 输入主题 ──
        textarea = page.locator("textarea")
        await textarea.wait_for(state="visible", timeout=10_000)
        await textarea.fill(topic)

        # ── 2. 发送 ──
        send_btn = page.locator("button.send-btn")
        await send_btn.wait_for(state="visible")
        await send_btn.click()
        print("已发送，等待生成…")

        # ── 3. 等生成完成：出现"成品卡"（assistant html 消息）──
        # 通过成品卡内 iframe 出现判定；最多等 TIMEOUT_MS
        deadline = time.monotonic() + TIMEOUT_MS / 1000
        html_msg = None
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1500)
            # 方式1（最可靠）：直接读 iframe 的 srcdoc 属性（无需跨帧）
            srcdoc = await page.evaluate(
                """() => {
                    const ifs = document.querySelectorAll('iframe[srcdoc]');
                    for (const f of ifs) {
                        const doc = f.srcdoc || '';
                        if (doc.includes('<h1') || doc.includes('<h2')) return doc;
                    }
                    return null;
                }"""
            )
            if srcdoc:
                html_msg = srcdoc
                break
            # 方式2（兜底）：跨帧读 documentElement（sandbox 允许时）
            if not html_msg:
                for f in page.frames:
                    try:
                        if f != page.main_frame and await f.evaluate("() => document.readyState") == "complete":
                            has_h1 = await f.evaluate("() => !!document.querySelector('h1')")
                            if has_h1:
                                html_msg = await f.evaluate("() => document.documentElement.outerHTML")
                                break
                    except Exception:
                        continue
            if html_msg:
                break
            # 中途检查是否失败（错误卡片）
            err = await page.locator(".tc-error").count()
            if err:
                print("⚠️ 生成失败卡片出现，查看前端")
                break

        if not html_msg:
            print("❌ 超时未生成产物")
            await browser.close()
            return 1

        # ── 4. 产物质量打分（Q4 决策：≥4/5 才截产物图）──
        quality = assess_artifact(html_msg)
        print(f"🎯 产物质量: {quality['score']}/5")
        for dim, (ok, detail) in quality["results"].items():
            print(f"   {'✅' if ok else '❌'} {dim}: {detail}")

        # 等最终 thinking 卡片流稳定（绿勾）
        await page.wait_for_timeout(1500)

        # ── 5. 图1：创作区（thinking 卡片流 + Composer）──
        await _screenshot(page, OUT_DIR / "01-composer.webp")

        # ── 6. 图2：产物首屏（窗口级，滚动到首个 section）──
        # Q3 决策：找第一个 h2/section 的 offsetTop，滚到其上方 100px
        prod_frame = None
        for f in page.frames:
            try:
                if f != page.main_frame and await f.evaluate("() => !!document.querySelector('h1')"):
                    prod_frame = f
                    break
            except Exception:
                continue
        if prod_frame:
            await prod_frame.evaluate(
                """() => {
                    const sec = document.querySelector('h2, section, .figure, .tl');
                    if (sec) {
                        const y = sec.getBoundingClientRect().top + window.scrollY - 100;
                        window.scrollTo(0, Math.max(0, y));
                    }
                }"""
            )
            await page.wait_for_timeout(300)
        else:
            # srcdoc 兜底：注入临时 <style> 定位（部分 sandbox 下帧不可达）
            await page.evaluate(
                """() => {
                    const ifs = document.querySelectorAll('iframe[srcdoc]');
                    for (const f of ifs) {
                        try {
                            const doc = f.contentDocument;
                            if (!doc) continue;
                            const sec = doc.querySelector('h2, section, .figure, .tl');
                            if (sec) {
                                const y = sec.getBoundingClientRect().top + (f.getBoundingClientRect().top) - 100;
                                window.scrollTo(0, Math.max(0, window.scrollY + y - 200));
                            }
                        } catch (e) { /* 跨域忽略 */ }
                    }
                }"""
            )
            await page.wait_for_timeout(300)
        await _screenshot(page, OUT_DIR / "02-preview.webp")

        # ── 7. 图3：思考回放抽屉（展开一个阶段）──
        # 找到成品卡上的"思考过程"按钮并点击
        trace_btn = page.locator("button[title='查看 AI 的思考过程']").first
        try:
            await trace_btn.wait_for(state="visible", timeout=5000)
            await trace_btn.click()
            await _wait_drawer_settled(page)

            # Q7 决策：展开"构思设计"阶段（若存在），让 thought 可见
            design_step = page.locator(".trace-step-head", has_text="构思设计").first
            if await design_step.count() > 0:
                await design_step.click()
                await page.wait_for_timeout(200)
            await _screenshot(page, OUT_DIR / "03-trace.webp")
        except Exception as e:
            print(f"⚠️ 思考回放截图跳过: {e}")

        # ── 8. 产物归档（Q6 决策：≥4/5 才写 examples/，带元数据注释）──
        if quality["score"] >= 4:
            slug = "".join(c for c in topic if c.isalnum())[:20] or "topic"
            out_html = BACKEND_ROOT.parent / "examples" / f"{slug}.html"
            os.makedirs(out_html.parent, exist_ok=True)
            meta = (
                "<!--\n"
                "  Generated by Lumen\n"
                f"  Topic: {topic}\n"
                "  Preset: 知识探险家 · 杂志长图\n"
                f"  Quality Score: {quality['score']}/5\n"
                f"  Date: {time.strftime('%Y-%m-%d')}\n"
                "-->\n"
            )
            out_html.write_text(meta + html_msg, encoding="utf-8")
            print(f"📄 产物归档 → {out_html.relative_to(BACKEND_ROOT.parent)}")

            # Q8 决策：脱敏检查
            raw = out_html.read_text(encoding="utf-8")
            leaks = [k for k in ("sk-", "C:\\Users", "api_key") if k.lower() in raw.lower()]
            if leaks:
                print(f"⚠️ 脱敏检查发现: {leaks} —— 需人工处理")
            else:
                print("🔒 脱敏检查通过（无 Key / 绝对路径残留）")

        await browser.close()
        print("\n完成 ✅ 截图目录:", OUT_DIR)
        return 0


def main():
    parser = argparse.ArgumentParser(description="README 截图自动化")
    parser.add_argument("topic", nargs="?", default="恐龙为什么灭绝", help="要生成的主题")
    args = parser.parse_args()
    rc = asyncio.run(run(args.topic))
    sys.exit(rc)


if __name__ == "__main__":
    main()
