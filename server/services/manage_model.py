import os
import time
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, TooManyRequests
from services.utilities import load_credentials

# Global lazy client instance
_client: Optional[genai.Client] = None

# Telemetry tracking for token usage and latency
_last_telemetry: Optional[Dict[str, Any]] = None
_session_telemetry: Dict[str, Any] = {
    "calls": 0,
    "prompt_tokens": 0,
    "candidates_tokens": 0,
    "thoughts_tokens": 0,
    "cached_tokens": 0,
    "total_tokens": 0,
    "estimated_cost_usd": 0.0,
    "invocations": []
}


def get_genai_provider() -> str:
    """Returns the active Gemini provider identifier ('ai_studio' or 'vertex_ai')."""
    try:
        from mmigram.adapters.gemini_provider import get_active_provider
        return get_active_provider()
    except ImportError:
        return os.environ.get("GEMINI_PROVIDER", "ai_studio").strip().lower()


def set_genai_provider(provider: str):
    """Explicitly switches active Gemini provider and resets client instance."""
    global _client
    clean = provider.strip().lower()
    if clean not in ("ai_studio", "vertex_ai"):
        raise ValueError(f"Invalid Gemini provider '{provider}'. Must be 'ai_studio' or 'vertex_ai'")
    try:
        from mmigram.adapters.gemini_provider import set_active_provider
        set_active_provider(clean)
    except ImportError:
        os.environ["GEMINI_PROVIDER"] = clean
    _client = None


def get_genai_client() -> genai.Client:
    """
    Initializes and returns the google-genai Client according to active provider.
    Defaults to 'ai_studio' (Google AI Studio via GEMINI_API_KEY).
    Optional: 'vertex_ai' (Google Cloud Vertex AI).
    """
    global _client
    if _client is None:
        provider = get_genai_provider()
        if provider == "ai_studio":
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError(
                    "❌ GEMINI_API_KEY or GOOGLE_API_KEY is not set.\n"
                    "To use Google AI Studio:\n"
                    "1. Obtain an API key at https://aistudio.google.com/app/apikey\n"
                    "2. Add it to your .env file: GEMINI_API_KEY=\"AIzaSy...\"\n"
                    "To use Vertex AI instead, run with: --provider vertex_ai"
                )
            _client = genai.Client(api_key=api_key.strip().strip('"').strip("'"))
        elif provider == "vertex_ai":
            project_id = os.environ.get("projectID") or os.environ.get("GCS_PROJECT_ID")
            location = os.environ.get("GCS_REGION", "us-central1")
            credentials = load_credentials()
            _client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location,
                credentials=credentials
            )
        else:
            raise ValueError(f"Unsupported Gemini provider '{provider}'. Must be 'ai_studio' or 'vertex_ai'")
    return _client


def set_genai_client(client: Optional[genai.Client]):
    """Injects or resets a custom/mock client (useful for unit testing)."""
    global _client
    _client = client


def get_safety_settings() -> List[types.SafetySetting]:
    """Returns standard research safety settings (unblocked for objective seismic assessment)."""
    return [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        )
    ]


# Supported thinking levels for Gemini 3.8 Flash
# Note: Google does NOT support MINIMAL for Gemini 3.8 Flash
SUPPORTED_THINKING_LEVELS_38 = {"HIGH", "MEDIUM", "LOW"}


