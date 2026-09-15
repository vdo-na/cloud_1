import os
from sqlalchemy import create_engine, text
from pymongo import MongoClient

PG_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:9999/appdb")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/shop_db")

def migrate():
    print("Подключение к базам данных...")
    pg_engine = create_engine(PG_URL)
    mongo_client = MongoClient(MONGO_URL)
    mongo_db = mongo_client.get_default_database()
    cart_col = mongo_db["cart_items"]

    # Чтение данных из PostgreSQL
    with pg_engine.connect() as conn:
        result = conn.execute(text("SELECT user_id, product_id, quantity FROM cart_items"))
        rows = result.fetchall()

    if not rows:
        print("В PostgreSQL нет данных в cart_items для миграции.")
        return

    print(f"Найдено записей в PG: {len(rows)}. Перенос в MongoDB...")

    migrated_count = 0
    for row in rows:
        user_id, product_id, qty = row[0], row[1], row[2]
        # Вставляем или обновляем запись в Mongo
        cart_col.update_one(
            {"user_id": user_id, "product_id": product_id},
            {"$set": {"quantity": qty}},
            upsert=True
        )
        migrated_count += 1

    print(f"Миграция успешно завершена! Перенесено документов: {migrated_count}")

if __name__ == "__main__":
    migrate()