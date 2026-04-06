import os

import anthropic
from fastapi import HTTPException


def claude_chat(system: str, user: str, max_tokens: int = 1000) -> str:
    """Substitui _openai_chat -- mesma interface, provider diferente."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY não configurado no Railway.")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text.strip()
