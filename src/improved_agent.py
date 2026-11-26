"""Improved Text-to-SQL Analytics Agent

8-Step Architecture:
- Step 1: Safety and missing-data check (refuse modifications & non-existent schema requests, no SQL runs)
- Step 2: Ambiguity check (ask clarifying questions for vague terms / shared customer names, no guessing)
- Step 3: Schema linking (prunes tables & columns to minimize token costs)
- Step 4: SQL generation (LLM generates aliased, qualified SQLite query)
- Step 5: ORDER BY gate (blocks unrequested sorting/ranking)
- Step 6: Execute and self-correct (read-only execution, max 3 retries on SQLite errors)
- Step 7: Result handling (applies safety LIMIT, passes summary + first 10 rows for large outputs)
- Step 8: Log and answer (returns answer with SQL, tables used, retries, tokens, latency, cost)
"""

import re
import time
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.database import (
    get_linked_schema_string,
    get_schema_metadata,
    execute_query,
    summarize_results,
    get_db_connection
)
from src.llm_client import LLMClient
from src.logger import log_trace
from src.config import TODAY_DATE, MAX_RETRIES


# Known schema terms for missing data validation
KNOWN_SCHEMA_TERMS = {
    # Tables
    "fact_sales", "dim_customer", "dim_product", "dim_date",
    # Customer columns
    "customer_id", "customer_name", "email", "city", "state", "customer_segment", "customer_age",
    "customer", "customers", "segment", "segments", "age",
    # Product columns
    "product_id", "product_name", "category", "sub_category", "brand", "unit_price",
    "product", "products", "tier", "tiers",
    # Date columns
    "date_id", "date", "year", "quarter", "month", "month_name", "week", "day", "day_name", "is_weekend",
    "weekend", "weekends", "today", "yesterday", "october", "november", "q4", "2026",
    # Sales columns
    "transaction_id", "quantity", "discount_percent", "discount_amount", "tax_percent", "tax_amount",
    "sales_amount", "cost_amount", "profit_amount", "sales", "revenue", "profit", "discount", "tax", "cost",
    "items", "sold", "purchases", "spend", "order", "orders", "transactions"
}

# Explicitly forbidden/missing entities
UNKNOWN_ENTITIES = [
    "employee", "salary", "salaries", "manager", "managers", "bonus", "payroll",
    "supplier", "vendor", "inventory", "warehouse", "competitor", "shipping_cost", "stock"
]

# Write commands
DANGEROUS_WRITE_KEYWORDS = [
    r"\bdelete\b", r"\binsert\b", r"\bupdate\b", r"\bdrop\b", r"\balter\b",
    r"\btruncate\b", r"\bcreate\b", r"\battach\b", r"\bdetach\b", r"\breplace\b"
]


class ImprovedAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.schema_meta = get_schema_metadata()

    # ------------------ STEP 1: SAFETY & MISSING DATA CHECK ------------------
    def check_safety_and_missing_data(self, question: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Returns (is_blocked, refusal_reason, block_type)"""
        q_lower = question.lower()

        # 1. Check for data modification commands
        for pattern in DANGEROUS_WRITE_KEYWORDS:
            if re.search(pattern, q_lower):
                return True, "Data modification commands (DELETE, UPDATE, INSERT, DROP, ALTER) are strictly forbidden. The database operates in read-only mode.", "data_modification"

        # 2. Check for missing entities / data outside schema
        for unk in UNKNOWN_ENTITIES:
            if re.search(rf"\b{unk}\b", q_lower):
                return True, f"The requested entity '{unk}' does not exist in the sales database schema. The available data covers sales transactions, customers, products, and dates.", "missing_schema"

        # 3. Check for unbounded huge table dumps
        if ("dump" in q_lower or "export all" in q_lower or "select *" in q_lower) and ("all records" in q_lower or "entire table" in q_lower or "fact_sales" in q_lower):
            return True, "Unbounded full-table export requests are restricted to protect system performance and token boundaries. Please specify targeted filters or aggregated metrics.", "huge_dump"

        return False, None, None

    # ------------------ STEP 2: AMBIGUITY CHECK ------------------
    def check_ambiguity(self, question: str, clarification_context: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """Identifies ambiguous business phrasing and prompts for clarification instead of guessing."""
        if clarification_context:
            return False, None, None

        q_lower = question.lower()

        # A. Ambiguous "revenue"
        if re.search(r"\brevenue\b", q_lower):
            clarifying_question = "The term 'revenue' has multiple definitions in our data: (1) Gross Sales including tax (Sales_Amount), or (2) Net Sales before tax (Quantity * Unit_Price - Discount_Amount). Which metric would you like to calculate?"
            return True, clarifying_question, "revenue"

        # B. Ambiguous "last month"
        if "last month" in q_lower:
            clarifying_question = f"Today is {TODAY_DATE}. Does 'last month' refer to (1) the prior calendar month (October 2026), or (2) the trailing 30-day window (19 Oct - 18 Nov 2026)?"
            return True, clarifying_question, "last month"

        # C. Ambiguous "best customer"
        if "best customer" in q_lower or "top customer" in q_lower:
            clarifying_question = "How would you like to define 'best customer': (1) by total gross sales spend, (2) by total net profit generated, or (3) by number of purchase transactions?"
            return True, clarifying_question, "best customer"

        # D. Ambiguous shared customer name (e.g. Sarah Johnson, John Smith)
        # Check database for customer names matching the question that have multiple accounts
        name_match = re.search(r"for\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", question)
        if name_match:
            candidate_name = name_match.group(1)
            conn = get_db_connection(read_only=True)
            cursor = conn.cursor()
            cursor.execute("SELECT Customer_ID, City, State FROM dim_customer WHERE Customer_Name = ?", (candidate_name,))
            rows = cursor.fetchall()
            conn.close()
            if len(rows) > 1:
                accounts_desc = ", ".join([f"ID {r['Customer_ID']} ({r['City']}, {r['State']})" for r in rows[:4]])
                clarifying_question = f"Multiple customer accounts exist under '{candidate_name}' ({accounts_desc}). Would you like to aggregate across all matching accounts or select a specific Customer_ID?"
                return True, clarifying_question, "shared customer name"

        return False, None, None

    # ------------------ STEP 3: SCHEMA LINKING ------------------
    def link_schema(self, question: str) -> Tuple[List[str], Dict[str, List[str]], str]:
        """Identifies relevant tables and columns, returning minimal schema definition to save tokens."""
        q_lower = question.lower()
        relevant_tables = ["fact_sales"] # fact_sales is central
        relevant_cols: Dict[str, List[str]] = {
            "fact_sales": ["Transaction_ID", "Date_ID", "Customer_ID", "Product_ID"]
        }

        # Check customer dimension
        if any(w in q_lower for w in ["customer", "segment", "city", "state", "age", "who", "sarah", "john"]):
            relevant_tables.append("dim_customer")
            relevant_cols["dim_customer"] = ["Customer_ID", "Customer_Name", "Customer_Segment", "City", "State"]

        # Check product dimension
        if any(w in q_lower for w in ["product", "category", "sub_category", "tier", "brand", "item", "items", "unit_price", "price"]):
            relevant_tables.append("dim_product")
            relevant_cols["dim_product"] = ["Product_ID", "Product_Name", "Category", "Sub_Category", "Brand", "Unit_Price"]

        # Check date dimension
        if any(w in q_lower for w in ["date", "month", "year", "week", "day", "weekend", "october", "november", "2026"]):
            relevant_tables.append("dim_date")
            relevant_cols["dim_date"] = ["Date_ID", "Date", "Year", "Month", "Month_Name", "Week", "Is_Weekend"]

        # Check numeric facts in sales
        if "profit" in q_lower:
            relevant_cols["fact_sales"].append("Profit_Amount")
        if "sale" in q_lower or "sales" in q_lower or "spend" in q_lower or "amount" in q_lower:
            relevant_cols["fact_sales"].append("Sales_Amount")
        if "quantity" in q_lower or "items" in q_lower or "count" in q_lower or "sold" in q_lower:
            relevant_cols["fact_sales"].append("Quantity")
        if "discount" in q_lower:
            relevant_cols["fact_sales"].extend(["Discount_Percent", "Discount_Amount"])
        if "tax" in q_lower:
            relevant_cols["fact_sales"].extend(["Tax_Percent", "Tax_Amount"])
        if "unit_price" in q_lower or "price" in q_lower:
            relevant_cols["fact_sales"].append("Unit_Price")

        linked_schema_str = get_linked_schema_string(relevant_tables, relevant_cols)
        return relevant_tables, relevant_cols, linked_schema_str

    # ------------------ STEP 4: SQL GENERATION ------------------
    def generate_sql(self, question: str, linked_schema: str, clarification_context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Generates SQLite query using the linked schema with strict qualification rules."""
        system_prompt = f"""You are an expert improved Text-to-SQL agent producing SQLite queries for sales analytics.
Reference Date for current time: {TODAY_DATE}.

CRITICAL DATABASE AND JOIN RULES:
1. Always qualify every column with its table alias (e.g. f.Unit_Price, p.Unit_Price, f.Customer_ID, c.Customer_ID).
   Failure to qualify Unit_Price or Customer_ID when joining fact_sales with dim_product or dim_customer causes 'ambiguous column name' errors!
2. All queries must be read-only SELECT queries.
3. Always include both the requested dimensions/attributes AND the aggregated metrics/measures in the SELECT clause (e.g. `SELECT p.Category, ROUND(SUM(f.Profit_Amount), 2) AS Total_Profit`) so numeric values are visible in results.
4. Round currency outputs to 2 decimal places using ROUND(..., 2).
5. Use standard SQLite date filtering with dim_date columns (Year, Month, Date, Week, Is_Weekend).
6. Only add ORDER BY if the user explicitly asked for sorting, ordering, ranking, or top-N.

Pruned Schema:
{linked_schema}
"""
        user_prompt = f"Question: {question}"
        if clarification_context:
            user_prompt += f"\nClarification: {clarification_context}"
        user_prompt += "\nGenerate the SQLite query. Return ONLY the raw SQL statement."

        sql_response, metrics = self.llm.invoke(user_prompt, system_prompt=system_prompt)
        raw_sql = sql_response.strip()
        if raw_sql.startswith("```"):
            raw_sql = raw_sql.split("```")[1]
            if raw_sql.lower().startswith("sql"):
                raw_sql = raw_sql[3:].strip()
        return raw_sql, metrics

    # ------------------ STEP 7: RESULT HANDLING (Safe LIMIT enforced in SQL) ------------------
    def apply_safe_limit(self, sql: str, limit: int = 500) -> str:
        """Appends a LIMIT clause to the SQL if one is not already present, to prevent unbounded dumps."""
        sql_stripped = sql.strip().rstrip(";")
        if not re.search(r"\bLIMIT\b", sql_stripped, re.IGNORECASE):
            return sql_stripped + f" LIMIT {limit};"
        return sql.strip()

    # ------------------ STEP 5: ORDER BY GATE ------------------
    def check_order_by_gate(self, question: str, sql: str) -> Tuple[bool, str]:
        """If SQL has ORDER BY but question did not ask for sorting/ranking/top-N, strips or rewrites ORDER BY."""
        has_order_by = bool(re.search(r"\border\s+by\b", sql, re.IGNORECASE))
        if not has_order_by:
            return False, sql

        sorting_keywords = [
            r"\btop\b", r"\bbest\b", r"\bhighest\b", r"\blowest\b", r"\bbottom\b",
            r"\border\b", r"\bordered\b", r"\bsort\b", r"\bsorted\b", r"\brank\b",
            r"\branked\b", r"\basc\b", r"\bdesc\b", r"\bmost\b", r"\bleast\b"
        ]
        q_lower = question.lower()
        asked_for_sorting = any(re.search(pattern, q_lower) for pattern in sorting_keywords)

        if not asked_for_sorting:
            # Send back to be rewritten without ORDER BY (or strip ORDER BY clause)
            cleaned_sql = re.sub(r"\s+ORDER\s+BY\s+[^;]+", "", sql, flags=re.IGNORECASE)
            return True, cleaned_sql
        return False, sql

    # ------------------ STEP 6: EXECUTE & SELF-CORRECT ------------------
    def execute_and_self_correct(
        self, question: str, initial_sql: str, linked_schema: str
    ) -> Tuple[List[Dict[str, Any]], str, int, Optional[str], List[Dict[str, Any]]]:
        """Executes query read-only. On SQLite error, feeds error and failed SQL back to LLM (max 3 retries)."""
        retries = 0
        current_sql = initial_sql
        additional_metrics = []

        while retries <= MAX_RETRIES:
            rows, err = execute_query(current_sql)
            if not err:
                return rows, current_sql, retries, None, additional_metrics

            # Hit SQLite error (e.g. Trap question unqualified column)
            if retries >= MAX_RETRIES:
                return [], current_sql, retries, f"Failed after {MAX_RETRIES} self-correction attempts: {err}", additional_metrics

            retries += 1
            # Self-correction prompt
            system_prompt = f"""You are an expert SQLite debugger.
The following query generated for the sales database failed with an error. Fix the query.
Schema:
{linked_schema}

Common Traps to Fix:
- If error is 'ambiguous column name: Unit_Price', qualify as f.Unit_Price or p.Unit_Price.
- If error is 'ambiguous column name: Customer_ID', qualify as f.Customer_ID or c.Customer_ID.
- Ensure all joined tables have explicit aliases.
Return ONLY the corrected raw SQL query.
"""
            prompt = f"Question: {question}\nFailed SQL: {current_sql}\nSQLite Error: {err}\nFix the query:"
            fixed_sql, m = self.llm.invoke(prompt, system_prompt=system_prompt)
            additional_metrics.append(m)

            raw_sql = fixed_sql.strip()
            if raw_sql.startswith("```"):
                raw_sql = raw_sql.split("```")[1]
                if raw_sql.lower().startswith("sql"):
                    raw_sql = raw_sql[3:].strip()
            current_sql = raw_sql

        return [], current_sql, retries, "Exceeded retry budget.", additional_metrics

    # ------------------ MAIN PIPELINE ------------------
    def run(self, question: str, clarification_context: Optional[str] = None) -> Dict[str, Any]:
        """Executes the full 8-step Improved Agent pipeline."""
        start_time = time.time()
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0

        # Step 1: Safety and missing-data check
        is_blocked, block_msg, block_type = self.check_safety_and_missing_data(question)
        if is_blocked:
            latency = time.time() - start_time
            trace = log_trace(
                question=question,
                agent_type="improved",
                sql=None,
                tables_used=[],
                retries=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost=0.0,
                latency=latency,
                status=f"REFUSED_{block_type.upper()}",
                answer=block_msg
            )
            return {
                "agent_type": "improved",
                "question": question,
                "status": f"REFUSED_{block_type.upper()}",
                "sql": None,
                "tables_used": [],
                "retries": 0,
                "answer": block_msg,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency": latency,
                "cost": 0.0,
                "action": "refuse" if block_type != "huge_dump" else "limit"
            }

        # Step 2: Ambiguity check
        is_ambiguous, clarify_question, amb_type = self.check_ambiguity(question, clarification_context)
        if is_ambiguous:
            latency = time.time() - start_time
            trace = log_trace(
                question=question,
                agent_type="improved",
                sql=None,
                tables_used=[],
                retries=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost=0.0,
                latency=latency,
                status="ASKED_CLARIFICATION",
                answer=clarify_question
            )
            return {
                "agent_type": "improved",
                "question": question,
                "status": "ASKED_CLARIFICATION",
                "sql": None,
                "tables_used": [],
                "retries": 0,
                "answer": clarify_question,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency": latency,
                "cost": 0.0,
                "action": "ask",
                "clarifying_question": clarify_question
            }

        # Step 3: Schema linking
        tables_used, cols_used, linked_schema = self.link_schema(question)

        # Step 4: SQL generation
        sql, m4 = self.generate_sql(question, linked_schema, clarification_context)
        total_prompt_tokens += m4["prompt_tokens"]
        total_completion_tokens += m4["completion_tokens"]
        total_cost += m4["cost"]

        # Step 5: ORDER BY gate
        order_by_blocked, sql = self.check_order_by_gate(question, sql)

        # Step 5b: Apply safe SQL LIMIT to prevent unbounded result dumps (Step 7 enforcement)
        sql = self.apply_safe_limit(sql, limit=500)

        # Step 6: Execute and self-correct (max 3 retries)
        rows, final_sql, retries, err_msg, retry_metrics = self.execute_and_self_correct(question, sql, linked_schema)
        for rm in retry_metrics:
            total_prompt_tokens += rm["prompt_tokens"]
            total_completion_tokens += rm["completion_tokens"]
            total_cost += rm["cost"]

        # Step 7: Result handling (Apply LIMIT and pass summary + 10 rows for large outputs)
        if err_msg:
            status = "ERROR"
            answer = f"Query Execution Error: {err_msg}"
        else:
            status = "SUCCESS"
            summary_info = summarize_results(rows, max_rows=10)
            
            # Step 8: Synthesize answer
            synth_prompt = f"""Question: {question}
Executed SQL: {final_sql}
Result Summary: {summary_info['summary']}
Sample Rows: {summary_info['sample_rows']}

Provide a clear, accurate analytical summary answering the user's question directly."""
            synth_response, m8 = self.llm.invoke(synth_prompt)
            total_prompt_tokens += m8["prompt_tokens"]
            total_completion_tokens += m8["completion_tokens"]
            total_cost += m8["cost"]
            answer = synth_response

        latency = time.time() - start_time
        total_tokens = total_prompt_tokens + total_completion_tokens

        # Step 8: Log and return
        log_trace(
            question=question,
            agent_type="improved",
            sql=final_sql,
            tables_used=tables_used,
            retries=retries,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            cost=total_cost,
            latency=latency,
            status=status,
            answer=answer,
            extra_metadata={
                "order_by_gate_triggered": order_by_blocked,
                "rows_returned": len(rows) if not err_msg else 0
            }
        )

        return {
            "agent_type": "improved",
            "question": question,
            "status": status,
            "sql": final_sql,
            "tables_used": tables_used,
            "retries": retries,
            "answer": answer,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "latency": latency,
            "cost": total_cost,
            "rows_count": len(rows) if not err_msg else 0,
            "order_by_blocked": order_by_blocked,
            "action": "answer"
        }
