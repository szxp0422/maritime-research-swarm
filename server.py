"""
Research Swarm — a tiny multi-agent research pipeline for Maritime.

Runs entirely on free tiers:
  LLM      -> Groq (OpenAI-compatible API, free rate-limited tier, no card)
  Search   -> Tavily (1,000 free search credits/month, no card)

Flow:
  dispatcher   -> breaks the question into N distinct research angles
  researchers  -> N parallel agents, each searches Tavily for one angle,
                  then asks Groq to write up a concise finding from the results
  synthesizer  -> merges all findings into one cited answer

Env vars:
  GROQ_API_KEY        required (get one free at console.groq.com)
  TAVILY_API_KEY      required (get one free at tavily.com)
  SWARM_MODEL         optional, defaults to "llama-3.3-70b-versatile"
  SWARM_SIZE          optional, defaults to 3 researchers
  TAVILY_MAX_RESULTS  optional, defaults to 5 results per search
"""

import asyncio
import json
import os
import re
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel
from tavily import TavilyClient

MODEL = os.environ.get("SWARM_MODEL", "llama-3.3-70b-versatile")
NUM_RESEARCHERS = int(os.environ.get("SWARM_SIZE", "3"))
TAVILY_MAX_RESULTS = int(os.environ.get("TAVILY_MAX_RESULTS", "5"))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

app = FastAPI(title="Research Swarm")

# Placeholder strings let the client construct even if a key is missing at
# boot — a real request without a key fails cleanly inside run_swarm and
# surfaces as a job "error" status instead of crashing the whole process.
groq = AsyncOpenAI(
    api_key=GROQ_API_KEY or "not-set",
    base_url="https://api.groq.com/openai/v1",
)
tavily = TavilyClient(api_key=TAVILY_API_KEY or "not-set")

JOBS: dict[str, dict] = {}


class RunRequest(BaseModel):
    question: str


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw)
    raw = re.sub(r"```$", "", raw)
    return raw.strip()


def new_job(question: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "job_id": job_id,
        "question": question,
        "status": "dispatching",  # dispatching -> researching -> synthesizing -> done | error
        "sub_questions": [],
        "answer": None,
        "sources": [],
        "error": None,
    }
    return job_id


async def call_text(system: str, user: str, max_tokens: int = 1024) -> str:
    resp = await groq.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def tavily_search(query: str) -> list[dict]:
    def _search():
        return tavily.search(
            query=query,
            search_depth="basic",
            max_results=TAVILY_MAX_RESULTS,
            include_answer=False,
        )

    result = await asyncio.to_thread(_search)
    return result.get("results", [])


async def dispatch(question: str) -> list[str]:
    system = (
        "You are the dispatcher of a research swarm. Break the user's question into "
        f"exactly {NUM_RESEARCHERS} distinct, non-overlapping research angles that "
        "together would produce a thorough answer. Respond with ONLY a JSON array of "
        "strings, nothing else — no prose, no markdown fences."
    )
    raw = await call_text(system, question, max_tokens=400)
    raw = _strip_fences(raw)
    try:
        angles = [str(a) for a in json.loads(raw)][:NUM_RESEARCHERS]
    except Exception:
        angles = []
    if not angles:
        angles = [question]
    while len(angles) < NUM_RESEARCHERS:
        angles.append(question)
    return angles


async def research(sub_question: str) -> dict:
    results = await tavily_search(sub_question)
    if not results:
        return {"finding": "No search results found for this angle.", "sources": []}

    bundle = "\n\n".join(
        f"Source: {r.get('title', 'untitled')} ({r.get('url', '')})\n"
        f"{(r.get('content') or '')[:800]}"
        for r in results
    )
    system = (
        "You are a research agent. Given raw web search results, write a concise "
        "4-8 sentence factual finding that answers the question. Only use "
        "information present in the results below — do not fabricate facts or "
        "cite anything not shown here."
    )
    user = f"Question: {sub_question}\n\nSearch results:\n{bundle}"
    finding = await call_text(system, user, max_tokens=500)

    sources = [
        {"title": r.get("title") or r.get("url"), "url": r.get("url")}
        for r in results
        if r.get("url")
    ]
    return {"finding": finding.strip(), "sources": sources[:5]}


async def synthesize(question: str, findings: list[dict]) -> dict:
    bundle = "\n\n".join(
        f"[Angle {i + 1}] {f['sub_question']}\n"
        f"Finding: {f['finding']}\n"
        f"Sources: {', '.join(s['url'] for s in f['sources']) or 'none'}"
        for i, f in enumerate(findings)
    )
    system = (
        "You are the synthesizer of a research swarm. Combine the researchers' "
        "findings into one clear, well-organized answer to the original question, "
        "150-300 words. Reference sources inline with bracketed numbers like [1], [2] "
        "matching a source list you also produce. Respond with ONLY JSON of the shape "
        '{"answer": string, "sources": [{"title": string, "url": string}]}. '
        "No markdown fences, no prose outside the JSON."
    )
    raw = await call_text(
        system, f"Original question: {question}\n\n{bundle}", max_tokens=1200
    )
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
    except Exception:
        data = {"answer": raw, "sources": []}
    return data


async def run_swarm(job_id: str) -> None:
    job = JOBS[job_id]
    try:
        job["status"] = "dispatching"
        angles = await dispatch(job["question"])
        job["sub_questions"] = [
            {"id": i, "text": a, "status": "pending", "finding": None, "sources": []}
            for i, a in enumerate(angles)
        ]
        job["status"] = "researching"

        async def run_one(i: int, sq: dict) -> None:
            job["sub_questions"][i]["status"] = "active"
            result = await research(sq["text"])
            job["sub_questions"][i]["status"] = "done"
            job["sub_questions"][i]["finding"] = result["finding"]
            job["sub_questions"][i]["sources"] = result["sources"]

        await asyncio.gather(
            *(run_one(i, sq) for i, sq in enumerate(job["sub_questions"]))
        )

        job["status"] = "synthesizing"
        findings = [
            {
                "sub_question": sq["text"],
                "finding": sq["finding"] or "",
                "sources": sq["sources"],
            }
            for sq in job["sub_questions"]
        ]
        result = await synthesize(job["question"], findings)
        job["answer"] = result.get("answer", "")
        job["sources"] = result.get("sources", [])
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)


@app.post("/run")
async def start_run(req: RunRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question required")
    job_id = new_job(req.question.strip())
    asyncio.create_task(run_swarm(job_id))
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "groq_key_set": bool(GROQ_API_KEY),
        "tavily_key_set": bool(TAVILY_API_KEY),
    }


@app.websocket_route("/{path:path}")
async def reject_websocket(websocket):
    # StaticFiles (mounted below) only handles HTTP scope and throws an
    # unhandled AssertionError on anything else. Maritime's tunnel/proxy
    # infra appears to probe with a WebSocket upgrade occasionally — close
    # it cleanly instead of letting that exception surface in the logs.
    await websocket.close(code=1008)


app.mount("/", StaticFiles(directory="static", html=True), name="static")