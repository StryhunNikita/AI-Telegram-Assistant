import os
import json
import httpx
import dotenv
from .db import Database

dotenv.load_dotenv()
openai_key = os.getenv("OPENAI_API_KEY")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_messages",
            "description": "Поиск сообщений пользователя в истории по ключевому слову",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Текст для поиска в истории сообщений пользователя"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное количество сообщений",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    }
]

async def _call_openai(data: dict) -> dict:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("[OPENAI ERROR]", e)
        return {"error": "openai_error"}

async def ask_openai(
    messages: list[dict],
    db: Database,
    user_id: int,
) -> str:
    if not openai_key:
        return "Ошибка: не найден OPENAI_API_KEY."

    system_prompt = (
        "Ты дружелюбный ассистент.\n"
        "Если пользователь просит найти, вспомнить или показать его прошлые сообщения, "
        "используй tool `search_messages`.\n"
        "Отвечай кратко и по делу."
    )

    base_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    data = {
        "model": "gpt-4.1-mini",
        "messages": base_messages,
        "max_tokens": 250,
        "temperature": 0.4,
        "tools": TOOLS,
        "tool_choice": "auto",
    }

    body = await _call_openai(data)
    if "error" in body:
        return body["error"]

    try:
        first_message = body["choices"][0]["message"]
    except (KeyError, IndexError):
        return "Не смог разобрать ответ от модели."

    tool_calls = first_message.get("tool_calls")

    if not tool_calls:
        content = first_message.get("content")
        if content is None:
            return "Модель не вернула текстового ответа."
        return content.strip()

    tool_messages = []

    for call in tool_calls:
        func = call.get("function", {})
        name = func.get("name")
        raw_args = func.get("arguments", "{}")

        if name != "search_messages":
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name or "unknown_tool",
                "content": "[]",
            })
            continue

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": "[]",
            })
            continue

        query = args.get("query")
        limit = args.get("limit", 5)

        if not query:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": "[]",
            })
            continue

        try:
            rows = await db.search_messages(user_id, query, limit)
        except Exception as e:
            return f"Ошибка при поиске в базе данных: {e}"

        search_result = [{"content": row["content"]} for row in rows]

        tool_messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "name": name,
            "content": json.dumps(search_result, ensure_ascii=False),
        })

    followup_messages = [
        *base_messages,
        {
            "role": "assistant",
            "tool_calls": tool_calls,
            "content": first_message.get("content") or "",
        },
        *tool_messages,
    ]

    second_data = {
        "model": "gpt-4.1-mini",
        "messages": followup_messages,
        "max_tokens": 250,
        "temperature": 0.4,
    }

    body2 = await _call_openai(second_data)
    if "error" in body2:
        return body2["error"]

    try:
        final_message = body2["choices"][0]["message"]
        content = final_message.get("content")
        if content is None:
            return "Модель не вернула текстового ответа после вызова инструмента."
        return content.strip()
    except (KeyError, IndexError):
        return "Не смог разобрать финальный ответ от модели."

async def extract_store_query(user_text: str) -> dict:
    if not openai_key:
        return {"is_store_query": False, "brand": None, "city": None, "region": None}

    system_prompt = """
    Ты модуль разбора запросов для поиска магазинов.

    Твоя задача:
    1) Определить, является ли сообщение пользователя запросом на поиск магазина/сети/заведения.
    2) Если да — извлечь:
    - brand: название сети/бренда (например: "Наша Ряба", "АТБ", "М’ясомаркет");
    - city: город (как он написан в тексте, даже с ошибками, например: "чернике");
    - region: область (если явно указана, иначе null).

    Если сообщение НЕ про поиск магазинов (обычный разговор, вопрос ни о чём и т.п.),
    то is_store_query = false, а brand/city/region = null.

    Важные примеры:
    - "найди нашу рябу в чернике" → is_store_query=true, brand="Наша Ряба", city="чернике"
    - "найди магазины мяса в Киеве" → is_store_query=true, brand=null, city="Киеве"
    - "привет, как дела?" → is_store_query=false

    Формат ответа: строго JSON
    {
    "is_store_query": boolean,
    "brand": string | null,
    "city": string | null,
    "region": string | null
    }
    """

    payload = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    response = await _call_openai(payload)
    if "error" in response:
        return {"is_store_query": False, "brand": None, "city": None, "region": None}

    try:
        raw = response["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except Exception as e:
        print("[extract_store_query] JSON parse error:", e)
        print("[extract_store_query] RAW:", response)
        return {"is_store_query": False, "brand": None, "city": None, "region": None}

    return {
        "is_store_query": bool(parsed.get("is_store_query", False)),
        "brand": parsed.get("brand"),
        "city": parsed.get("city"),
        "region": parsed.get("region"),
    }