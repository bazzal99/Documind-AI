# 🧠 DocuMind AI

> **Multi-agent document intelligence platform** powered by Gemini + LangGraph + FastAPI

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)](https://langchain-ai.github.io/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)](https://docker.com)
[![Gemini](https://img.shields.io/badge/Gemini-API-red?logo=google)](https://ai.google.dev)

---

## 🎯 What is DocuMind AI?

DocuMind AI is a **production-grade** document intelligence system that lets users upload documents and query them using a multi-agent AI pipeline. Unlike simple RAG systems, DocuMind uses a **LangGraph supervisor agent** that autonomously decides how to answer each query — whether to retrieve, summarize, or answer directly.

Every query logs a full **agent execution trace** (which nodes ran, latency, token usage), making the system fully observable and debuggable, exactly what production AI teams need.

---

## ✨ Key Features

- 🤖 **Multi-agent LangGraph pipeline** — Supervisor routes queries to Retriever, Summarizer, or Synthesizer nodes
- 🔍 **Semantic search** — Gemini embeddings + Qdrant vector database with per-user namespaces
- 🛡️ **JWT authentication** — Register, login, token refresh, logout with Redis blacklisting
- 📊 **Full agent trace** — Every query stores which nodes ran, latency, and sources in PostgreSQL
- 🔄 **Async document ingestion** — Upload returns instantly, indexing runs in background
- ⚡ **Rate limiting** — Redis-based per-user rate limiting (20 req/min)
- 🐳 **Fully containerized** — One `docker compose up` starts all 5 services
- 🖥️ **Streamlit UI** — Clean chat interface with source citations and agent trace viewer
- 🆓 **100% free** — Uses Gemini free tier, no paid APIs required

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Streamlit UI                          │
│                     localhost:8501                           │
└─────────────────────┬───────────────────────────────────────┘
                       │ HTTP
┌─────────────────────▼───────────────────────────────────────┐
│                   FastAPI Backend                            │
│              Auth · Documents · Query                        │
│                     localhost:8000                           │
└──────┬──────────────┬──────────────┬────────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌────▼────────────────────────┐
│ PostgreSQL  │ │   Redis    │ │      LangGraph Agent         │
│  Users      │ │  Sessions  │ │                              │
│  Documents  │ │  Rate      │ │  Supervisor → routes query   │
│  Sessions   │ │  Limits    │ │  Retriever  → Qdrant search  │
│  Queries    │ │  Blacklist │ │  Summarizer → map-reduce     │
└─────────────┘ └────────────┘ │  Synthesizer→ final answer   │
                               └──────────────┬───────────────┘
                                              │
                              ┌───────────────▼──────────────┐
                              │           Qdrant             │
                              │     Vector Database          │
                              │  3072-dim Gemini embeddings  │
                              │    Per-user namespaces       │
                              └──────────────────────────────┘
```

---

## 🤖 Agent Flow

```
User Query
    │
    ▼
Supervisor Node ──── classifies intent ────┐
    │                                      │
    ├── "specific question" ──► Retriever  │
    │        │                             │
    ├── "summarize" ──► Summarizer         │
    │        │                             │
    └── "general" ──────────────────────── ┘
                    │
                    ▼
             Synthesizer Node
          (citations + self-critique)
                    │
                    ▼
        Final Answer + Sources + Trace
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Google Gemini (free tier) |
| Embeddings | Gemini Embedding-001 (3072 dim) |
| Agent Framework | LangGraph 0.2 |
| API | FastAPI 0.115 + uvicorn |
| Database | PostgreSQL 15 (SQLAlchemy async) |
| Vector DB | Qdrant |
| Cache | Redis 7 |
| Frontend | Streamlit 1.40 |
| Containerization | Docker + Docker Compose |
| Auth | JWT (python-jose) + bcrypt |

---

## 🚀 Quick Start

### Prerequisites
- Docker Desktop
- Google Gemini API key (free at [ai.google.dev](https://ai.google.dev))

### 1. Clone the repo
```bash
git clone https://github.com/bazzal99/Documind-AI.git
cd Documind-AI
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Check available Gemini models (optional)
```bash
pip install requests python-dotenv
python check_models.py
```
This lists all Gemini models available on your API key and their supported methods. Use it to verify your key works and pick the best free model.

### 4. Start everything with Docker
```bash
cd infra
docker compose up -d
```

### 5. Open the app
- **UI:** http://localhost:8501
- **API docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

---

## 📁 Project Structure

```
Documind-AI/
├── backend/
│   ├── app/
│   │   ├── agents/           # LangGraph nodes
│   │   │   ├── graph.py      # Agent state + graph definition
│   │   │   ├── supervisor.py # Intent classification + routing
│   │   │   ├── retriever.py  # Qdrant semantic search
│   │   │   ├── summarizer.py # Map-reduce summarization
│   │   │   └── synthesizer.py# Final answer + self-critique
│   │   ├── api/routes/       # FastAPI endpoints
│   │   │   ├── auth.py       # Register, login, logout
│   │   │   ├── documents.py  # Upload, list, delete
│   │   │   └── query.py      # Main chat endpoint
│   │   ├── core/             # Config, security
│   │   ├── db/               # Models, session
│   │   └── services/         # Document, vector, cache
│   └── Dockerfile
├── frontend/
│   ├── app.py                # Streamlit UI
│   └── Dockerfile
├── infra/
│   └── docker-compose.yml    # All 5 services
├── check_models.py           # Utility: list available Gemini models
├── .env.example              # Environment template
├── requirements.txt
└── README.md
```

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Login → JWT tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Blacklist token |
| POST | `/api/v1/documents/upload` | Upload + index document |
| GET | `/api/v1/documents/` | List user documents |
| DELETE | `/api/v1/documents/{id}` | Delete document |
| POST | `/api/v1/query/` | Ask question → agent runs |
| GET | `/api/v1/query/sessions` | List chat sessions |
| GET | `/api/v1/query/sessions/{id}/history` | Chat history |
| GET | `/health` | Service health check |

---

## 💡 Example Query Response

```json
{
  "answer": "The methodology uses a ConvLSTM2D architecture trained on 2,000 videos...",
  "sources": [
    {
      "filename": "research_paper.pdf",
      "relevance_score": 0.94
    }
  ],
  "nodes_invoked": ["supervisor", "retriever", "synthesizer"],
  "agent_trace": [
    {"node": "supervisor", "route": "retriever", "latency_ms": 702},
    {"node": "retriever", "chunks_found": 3, "latency_ms": 366},
    {"node": "synthesizer", "hallucination_detected": false, "latency_ms": 2100}
  ],
  "latency_ms": 3200
}
```

---

## 🆓 Running for Free

This project uses **only free services**:

- **Gemini API** — free tier (30 RPM, 1500 RPD)
- **Docker** — free personal plan
- **Qdrant** — self-hosted in Docker
- **PostgreSQL** — self-hosted in Docker
- **Redis** — self-hosted in Docker

No credit card required. Total cost: **$0/month**.

To check which Gemini models are available on your free API key:
```bash
python check_models.py
```

---

## 👨‍💻 Author

**Mohammad Bazzal** — ML Engineer | PhD in Telecommunications | 3× IEEE Author

- 🔗 [LinkedIn](https://linkedin.com/in/mohammadbazzal-3b768b20b)
- 🐙 [GitHub](https://github.com/bazzal99)
- 📧 mhmd.bazzal.99@gmail.com

---

## 📄 License

MIT License — free to use and modify.
