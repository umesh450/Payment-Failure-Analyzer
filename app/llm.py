"""
Optional AI narrative layer.

Takes the deterministic, rule-based insights produced by analyzer.py
and asks an LLM (Anthropic's Claude, via the Messages API) to turn
them into a short, readable executive summary. This is intentionally
kept separate from analyzer.py: the rule-based insights are the
trustworthy, auditable core, and the LLM only rephrases/summarizes
them — it never invents numbers.

If ANTHROPIC_API_KEY is not set, callers should fall back to just
displaying the raw insights (see main.py), so the app still works
end-to-end without an API key.
"""

from __future__ import annotations

import os
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

MODEL = "claude-sonnet-4-6"


def is_available() -> bool:
    return anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def summarize_insights(summary: dict[str, Any], insights: list[dict[str, str]]) -> str:
    """
    Ask Claude to write a short executive summary from the structured
    insights. Raises if the API is unavailable — callers should check
    is_available() first and handle the fallback themselves.
    """
    if not is_available():
        raise RuntimeError("ANTHROPIC_API_KEY not set; LLM summary unavailable.")

    client = anthropic.Anthropic()

    insight_lines = "\n".join(
        f"- {i['title']}: {i['detail']} Recommendation: {i['recommendation']}"
        for i in insights
    )

    prompt = f"""You are a payments analyst writing a short executive summary for a
merchant dashboard. Below is structured data on payment failures and a list of
pre-computed insights. Write a concise (120-180 word) plain-English summary
for a non-technical merchant, highlighting the 2-3 most important issues and
what to do about them. Do not invent numbers beyond what's given.

Overall failure rate: {summary['overall_failure_rate_pct']}%
Total transactions: {summary['total_transactions']}
Failed transactions: {summary['failed_transactions']}

Computed insights:
{insight_lines}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_blocks).strip()
