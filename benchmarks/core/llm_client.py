import os
import openai

def get_llm_client() -> openai.OpenAI:
    """Returns an OpenAI-compatible client based on environment variables.
    
    Supports:
    - Azure OpenAI (set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT)
    - Cloud OpenAI / Compatible (set OPENAI_API_KEY, optionally OPENAI_BASE_URL)
    - Local Ollama (default fallback)
    """
    if "AZURE_OPENAI_API_KEY" in os.environ and "AZURE_OPENAI_ENDPOINT" in os.environ:
        from openai import AzureOpenAI
        return AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"]
        )
    elif "OPENAI_API_KEY" in os.environ:
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=base_url)
        return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    else:
        # Fallback to local Ollama
        return openai.OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
