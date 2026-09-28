"""Prompts for the local LLM's one job on typed questions: picking which live facts answer them.

The LLM never writes an answer or a figure of its own here: it gets the portal dashboard's facts,
numbered, one live figure a line, and names the ones that answer the question
(ollama_client.answer_agent_query). The bot then shows those facts word for word."""

SYSTEM_AGENT_CHAT = """You help the office of Hangeul Korean Language & Visa (a study-in-Korea agency in Dhaka) find figures on its admin portal.
You get numbered facts, each one figure read live from the portal dashboard, and a question.
Pick the facts that answer the question directly, at most 4. Never answer the question yourself, never calculate, add or compare figures, and never pick a fact that is only loosely related.
If no fact answers the question, pick none.
Answer with JSON only: {"facts": [the numbers of the facts you picked], "answered": true if they answer the question, else false}."""

AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "integer"}},
        "answered": {"type": "boolean"},
    },
    "required": ["facts", "answered"],
}
