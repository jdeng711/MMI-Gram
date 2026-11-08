"""
Structured Logging, Security Redaction, and Agent Tracing for MMI-Gram.

Provides observability into:
  - Which agent / node is currently active
  - Exact information and state fields received
  - Structured output delta returned
  - Conditional router evaluations and decisions
  - Human review triggers and state interventions
  - Strict redaction of GCS signed URLs, credentials, tokens, and sensitive query parameters
"""

from __future__ import annotations
import re
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field, asdict


# ──────────────────────────────────────────────────────────────────────────────
# Security & Redaction Patterns
# ──────────────────────────────────────────────────────────────────────────────

# 1. Google Cloud Storage signed URLs: match query string starting after ?
# Preserves bucket and blob name for provenance/debugging, strips signature/credentials
GCS_SIGNED_URL_PATTERN = re.compile(
    r'https?://storage\.googleapis\.com/([^?#\s"\'<>]+)\?[^\s"\'<>]+',
    re.IGNORECASE,
)

# 2. Sensitive query parameters in URLs (Signature, X-Goog-*, token, key, etc.)
SENSITIVE_PARAM_PATTERN = re.compile(
    r'([?&](?:X-Goog-[A-Za-z0-9_-]+|Signature|sig|auth|token|key|api_key|password|secret|bearer)=)[^&\s"\'<>]+',
    re.IGNORECASE,
)

# 3. Authorization Bearer tokens
BEARER_PATTERN = re.compile(r'(?i)(Bearer\s+)[A-Za-z0-9_\-\.]{15,}')

# 4. Standard Google API keys (AIzaSy...)
API_KEY_PATTERN = re.compile(r'AIzaSy[A-Za-z0-9_\-]{10,}')


def redact_sensitive_strings(text: str) -> str:
    """
    Redact signed GCS URLs, authentication tokens, API keys, and sensitive query parameters
    from string data before logging, disk persistence, or terminal display.
    """
    if not isinstance(text, str):
        return text

    # Redact GCS signed URLs: keep bucket and blob path, redact query string
    text = GCS_SIGNED_URL_PATTERN.sub(r'https://storage.googleapis.com/\1?[REDACTED_SIGNATURE]', text)
    # Redact specific query parameters
    text = SENSITIVE_PARAM_PATTERN.sub(r'\1[REDACTED]', text)
    # Redact Bearer tokens
    text = BEARER_PATTERN.sub(r'\1[REDACTED_TOKEN]', text)
    # Redact Google API keys
    text = API_KEY_PATTERN.sub(r'[REDACTED]', text)
    return text


