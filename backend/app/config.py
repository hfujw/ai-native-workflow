"""集中配置管理 — pydantic-settings 从环境变量加载（默认值兜底）。

Key 全部来自前端设置（会话级绑定），不在这里配置。
所有字段都有默认值——不配任何环境变量也能零配置启动。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",  # 未定义的环境变量不报错
        # 读 backend/.env（本地兜底 key 等）——pydantic-settings 默认不读 .env，
        # 必须显式声明 env_file；真实环境变量仍优先于 .env
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ── LLM ──
    # Key 优先来自前端设置（会话级绑定，LobeChat/WebUI 传 Authorization）。
    # 本地 WebUI 没有填 key 的 UI（task 14 补）——deepseek_api_key 作 .env 兜底，
    # 仅当无会话级 key 时生效；可空（空 = 没配，报 LLMNotConfiguredError）。
    deepseek_base_url: str = Field("https://api.deepseek.com")
    deepseek_api_key: str = Field("", description="本地 WebUI 兜底 API Key（.env 填，可空）")

    # ── 步数护栏（计费已砍——防跑飞靠步数上限，不追金额） ──
    max_steps: int = Field(20, ge=1, le=100)
    search_max: int = Field(8, ge=0, le=20)
    # 创意脑数量（创作阶段人海战术：并行发散的子脑数）。默认 3，硬核创意可调 5-6。
    creative_swarm_size: int = Field(3, ge=1, le=6)
    # LLM 步数 = 每类 LLM 内部决策循环（重试）的上限：
    # render 自检重试 / design 重试 / search 换词 / 质量审查回退
    llm_steps: int = Field(10, ge=1, le=100)

    # ── 安全（本地工具的健壮性护栏，非公网防护）──
    input_max_length: int = Field(500, ge=10, le=2000, description="用户输入最大长度（字符）")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:1420", "http://127.0.0.1:1420",  # tauri dev 窗口
            "http://tauri.localhost",                          # tauri 打包后 webview 源
        ],
        description="CORS 白名单（Tauri 桌面端访问本地后端用）",
    )

    # ── 质量审查（四维对抗：事实/覆盖/可读/美学）──
    judge_enabled: bool = Field(True, description="生成后执行质量审查（额外一次 LLM 调用）")
    # 审查回退轮数上限（用户拍板 ≤2 轮）——同时受 llm_steps 钳制（min 取小）
    judge_max_retries: int = Field(2, ge=0, le=5, description="审查不通过的最大回退轮数，超限诚实交付")

    # ── 工具级参数（仅保留被读的；其余温度/maxtokens 已随死代码清理，工具内硬编码） ──
    tool_render_max_tokens: int = Field(32768, ge=100, le=32768)  # render 生成完整教育网页需要更多 token，16384 会截断


@lru_cache
def get_settings() -> Settings:
    """单例，启动时只解析一次 .env。"""
    return Settings()


settings = get_settings()
