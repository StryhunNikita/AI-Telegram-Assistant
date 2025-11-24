from Bot.db import Database

async def add_user_message(db: Database, user_id: int, text: str) -> None:
    await db.save_message(user_id, "user", text)

    count = await db.count_messages(user_id)
    if count > 30:
        extra = count - 30
        await db.delete_old_messages(user_id, extra)

async def add_assistant_message(db: Database,user_id: int, text: str) -> None:
    await db.save_message(user_id, "assistant", text)

    count = await db.count_messages(user_id)
    if count > 30:
        extra = count - 30
        await db.delete_old_messages(user_id, extra)

async def get_messages_for_model(db: Database, user_id: int, limit: int = 10) -> list[dict]:
    rows = await db.fetch("SELECT role, content FROM messages WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2", user_id, limit)        

    messages = []
    for row in reversed(rows):
        messages.append({
            "role": row["role"],
            "content": row["content"],
        })
    return messages

async def reset_history(db: Database, user_id: int) -> None:
    await db.execute(
        "DELETE FROM messages WHERE user_id = $1",
        user_id,
    )
