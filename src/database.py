"""Database Access Layer for Sales SQLite Database

- Enforces read-only SQLite connection (file:URI with ?mode=ro)
- Full schema introspection for Baseline Agent
- Column-level schema linking for Improved Agent
- Result truncation & statistical summarization for Step 7
"""

import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from src.config import DB_PATH


def get_db_connection(read_only: bool = True) -> sqlite3.Connection:
    """Returns a SQLite connection. Defaults to strict read-only mode."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run 'python data/generate_data.py' first.")
    
    if read_only:
        uri_path = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri_path, uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
        
    conn.row_factory = sqlite3.Row
    return conn


def get_full_schema_string() -> str:
    """Returns complete schema of all 4 tables with column types and comments for Baseline Agent."""
    conn = get_db_connection(read_only=True)
    cursor = conn.cursor()
    schema_lines = []
    
    tables = ["dim_customer", "dim_product", "dim_date", "fact_sales"]
    for table in tables:
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        row = cursor.fetchone()
        if row and row["sql"]:
            schema_lines.append(row["sql"] + ";\n")
            
    conn.close()
    return "\n".join(schema_lines)


def get_schema_metadata() -> Dict[str, List[str]]:
    """Returns a dictionary mapping table name to list of column names."""
    conn = get_db_connection(read_only=True)
    cursor = conn.cursor()
    metadata = {}
    
    tables = ["dim_customer", "dim_product", "dim_date", "fact_sales"]
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [r["name"] for r in cursor.fetchall()]
        metadata[table] = cols
        
    conn.close()
    return metadata


def get_linked_schema_string(relevant_tables: List[str], relevant_columns: Optional[Dict[str, List[str]]] = None) -> str:
    """Returns minimal schema string containing only linked tables and columns for Improved Agent (Step 3)."""
    conn = get_db_connection(read_only=True)
    cursor = conn.cursor()
    schema_parts = []
    
    for table in relevant_tables:
        cursor.execute(f"PRAGMA table_info({table})")
        col_rows = cursor.fetchall()
        cols_to_include = relevant_columns.get(table) if relevant_columns else None
        
        col_defs = []
        for r in col_rows:
            col_name = r["name"]
            col_type = r["type"]
            if cols_to_include is None or col_name in cols_to_include or col_name in ["Transaction_ID", "Customer_ID", "Product_ID", "Date_ID"]:
                col_defs.append(f"  {col_name} {col_type}")
                
        table_str = f"TABLE {table} (\n" + ",\n".join(col_defs) + "\n);"
        schema_parts.append(table_str)
        
    conn.close()
    return "\n\n".join(schema_parts)


def execute_query(sql: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Executes a SQL query in read-only mode and returns (rows, error_message)."""
    conn = None
    try:
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        return rows, None
    except Exception as e:
        return [], str(e)
    finally:
        if conn:
            conn.close()


def summarize_results(rows: List[Dict[str, Any]], max_rows: int = 10) -> Dict[str, Any]:
    """Result handling for Step 7: For large results pass only summary and first 10 rows."""
    total_rows = len(rows)
    if total_rows == 0:
        return {
            "total_rows": 0,
            "sample_rows": [],
            "summary": "Query returned 0 rows."
        }
        
    sample = rows[:max_rows]
    if total_rows <= max_rows:
        return {
            "total_rows": total_rows,
            "sample_rows": sample,
            "summary": f"All {total_rows} rows displayed."
        }
        
    # Large results: Compute numeric summaries
    numeric_sums = {}
    numeric_cols = []
    first_row = rows[0]
    for k, v in first_row.items():
        if isinstance(v, (int, float)):
            numeric_cols.append(k)
            numeric_sums[k] = 0.0
            
    for r in rows:
        for c in numeric_cols:
            val = r.get(c)
            if isinstance(val, (int, float)):
                numeric_sums[c] += val
                
    summary_parts = [f"Total rows: {total_rows}. Showing first {max_rows} rows."]
    for c in numeric_cols:
        col_sum = numeric_sums[c]
        avg = col_sum / total_rows
        summary_parts.append(f"{c}: Total={col_sum:,.2f}, Avg={avg:,.2f}")
        
    return {
        "total_rows": total_rows,
        "sample_rows": sample,
        "summary": " | ".join(summary_parts)
    }
