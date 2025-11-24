import os
import re
import asyncpg
from dotenv import load_dotenv
from typing import Optional
from rapidfuzz import fuzz, process

load_dotenv()

class Database:
    def __init__(self):
        self.pool = None
    
    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user= os.getenv("DB_USER"),
            password= os.getenv("DB_PASSWORD"),
            database= os.getenv("DB_NAME"),
            host= os.getenv("DB_HOST"),
            port= os.getenv("DB_PORT"),
        )

    async def fetchrow(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
        
    async def fetch(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
        
    async def execute(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def save_user(self, telegram_id, username):
        row = await self.fetchrow(
            "SELECT id FROM users WHERE telegram_id = $1",
            telegram_id
        )

        if row:
            return row["id"]

        row = await self.fetchrow(
            """
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            RETURNING id
            """,
            telegram_id,
            username
        )
        return row["id"]
    
    async def save_message(self, user_id, role, content):
        await self.execute(
            "INSERT INTO messages (user_id, role, content) VALUES ($1, $2, $3)",
            user_id,
            role,
            content,
        )

    async def search_messages(self, user_id: int, query: str, limit: int = 5):
        return await self.fetch(
            """
            SELECT content
            FROM messages
            WHERE user_id = $1
                AND content ILIKE '%' || $2 || '%'
            ORDER BY created_at DESC
            LIMIT $3;
            """,
            user_id,
            query,
            limit,
        )

    async def count_messages(self, user_id):
        row = await self.fetchrow(
            "SELECT COUNT(*) AS count FROM messages WHERE user_id = $1;", 
            user_id,
        )
        return row["count"]
    
    async def delete_old_messages(self, user_id: int, extra: int):
        await self.execute(
            """
            DELETE FROM messages
            WHERE id IN (
                SELECT id FROM messages
                WHERE user_id = $1
                ORDER BY created_at ASC
                LIMIT $2
            )
            """,
            user_id,
            extra
        )

import json

STORES_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "stores.json")

STORES: list[dict] = []

def load_stores():
    global STORES
    if STORES:
        return

    try:
        with open(STORES_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            STORES = data.get("stores", [])
            print(f"[DB] Loaded {len(STORES)} stores from JSON")
    except Exception as e:
        print(f"[DB] Error loading stores.json: {e}")
        STORES = []

def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _fuzzy_score(query: Optional[str], candidate: Optional[str]) -> float:
    query_norm = _normalize_text(query)
    candidate_norm = _normalize_text(candidate)
    if not query_norm or not candidate_norm:
        return 0.0
    return float(fuzz.token_set_ratio(query_norm, candidate_norm))


def search_stores(
    brand: Optional[str],
    city: Optional[str],
    region: Optional[str] = None,
    *,
    address: Optional[str] = None,
    limit: int = 10,
):

    load_stores()

    if not STORES:
        return []

    limit = max(1, limit or 10)

    field_weights = {
        "brand": 0.45,
        "city": 0.35,
        "address": 0.20,
    }

    query_values = {
        "brand": brand,
        "city": city,
        "address": address,
    }

    active_weights = {
        field: weight
        for field, weight in field_weights.items()
        if query_values.get(field)
    }

    if not active_weights:
        return []

    total_weight = sum(active_weights.values()) or 1.0

    scored_results: list[tuple[float, dict]] = []

    for store in STORES:
        if region:
            region_score = _fuzzy_score(region, store.get("region"))
            if region_score < 55:
                continue

        score = 0.0
        for field, weight in active_weights.items():
            store_value = store.get(field)
            score += (weight / total_weight) * _fuzzy_score(
                query_values[field],
                store_value,
            )

        if score == 0.0:
            continue

        scored_results.append((score, store))

    scored_results.sort(key=lambda item: item[0], reverse=True)

    return [store for _, store in scored_results[:limit]]

if __name__ == "__main__":
    load_stores()
    print(search_stores("Наша Ряба", "Покровськ"))