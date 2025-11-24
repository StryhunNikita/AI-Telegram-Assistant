import os
import json
from typing import Optional
import httpx
import dotenv
from .db import Database, search_stores

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
    },
    {
        "type": "function",
        "function": {
            "name": "search_stores",
            "description": "Поиск магазинов по бренду, городу, адресу и/или региону",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Название сети или бренда",
                    },
                    "city": {
                        "type": "string",
                        "description": "Город или населённый пункт",
                    },
                    "address": {
                        "type": "string",
                        "description": "Улица, микрорайон или ориентир",
                    },
                    "region": {
                        "type": "string",
                        "description": "Регион или область",
                    },
                },
            },
        },
    },
]


def _build_tool_message(call: dict, name: Optional[str], content: str = "[]") -> dict:
    return {
        "role": "tool",
        "tool_call_id": call.get("id", ""),
        "name": name or "unknown_tool",
        "content": content,
    }

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


async def _handle_search_messages_call(
    call: dict,
    args: dict,
    db: Database,
    user_id: int,
):
    query = args.get("query")
    limit = args.get("limit", 5)

    if not query:
        return _build_tool_message(call, "search_messages")

    try:
        rows = await db.search_messages(user_id, query, limit)
    except Exception as e:
        return f"Ошибка при поиске в базе данных: {e}"

    payload = [{"content": row["content"]} for row in rows]
    return _build_tool_message(
        call,
        "search_messages",
        json.dumps(payload, ensure_ascii=False),
    )


def _handle_search_stores_call(call: dict, args: dict):
    brand = args.get("brand")
    city = args.get("city")
    address = args.get("address")
    region = args.get("region")

    if not any([brand, city, address, region]):
        return _build_tool_message(call, "search_stores")

    stores = search_stores(
        brand=brand,
        city=city,
        region=region,
        address=address,
        limit=10,
    )

    return _build_tool_message(
        call,
        "search_stores",
        json.dumps(stores, ensure_ascii=False),
    )


async def _process_tool_calls(
    tool_calls: list[dict],
    db: Database,
    user_id: int,
) -> tuple[Optional[str], list[dict]]:
    tool_messages: list[dict] = []

    for call in tool_calls:
        func = call.get("function", {})
        name = func.get("name")
        raw_args = func.get("arguments", "{}")

        if name not in {"search_messages", "search_stores"}:
            tool_messages.append(_build_tool_message(call, name))
            continue

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            tool_messages.append(_build_tool_message(call, name))
            continue

        if name == "search_messages":
            result = await _handle_search_messages_call(call, args, db, user_id)
        else:
            result = _handle_search_stores_call(call, args)

        if isinstance(result, str):
            return result, []

        tool_messages.append(result)

    return None, tool_messages

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
        "Если пользователь хочет найти магазины/бренд по городу/адресу, вызывай tool `search_stores`.\n"
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

    error, tool_messages = await _process_tool_calls(tool_calls, db, user_id)
    if error:
        return error

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