# 👻 GhostDebugger

**Token-efficient multi-agent AI debugging system**  
AMD AI Developer Hackathon Act II · Track 1 · Team Singleton Vanguard

---

## What It Does

GhostDebugger takes broken Python code and autonomously:

1. **Routes** it to the right LLM tier based on bug complexity (saving 60–80% tokens)
2. **Reproduces** the bug by actually running the code in a sandbox
3. **Traces** the root cause through the execution path
4. **Fixes** the code and verifies the fix by re-running it
5. **Reviews** the session with a Gemma 4 senior-dev style post-mortem

---

## Architecture

```
Broken Code Input
      ↓
[Agent 1: Complexity Router] ← Qwen3-8B (~50 tokens)
      ↓
  SIMPLE → mid model (Llama-3.1-8B)
  MEDIUM → mid model (Llama-3.1-8B)
  COMPLEX → heavy model (Llama-3.1-70B)
      ↓
[Agent 2: Reproducer] ← subprocess.run() — ZERO tokens
      ↓
[Agent 3: Tracer] ← routed model
      ↓
[Agent 4: Fixer] ← routed model + sandbox verification
      ↓
[Agent 5: Reviewer] ← Gemma 4 31B (AMD Gemma prize)
      ↓
Fix + Explanation + Token Savings Report
```

---

## Token Efficiency (Track 1 criteria)

| Bug Type       | Without Routing | With Routing | Savings |
|----------------|-----------------|--------------|---------|
| Syntax error   | 70B → ~800 tok  | 8B → ~180 tok| **78%** |
| Logic error    | 70B → ~1200 tok | 8B → ~300 tok| **75%** |
| Architecture   | 70B → ~2000 tok | 70B → ~2000  | **0%**  |
| Average        |                 |              | **~65%**|

The router itself costs ~50 tokens. That overhead pays for itself immediately.

---

## AMD Stack

- **AMD Developer Cloud** — GPU compute for inference
- **ROCm** — AMD's open-source GPU platform
- **Fireworks AI API** — Model serving on AMD hardware
- **Gemma 4 31B** — Google DeepMind model via Fireworks (AMD Gemma prize eligible)

---

## Quick Start

### 1. Clone and configure
```bash
git clone <your-repo>
cd ghostdebugger
cp .env.example .env
# Edit .env and add your FIREWORKS_API_KEY
```

### 2. Get your API keys
- **Fireworks AI**: https://fireworks.ai/account/api-keys
- **AMD Developer Cloud**: https://developer.amd.com (hackathon credits included)

### 3. Run with Docker
```bash
docker compose up --build
```

Open http://localhost:8501 for the UI  
Open http://localhost:8000/docs for the API

### 4. Or run locally
```bash
pip install -r requirements.txt
# Terminal 1
python -m uvicorn api.main:app --port 8000 --reload
# Terminal 2
streamlit run frontend/app.py
```

---

## Project Structure

```
ghostdebugger/
├── agents/
│   ├── router.py       # Agent 1 — Complexity classification
│   ├── reproducer.py   # Agent 2 — Sandbox execution
│   ├── tracer.py       # Agent 3 — Root cause analysis
│   ├── fixer.py        # Agent 4 — Verified patch generation
│   └── reviewer.py     # Agent 5 — Gemma 4 post-mortem
├── core/
│   ├── llm_client.py   # Fireworks AI + AMD fallback client
│   ├── sandbox.py      # Safe subprocess code execution
│   └── pipeline.py     # Orchestrator
├── api/
│   └── main.py         # FastAPI backend
├── frontend/
│   └── app.py          # Streamlit UI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Why This Wins

1. **Real debugging** — not a chatbot. It actually runs your code.
2. **Verified fixes** — the fix is re-executed to confirm it works.
3. **Token efficiency is the core mechanic** — not a side feature.
4. **Gemma 4 as the reviewer** — AMD Gemma prize eligible.
5. **Engineered, not thrown together** — clean architecture, typed, logged, Dockerized, with resource-limited sandboxed execution.

---

## Known Limitations

Scoped deliberately for the hackathon timeline — flagged here rather than left for someone else to discover:

- **No authentication or rate limiting** on the API. Fine for a local/private demo; add before exposing publicly.
- **Sandbox is process-level isolation** (timeout + memory/CPU limits), not container/VM-level (gVisor, nsjail, Firecracker). Don't expose this instance to untrusted users on the open internet.
- **No persistence** — session stats and history are in-memory and reset on restart.
- **Single worker** — the pipeline runs in a background thread per request, so the server stays responsive, but overall throughput is still bounded by one process.

---

Built by **Franklin Josva A** · Team Singleton Vanguard  
*Build quietly. Win loudly.*
