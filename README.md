# Лабораторная работа №1 — PostgreSQL multimaster + интернет-магазин

Минимальный стек для лабы: **3 узла PostgreSQL** в режиме multimaster через **Pgpool II**, поверх — **FastAPI**-backend простого интернет-магазина (товары + корзина).

Одна команда `docker compose up` поднимает всё: базы, балансировщик и API.

---

## Что здесь есть (пункты 1–2)

| Пункт | Что сделано |
|-------|-------------|
| **1** | 3 инстанса PostgreSQL 16 + Pgpool II (native replication + load balancing) |
| **2** | Backend магазина на FastAPI: CRUD товаров и корзины, чтение/запись через pgpool |

Дальше по заданию (ещё не в этом репо):
- **п.3** — перенести часть данных (например корзину) в NoSQL / in-memory СУБД
- **п.4** — нагрузочное тестирование обоих вариантов архитектуры

---

## Как это устроено

```
                    ┌─────────────────┐
   браузер / curl   │  FastAPI        │  :8000
   http://localhost:8000/docs         │  shop-api
                    └────────┬────────┘
                             │  DATABASE_URL → pgpool:9999
                             ▼
                    ┌─────────────────┐
                    │  Pgpool II      │  :9999  (с хоста)
                    │  балансировка   │
                    │  + репликация   │
                    └─────┬───┬───┬───┘
                          │   │   │
              ┌───────────┘   │   └───────────┐
              ▼               ▼               ▼
         ┌────────┐      ┌────────┐      ┌────────┐
         │  pg1   │      │  pg2   │      │  pg3   │
         │ :5433  │      │ :5434  │      │ :5435  │
         └────────┘      └────────┘      └────────┘
```

**Идея простыми словами**

1. Клиент ходит только в **API** (`:8000`), а не в базы напрямую.
2. API пишет и читает через **один вход** — Pgpool (`:9999`).
3. Pgpool раздаёт запросы по трём PostgreSQL и держит их синхронизированными (режим `native_replication`).
4. С хоста можно зайти и в отдельный узел (`5433` / `5434` / `5435`), если нужно проверить, что данные реально реплицируются.

---

## Быстрый старт

### Что нужно

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (или Docker Engine + Compose)
- Порты свободны: `8000`, `9999`, `5433–5435`

### Запуск

```bash
cd pg-multimaster
docker compose up -d --build
```

Первый раз сборка займёт пару минут (образы Postgres, pgpool, backend).

Проверка, что всё живо:

```bash
docker compose ps
curl http://localhost:8000/health
```

Ожидаемый ответ health:

```json
{"status":"ok","db":"postgresql via pgpool"}
```

### Куда кликать

| Что | Адрес |
|-----|--------|
| **Swagger UI** (тыкай API мышкой) | http://localhost:8000/docs |
| Healthcheck | http://localhost:8000/health |
| Pgpool (PostgreSQL-протокол) | `localhost:9999` |

### Остановка

```bash
docker compose down          # остановить, данные сохранить
docker compose down -v       # остановить И удалить данные БД
```

---

## Учётные данные БД

Везде одинаково (для лабы, не для продакшена):

| Параметр | Значение |
|----------|----------|
| Пользователь | `app` |
| Пароль | `app` |
| База | `appdb` |
| Через pgpool | `localhost:9999` |
| Напрямую pg1 / pg2 / pg3 | `localhost:5433` / `5434` / `5435` |

Строка подключения с хоста:

```text
postgresql://app:app@localhost:9999/appdb
```

Внутри Docker backend использует:

```text
postgresql+psycopg2://app:app@pgpool:9999/appdb
```

---

## Модель данных

Две таблицы (создаются из `postgres/init.sql` при первом старте томов; backend тоже умеет создать их сам и засеять товары, если пусто).

### `products` — каталог

| Поле | Тип | Смысл |
|------|-----|--------|
| `id` | serial | PK |
| `name` | text | название |
| `description` | text | описание |
| `price` | numeric(10,2) | цена ≥ 0 |
| `stock` | int | остаток ≥ 0 |

При старте заливаются 5 демо-товаров: ноутбук, мышь, клавиатура, наушники, монитор.

### `cart_items` — корзина

| Поле | Тип | Смысл |
|------|-----|--------|
| `id` | serial | PK |
| `user_id` | text | «кто» (строка, без отдельной таблицы users) |
| `product_id` | int | FK → products |
| `quantity` | int | количество > 0 |

Уникальность: один товар один раз на пользователя (`UNIQUE(user_id, product_id)`). Повторный `POST` увеличивает `quantity`.

---

## API — что умеет

Базовый URL: `http://localhost:8000`

