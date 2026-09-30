"""Public provider presets shared by initial settings and the model dialog."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    base_url: str
    default_model: str
    protocol: str = "openai-chat"
    suggested_models: tuple[str, ...] = ()
    key_site: str = ""
    local: bool = False


PROVIDER_PRESETS = (
    ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash", suggested_models=("deepseek-v4-pro",), key_site="platform.deepseek.com"),
    ProviderPreset("dashscope", "通义千问（阿里云百炼·北京）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.8-flash", suggested_models=("qwen3.7-plus", "qwen3.8-max"), key_site="bailian.console.aliyun.com"),
    ProviderPreset("moonshot", "Kimi（月之暗面）", "https://api.moonshot.cn/v1", "kimi-k3", key_site="platform.kimi.com"),
    ProviderPreset("zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-5.3", suggested_models=("glm-5.3-flash",), key_site="bigmodel.cn"),
    ProviderPreset("ark", "豆包（火山方舟）", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-2.0", key_site="console.volcengine.com/ark"),
    ProviderPreset("siliconflow", "硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3.2", suggested_models=("Pro/moonshotai/Kimi-K2.6",), key_site="cloud.siliconflow.cn"),
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-6.1-sol", protocol="openai-responses", suggested_models=("gpt-6-luna",), key_site="platform.openai.com"),
    ProviderPreset("anthropic", "Anthropic Claude", "https://api.anthropic.com/v1", "claude-sonnet-5-5", protocol="anthropic", key_site="platform.claude.com"),
    ProviderPreset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash", key_site="aistudio.google.com"),
    ProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "google/gemini-3.8-flash", key_site="openrouter.ai"),
    ProviderPreset("ollama", "Ollama（本地）", "http://localhost:11434/v1", "qwen3", local=True),
)
PRESETS_BY_ID = {preset.id: preset for preset in PROVIDER_PRESETS}


def preset_data() -> list[dict]:
    result = []
    for preset in PROVIDER_PRESETS:
        item = asdict(preset)
        item["models"] = list(dict.fromkeys((preset.default_model, *preset.suggested_models)))
        result.append(item)
    return result


def default_profiles():
    from .config import ModelProfile
    return [ModelProfile(id=p.id, name=p.name, base_url=p.base_url,
                         model=p.default_model, protocol=p.protocol)
            for p in PROVIDER_PRESETS]


def match_preset(base_url: str, protocol: str) -> str | None:
    def normalize(value):
        value = value.strip().rstrip("/")
        for suffix in ("/chat/completions", "/responses", "/messages", "/models"):
            if value.endswith(suffix):
                return value[:-len(suffix)]
        return value
    return next((p.id for p in PROVIDER_PRESETS
                 if p.protocol == protocol and normalize(p.base_url) == normalize(base_url)), None)