def build_generation_config(
    model_name: str,
    json_mode: bool = True,
    thinking_level: Optional[str] = None
) -> types.GenerateContentConfig:
    """
    Builds GenerateContentConfig tailored to the target model.
    
    For Gemini 3.8 Flash:
      - Explicitly configures thinking_level (HIGH, MEDIUM, LOW; default: HIGH) with include_thoughts=True.
      - Rejects unsupported levels such as MINIMAL.
      - Strictly omits deprecated sampling parameters (temperature, top_p, top_k, candidate_count).
    
    For Gemini 2.5 Flash / legacy comparative models:
      - Preserves legacy sampling parameters (temperature=0.4, top_p=0.95, top_k=20, candidate_count=1).
      - Omits thinking_config.
    """
    sf_settings = get_safety_settings()
    is_gemini_38 = "3.8" in model_name.lower() or "gemini-3" in model_name.lower()

    if is_gemini_38:
        t_level_str = (thinking_level or os.environ.get("GEMINI_THINKING_LEVEL", "HIGH")).upper()
        if t_level_str not in SUPPORTED_THINKING_LEVELS_38:
            raise ValueError(
                f"Unsupported thinking level '{t_level_str}' for Gemini 3.8 Flash. "
                f"Google supports: {sorted(list(SUPPORTED_THINKING_LEVELS_38))}. "
                f"(MINIMAL is not supported for Gemini 3.8 Flash)"
            )
        level_enum = getattr(types.ThinkingLevel, t_level_str, types.ThinkingLevel.HIGH)
        thinking_cfg = types.ThinkingConfig(
            thinking_level=level_enum,
            include_thoughts=True
        )

        return types.GenerateContentConfig(
            thinking_config=thinking_cfg,
            safety_settings=sf_settings,
            response_mime_type="application/json" if json_mode else None,
        )
    else:
        # Legacy fallback configuration for comparative benchmarking (e.g. gemini-2.5-flash)
        return types.GenerateContentConfig(
            temperature=0.4,
            top_p=0.95,
            top_k=20,
            candidate_count=1,
            safety_settings=sf_settings,
            response_mime_type="application/json" if json_mode else None,
        )


class PartCompat:
    """
    Compatibility wrapper ensuring legacy vertexai Part call styles work seamlessly
    with google.genai types.Part.
    """
    @staticmethod
    def from_text(text: str = None, **kwargs) -> types.Part:
        t = text if text is not None else kwargs.get("text", "")
        return types.Part.from_text(text=t)

    @staticmethod
    def from_data(data: bytes = None, mime_type: str = None, **kwargs) -> types.Part:
        d = data if data is not None else kwargs.get("data")
        m = mime_type if mime_type is not None else kwargs.get("mime_type")
        return types.Part.from_bytes(data=d, mime_type=m)

    @staticmethod
    def from_bytes(data: bytes = None, mime_type: str = None, **kwargs) -> types.Part:
        d = data if data is not None else kwargs.get("data")
        m = mime_type if mime_type is not None else kwargs.get("mime_type")
        return types.Part.from_bytes(data=d, mime_type=m)

    @staticmethod
    def from_uri(uri: str = None, mime_type: str = None, file_uri: str = None, **kwargs) -> types.Part:
        u = uri or file_uri or kwargs.get("uri") or kwargs.get("file_uri")
        m = mime_type if mime_type is not None else kwargs.get("mime_type")
        return types.Part.from_uri(file_uri=u, mime_type=m)


# Export Part as drop-in replacement
Part = PartCompat


def get_last_telemetry() -> Optional[Dict[str, Any]]:
    """Returns telemetry from the most recent model invocation."""
    return _last_telemetry


def get_session_telemetry() -> Dict[str, Any]:
    """Returns aggregated token usage and invocation metrics across the current run."""
    return dict(_session_telemetry)


def reset_session_telemetry():
    """Resets aggregated telemetry for a new pipeline execution."""
    global _session_telemetry, _last_telemetry
    _last_telemetry = None
    _session_telemetry = {
        "calls": 0,
        "prompt_tokens": 0,
        "candidates_tokens": 0,
        "thoughts_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "invocations": []
    }


def get_model(model_name: str = None) -> str:
    """Returns the active model identifier."""
    if not model_name:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    return model_name


