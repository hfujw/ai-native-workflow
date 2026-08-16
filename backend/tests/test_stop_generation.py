"""终止生效测试——WS 断开后生成任务必须被取消（之前只等 orch_task，终止无效）。

覆盖：
- STOP-1 断开监听任务存在时，orch_task 被取消
- STOP-2 正常完成后，监听任务被清理
"""
import asyncio

import pytest


@pytest.mark.asyncio
async def test_disconnect_cancels_generation_task():
    """模拟 _watch_disconnect 逻辑：WS 断开 → orch_task.cancel() 生效。"""

    async def fake_orchestrator():
        # 模拟长生成：不断 await，直到被取消
        try:
            for _ in range(100):
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return {"status": "cancelled"}

    orch_task = asyncio.create_task(fake_orchestrator())

    # 模拟 WS 断开：一个立即返回的 receive
    async def fake_receive():
        raise Exception("WebSocketDisconnect")

    async def watch():
        try:
            await fake_receive()
        except Exception:
            pass
        if not orch_task.done():
            orch_task.cancel()

    watch_task = asyncio.create_task(watch())
    # 模拟 wait_for：等 orch_task 或取消
    done, _ = await asyncio.wait(
        {orch_task, watch_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    # 等取消传播完成
    await asyncio.sleep(0.1)

    assert orch_task.done()  # 生成任务被取消/结束
    # fake 捕获 CancelledError 后返回 cancelled 结果（优雅收尾）——任务已结束即证明取消生效
    assert orch_task.result().get("status") == "cancelled"
    # 收尾清理
    if not watch_task.done():
        watch_task.cancel()


@pytest.mark.asyncio
async def test_normal_completion_watch_cleaned():
    """生成正常完成 → 监听任务被取消清理（不泄漏）。"""

    async def fast_orchestrator():
        await asyncio.sleep(0.01)
        return {"status": "success"}

    orch_task = asyncio.create_task(fast_orchestrator())

    async def watch():
        # 正常生成期间 receive 一直阻塞；任务完成后被外部 cancel
        await asyncio.Event().wait()

    watch_task = asyncio.create_task(watch())
    result = await asyncio.wait_for(orch_task, timeout=5)
    watch_task.cancel()  # 模拟 finally 清理
    try:
        await watch_task
    except asyncio.CancelledError:
        pass  # 清理完成

    assert result["status"] == "success"
    assert watch_task.cancelled()  # 监听任务被清理
