"""簡易壓力測試腳本：模擬 5~10 併發對 bot 核心函式的壓力，觀察 RSS/延遲/錯誤。

用法：
  python3 tools/stress_test_bot.py --workers 5 --seconds 30 --mode dry
  python3 tools/stress_test_bot.py --workers 10 --seconds 30 --mode dry
  python3 tools/stress_test_bot.py --workers 5 --seconds 20 --mode real
"""

from __future__ import annotations

import argparse
import random
import statistics
import threading
import time
from dataclasses import dataclass, field

import psutil


@dataclass
class WorkerStats:
    latencies: list[float] = field(default_factory=list)
    ok: int = 0
    err: int = 0


def _dry_task() -> None:
    # 模擬輕量邏輯
    _ = sum(i * i for i in range(1500))


def _real_task() -> None:
    # 盡量貼近 bot 常用流程（不走 Telegram API）
    import command

    user_name = "stress_test"
    user_id = 0
    sample = random.choice([
        lambda: command.cmd_risk(user_id=user_id, user_name=user_name),
        lambda: command.cmd_marco(user_id=user_id, user_name=user_name),
        lambda: command.cmd_theory("/theory smc"),
    ])
    sample()


def worker(stop_at: float, mode: str, stats: WorkerStats) -> None:
    fn = _dry_task if mode == "dry" else _real_task
    while time.time() < stop_at:
        t0 = time.perf_counter()
        try:
            fn()
            stats.ok += 1
        except Exception:
            stats.err += 1
        finally:
            stats.latencies.append((time.perf_counter() - t0) * 1000.0)


def monitor(stop_at: float, rss_samples: list[float]) -> None:
    proc = psutil.Process()
    while time.time() < stop_at:
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        rss_samples.append(rss_mb)
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--mode", choices=["dry", "real"], default="dry")
    args = parser.parse_args()

    stop_at = time.time() + max(5, args.seconds)
    all_stats = [WorkerStats() for _ in range(max(1, args.workers))]
    rss_samples: list[float] = []

    threads: list[threading.Thread] = []
    threads.append(threading.Thread(target=monitor, args=(stop_at, rss_samples), daemon=True))
    for i in range(len(all_stats)):
        threads.append(threading.Thread(target=worker, args=(stop_at, args.mode, all_stats[i]), daemon=True))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    merged_lat = [x for s in all_stats for x in s.latencies]
    total_ok = sum(s.ok for s in all_stats)
    total_err = sum(s.err for s in all_stats)

    avg_lat = statistics.mean(merged_lat) if merged_lat else 0.0
    p95_lat = statistics.quantiles(merged_lat, n=100)[94] if len(merged_lat) >= 100 else max(merged_lat or [0.0])
    rss_peak = max(rss_samples or [0.0])
    rss_avg = statistics.mean(rss_samples) if rss_samples else 0.0

    print("\n=== Stress Test Result ===")
    print(f"mode={args.mode} workers={args.workers} seconds={args.seconds}")
    print(f"ok={total_ok} err={total_err}")
    print(f"latency_avg_ms={avg_lat:.2f} latency_p95_ms={p95_lat:.2f}")
    print(f"rss_avg_mb={rss_avg:.2f} rss_peak_mb={rss_peak:.2f}")


if __name__ == "__main__":
    main()
