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
    "total_tokens": 0,
    "invocations": []
}


def get_genai_client() -> genai.Client:
    """Initializes and returns the Vertex AI google-genai Client."""
    global _client
    if _client is None:
        project_id = os.environ.get("projectID") or os.environ.get("GCS_PROJECT_ID")
        location = os.environ.get("GCS_REGION", "us-central1")
        credentials = load_credentials()
        _client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            credentials=credentials
        )
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
        "total_tokens": 0,
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
            prompt_tokens = getattr(usage, "prompt_token_count", None) or 0
            candidates_tokens = getattr(usage, "candidates_token_count", None) or 0
            thoughts_tokens = getattr(usage, "thoughts_token_count", None) or 0
            total_tokens = getattr(usage, "total_token_count", None) or (prompt_tokens + candidates_tokens)

            telemetry = {
                "model_identifier": current_model,
                "thinking_level": current_thinking_level if ("3.8" in current_model or "gemini-3" in current_model) else None,
                "prompt_tokens": prompt_tokens,
                "candidates_tokens": candidates_tokens,
                "thoughts_tokens": thoughts_tokens,
                "total_tokens": total_tokens,
                "duration_s": round(duration, 3)
            }
            _last_telemetry = telemetry

            # Accumulate in session telemetry
            _session_telemetry["calls"] += 1
            _session_telemetry["prompt_tokens"] += prompt_tokens
            _session_telemetry["candidates_tokens"] += candidates_tokens
            _session_telemetry["thoughts_tokens"] += thoughts_tokens
            _session_telemetry["total_tokens"] += total_tokens
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
                    print(f"⚠️ Vertex AI rate limit hit ({e}). Waiting {backoff:.1f}s before retry ({attempt+1}/{max_retries}) on {current_model}...")
                    time.sleep(backoff)
                    backoff *= 2.0
                    # CRITICAL SCIENTIFIC INTEGRITY REQUIREMENT:
                    # NEVER silently switch models on rate limit. Always retry on the requested model.
                else:
                    raise e
            else:
                raise e
