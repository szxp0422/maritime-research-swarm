import asyncio
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GROQ_API_KEY", "test-groq-key-not-real")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key-not-real")

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def chat_response(text):
    """Mimic an OpenAI-compatible chat.completions.create response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_dispatch_parses_json_array():
    resp = chat_response('["angle a", "angle b", "angle c"]')
    with patch.object(server.groq.chat.completions, "create", AsyncMock(return_value=resp)):
        angles = asyncio.run(server.dispatch("what happened with X?"))
    assert angles == ["angle a", "angle b", "angle c"]


def test_dispatch_falls_back_on_bad_json():
    resp = chat_response("not json at all")
    with patch.object(server.groq.chat.completions, "create", AsyncMock(return_value=resp)):
        angles = asyncio.run(server.dispatch("q"))
    assert len(angles) == server.NUM_RESEARCHERS
    assert all(a == "q" for a in angles)


def test_research_combines_tavily_and_groq():
    fake_search_result = {
        "results": [
            {"title": "Example A", "url": "https://example.com/a", "content": "Some raw content."},
            {"title": "Example B", "url": "https://example.com/b", "content": "More raw content."},
        ]
    }
    resp = chat_response("Some synthesized finding.")
    with patch.object(server.tavily, "search", MagicMock(return_value=fake_search_result)), patch.object(
        server.groq.chat.completions, "create", AsyncMock(return_value=resp)
    ):
        result = asyncio.run(server.research("sub question"))

    assert result["finding"] == "Some synthesized finding."
    assert result["sources"] == [
        {"title": "Example A", "url": "https://example.com/a"},
        {"title": "Example B", "url": "https://example.com/b"},
    ]


def test_research_handles_empty_search_results():
    with patch.object(server.tavily, "search", MagicMock(return_value={"results": []})):
        result = asyncio.run(server.research("obscure question"))
    assert result["sources"] == []
    assert "no search results" in result["finding"].lower()


def test_synthesize_parses_json():
    payload = {"answer": "final answer", "sources": [{"title": "t", "url": "u"}]}
    resp = chat_response(json.dumps(payload))
    with patch.object(server.groq.chat.completions, "create", AsyncMock(return_value=resp)):
        result = asyncio.run(
            server.synthesize("q", [{"sub_question": "a", "finding": "f", "sources": []}])
        )
    assert result == payload


def test_synthesize_falls_back_to_raw_text_on_bad_json():
    resp = chat_response("just prose, not json")
    with patch.object(server.groq.chat.completions, "create", AsyncMock(return_value=resp)):
        result = asyncio.run(
            server.synthesize("q", [{"sub_question": "a", "finding": "f", "sources": []}])
        )
    assert result["answer"] == "just prose, not json"
    assert result["sources"] == []


def test_full_http_flow_with_mocked_agents():
    """Exercise /run -> background task -> /jobs/{id} end to end with fast fake agents."""

    async def fake_dispatch(question):
        return ["angle 1", "angle 2", "angle 3"]

    async def fake_research(sub_question):
        return {
            "finding": f"finding for {sub_question}",
            "sources": [{"title": "src", "url": "https://example.com"}],
        }

    async def fake_synthesize(question, findings):
        return {"answer": "merged answer", "sources": [{"title": "s", "url": "https://x.com"}]}

    with patch.object(server, "dispatch", fake_dispatch), patch.object(
        server, "research", fake_research
    ), patch.object(server, "synthesize", fake_synthesize):
        with TestClient(server.app) as client:
            res = client.post("/run", json={"question": "why is the sky blue"})
            assert res.status_code == 200
            job_id = res.json()["job_id"]

            deadline = time.time() + 5
            job = None
            while time.time() < deadline:
                job = client.get(f"/jobs/{job_id}").json()
                if job["status"] in ("done", "error"):
                    break
                time.sleep(0.05)

            assert job["status"] == "done", job
            assert job["answer"] == "merged answer"
            assert len(job["sub_questions"]) == 3
            assert all(sq["status"] == "done" for sq in job["sub_questions"])


def test_health_reports_key_presence():
    with TestClient(server.app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["groq_key_set"] is True
        assert body["tavily_key_set"] is True


def test_run_requires_question():
    with TestClient(server.app) as client:
        res = client.post("/run", json={"question": "   "})
        assert res.status_code == 400