### Товары

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/products` | список всех товаров |
| `GET` | `/products/{id}` | один товар |
| `POST` | `/products` | создать |
| `PUT` | `/products/{id}` | обновить (частично) |
| `DELETE` | `/products/{id}` | удалить |

Пример создания:

```bash
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"USB-хаб\",\"description\":\"4 порта\",\"price\":990,\"stock\":100}"
```

### Корзина

`user_id` — любая строка (например `artem` или `demo`). Отдельной регистрации нет — так проще для лабы.

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/cart/{user_id}` | корзина + итоговая сумма |
| `POST` | `/cart/{user_id}/items` | добавить товар `{"product_id":1,"quantity":2}` |
| `PUT` | `/cart/{user_id}/items/{item_id}` | изменить количество |
| `DELETE` | `/cart/{user_id}/items/{item_id}` | убрать позицию |
| `DELETE` | `/cart/{user_id}` | очистить корзину |

Мини-сценарий «купил мышь»:

```bash
# 1. Посмотреть каталог
curl http://localhost:8000/products

# 2. Положить товар id=2 в корзину пользователя artem
curl -X POST http://localhost:8000/cart/artem/items \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":2,\"quantity\":1}"

# 3. Посмотреть корзину
curl http://localhost:8000/cart/artem
```

Ответ корзины roughly такой:

```json
{
  "user_id": "artem",
  "items": [
    {
      "id": 1,
      "user_id": "artem",
      "product_id": 2,
      "quantity": 1,
      "product_name": "Мышь",
      "product_price": "1490.00",
      "line_total": "1490.00"
    }
  ],
  "total": "1490.00"
}
```

Удобнее всего гонять запросы через **http://localhost:8000/docs** — там формы и схемы тел запросов.

---

## Структура репозитория

```text
pg-multimaster/
├── docker-compose.yaml     # весь стек: pg1–3, pgpool, backend
├── README.md               # этот файл
├── postgres/
│   └── init.sql            # схема + сиды при первом создании томов
├── pgpool/
│   ├── Dockerfile
│   ├── pgpool.conf         # native_replication, load_balance, 3 backend'а
│   ├── pool_hba.conf
│   └── pcp.conf
└── backend/
    ├── Dockerfile
    ├── main.py             # FastAPI + SQLAlchemy
    ├── requirements.txt
    └── init_shop.sql       # копия схемы (удобно смотреть / гонять вручную)
```

**Порядок старта в Compose**

1. `pg1`, `pg2`, `pg3` → healthcheck `pg_isready`
2. `pgpool` → ждёт здоровые узлы, сам проходит healthcheck
3. `backend` → ждёт здоровый pgpool, при старте создаёт таблицы (если надо) и сиды

---

## Полезные команды

```bash
# Статус контейнеров
docker compose ps

# Логи API / pgpool / одной из баз
docker compose logs -f backend
docker compose logs -f pgpool
docker compose logs -f pg1

# Пересобрать только API после правок main.py
docker compose up -d --build backend

# Зайти в psql через pgpool
docker compose exec pg1 psql -h pgpool -p 9999 -U app -d appdb

# Или напрямую в узел
docker compose exec pg1 psql -U app -d appdb
```

Проверка репликации (вставили через API → видно на всех трёх):

```bash
docker compose exec pg1 psql -U app -d appdb -c "SELECT count(*) FROM products;"
docker compose exec pg2 psql -U app -d appdb -c "SELECT count(*) FROM products;"
docker compose exec pg3 psql -U app -d appdb -c "SELECT count(*) FROM products;"
```

---

## Если что-то не взлетело

| Симптом | Что сделать |
|---------|-------------|
| `port is already allocated` | Занят порт `8000` / `9999` / `5433–5435`. Освободи или поменяй mapping в `docker-compose.yaml` |
| backend в `Restarting` | `docker compose logs backend` — часто ещё не готов pgpool; у API есть ретраи ~1 мин |
| Пустой каталог `/products` | Тома старые без сидов: `docker compose down -v && docker compose up -d --build` |
| `connection refused` на `:8000` | Контейнер ещё поднимается: `docker compose ps` и подожди `healthy` / `running` |
| Docker Desktop не запущен | Запусти Docker и повтори `docker compose up -d --build` |

---

## Запуск API без Docker (опционально)

Если Postgres+pgpool уже крутятся в Docker, а код API хочется править локально:

```bash
cd backend
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

По умолчанию `main.py` ходит на `localhost:9999`. В Compose URL переопределяется переменной `DATABASE_URL`.

---

## Итог для проверяющего

- **Multimaster PostgreSQL**: три узла + Pgpool II (`backend_clustering_mode = native_replication`, `load_balance_mode = on`).
- **Backend**: FastAPI, достаточный CRUD для каталога и корзины, доступ к БД только через pgpool.
- **Данные**: сгенерированные товары при старте; корзина привязана к строковому `user_id`.
- **Запуск**: `docker compose up -d --build` → http://localhost:8000/docs
