# Лабораторная работа №1 — PostgreSQL multimaster + интернет-магазин

Минимальный стек для лабы: **3 узла PostgreSQL** в режиме multimaster через **Pgpool II**, поверх — **FastAPI**-backend простого интернет-магазина (товары + корзина).

Одна команда `docker compose up` поднимает всё: базы, балансировщик и API.

---

## Что здесь есть (пункты 1–4)

| Пункт | Что сделано |
|-------|-------------|
| **1** | 3 инстанса PostgreSQL 16 + Pgpool II (native replication + load balancing) |
| **2** | Backend магазина на FastAPI: CRUD товаров и корзины |
| **3** | Корзина перенесена в MongoDB (`main.py`); каталог остаётся в PostgreSQL через pgpool |
| **4** | Два нагрузочных теста: Mongo (`load_test.py` → `:8000`) и pgpool (`load_test_pgpool.py` → `:8001`) |

Одна команда поднимает **оба** API сразу:

| Сервис | Порт | Корзина | Файл |
|--------|------|---------|------|
| `shop-api` | `:8000` | MongoDB | `backend/main.py` |
| `shop-api-pgpool` | `:8001` | PostgreSQL через pgpool | `backend/main_pgpool.py` |

---

## Как это устроено

```
   :8000 shop-api          :8001 shop-api-pgpool
   (корзина → Mongo)       (корзина → PostgreSQL)
          │                         │
          │    ┌────────────────────┘
          ▼    ▼
     товары всегда через Pgpool :9999
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        pg1       pg2       pg3
       :5433     :5434     :5435

   MongoDB :27017 — только для корзины API на :8000
```

**Идея простыми словами**

1. Клиент ходит в API, а не в базы напрямую.
2. **Каталог товаров** всегда в PostgreSQL через Pgpool (`:9999`).
3. Есть **два варианта корзины** для сравнения в п.4:
   - `:8000` — корзина в MongoDB (п.3)
   - `:8001` — корзина тоже в PostgreSQL через pgpool (как в п.2)
4. Pgpool раздаёт SQL по трём узлам (`native_replication` + load balancing).

---

## Быстрый старт

### Что нужно

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (или Docker Engine + Compose)
- Порты свободны: `8000`, `8001`, `9999`, `5433–5435`, `27017`

### Запуск

```bash
cd cloud_1
docker compose up -d --build
```

Первый раз сборка займёт пару минут (образы Postgres, pgpool, backend).

Проверка, что всё живо:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

Ожидаемо:

- `:8000` → `"cart": "mongodb"`
- `:8001` → `"cart": "postgresql via pgpool"` (и `"variant": "pgpool-postgres"`)

### Куда кликать

| Что | Адрес |
|-----|--------|
| Swagger UI (Mongo-корзина) | http://localhost:8000/docs |
| Swagger UI (pgpool-корзина) | http://localhost:8001/docs |
| Health Mongo-API | http://localhost:8000/health |
| Health pgpool-API | http://localhost:8001/health |
| Pgpool | `localhost:9999` |
| MongoDB | `localhost:27017` |

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
cloud_1/
├── docker-compose.yaml       # весь стек: pg1–3, pgpool, mongo, оба API
├── README.md
├── load_test.py              # нагрузка Mongo-API (:8000)
├── load_test_pgpool.py       # нагрузка pgpool-API (:8001)
├── postgres/
│   └── init.sql
├── pgpool/
│   ├── Dockerfile
│   ├── pgpool.conf
│   ├── pool_hba.conf
│   └── pcp.conf
└── backend/
    ├── Dockerfile            # один образ: main.py + main_pgpool.py
    ├── main.py               # товары PG + корзина Mongo
    ├── main_pgpool.py        # товары и корзина через pgpool
    ├── migrate_to_mongo.py
    ├── mongo.py
    ├── requirements.txt
    └── init_shop.sql
```

**Порядок старта в Compose**

1. `pg1`, `pg2`, `pg3` → healthcheck `pg_isready`
2. `mongo` стартует параллельно
3. `pgpool` → ждёт здоровые узлы
4. `backend` (`:8000`) → Mongo-корзина
5. `backend_pgpool` (`:8001`) → корзина в PostgreSQL через pgpool

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
| `port is already allocated` | Занят порт `8000` / `8001` / `9999` / `5433–5435` / `27017`. Освободи или поменяй mapping в `docker-compose.yaml` |
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


---

## Пункт 3 — корзина в MongoDB

- Сервис `mongo` в Compose, порт `27017`
- API `:8000` (`backend/main.py`) пишет корзину в коллекцию `cart_items`
- Каталог товаров по-прежнему через pgpool
- Разовая миграция старых строк из PG: `backend/migrate_to_mongo.py`

```powershell
$env:DATABASE_URL="postgresql+psycopg2://app:app@localhost:9999/appdb"
$env:MONGO_URL="mongodb://localhost:27017/shop_db"
python backend/migrate_to_mongo.py
```

---

## Пункт 4 — нагрузочное тестирование

Одинаковый сценарий в обоих тестах: **20** потоков, **20** секунд, `POST /cart/.../items` + `GET /cart/...`.

### Тест Mongo (порт 8000)

```powershell
cd C:\Users\admin\Desktop\cloud_1
docker compose up -d --build
python load_test.py
```

### Тест pgpool / PostgreSQL (порт 8001)

```powershell
cd C:\Users\admin\Desktop\cloud_1
docker compose up -d --build
python load_test_pgpool.py
```

Отчёт pgpool-теста сохраняется в `results_pgpool.json` (RPS, avg, p95, ошибки).

Сравни метрики двух прогонов и занеси в отчёт по лабе.

---

## Итог для проверяющего

- **Multimaster PostgreSQL**: три узла + Pgpool II (`native_replication`, `load_balance_mode = on`).
- **Два API из одного образа**: `:8000` — корзина в MongoDB; `:8001` — корзина через pgpool.
- **п.3**: MongoDB + `migrate_to_mongo.py`.
- **п.4**: `load_test.py` (Mongo) и `load_test_pgpool.py` (pgpool).
- **Запуск всего стека**: `docker compose up -d --build`
