"""
Live smoke test — hits your real Groq + Tavily keys directly, bypassing all
mocks. Use this to confirm your keys actually work before deploying.

Named live_check.py (not smoke_test.py / *_test.py) on purpose, so pytest's
default collection doesn't try to pick it up alongside test_server.py.

Cost: a handful of Groq requests + one Tavily search. Well within free tiers.

Usage:
    export GROQ_API_KEY=gsk_...
    export TAVILY_API_KEY=tvly-...
    python live_check.py
"""

import asyncio
import os
import sys


def check_keys() -> None:
    missing = [k for k in ("GROQ_API_KEY", "TAVILY_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        print("Set them and try again, e.g.:")
        print("  export GROQ_API_KEY=gsk_...")
        print("  export TAVILY_API_KEY=tvly-...")
        sys.exit(1)


async def main() -> None:
    check_keys()
    import server  # import after confirming env vars, so the clients pick them up

    print("1/3 — Testing Groq (LLM)...")
    text = await server.call_text(
        "You are terse.", "Say 'ok' and nothing else.", max_tokens=10
    )
    print(f"    Groq responded: {text!r}")

    print("\n2/3 — Testing Tavily (search)...")
    results = await server.tavily_search("current weather in San Francisco")
    print(f"    Tavily returned {len(results)} result(s)")
    if results:
        print(f"    First result: {results[0].get('title')} ({results[0].get('url')})")

    print("\n3/3 — Running one full researcher step (Tavily + Groq combined)...")
    result = await server.research("What is Maritime's pricing model?")
    print(f"    Finding: {result['finding'][:200]}...")
    print(f"    Sources: {[s['url'] for s in result['sources']]}")

    print("\nAll checks passed — both keys are working.")


if __name__ == "__main__":
    asyncio.run(main())