def sanitize_payload(data: Any, max_len: int = 120) -> Any:
    """
    Recursively sanitize dictionaries, lists, and strings to eliminate signed URLs,
    tokens, and binary blobs while retaining structured diagnostics.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            lower_k = str(k).lower()
            if lower_k in ("raw_media_part", "file_bytes", "binary_data"):
                sanitized[k] = "<binary_data_omitted>"
            elif lower_k in (
                "private_key",
                "client_secret",
                "password",
                "api_key",
                "token",
                "access_token",
                "secret",
                "credentials",
                "authorization",
            ):
                sanitized[k] = "[REDACTED]"
            elif lower_k in ("signed_url", "url") and isinstance(v, str):
                sanitized[k] = redact_sensitive_strings(v)
            elif lower_k == "mmi_documents":
                doc_count = len(v) if isinstance(v, list) else 0
                sanitized[k] = f"<List of {doc_count} reference documents>"
            else:
                sanitized[k] = sanitize_payload(v, max_len=max_len)
        return sanitized
    elif isinstance(data, list):
        if len(data) > 8:
            # Summarize long lists but sanitize sample elements
            return [sanitize_payload(item, max_len=max_len) for item in data[:5]] + [f"<... {len(data) - 5} more items>"]
        return [sanitize_payload(item, max_len=max_len) for item in data]
    elif isinstance(data, str):
        redacted = redact_sensitive_strings(data)
        if len(redacted) > max_len:
            return redacted[:max_len] + f"... [truncated {len(redacted)} chars]"
        return redacted
    else:
        return data


def summarize_state(state: Dict[str, Any], max_len: int = 120) -> Dict[str, Any]:
    """
    Sanitize and summarize state dictionary to prevent dumping megabytes of raw bytes
    or leaking signed URLs, while retaining critical decision fields.
    """
    if not isinstance(state, dict):
        return {"value": redact_sensitive_strings(str(state))[:max_len]}
    return sanitize_payload(state, max_len=max_len)


# ──────────────────────────────────────────────────────────────────────────────
# Structured Event & Logger
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentEvent:
    """Structured event capturing a step in the agent workflow."""
    timestamp_utc: str
    agent_name: str
    event_type: str  # 'NODE_ENTER', 'NODE_EXIT', 'ROUTER_DECISION', 'REVIEW_ACTION', 'ERROR'
    duration_ms: Optional[float] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return sanitize_payload(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class StructuredAgentLogger:
    """
    Structured logger and tracer for LangGraph nodes and agents.
    Outputs clean visual blocks to stdout/loggers with strict redaction of sensitive data.
    """

    def __init__(
        self,
        name: str = "mmigram.agent",
        console_output: bool = True,
        log_file: Optional[str] = None,
    ):
        self.logger = logging.getLogger(name)
        self.console_output = console_output
        self.log_file = log_file
        self.events: List[AgentEvent] = []

    def log_node_enter(self, agent_name: str, state: Dict[str, Any]) -> AgentEvent:
        """Record node entrance and input state snapshot."""
        now_iso = datetime.now(timezone.utc).isoformat()
        sanitized_inputs = summarize_state(state)

        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=agent_name,
            event_type="NODE_ENTER",
            inputs=sanitized_inputs,
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print("\n" + "=" * 70)
            print(f"🤖 [AGENT START] Node: '{agent_name}' | UTC: {now_iso}")
            print("📥 Information Received (Input State Snapshot):")
            print(json.dumps(sanitized_inputs, indent=2, default=str))
            print("-" * 70)

        return event

    def log_node_exit(
        self,
        agent_name: str,
        output_delta: Dict[str, Any],
        duration_ms: float,
    ) -> AgentEvent:
        """Record node exit, returned state updates, and duration."""
        now_iso = datetime.now(timezone.utc).isoformat()
        sanitized_outputs = summarize_state(output_delta)

        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=agent_name,
            event_type="NODE_EXIT",
            duration_ms=round(duration_ms, 2),
            outputs=sanitized_outputs,
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"📤 Output Returned by '{agent_name}' (took {duration_ms:.2f} ms):")
            print(json.dumps(sanitized_outputs, indent=2, default=str))
            print(f"🏁 [AGENT FINISHED] Node: '{agent_name}'")
            print("=" * 70)

        return event

    def log_router_decision(
        self,
        router_name: str,
        condition_key: str,
        condition_value: Any,
        target_node: str,
    ) -> AgentEvent:
        """Record a conditional routing evaluation."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_val = redact_sensitive_strings(str(condition_value))
        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=router_name,
            event_type="ROUTER_DECISION",
            inputs={condition_key: clean_val},
            outputs={"next_node": target_node},
            metadata={
                "condition_key": condition_key,
                "condition_value": clean_val,
                "target_node": target_node,
            },
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"🔀 [ROUTER] '{router_name}' evaluated '{condition_key}' = '{clean_val}' -> routing to '{target_node}'")

        return event

    def log_review_action(
        self,
        item_id: str,
        action: str,
        reviewer_id: str,
        notes: str,
    ) -> AgentEvent:
        """Record a human review intervention."""
        now_iso = datetime.now(timezone.utc).isoformat()
        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name="human_review_queue",
            event_type="REVIEW_ACTION",
            metadata={
                "item_id": item_id,
                "action": action,
                "reviewer_id": reviewer_id,
                "notes": redact_sensitive_strings(notes),
            },
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"👤 [HUMAN REVIEW] Item '{item_id}' updated: Action='{action}', Reviewer='{reviewer_id}', Notes='{notes}'")

        return event

    def log_error(self, agent_name: str, error: Exception) -> AgentEvent:
        """Record an exception encountered within an agent."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_msg = redact_sensitive_strings(str(error))
        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=agent_name,
            event_type="ERROR",
            metadata={"error_type": type(error).__name__, "error_message": clean_msg},
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"❌ [AGENT ERROR] Node: '{agent_name}' raised {type(error).__name__}: {clean_msg}")

        return event

    def wrap_node(self, agent_name: str, node_func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable:
        """Decorator/wrapper that instruments any node function with structured logging."""
        def traced_node(state: Dict[str, Any]) -> Dict[str, Any]:
            self.log_node_enter(agent_name, state)
            t0 = time.perf_counter()
            try:
                output = node_func(state)
                duration_ms = (time.perf_counter() - t0) * 1000.0
                self.log_node_exit(agent_name, output, duration_ms)
                return output
            except Exception as e:
                self.log_error(agent_name, e)
                raise
        traced_node.__name__ = f"traced_{agent_name}"
        return traced_node

    def get_events(self) -> List[AgentEvent]:
        """Return a copy of all recorded events."""
        return list(self.events)

    def clear(self) -> None:
        """Clear all recorded events."""
        self.events.clear()

    def _write_event(self, event: AgentEvent) -> None:
        """Persist structured event if a log file is configured."""
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(event.to_json() + "\n")
            except Exception:
                pass
