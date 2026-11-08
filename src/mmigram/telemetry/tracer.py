"""
Structured Logging and Agent Tracing for MMI-Gram LangGraph Workflows.

Provides observability into:
  - Which agent / node is currently active
  - Exact information and state fields received
  - Structured output delta returned
  - Conditional router evaluations and decisions
  - Human review triggers and state interventions
"""

import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field, asdict


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
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


def summarize_state(state: Dict[str, Any], max_len: int = 120) -> Dict[str, Any]:
    """
    Sanitize and summarize state dictionary to prevent dumping megabytes of raw bytes,
    while retaining critical decision fields (blob_name, MMI, coordinates, QC, etc.).
    """
    if not isinstance(state, dict):
        return {"value": str(state)[:max_len]}

    summary = {}
    for k, v in state.items():
        if k in ("raw_media_part", "file_bytes"):
            summary[k] = "<binary_data_omitted>"
        elif k == "mmi_documents":
            doc_count = len(v) if isinstance(v, list) else 0
            summary[k] = f"<List of {doc_count} reference documents>"
        elif isinstance(v, str) and len(v) > max_len:
            summary[k] = v[:max_len] + f"... [truncated {len(v)} chars]"
        elif isinstance(v, dict):
            summary[k] = summarize_state(v, max_len=max_len)
        elif isinstance(v, list) and len(v) > 5:
            summary[k] = f"<List with {len(v)} items>"
        else:
            summary[k] = v
    return summary


class StructuredAgentLogger:
    """
    Structured logger and tracer for LangGraph nodes and agents.
    Outputs clean visual blocks to stdout/loggers and captures events in memory.
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
        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=router_name,
            event_type="ROUTER_DECISION",
            inputs={condition_key: condition_value},
            outputs={"next_node": target_node},
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"🔀 [ROUTER DECISION] '{router_name}': evaluated {condition_key} = '{condition_value}' -> Routing to: '{target_node}'")

        return event

    def log_error(self, agent_name: str, error: Exception) -> AgentEvent:
        """Record an exception encountered within an agent."""
        now_iso = datetime.now(timezone.utc).isoformat()
        event = AgentEvent(
            timestamp_utc=now_iso,
            agent_name=agent_name,
            event_type="ERROR",
            metadata={"error_type": type(error).__name__, "error_message": str(error)},
        )
        self.events.append(event)
        self._write_event(event)

        if self.console_output:
            print(f"❌ [AGENT ERROR] Node: '{agent_name}' raised {type(error).__name__}: {error}")

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

    def _write_event(self, event: AgentEvent) -> None:
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(event.to_json() + "\n")
            except Exception:
                pass

    def get_events(self) -> List[AgentEvent]:
        return list(self.events)

    def clear(self) -> None:
        self.events.clear()
