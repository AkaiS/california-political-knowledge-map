import os
from dotenv import load_dotenv
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

def get_ollama_model(
    default_model: str,
    env_var_name: str | None = None,
) -> OllamaModel:
    """
    Get a configured OllamaModel instance.
    
    Loads configuration from environment variables:
    1. Base URL is read from `OLLAMA_BASE_URL` (default: "http://localhost:11434").
       Automatically ensures the URL ends with "/v1".
    2. Model name is read from:
       - The custom `env_var_name` if specified (e.g., OLLAMA_MODEL_HEALING).
       - Fallback to the general `OLLAMA_MODEL` environment variable.
       - Fallback to the provided `default_model`.
    """
    load_dotenv()
    
    # 1. Resolve Base URL
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    base_url = ollama_base_url
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
        
    provider = OllamaProvider(base_url=base_url)
    
    # 2. Resolve Model Name
    model_name = None
    if env_var_name:
        model_name = os.environ.get(env_var_name)
        
    if not model_name:
        model_name = os.environ.get("OLLAMA_MODEL")
        
    if not model_name:
        model_name = default_model
        
    return OllamaModel(model_name=model_name, provider=provider)
