"""
Минимальный backend интернет-магазина для лабы №1 (п.3).
Товары (каталог) хранятся в PostgreSQL через Pgpool II.
Корзина пользователей перенесена в NoSQL базу данных MongoDB.
"""
import sys
import io

# Принудительно устанавливаем кодировку вывода в UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
import time
from decimal import Decimal
from typing import List

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# ---------- Подключение к PostgreSQL ----------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://app:app@localhost:9999/appdb",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------- Подключение к MongoDB ----------
MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://localhost:27017/shop_db",
)
mongo_client = MongoClient(MONGO_URL)
mongo_db = mongo_client.get_default_database()
cart_collection = mongo_db["cart_items"]


# ---------- SQLAlchemy модели (PostgreSQL) ----------
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
    )


# Старая таблица корзины (оставлена в схеме для возможности миграции данных)
class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_user_product"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


SEED_PRODUCTS = [
    ("Ноутбук", 'Легкий ноутбук 14"', Decimal("79990.00"), 10),
    ("Мышь", "Беспроводная мышь", Decimal("1490.00"), 50),
    ("Клавиатура", "Механическая клавиатура", Decimal("5990.00"), 25),
    ("Наушники", "Накладные наушники", Decimal("3490.00"), 40),
    ("Монитор", '27" IPS монитор', Decimal("24990.00"), 15),
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_if_empty(db: Session) -> None:
    if db.query(Product).count() == 0:
        for name, description, price, stock in SEED_PRODUCTS:
            db.add(
                Product(name=name, description=description, price=price, stock=stock)
            )
        db.commit()


app = FastAPI(
    title="Shop API",
    description="Минимальный CRUD интернет-магазина (PostgreSQL товары + MongoDB корзина)",
    version="2.0.0",
)


@app.on_event("startup")
def on_startup():
    # 1. Настройка индексов MongoDB
    try:
        cart_collection.create_index([("user_id", 1), ("product_id", 1)], unique=True)
    except Exception as exc:
        print(f"Предупреждение при создании индекса MongoDB: {exc}")

    # 2. Ожидание и инициализация PostgreSQL / Pgpool
    last_error = None
    for attempt in range(30):
        try:
            Base.metadata.create_all(bind=engine)
            db = SessionLocal()
            try:
                seed_if_empty(db)
            finally:
                db.close()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Не удалось подключиться к БД PostgreSQL: {last_error}")


# ---------- Pydantic-схемы ----------

class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    price: Decimal = Field(ge=0)
    stock: int = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)


class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    price: Decimal
    stock: int

    model_config = {"from_attributes": True}


class CartItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1)


class CartItemOut(BaseModel):
    id: str  # В Mongo идентификатор позиции представлен строковым ObjectId
    user_id: str
    product_id: int
    quantity: int
    product_name: str
    product_price: Decimal
    line_total: Decimal


class CartOut(BaseModel):
    user_id: str
    items: List[CartItemOut]
    total: Decimal


# ---------- Товары (PostgreSQL Multimaster) ----------

@app.get("/products", response_model=List[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).order_by(Product.id).all()


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return product


@app.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.put("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return product


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    db.delete(product)
    db.commit()


# ---------- Корзина (MongoDB) ----------

@app.get("/cart/{user_id}", response_model=CartOut)
def get_cart(user_id: str, db: Session = Depends(get_db)):
    # Читаем элементы корзины пользователя из MongoDB
    docs = list(cart_collection.find({"user_id": user_id}))
    if not docs:
        return CartOut(user_id=user_id, items=[], total=Decimal("0"))

    # Собираем product_id для пакетного запроса данных из PostgreSQL
    product_ids = [doc["product_id"] for doc in docs]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    prod_map = {p.id: p for p in products}

    out_items: List[CartItemOut] = []
    for doc in docs:
        prod = prod_map.get(doc["product_id"])
        name = prod.name if prod else "Неизвестный товар"
        price = prod.price if prod else Decimal("0.00")
        qty = doc["quantity"]
        out_items.append(
            CartItemOut(
                id=str(doc["_id"]),
                user_id=doc["user_id"],
                product_id=doc["product_id"],
                quantity=qty,
                product_name=name,
                product_price=price,
                line_total=price * qty,
            )
        )

    total = sum((i.line_total for i in out_items), Decimal("0"))
    return CartOut(user_id=user_id, items=out_items, total=total)


@app.post("/cart/{user_id}/items", response_model=CartItemOut, status_code=201)
def add_to_cart(user_id: str, payload: CartItemCreate, db: Session = Depends(get_db)):
    # 1. Проверяем наличие товара и остаток на складе в PostgreSQL
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")

    existing_doc = cart_collection.find_one({"user_id": user_id, "product_id": payload.product_id})
    current_qty = existing_doc["quantity"] if existing_doc else 0
    total_qty = current_qty + payload.quantity

    if product.stock < total_qty:
        raise HTTPException(status_code=400, detail="Недостаточно товара на складе")

    # 2. Сохраняем/обновляем в MongoDB
    doc = cart_collection.find_one_and_update(
        {"user_id": user_id, "product_id": payload.product_id},
        {"$inc": {"quantity": payload.quantity}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    return CartItemOut(
        id=str(doc["_id"]),
        user_id=user_id,
        product_id=payload.product_id,
        quantity=doc["quantity"],
        product_name=product.name,
        product_price=product.price,
        line_total=product.price * doc["quantity"],
    )


@app.put("/cart/{user_id}/items/{item_id}", response_model=CartItemOut)
def update_cart_item(
    user_id: str,
    item_id: str,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        obj_id = ObjectId(item_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Некорректный ID позиции")

    doc = cart_collection.find_one({"_id": obj_id, "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Позиция корзины не найдена")

    product = db.get(Product, doc["product_id"])
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден в каталоге")
    if product.stock < payload.quantity:
        raise HTTPException(status_code=400, detail="Недостаточно товара на складе")

    updated_doc = cart_collection.find_one_and_update(
        {"_id": obj_id},
        {"$set": {"quantity": payload.quantity}},
        return_document=ReturnDocument.AFTER,
    )

    return CartItemOut(
        id=str(updated_doc["_id"]),
        user_id=user_id,
        product_id=updated_doc["product_id"],
        quantity=updated_doc["quantity"],
        product_name=product.name,
        product_price=product.price,
        line_total=product.price * updated_doc["quantity"],
    )


@app.delete("/cart/{user_id}/items/{item_id}", status_code=204)
def remove_from_cart(user_id: str, item_id: str):
    try:
        obj_id = ObjectId(item_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Некорректный ID позиции")

    res = cart_collection.delete_one({"_id": obj_id, "user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Позиция корзины не найдена")


@app.delete("/cart/{user_id}", status_code=204)
def clear_cart(user_id: str):
    cart_collection.delete_many({"user_id": user_id})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    # Проверка PostgreSQL
    db.execute(text("SELECT 1"))
    # Проверка MongoDB
    mongo_client.admin.command("ping")
    return {
        "status": "ok",
        "databases": {
            "products": "postgresql via pgpool",
            "cart": "mongodb",
        },
    }