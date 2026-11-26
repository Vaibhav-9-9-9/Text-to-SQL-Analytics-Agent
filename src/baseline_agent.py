"""Baseline Text-to-SQL Agent

Stage 1 Architecture:
- Sends full schema of all four tables in the prompt.
- LLM writes SQL once (single-turn).
- Query is executed read-only once.
- LLM writes final answer from the raw query output.
- No validation, no retry, no safety checks, no ambiguity check, no order-by gate.
"""

import time
from typing import Any, Dict, List, Optional
from src.database import get_full_schema_string, execute_query
from src.llm_client import LLMClient
from src.logger import log_trace
from src.config import TODAY_DATE


BASELINE_SYSTEM_PROMPT = f"""You are a basic Text-to-SQL assistant.
Today's reference date is {TODAY_DATE}.
Given the complete database schema below, write a single SQLite query to answer the user's question.
Return ONLY the raw SQL query, with no markdown code blocks or explanations.

Database Schema:
{get_full_schema_string()}
"""


class BaselineAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.all_tables = ["dim_customer", "dim_product", "dim_date", "fact_sales"]

    def run(self, question: str) -> Dict[str, Any]:
        """Runs the baseline agent pipeline for a given question."""
        start_time = time.time()
        retries = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0

        # Step 1: Prompt LLM with full schema to generate SQL once
        sql_prompt = f"User Question: {question}\nWrite a single SQLite query to answer this question."
        sql_response, m1 = self.llm.invoke(sql_prompt, system_prompt=BASELINE_SYSTEM_PROMPT)
        
        total_prompt_tokens += m1["prompt_tokens"]
        total_completion_tokens += m1["completion_tokens"]
        total_cost += m1["cost"]

        # Clean potential markdown formatting
        raw_sql = sql_response.strip()
        if raw_sql.startswith("```"):
            raw_sql = raw_sql.split("```")[1]
            if raw_sql.lower().startswith("sql"):
                raw_sql = raw_sql[3:].strip()

        # Step 2: Execute query once (no retry, no validation)
        rows, err = execute_query(raw_sql)

        # Step 3: Synthesis or error reporting
        if err:
            status = "ERROR"
            answer = f"SQL Execution Error: {err}"
        else:
            status = "SUCCESS"
            ans_prompt = f"Question: {question}\nExecuted SQL: {raw_sql}\nQuery Results: {rows[:100]}\nProvide a direct answer to the question based on the query results."
            ans_response, m2 = self.llm.invoke(ans_prompt)
            total_prompt_tokens += m2["prompt_tokens"]
            total_completion_tokens += m2["completion_tokens"]
            total_cost += m2["cost"]
            answer = ans_response

        latency = time.time() - start_time
        total_tokens = total_prompt_tokens + total_completion_tokens

        # Step 4: Log trace
        trace_record = log_trace(
            question=question,
            agent_type="baseline",
            sql=raw_sql,
            tables_used=self.all_tables, # Baseline sends full schema
            retries=retries,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            cost=total_cost,
            latency=latency,
            status=status,
            answer=answer,
            extra_metadata={"rows_returned": len(rows) if not err else 0}
        )

        return {
            "agent_type": "baseline",
            "question": question,
            "status": status,
            "sql": raw_sql,
            "tables_used": self.all_tables,
            "retries": retries,
            "answer": answer,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "latency": latency,
            "cost": total_cost,
            "rows_count": len(rows) if not err else 0
        }
