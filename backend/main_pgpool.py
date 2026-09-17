"""
Отдельный backend для нагрузочного теста pgpool (п.4).
Корзина и товары — в PostgreSQL через Pgpool II.
Файлы подруги (main.py с Mongo) не трогаем.
Подключается к PostgreSQL через Pgpool II.
DATABASE_URL по умолчанию — localhost:9999; в Docker — хост pgpool.
"""

import os
import time
from decimal import Decimal
from typing import List

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
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
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://app:app@localhost:9999/appdb",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


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

    cart_items = relationship("CartItem", back_populates="product", cascade="all, delete-orphan")


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

    product = relationship("Product", back_populates="cart_items")


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
    title="Shop API (pgpool / PostgreSQL cart)",
    description="Вариант для п.4: товары и корзина через PostgreSQL multimaster + pgpool",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    # Ждём pgpool/postgres (в docker compose они могут стартовать чуть позже)
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
    raise RuntimeError(f"Не удалось подключиться к БД: {last_error}")


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
    id: int
    user_id: str
    product_id: int
    quantity: int
    product_name: str
    product_price: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class CartOut(BaseModel):
    user_id: str
    items: List[CartItemOut]
    total: Decimal


def cart_item_to_out(item: CartItem) -> CartItemOut:
    return CartItemOut(
        id=item.id,
        user_id=item.user_id,
        product_id=item.product_id,
        quantity=item.quantity,
        product_name=item.product.name,
        product_price=item.product.price,
        line_total=item.product.price * item.quantity,
    )


# ---------- Товары ----------

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


# ---------- Корзина ----------

@app.get("/cart/{user_id}", response_model=CartOut)
def get_cart(user_id: str, db: Session = Depends(get_db)):
    items = (
        db.query(CartItem)
        .filter(CartItem.user_id == user_id)
        .order_by(CartItem.id)
        .all()
    )
    out_items = [cart_item_to_out(i) for i in items]
    total = sum((i.line_total for i in out_items), Decimal("0"))
    return CartOut(user_id=user_id, items=out_items, total=total)


@app.post("/cart/{user_id}/items", response_model=CartItemOut, status_code=201)
def add_to_cart(user_id: str, payload: CartItemCreate, db: Session = Depends(get_db)):
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    if product.stock < payload.quantity:
        raise HTTPException(status_code=400, detail="Недостаточно товара на складе")

    item = (
        db.query(CartItem)
        .filter(CartItem.user_id == user_id, CartItem.product_id == payload.product_id)
        .first()
    )
    if item:
        new_qty = item.quantity + payload.quantity
        if product.stock < new_qty:
            raise HTTPException(status_code=400, detail="Недостаточно товара на складе")
        item.quantity = new_qty
    else:
        item = CartItem(
            user_id=user_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
        )
        db.add(item)

    db.commit()
    db.refresh(item)
    return cart_item_to_out(item)


@app.put("/cart/{user_id}/items/{item_id}", response_model=CartItemOut)
def update_cart_item(
    user_id: str,
    item_id: int,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == item_id, CartItem.user_id == user_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Позиция корзины не найдена")
    if item.product.stock < payload.quantity:
        raise HTTPException(status_code=400, detail="Недостаточно товара на складе")
    item.quantity = payload.quantity
    db.commit()
    db.refresh(item)
    return cart_item_to_out(item)


@app.delete("/cart/{user_id}/items/{item_id}", status_code=204)
def remove_from_cart(user_id: str, item_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == item_id, CartItem.user_id == user_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Позиция корзины не найдена")
    db.delete(item)
    db.commit()


@app.delete("/cart/{user_id}", status_code=204)
def clear_cart(user_id: str, db: Session = Depends(get_db)):
    db.query(CartItem).filter(CartItem.user_id == user_id).delete()
    db.commit()


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(__import__("sqlalchemy").text("SELECT 1"))
    return {
        "status": "ok",
        "variant": "pgpool-postgres",
        "databases": {
            "products": "postgresql via pgpool",
            "cart": "postgresql via pgpool",
        },
    }