def get_response(
    contents: list,
    json_mode: bool = True,
    max_retries: int = 5,
    model_name: Optional[str] = None,
    thinking_level: Optional[str] = None
) -> str:
    """
    Executes model generation using Google Gen AI SDK on Vertex AI.
    
    Includes:
      - Exponential backoff retry logic on quota/rate-limits.
      - STRICT scientific requirement: NEVER silently switch models on failure.
      - Detailed token usage tracking (input, output, and thinking tokens).
    """
    global _last_telemetry
    current_model = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    current_thinking_level = thinking_level or os.environ.get("GEMINI_THINKING_LEVEL", "HIGH")

    config = build_generation_config(
        current_model,
        json_mode=json_mode,
        thinking_level=current_thinking_level
    )
    client = get_genai_client()
    backoff = 4.0

    for attempt in range(max_retries + 1):
        try:
            t0 = time.time()
            response = client.models.generate_content(
                model=current_model,
                contents=contents,
                config=config
            )
            duration = time.time() - t0

            # Extract token metrics safely from usage_metadata
            usage = getattr(response, "usage_metadata", None)

            def _to_int(v: Any) -> int:
                if isinstance(v, (int, float)):
                    return int(v)
                return 0

            prompt_tokens = _to_int(getattr(usage, "prompt_token_count", 0))
            candidates_tokens = _to_int(getattr(usage, "candidates_token_count", 0))
            thoughts_tokens = _to_int(getattr(usage, "thoughts_token_count", 0))
            cached_tokens = _to_int(getattr(usage, "cached_content_token_count", 0))
            total_tokens = _to_int(getattr(usage, "total_token_count", 0)) or (prompt_tokens + candidates_tokens)

            # Accurate pricing calculation (candidates_token_count ALREADY includes thinking tokens)
            price_prompt_m = 0.15
            price_cached_m = 0.0375
            price_candidates_m = 0.60
            unpromoted_prompt = max(0, prompt_tokens - cached_tokens)
            call_cost_usd = round(
                (unpromoted_prompt / 1_000_000.0) * price_prompt_m
                + (cached_tokens / 1_000_000.0) * price_cached_m
                + (candidates_tokens / 1_000_000.0) * price_candidates_m,
                6,
            )

            telemetry = {
                "model_identifier": current_model,
                "thinking_level": current_thinking_level if ("3.8" in current_model or "gemini-3" in current_model) else None,
                "prompt_tokens": prompt_tokens,
                "candidates_tokens": candidates_tokens,
                "thoughts_tokens": thoughts_tokens,
                "cached_tokens": cached_tokens,
                "total_tokens": total_tokens,
                "input_price_per_m": price_prompt_m,
                "cached_price_per_m": price_cached_m,
                "output_price_per_m": price_candidates_m,
                "estimated_cost_usd": call_cost_usd,
                "duration_s": round(duration, 3),
            }
            _last_telemetry = telemetry

            # Accumulate in session telemetry
            _session_telemetry["calls"] += 1
            _session_telemetry["prompt_tokens"] += prompt_tokens
            _session_telemetry["candidates_tokens"] += candidates_tokens
            _session_telemetry["thoughts_tokens"] += thoughts_tokens
            _session_telemetry["cached_tokens"] += cached_tokens
            _session_telemetry["total_tokens"] += total_tokens
            _session_telemetry["estimated_cost_usd"] = round(
                _session_telemetry.get("estimated_cost_usd", 0.0) + call_cost_usd, 6
            )
            _session_telemetry["invocations"].append(telemetry)

            return response.text or ""

        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = (
                "resource_exhausted" in err_str or 
                "429" in err_str or 
                "resource exhausted" in err_str or 
                "quota" in err_str or
                isinstance(e, (ResourceExhausted, TooManyRequests))
            )
            if is_rate_limit:
                if attempt < max_retries:
                    provider_name = "Google AI Studio" if get_genai_provider() == "ai_studio" else "Vertex AI"
                    print(f"⚠️ {provider_name} rate limit hit ({e}). Waiting {backoff:.1f}s before retry ({attempt+1}/{max_retries}) on {current_model}...")
                    time.sleep(backoff)
                    backoff *= 2.0
                    # CRITICAL SCIENTIFIC INTEGRITY REQUIREMENT:
                    # NEVER silently switch models on rate limit. Always retry on the requested model.
                else:
                    raise e
            else:
                raise e
