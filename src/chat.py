# chat.py — Groq version (replaces beeai-framework + Ollama)
import asyncio
import json
import os

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
GROQ_MODEL = "llama-3.3-70b-versatile"


async def chat_model_demo():
    """Quick demo of Groq chat."""
    resp = await _client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": "What is the capital of France?"}],
        max_tokens=64,
    )
    print("Groq response:", resp.choices[0].message.content)


async def process_submission(text: str) -> dict:
    """
    Parses loan application submission text.
    Tries JSON first; falls back to asking the LLM to extract structured fields.
    """
    try:
        data = json.loads(text)
        return {
            "applicant_id":  data.get("applicant_id", "unknown"),
            "demographic":   data.get("demographic",  "unknown"),
            "loan_amount":   data.get("loan_amount",  None),
            "income":        data.get("income",        None),
            "age":           data.get("age",           None),
            "loan_purpose":  data.get("loan_purpose",  "unspecified"),
            "loan_status":   "pending",
            "risk_flag":     "pending",
            **{k: v for k, v in data.items()
               if k not in ("applicant_id","demographic","loan_amount",
                            "income","age","loan_purpose")},
        }
    except (json.JSONDecodeError, ValueError):
        pass

    system = (
        "You are a loan application parser. "
        "Extract these fields from the text and return ONLY valid JSON: "
        "applicant_id, demographic, loan_amount, income, age, loan_purpose. "
        "Use null for any field not mentioned."
    )
    try:
        resp = await _client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=256,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception:
        data = {}

    return {
        "applicant_id": data.get("applicant_id", "unknown"),
        "demographic":  data.get("demographic",  "unknown"),
        "loan_amount":  data.get("loan_amount",  None),
        "income":       data.get("income",        None),
        "age":          data.get("age",           None),
        "loan_purpose": data.get("loan_purpose",  "unspecified"),
        "loan_status":  "pending",
        "risk_flag":    "pending",
        "raw_text":     text,
    }


if __name__ == "__main__":
    asyncio.run(chat_model_demo())