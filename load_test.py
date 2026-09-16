import concurrent.futures
import json
import random
import statistics
import time
import urllib.error
import urllib.request

# Используем прямой IPv4 адрес вместо localhost
BASE_URL = "http://127.0.0.1:8000"
CONCURRENT_USERS = 20     # Уменьшим для стабильности пула соединений
TEST_DURATION_SEC = 20

latencies = []
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


def log_error(err: Exception):
    global first_error_printed, error_count
    error_count += 1
    if not first_error_printed:
        first_error_printed = True
        print(f"\n[!] ТЕКСТ ПЕРВОЙ ОШИБКИ: {type(err).__name__}: {err}")
        if isinstance(err, urllib.error.HTTPError):
            print(f"[!] Ответ от FastAPI: {err.read().decode('utf-8', errors='ignore')}")


def user_worker(stop_time: float):
    global success_count
    user_id = f"user_{random.randint(1, 500)}"

    while time.time() < stop_time:
        product_id = random.randint(1, 5)

        # 1. POST
        try:
            dur = make_request(
                f"{BASE_URL}/cart/{user_id}/items",
                method="POST",
                data={"product_id": product_id, "quantity": 1},
            )
            latencies.append(dur)
            success_count += 1
        except Exception as e:
            log_error(e)

        # 2. GET
        try:
            dur = make_request(f"{BASE_URL}/cart/{user_id}", method="GET")
            latencies.append(dur)
            success_count += 1
        except Exception as e:
            log_error(e)

        time.sleep(0.05)


def run():
    print(f"Запуск теста на {BASE_URL} ({CONCURRENT_USERS} пользователей)...")
    stop_time = time.time() + TEST_DURATION_SEC
    start_total = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as ex:
        futures = [ex.submit(user_worker, stop_time) for _ in range(CONCURRENT_USERS)]
        concurrent.futures.wait(futures)

    total_time = time.perf_counter() - start_total
    total = success_count + error_count
    rps = total / total_time if total_time > 0 else 0

    print("\n" + "=" * 40)
    print(f"Всего:    {total}")
    print(f"Успешно:  {success_count}")
    print(f"Ошибок:   {error_count}")
    print(f"RPS:      {rps:.2f} запр/сек")
    if latencies:
        print(f"Avg time: {statistics.mean(latencies):.2f} ms")
        print(f"p95:      {sorted(latencies)[int(len(latencies)*0.95)]:.2f} ms")
    print("=" * 40)


if __name__ == "__main__":
    run()