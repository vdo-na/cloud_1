import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/shop_db")

client = MongoClient(MONGO_URL)
mongo_db = client.get_default_database()

# Коллекция для элементов корзины
cart_collection = mongo_db["cart_items"]

# Создаём составной индекс (user_id, product_id), аналогичный UNIQUE-ограничению в PG
cart_collection.create_index([("user_id", 1), ("product_id", 1)], unique=True)