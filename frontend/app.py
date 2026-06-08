import streamlit as st
import requests
import json
import time
import os

# Reads from environment variable when running in Docker
# Falls back to localhost for local development
API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1")

st.set_page_config(
    page_title="DocuMind AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        text-align: center;
    }
    .main-header h1 { color: #ff6b8a; margin: 0; font-size: 2.5em; }
    .main-header p { color: #c8d8ff; margin: 5px 0 0; font-size: 1.1em; }
    .chat-message-user {
        background: #1e3a5f;
        padding: 14px 18px;
        border-radius: 10px;
        margin: 10px 0;
        border-left: 4px solid #4a9eff;
        color: #ffffff !important;
        font-size: 15px;
    }
    .chat-message-user b { color: #7ec8ff; }
    .chat-message-ai {
        background: #1e2d1e;
        padding: 14px 18px;
        border-radius: 10px;
        margin: 10px 0;
        border-left: 4px solid #4caf50;
        color: #e8f5e9 !important;
        font-size: 15px;
    }
    .chat-message-ai b { color: #80e080; }
    .trace-box {
        background: #1a1a2e;
        border: 1px solid #444;
        border-radius: 8px;
        padding: 12px;
        font-family: monospace;
        font-size: 12px;
        color: #c8d8ff;
        margin: 6px 0;
    }
    .source-badge {
        background: #2a3a5a;
        border: 1px solid #4a6a9a;
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 13px;
        color: #a8d0ff;
        margin: 3px;
        display: inline-block;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        border: none;
        background: #e94560;
        color: white !important;
        font-weight: bold;
        font-size: 15px;
        padding: 10px;
    }
    .stButton>button:hover { background: #c73652; }
    /* Small delete button override */
    .delete-btn>button {
        background: transparent !important;
        color: #ff6b6b !important;
        border: 1px solid #ff6b6b !important;
        padding: 2px 8px !important;
        font-size: 13px !important;
        width: auto !important;
    }
    .delete-btn>button:hover { background: #ff6b6b !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

if "token" not in st.session_state:
    st.session_state.token = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "documents" not in st.session_state:
    st.session_state.documents = []


def api_post(endpoint, data, auth=False):
    headers = {"Content-Type": "application/json"}
    if auth and st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=data, headers=headers, timeout=60)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def api_get(endpoint):
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    try:
        r = requests.get(f"{API_URL}{endpoint}", headers=headers, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def api_delete(endpoint):
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    try:
        r = requests.delete(f"{API_URL}{endpoint}", headers=headers, timeout=30)
        return r.status_code
    except Exception as e:
        return None


def upload_file(file):
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    try:
        r = requests.post(
            f"{API_URL}/documents/upload",
            files={"file": (file.name, file.getvalue(), file.type)},
            headers=headers,
            timeout=30,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def refresh_documents():
    docs = api_get("/documents/")
    if isinstance(docs, list):
        st.session_state.documents = docs


def show_auth():
    st.markdown("""
    <div class="main-header">
        <h1>🧠 DocuMind AI</h1>
        <p>Multi-agent document intelligence powered by Gemini + LangGraph</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab1, tab2 = st.tabs(["🔑 Login", "📝 Register"])

        with tab1:
            st.markdown("### Welcome back")
            email = st.text_input("Email", key="login_email", placeholder="you@example.com")
            password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Login", key="login_btn"):
                if email and password:
                    result = api_post("/auth/login", {"email": email, "password": password})
                    if "access_token" in result:
                        st.session_state.token = result["access_token"]
                        st.success("✅ Logged in!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('detail', 'Login failed')}")
                else:
                    st.warning("Please enter email and password")

        with tab2:
            st.markdown("### Create account")
            email = st.text_input("Email", key="reg_email", placeholder="you@example.com")
            password = st.text_input("Password (min 8 chars, 1 number)", type="password", key="reg_pass")
            if st.button("Register", key="reg_btn"):
                if email and password:
                    result = api_post("/auth/register", {"email": email, "password": password})
                    if "access_token" in result:
                        st.session_state.token = result["access_token"]
                        st.success("✅ Account created!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('detail', 'Registration failed')}")
                else:
                    st.warning("Please fill in all fields")


def show_sidebar():
    with st.sidebar:
        st.markdown("## 🧠 DocuMind AI")
        st.markdown("---")

        st.markdown("### 📄 Upload Document")
        uploaded = st.file_uploader(
            "Choose a file (PDF, DOCX, TXT)",
            type=["pdf", "docx", "txt"],
            key="file_uploader",
        )
        if uploaded:
            if st.button("⬆️ Upload & Index"):
                with st.spinner("Uploading..."):
                    result = upload_file(uploaded)
                if "document_id" in result:
                    st.success("✅ Uploaded! Indexing in background...")
                    time.sleep(1)
                    refresh_documents()
                else:
                    st.error(f"❌ {result.get('detail', 'Upload failed')}")

        st.markdown("---")
        st.markdown("### 📚 Your Documents")

        if st.button("🔄 Refresh"):
            refresh_documents()

        refresh_documents()

        # Only show indexed documents
        indexed_docs = [d for d in st.session_state.documents if d["status"] == "indexed"]

        if indexed_docs:
            for doc in indexed_docs:
                name = doc.get("original_filename") or doc.get("filename", "unknown")
                chunks = doc.get("chunk_count", 0)
                doc_id = doc["id"]

                # Two columns: name + delete button
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f"✅ **{name[:26]}**")
                    st.caption(f"{chunks} chunks")
                with col2:
                    st.markdown('<div class="delete-btn">', unsafe_allow_html=True)
                    if st.button("✕", key=f"del_{doc_id}", help=f"Delete {name}"):
                        status = api_delete(f"/documents/{doc_id}")
                        if status == 204:
                            st.success("Deleted")
                            refresh_documents()
                            st.rerun()
                        else:
                            st.error("Failed to delete")
                    st.markdown('</div>', unsafe_allow_html=True)
                st.markdown("---")
        else:
            st.info("No indexed documents yet.")

        st.markdown("### 💬 Session")
        if st.button("🆕 New Conversation"):
            st.session_state.messages = []
            st.session_state.session_id = None
            st.rerun()

        st.markdown("---")
        if st.button("🚪 Logout"):
            api_post("/auth/logout", {}, auth=True)
            for key in ["token", "messages", "session_id", "documents"]:
                st.session_state[key] = None if key == "token" else []
            st.rerun()


def show_chat():
    st.markdown("""
    <div class="main-header">
        <h1>🧠 DocuMind AI</h1>
        <p>Ask questions about your uploaded documents</p>
    </div>
    """, unsafe_allow_html=True)

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(
                f'<div class="chat-message-user">'
                f'👤 <b>You</b><br><br>{msg["content"]}'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="chat-message-ai">'
                f'🧠 <b>DocuMind</b><br><br>{msg["content"]}'
                f'</div>',
                unsafe_allow_html=True,
            )

            if msg.get("sources"):
                st.markdown("**📌 Sources:**")
                for src in msg["sources"]:
                    score = src.get("relevance_score", 0)
                    name = (src.get("filename") or "")[:45]
                    st.markdown(
                        f'<span class="source-badge">📄 {name} · score: {score:.2f}</span>',
                        unsafe_allow_html=True,
                    )
                st.markdown("")

            if msg.get("trace"):
                with st.expander("🔍 View agent trace", expanded=False):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("⏱ Latency", f"{msg.get('latency_ms', 0)}ms")
                    c2.metric("🔗 Nodes", len(msg.get("trace", [])))
                    c3.metric("📄 Sources", len(msg.get("sources", [])))
                    st.markdown("---")
                    for step in msg["trace"]:
                        node = step.get("node", "unknown")
                        latency = step.get("latency_ms", 0)
                        details = {k: v for k, v in step.items() if k not in ["node", "latency_ms"]}
                        st.markdown(
                            f'<div class="trace-box">'
                            f'<b style="color:#ff9f7f">▶ {node}</b> '
                            f'<span style="color:#aaa">({latency}ms)</span><br>'
                            f'<pre style="color:#c8d8ff;margin:6px 0 0">{json.dumps(details, indent=2)}</pre>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    question = st.chat_input("Ask a question about your documents...")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})

        with st.spinner("🧠 Thinking..."):
            payload = {"question": question}
            if st.session_state.session_id:
                payload["session_id"] = st.session_state.session_id
            headers = {"Authorization": f"Bearer {st.session_state.token}"}
            try:
                r = requests.post(f"{API_URL}/query/", json=payload, headers=headers, timeout=90)
                result = r.json()
            except Exception as e:
                result = {"error": str(e)}

        if "answer" in result:
            st.session_state.session_id = result.get("session_id")
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["answer"],
                "sources": result.get("sources", []),
                "trace": result.get("agent_trace", []),
                "latency_ms": result.get("latency_ms", 0),
            })
        else:
            error = result.get("detail", result.get("error", "Unknown error"))
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"⚠️ Error: {error}",
            })

        st.rerun()


if not st.session_state.token:
    show_auth()
else:
    show_sidebar()
    show_chat()