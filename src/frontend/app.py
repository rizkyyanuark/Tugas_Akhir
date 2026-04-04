"""
Streamlit App: Academic GraphRAG Interface
============================================
Chat interface for querying the UNESA academic Knowledge Graph
using the AcademicRAG pipeline with real-time analytics.
"""

import asyncio
import time
import streamlit as st
import pandas as pd

# Must be first Streamlit command
st.set_page_config(
    page_title="Academic GraphRAG — UNESA",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ──
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from src.graphrag.query import GraphRAGQuery


# ── Session State ──
def init_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "query_history" not in st.session_state:
        st.session_state.query_history = []
    if "gq" not in st.session_state:
        st.session_state.gq = None


def get_gq() -> GraphRAGQuery:
    """Lazy-init GraphRAG query engine."""
    if st.session_state.gq is None:
        with st.spinner("🔌 Menghubungkan ke Knowledge Graph..."):
            st.session_state.gq = GraphRAGQuery()
    return st.session_state.gq


# ── Sidebar ──
def render_sidebar():
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/id/3/3c/Logo_baru_unesa.png", width=80)
        st.title("🎓 Academic GraphRAG")
        st.caption("Hybrid Vector-Graph Retrieval untuk riset dosen UNESA")

        st.divider()

        # Mode selector
        mode = st.selectbox(
            "🔍 Mode Retrieval",
            options=["hybrid", "local", "global", "mix"],
            index=0,
            help=(
                "**hybrid**: Local + Global (recommended)\n"
                "**local**: Subgraph extraction only\n"
                "**global**: Edge network only\n"
                "**mix**: KG + Vector search"
            ),
        )

        st.divider()

        # Stats
        if st.session_state.query_history:
            st.subheader("📊 Session Stats")
            total_queries = len(st.session_state.query_history)
            avg_latency = sum(q["latency"] for q in st.session_state.query_history) / total_queries
            total_tokens = sum(q.get("tokens", 0) for q in st.session_state.query_history)

            col1, col2 = st.columns(2)
            col1.metric("Queries", total_queries)
            col2.metric("Avg Time", f"{avg_latency:.1f}s")
            st.metric("Total Tokens", f"{total_tokens:,}")

        st.divider()

        # Links
        st.subheader("🔗 Links")
        st.markdown("[📊 Opik Dashboard](http://opik.tugasakhir.space)")
        st.markdown("[🔬 Neo4j Browser](http://neo4j.tugasakhir.space)")

        # Clear history
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.query_history = []
            st.rerun()

    return mode


# ── Main Chat ──
def render_chat(mode: str):
    st.title("🎓 Academic Knowledge Graph — Q&A")
    st.caption("Tanyakan tentang riset, dosen, metode, atau kolaborasi di Fakultas Teknik UNESA")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Show debug info for assistant messages
            if msg["role"] == "assistant" and msg.get("debug"):
                with st.expander("📋 Detail Retrieval", expanded=False):
                    debug = msg["debug"]
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Entities", debug.get("local_entities", 0) + debug.get("global_entities", 0))
                    col2.metric("Relations", debug.get("local_relationships", 0) + debug.get("global_relationships", 0))
                    col3.metric("Text Units", debug.get("text_units", 0))

                    # Keywords
                    meta = msg.get("metadata", {})
                    if meta.get("hl_keywords"):
                        st.write("**High-Level Keywords:**", ", ".join(meta["hl_keywords"]))
                    if meta.get("ll_keywords"):
                        st.write("**Low-Level Keywords:**", ", ".join(meta["ll_keywords"]))

    # Chat input
    if prompt := st.chat_input("Tanyakan sesuatu tentang riset UNESA..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("🧠 Menganalisis Knowledge Graph..."):
                gq = get_gq()

                # Run async query
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(gq.query(prompt, mode=mode))
                finally:
                    loop.close()

                response = result["response"]
                metadata = result["metadata"]
                debug = result["debug"]

                st.markdown(response)

                # Show debug
                with st.expander("📋 Detail Retrieval", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Entities", debug.get("local_entities", 0) + debug.get("global_entities", 0))
                    col2.metric("Relations", debug.get("local_relationships", 0) + debug.get("global_relationships", 0))
                    col3.metric("Text Units", debug.get("text_units", 0))

                    if metadata.get("hl_keywords"):
                        st.write("**High-Level Keywords:**", ", ".join(metadata["hl_keywords"]))
                    if metadata.get("ll_keywords"):
                        st.write("**Low-Level Keywords:**", ", ".join(metadata["ll_keywords"]))

                    st.write(f"**Latency:** {metadata['latency_s']}s | **Mode:** {metadata['mode']}")

        # Save to state
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "debug": debug,
            "metadata": metadata,
        })
        st.session_state.query_history.append({
            "query": prompt,
            "latency": metadata["latency_s"],
            "tokens": metadata.get("llm_stats", {}).get("total_tokens", 0),
            "mode": mode,
        })


# ── Analytics Tab ──
def render_analytics():
    if not st.session_state.query_history:
        st.info("Belum ada query. Mulai bertanya di tab Chat!")
        return

    st.subheader("📊 Query Analytics")

    df = pd.DataFrame(st.session_state.query_history)
    df["index"] = range(1, len(df) + 1)

    col1, col2 = st.columns(2)
    with col1:
        st.line_chart(df.set_index("index")["latency"], use_container_width=True)
        st.caption("Latency per Query (seconds)")
    with col2:
        st.bar_chart(df.set_index("index")["tokens"], use_container_width=True)
        st.caption("Token Usage per Query")

    st.dataframe(df[["query", "latency", "tokens", "mode"]], use_container_width=True)


# ── Main ──
def main():
    init_session()
    mode = render_sidebar()

    tab1, tab2 = st.tabs(["💬 Chat", "📊 Analytics"])
    with tab1:
        render_chat(mode)
    with tab2:
        render_analytics()


if __name__ == "__main__":
    main()
