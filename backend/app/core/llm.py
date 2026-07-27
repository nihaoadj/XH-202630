from functools import lru_cache
from langchain_openai import ChatOpenAI
from app.config import get_settings


@lru_cache()
def get_llm() -> ChatOpenAI:
    """统一大模型封装，兼容 OpenAI 格式与国产大模型 API

    实例被缓存，避免每次 Agent 调用时重复初始化。
    """
    settings = get_settings()
    return ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0.3,
    )
