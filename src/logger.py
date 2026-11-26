"""Logging and Tracing Layer

- Configures LangChain / LangSmith tracing when LANGCHAIN_API_KEY is available
- Maintains an append-only JSONL log (langsmith_traces.jsonl) containing:
  * timestamp
  * question_id / question
  * agent_type (Baseline vs Improved)
  * sql
  * tables_used
  * retries
  * prompt_tokens, completion_tokens, total_tokens
  * cost ($)
  * latency (seconds)
  * status (SUCCESS, ERROR, REFUSED, ASKED_CLARIFICATION, LIMITED)
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.config import (
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_API_KEY,
    LANGCHAIN_PROJECT,
    TRACES_LOG_PATH
)

# Initialize LangSmith environment variables if configured
if LANGCHAIN_TRACING_V2 and LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT


def log_trace(
    question: str,
    agent_type: str,
    sql: Optional[str],
    tables_used: List[str],
    retries: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost: float,
    latency: float,
    status: str,
    answer: str,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Records an execution trace to the structured JSONL log file."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_type": agent_type,
        "question": question,
        "sql": sql or "N/A",
        "tables_used": tables_used,
        "retries": retries,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_dollars": round(cost, 6),
        "latency_seconds": round(latency, 4),
        "status": status,
        "answer_summary": (answer[:200] + "...") if len(answer) > 200 else answer,
        "metadata": extra_metadata or {}
    }

    try:
        with open(TRACES_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to {TRACES_LOG_PATH}: {e}")

    return record


def get_recent_traces(limit: int = 50) -> List[Dict[str, Any]]:
    """Reads back the most recent execution traces."""
    if not TRACES_LOG_PATH.exists():
        return []
    traces = []
    with open(TRACES_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    traces.append(json.loads(line))
                except Exception:
                    pass
    return traces[-limit:]
