# Research Swarm

A tiny multi-agent research pipeline, built to run on [Maritime](https://maritime.sh).
Runs entirely on **free tiers — $0 to run**.

Ask it a question. Under the hood:

1. **Dispatcher** — breaks your question into 3 distinct research angles (Groq)
2. **Researchers** — 3 agents run in parallel, each searches the web for one
   angle (Tavily) and writes up a finding (Groq)
3. **Synthesizer** — merges all findings into one answer with cited sources (Groq)

The UI shows the swarm working in real time: a dispatcher node pings out to
each researcher, they light up as they report back, then everything converges
into a synthesizer node and a final cited answer.

**Stack:**
- LLM: [Groq](https://groq.com) — free, no credit card, runs Llama 3.3 70B at
  very high speed
- Search: [Tavily](https://tavily.com) — 1,000 free search credits/month, no
  credit card

---

## 1. Get your two free API keys

### Groq (LLM)
1. Go to **console.groq.com**
2. Sign up with email or Google/GitHub — no credit card required
3. Go to **API Keys** in the left sidebar → **Create API Key**
4. Copy the key (starts with `gsk_...`)

### Tavily (search)
1. Go to **tavily.com** → **Get API Key** / **Sign Up**
2. Sign up with email or Google/GitHub — no credit card required
3. Your API key is shown on your dashboard immediately (starts with `tvly-...`)
4. Copy it

That's it — both are genuinely free tiers, no trial period, no card on file.

---

## 2. Run it locally first

```bash
cd research-swarm
pip install -r requirements.txt

export GROQ_API_KEY=gsk_...
export TAVILY_API_KEY=tvly-...

uvicorn server:app --reload --port 8080
```

Open **http://localhost:8080**, type a question, watch it run.

Quick sanity check without opening a browser:
```bash
curl http://localhost:8080/health
# {"status":"ok","groq_key_set":true,"tavily_key_set":true}
```

### Run the test suite
No API keys or network needed — all Groq/Tavily calls are mocked:
```bash
pip install pytest httpx
python -m pytest test_server.py -v
```

---

## 3. Deploy to Maritime

From the `research-swarm` directory:

```bash
# 1. install the CLI if you haven't already
npm i -g maritime

# 2. log in
maritime login

# 3. create the agent — Maritime detects the Dockerfile and builds from it
maritime init research-swarm
maritime deploy

# 4. set your two keys as encrypted secrets (never baked into the image)
maritime env set GROQ_API_KEY=gsk_...
maritime env set TAVILY_API_KEY=tvly-...
```

Once deployed you'll get a live URL — open it, ask a question, watch the
pings go out. Check `/health` on that URL to confirm both keys made it
through.

### Optional tuning
```bash
maritime env set SWARM_SIZE=3            # number of parallel researchers
maritime env set SWARM_MODEL=llama-3.3-70b-versatile
maritime env set TAVILY_MAX_RESULTS=5    # search results per researcher
```

---

## Cost / free-tier limits to know

- **Groq free tier**: no credit card, rate-limited (roughly 30 requests/min,
  ~1,000 requests/day depending on model). Every question run uses 5 Groq
  calls (1 dispatcher + 3 researchers + 1 synthesizer), so that's plenty of
  headroom for a demo — you'd need sustained heavy traffic to hit the ceiling.
- **Tavily free tier**: 1,000 search credits/month, no credit card. Each
  question run uses 3 searches (one per researcher), so ~330 question runs/month
  before you'd need to pay anything.
- **Maritime hosting**: the $1/month Smart tier covers up to 1,000
  invocations, which is what this is built for.

If you outgrow the free tiers: Groq's paid Developer tier removes the rate
caps for free (just adds a card, no minimum spend); Tavily's paid plans start
around $30/month for more search volume.

---

## Notes / things to know

- **Concurrency**: each `/run` call spawns a background asyncio task and
  returns immediately with a `job_id`; the frontend polls `/jobs/{job_id}`
  every ~900ms.
- **Job state lives in memory** — fine for a demo, but resets if the
  container sleeps and wakes on a fresh instance. Swap in Redis/Postgres if
  you want jobs to survive restarts.
- **Model choice**: Groq only hosts open-source models (no Claude/GPT).
  `llama-3.3-70b-versatile` is the default and is the closest match in
  quality; swap via `SWARM_MODEL` if you want to try something else Groq
  hosts (e.g. a smaller/faster model for even lower latency).
- **No fabricated sources**: researchers are instructed to only use
  information present in the actual Tavily search results, and sources shown
  in the UI come directly from Tavily's structured output — not from the LLM
  guessing URLs.

## Files

```
server.py        FastAPI app: dispatcher / researcher / synthesizer + job API
static/index.html  Sonar-style swarm visualization + polling frontend
requirements.txt
Dockerfile        Python 3.12-slim, uvicorn on port 8080 (Maritime's standard pattern)
test_server.py    Unit + integration tests with mocked Groq/Tavily calls
```
