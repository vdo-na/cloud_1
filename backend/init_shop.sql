-- Схема интернет-магазина (для чистого старта контейнеров)
DROP TABLE IF EXISTS cart_items;
DROP TABLE IF EXISTS products;

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0)
);

CREATE TABLE cart_items (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    UNIQUE (user_id, product_id)
);

INSERT INTO products (name, description, price, stock) VALUES
    ('Ноутбук', 'Легкий ноутбук 14"', 79990.00, 10),
    ('Мышь', 'Беспроводная мышь', 1490.00, 50),
    ('Клавиатура', 'Механическая клавиатура', 5990.00, 25),
    ('Наушники', 'Накладные наушники', 3490.00, 40),
    ('Монитор', '27" IPS монитор', 24990.00, 15);
