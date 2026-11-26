"""Streamlit Frontend for Text-to-SQL Analytics Agent (Baseline vs Improved)

Deliverable 3:
- Interactive query interface supporting free-form and benchmark questions
- Side-by-side / Comparative view: Baseline vs Improved Agent
- Metrics display: Answer, SQL, Tables Used, Retries, Tokens, Time, Cost
- Interactive Clarification Workflow: Shows clarifying questions and enables user reply
- Evaluation Leaderboard and Database Inspector
"""

import os
import sys
import time
import pandas as pd
import streamlit as st
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import TODAY_DATE, DEFAULT_MODEL, DB_PATH
from src.llm_client import LLMClient
from src.baseline_agent import BaselineAgent
from src.improved_agent import ImprovedAgent
from src.database import get_db_connection, execute_query
from src.logger import get_recent_traces
from evaluation.questions import QUESTIONS

# Streamlit Page Config
st.set_page_config(
    page_title="Text-to-SQL Analytics Agent | Baseline vs Improved",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px 16px;
        border: 1px solid #dee2e6;
        margin-bottom: 8px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.15rem !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.82rem !important;
    }
    .badge-success { background-color: #d4edda; color: #155724; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .badge-danger { background-color: #f8d7da; color: #721c24; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .badge-warning { background-color: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .badge-info { background-color: #d1ecf1; color: #0c5460; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# Sidebar Configuration
with st.sidebar:
    st.image("https://img.icons8.com/color/96/database.png", width=64)
    st.title("Settings & Status")
    
    st.markdown(f"**Reference Date (`Today`):** `{TODAY_DATE}`")
    st.markdown(f"**Database:** `{DB_PATH.name}` (SQLite Read-Only)")
    
    # API Key Configuration
    st.markdown("---")
    st.subheader("🔑 Gemini API Key")
    api_key_input = st.text_input(
        "Enter Google Gemini API Key",
        value=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
        type="password",
        help="Reads from .env or override here. If empty, runs in high-fidelity deterministic mode."
    )
    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input
        os.environ["GOOGLE_API_KEY"] = api_key_input

    model_choice = st.selectbox(
        "LLM Model",
        ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"],
        index=0,
        help="gemini-2.5-flash-lite: best SQL accuracy & cost balance. gemini-2.0-flash: fastest. gemini-1.5-flash: legacy fallback."
    )
    
    st.markdown("---")
    st.subheader("📋 Recent Traces")
    try:
        recent = get_recent_traces(limit=10)
        if recent:
            st.write(f"Last {len(recent)} executions logged.")
            for t in reversed(recent[-3:]):
                status_icon = "✅" if t["status"] == "SUCCESS" else ("⚠️" if "CLARIF" in t["status"] else "🔴")
                st.caption(f"{status_icon} [{t['agent_type'].upper()}] {t['question'][:50]}... | {t['status']} | Tokens: {t['total_tokens']}")
        else:
            st.caption("No traces yet. Run a query above.")
    except Exception:
        st.caption("Traces unavailable.")

    st.markdown("---")
    st.subheader("📁 Database Overview")
    if DB_PATH.exists():
        try:
            conn = get_db_connection(read_only=True)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM fact_sales")
            fs_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM dim_customer")
            dc_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM dim_product")
            dp_count = cur.fetchone()[0]
            conn.close()
            st.write(f"• **Sales Records:** `{fs_count:,}`")
            st.write(f"• **Customers:** `{dc_count:,}`")
            st.write(f"• **Products:** `{dp_count:,}`")
        except Exception as e:
            st.error(f"DB Error: {e}")
    else:
        st.warning("Database not generated. Run `python data/generate_data.py`.")


# Initialize session state for clarification workflows and agents
if "clarification_state" not in st.session_state:
    st.session_state.clarification_state = None

if "last_question" not in st.session_state:
    st.session_state.last_question = ""


# Main Title and Overview
st.title("🤖 Text-to-SQL Analytics Agent")
st.caption("Cost-Aware & Ambiguity-Aware Sales Intelligence | Baseline vs Improved Agent")

tabs = st.tabs(["🚀 Interactive Query Runner", "📋 15 Benchmark Questions", "📈 Evaluation Metrics & Gain", "🔍 Schema & Data Explorer"])


# ------------------ TAB 1: INTERACTIVE QUERY RUNNER ------------------
with tabs[0]:
    st.markdown("### Ask a Question About Sales Data")
    
    # Question selector / custom text
    col_pre, col_run = st.columns([4, 1])
    with col_pre:
        question_text = st.text_input(
            "Enter your business question in plain English:",
            value=st.session_state.last_question or "What are the top 3 product categories by total profit amount in October 2026?",
            placeholder="e.g. Which customer segment generated the highest weekend sales in November?"
        )
    with col_run:
        st.write("")
        st.write("")
        run_btn = st.button("🚀 Run Both Agents", type="primary", use_container_width=True)

    # Clarification handling banner if pending
    if st.session_state.clarification_state:
        cs = st.session_state.clarification_state
        st.warning(f"🤔 **Clarification Needed for Improved Agent:**\n\n{cs['clarifying_question']}")
        
        col_c1, col_c2 = st.columns([3, 1])
        with col_c1:
            clarification_reply = st.text_input("Your clarification response:", placeholder="e.g. Gross sales including tax")
        with col_c2:
            st.write("")
            st.write("")
            submit_clarify = st.button("Submit Clarification", key="btn_clarify")
            
        if submit_clarify and clarification_reply:
            with st.spinner("Processing clarification with Improved Agent..."):
                llm = LLMClient(model_name=model_choice, api_key=api_key_input)
                improved = ImprovedAgent(llm_client=llm)
                res_clarified = improved.run(cs["original_question"], clarification_context=clarification_reply)
                st.session_state.improved_result = res_clarified
                st.session_state.clarification_state = None
                st.rerun()

    if run_btn and question_text:
        st.session_state.last_question = question_text
        st.session_state.clarification_state = None
        
        llm = LLMClient(model_name=model_choice, api_key=api_key_input)
        baseline = BaselineAgent(llm_client=llm)
        improved = ImprovedAgent(llm_client=llm)
        
        with st.spinner("Executing Baseline Agent (single-turn full schema)..."):
            b_res = baseline.run(question_text)
            st.session_state.baseline_result = b_res
            
        with st.spinner("Executing Improved Agent (8-step cost & ambiguity pipeline)..."):
            i_res = improved.run(question_text)
            st.session_state.improved_result = i_res
            
            if i_res.get("status") == "ASKED_CLARIFICATION":
                st.session_state.clarification_state = {
                    "original_question": question_text,
                    "clarifying_question": i_res.get("clarifying_question")
                }
                st.rerun()

    # Display Side-by-Side Results
    if "baseline_result" in st.session_state and "improved_result" in st.session_state:
        b = st.session_state.baseline_result
        i = st.session_state.improved_result

        st.markdown("---")
        st.subheader("📊 Comparative Execution Breakdown")

        col_b, col_i = st.columns(2)

        # Baseline Column
        with col_b:
            st.markdown("### 🔴 Baseline Agent")
            st.caption("Full 4-table schema sent | No validation | No retries | No safety checks")
            
            # Status Badge
            if b["status"] == "SUCCESS":
                st.markdown('<span class="badge-success">STATUS: SUCCESS</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="badge-danger">STATUS: ERROR / FAILED</span>', unsafe_allow_html=True)

            m_c1, m_c2, m_c3, m_c4 = st.columns(4)
            m_c1.metric("Latency", f"{b['latency']:.2f}s")
            m_c2.metric("Total Tokens", f"{b['total_tokens']:,}")
            m_c3.metric("Cost", f"${b['cost']:.6f}")
            m_c4.metric("Retries", b["retries"])

            st.markdown(f"**Tables Sent in Prompt:** `{len(b['tables_used'])} tables` (`{', '.join(b['tables_used'])}`)")

            st.markdown("**Generated SQL:**")
            st.code(b["sql"] or "No SQL generated", language="sql")

            st.markdown("**Agent Output / Response:**")
            if b["status"] == "SUCCESS":
                st.info(b["answer"])
            else:
                st.error(b["answer"])

        # Improved Column
        with col_i:
            st.markdown("### 🟢 Improved Agent")
            st.caption("Safety Check | Ambiguity Detection | Schema Linking | ORDER BY Gate | Self-Correction | Safe LIMIT")
            
            # Status Badge
            if i["status"] == "SUCCESS":
                st.markdown('<span class="badge-success">STATUS: SUCCESS</span>', unsafe_allow_html=True)
            elif "REFUSED" in i["status"]:
                st.markdown(f'<span class="badge-danger">STATUS: {i["status"]} (BLOCKED)</span>', unsafe_allow_html=True)
            elif i["status"] == "ASKED_CLARIFICATION":
                st.markdown('<span class="badge-warning">STATUS: ASKED CLARIFICATION</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="badge-danger">STATUS: ERROR</span>', unsafe_allow_html=True)

            m_i1, m_i2, m_i3, m_i4 = st.columns(4)
            m_i1.metric("Latency", f"{i['latency']:.2f}s", delta=f"{i['latency'] - b['latency']:.2f}s", delta_color="inverse")
            m_i2.metric("Total Tokens", f"{i['total_tokens']:,}", delta=f"{i['total_tokens'] - b['total_tokens']:,}", delta_color="inverse")
            m_i3.metric("Cost", f"${i['cost']:.6f}", delta=f"${i['cost'] - b['cost']:.6f}", delta_color="inverse")
            m_i4.metric("Retries", i["retries"])

            st.markdown(f"**Linked Tables Used:** `{len(i['tables_used'])} tables` (`{', '.join(i['tables_used']) or 'None (Blocked)'}`)")
            if i.get("order_by_blocked"):
                st.warning("⚠️ ORDER BY Gate: Unrequested sorting was detected and stripped.")

            st.markdown("**Executed SQL:**")
            st.code(i["sql"] or "N/A (Query execution withheld for safety/clarity)", language="sql")

            st.markdown("**Agent Output / Response:**")
            if i["status"] == "SUCCESS":
                st.success(i["answer"])
            elif i["status"] == "ASKED_CLARIFICATION":
                st.warning(f"❓ Clarifying Question Asked: {i['answer']}")
            else:
                st.error(i["answer"])

            # Data Table Preview if available
            if i["sql"] and i["status"] == "SUCCESS":
                with st.expander("👁️ View Query Result Dataset (First 15 Rows)"):
                    try:
                        rows, err = execute_query(i["sql"])
                        if rows:
                            st.dataframe(pd.DataFrame(rows[:15]), use_container_width=True)
                    except Exception as ex:
                        st.write(f"Could not load preview: {ex}")


# ------------------ TAB 2: 15 BENCHMARK QUESTIONS ------------------
with tabs[1]:
    st.subheader("📋 15 Frozen Benchmark Questions")
    st.markdown("Select any pre-configured evaluation question to immediately test both agents against gold expectations.")
    
    q_data = []
    for q in QUESTIONS:
        q_data.append({
            "ID": q["id"],
            "Type": q["type"],
            "Question": q["question"],
            "Expected Behavior": q["expected_behavior"],
            "Gold Answer": q["gold_summary"]
        })
    df_questions = pd.DataFrame(q_data)
    st.dataframe(df_questions, use_container_width=True, hide_index=True)
    
    st.markdown("#### Test a Benchmark Question Directly")
    sel_q_id = st.selectbox("Choose a question to load:", [f"{q['id']} - [{q['type']}] {q['question']}" for q in QUESTIONS])
    selected_id = sel_q_id.split(" - ")[0]
    
    if st.button("Load into Query Runner", key="btn_load_q"):
        sel_q = next(q for q in QUESTIONS if q["id"] == selected_id)
        st.session_state.last_question = sel_q["question"]
        st.session_state.clarification_state = None
        st.rerun()


# ------------------ TAB 3: EVALUATION METRICS & GAIN ------------------
with tabs[2]:
    st.subheader("📈 Benchmark Evaluation Results & Performance Gain")
    
    eval_excel_path = PROJECT_ROOT / "Evaluation.xlsx"
    if eval_excel_path.exists():
        try:
            excel_file = pd.ExcelFile(eval_excel_path)
            sheet_names = excel_file.sheet_names
            
            st.markdown("#### Summary Comparison (Baseline vs Improved)")
            df_summary = pd.read_excel(eval_excel_path, sheet_name="summary")
            st.dataframe(df_summary, use_container_width=True, hide_index=True)
            
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("#### Baseline Results Sheet")
                df_b = pd.read_excel(eval_excel_path, sheet_name="baseline")
                display_cols_b = [c for c in ["question_id", "type", "label", "tokens", "cost", "latency", "retries"] if c in df_b.columns]
                st.dataframe(df_b[display_cols_b], use_container_width=True)
            with col_s2:
                st.markdown("#### Improved Results Sheet")
                df_i = pd.read_excel(eval_excel_path, sheet_name="improved")
                display_cols_i = [c for c in ["question_id", "type", "label", "tokens", "cost", "latency", "retries"] if c in df_i.columns]
                st.dataframe(df_i[display_cols_i], use_container_width=True)
        except Exception as e:
            st.error(f"Error loading Excel evaluation: {e}")
    else:
        st.info("Evaluation results will appear here once you run `python evaluation/run_eval.py`.")


# ------------------ TAB 4: SCHEMA & DATA EXPLORER ------------------
with tabs[3]:
    st.subheader("🔍 SQLite Database Schema & Sample Rows")
    if DB_PATH.exists():
        conn = get_db_connection(read_only=True)
        cur = conn.cursor()
        
        tables = ["fact_sales", "dim_customer", "dim_product", "dim_date"]
        selected_tbl = st.selectbox("Select Table:", tables)
        
        # Schema
        cur.execute(f"PRAGMA table_info({selected_tbl})")
        cols = cur.fetchall()
        df_cols = pd.DataFrame([dict(c) for c in cols])
        st.markdown(f"**Schema Definition for `{selected_tbl}`:**")
        st.dataframe(df_cols[["cid", "name", "type", "notnull", "pk"]], use_container_width=True)
        
        # Data sample
        st.markdown(f"**Sample Records (First 10 Rows):**")
        cur.execute(f"SELECT * FROM {selected_tbl} LIMIT 10")
        sample_rows = cur.fetchall()
        st.dataframe(pd.DataFrame([dict(r) for r in sample_rows]), use_container_width=True)
        
        conn.close()
    else:
        st.warning("Database not found.")
