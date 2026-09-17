"""
Нагрузочный тест архитектуры PostgreSQL multimaster + Pgpool II
(товары и корзина через pgpool).

Подруга тестирует Mongo своим load_test.py на порту 8000 — этот файл её не трогает.

Перед запуском подними весь стек (оба API сразу):
  docker compose up -d --build

Проверка:
  curl http://127.0.0.1:8001/health

Запуск:
  python load_test_pgpool.py
"""

from __future__ import annotations

import concurrent.futures
import json
import random
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

MODE = "pgpool-postgres"
BASE_URL = "http://127.0.0.1:8001"
CONCURRENT_USERS = 20
TEST_DURATION_SEC = 20
RESULTS_FILE = Path(__file__).with_name("results_pgpool.json")

latencies: list[float] = []
success_count = 0
error_count = 0
first_error_printed = False


def make_request(url: str, method: str = "GET", data: dict | None = None) -> float:
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=5) as resp:
        _ = resp.read()
    return (time.perf_counter() - start) * 1000.0


def log_error(err: Exception) -> None:
    global first_error_printed, error_count
    error_count += 1
    if not first_error_printed:
        first_error_printed = True
        print(f"\n[!] Первая ошибка: {type(err).__name__}: {err}")
        if isinstance(err, urllib.error.HTTPError):
            print(f"[!] Тело ответа: {err.read().decode('utf-8', errors='ignore')}")


def ensure_pgpool_api() -> None:
    req = urllib.request.Request(f"{BASE_URL}/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    print(f"health: {payload}")
    variant = payload.get("variant")
    cart = (payload.get("databases") or {}).get("cart", "")
    if variant != "pgpool-postgres" and "pgpool" not in str(cart).lower():
        raise SystemExit(
            "На :8001 не тот API. Подними backend_pgpool:\n"
            "  docker compose up -d --build"
        )


def user_worker(stop_time: float) -> None:
    global success_count
    user_id = f"user_{random.randint(1, 500)}"

    while time.time() < stop_time:
        product_id = random.randint(1, 5)

        try:
            dur = make_request(
                f"{BASE_URL}/cart/{user_id}/items",
                method="POST",
                data={"product_id": product_id, "quantity": 1},
            )
            latencies.append(dur)
            success_count += 1
        except Exception as e:  # noqa: BLE001
            log_error(e)

        try:
            dur = make_request(f"{BASE_URL}/cart/{user_id}", method="GET")
            latencies.append(dur)
            success_count += 1
        except Exception as e:  # noqa: BLE001
            log_error(e)

        time.sleep(0.05)


def run() -> None:
    print(f"=== Load test: {MODE} ===")
    print(f"URL={BASE_URL}, users={CONCURRENT_USERS}, duration={TEST_DURATION_SEC}s")
    ensure_pgpool_api()

    stop_time = time.time() + TEST_DURATION_SEC
    start_total = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as ex:
        futures = [ex.submit(user_worker, stop_time) for _ in range(CONCURRENT_USERS)]
        concurrent.futures.wait(futures)

    total_time = time.perf_counter() - start_total
    total = success_count + error_count
    rps = total / total_time if total_time > 0 else 0.0
    avg = statistics.mean(latencies) if latencies else None
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else None

    print("\n" + "=" * 40)
    print(f"Режим:    {MODE}")
    print(f"Всего:    {total}")
    print(f"Успешно:  {success_count}")
    print(f"Ошибок:   {error_count}")
    print(f"RPS:      {rps:.2f} запр/сек")
    if avg is not None:
        print(f"Avg time: {avg:.2f} ms")
        print(f"p95:      {p95:.2f} ms")
    print("=" * 40)

    report = {
        "mode": MODE,
        "base_url": BASE_URL,
        "concurrent_users": CONCURRENT_USERS,
        "duration_sec": TEST_DURATION_SEC,
        "total": total,
        "success": success_count,
        "errors": error_count,
        "rps": round(rps, 2),
        "avg_ms": round(avg, 2) if avg is not None else None,
        "p95_ms": round(p95, 2) if p95 is not None else None,
    }
    RESULTS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Отчёт сохранён: {RESULTS_FILE}")


if __name__ == "__main__":
    run()
