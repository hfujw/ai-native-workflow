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
    deepseek_api_key: str = Field(..., description="DeepSeek API Key")
    deepseek_base_url: str = Field("https://api.deepseek.com")
    deepseek_model: str = Field("deepseek-chat")

    # ── 搜索 ──
    tavily_api_key: str = Field("", description="Tavily Search API Key（免费1000次/月，国内可访问）")

    # ── 预算（可通过 env 覆盖，调试和部署时都能改） ──
    max_steps: int = Field(20, ge=1, le=100)
    budget_total: float = Field(1.0, gt=0)
    search_max: int = Field(8, ge=0, le=20)

    # ── 限流 ──
    daily_budget: float = Field(5.0, gt=0)
    trials_per_ip: int = Field(1, ge=0)

    # ── WebSocket ──
    max_connections: int = Field(20, ge=1)
    receive_timeout: int = Field(30, ge=5)
    generation_timeout: int = Field(300, ge=60)

    # ── 安全 ──
    input_max_length: int = Field(500, ge=10, le=2000, description="用户输入最大长度（字符）")
    max_connections_per_ip: int = Field(3, ge=1, le=20, description="单 IP 最大并发连接数")
    trust_proxy: bool = Field(False, description="是否信任反向代理的 X-Forwarded-For 头（docker-compose + Caddy 部署时设 true，防止伪造 XFF 绕过限流）")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="CORS 白名单（dev 走 vite 代理同源，直连时才需要；上线前按需收紧）",
    )

    # ── 日志 ──
    log_prompts: bool = Field(False, description="是否在日志中记录完整 prompt（调试用）")
    log_retention_days: int = Field(30, ge=1, le=365, description="日志保留天数")

    # ── 状态后端 ──
    state_backend: str = Field("memory", description="memory | redis")
    redis_url: str = Field("redis://localhost:6379")

    # ── 断路器 ──
    circuit_failure_threshold: int = Field(3, ge=1)
    circuit_recovery_timeout: int = Field(30, ge=5)

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

    @field_validator("deepseek_api_key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DEEPSEEK_API_KEY 必须设置且不能为空")
        return v.strip()


@lru_cache
def get_settings() -> Settings:
    """单例，启动时只解析一次 .env。"""
    return Settings()


settings = get_settings()
