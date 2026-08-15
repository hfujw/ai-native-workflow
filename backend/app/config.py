"""集中配置管理 — pydantic-settings 从 .env + 环境变量加载。

所有模块通过 `from app.config import settings` 获取配置，
不再各自读 os.getenv() 或硬编码常量。
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 未定义的环境变量不报错
    )

    # ── LLM ──
    # 默认 API Key 可选：用户在前端设置里填（会话级绑定，优先于这里）；
    # 这里没配、前端也没填 → 生成时报"未配置 API Key"（不静默、不让启动卡死）
    deepseek_api_key: str = Field("", description="DeepSeek API Key（可选；前端填的优先）")
    deepseek_base_url: str = Field("https://api.deepseek.com")
    deepseek_model: str = Field("deepseek-chat")

    # ── 搜索（用户在前端设置里填搜索服务的 Key——不回落 .env，没填 = 不联网） ──

    # ── 预算（可通过 env 覆盖，调试和部署时都能改） ──
    max_steps: int = Field(20, ge=1, le=100)
    budget_total: float = Field(1.0, gt=0)
    search_max: int = Field(8, ge=0, le=20)
    # LLM 步数 = 每类 LLM 内部决策循环（重试）的上限：
    # render 自检重试 / design 重试 / search 换词 / 质量审查回退
    llm_steps: int = Field(10, ge=1, le=100)

    # ── WebSocket ──
    max_connections: int = Field(20, ge=1)
    receive_timeout: int = Field(30, ge=5)
    generation_timeout: int = Field(300, ge=60)

    # ── 安全（本地工具的健壮性护栏，非公网防护）──
    input_max_length: int = Field(500, ge=10, le=2000, description="用户输入最大长度（字符）")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:1420", "http://127.0.0.1:1420",  # tauri dev 窗口
            "http://tauri.localhost",                          # tauri 打包后 webview 源
        ],
        description="CORS 白名单（Tauri 桌面端访问本地后端用）",
    )

    # ── 日志 ──
    log_prompts: bool = Field(False, description="是否在日志中记录完整 prompt（调试用）")
    log_retention_days: int = Field(30, ge=1, le=365, description="日志保留天数")

    # ── 断路器 ──
    circuit_failure_threshold: int = Field(3, ge=1)
    circuit_recovery_timeout: int = Field(30, ge=5)

    # ── 质量审查（四维对抗：事实/覆盖/可读/美学）──
    judge_enabled: bool = Field(True, description="生成后执行质量审查（额外一次 LLM 调用）")
    # 审查回退轮数上限（用户拍板 ≤2 轮）——同时受 llm_steps 钳制（min 取小）
    judge_max_retries: int = Field(2, ge=0, le=5, description="审查不通过的最大回退轮数，超限诚实交付")

    # ── 工具级参数（不同工具不同行为——调试就是改这里，不是改代码）──
    tool_decide_temperature: float = Field(0.5, ge=0, le=2)
    tool_decide_max_tokens: int = Field(2048, ge=100, le=16384)
    tool_design_temperature: float = Field(0.3, ge=0, le=2)
    tool_design_max_tokens: int = Field(2048, ge=100, le=16384)
    tool_compose_temperature: float = Field(0.5, ge=0, le=2)
    tool_compose_max_tokens: int = Field(4096, ge=100, le=16384)
    tool_render_temperature: float = Field(0.3, ge=0, le=2)
    tool_render_max_tokens: int = Field(16384, ge=100, le=32768)

    @field_validator("log_prompts", mode="before")
    @classmethod
    def parse_bool(cls, v):
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes", "on")
        return bool(v)


@lru_cache
def get_settings() -> Settings:
    """单例，启动时只解析一次 .env。"""
    return Settings()


settings = get_settings()
