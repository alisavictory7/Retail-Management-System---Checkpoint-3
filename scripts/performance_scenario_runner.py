#!/usr/bin/env python
"""
Utility script to reproduce Performance Scenario P.1 (flash-sale throttling).

Steps performed per iteration:
1. Log in (if session expired).
2. Add a product to the cart.
3. Submit /checkout with the desired payment method.

Use --runs and --delay to control baseline load, and add --concurrency to spin up
parallel sessions (e.g., --runs 1000 --concurrency 200 --delay 0) to approximate
the 1,000 RPS stimulus referenced in the quality scenario. Combine with
THROTTLING_MAX_RPS / THROTTLING_WINDOW_SECONDS in .env to hit your desired
throttling/latency behavior.
"""

from __future__ import annotations

import argparse
import copy
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin

import requests


DEFAULT_BASE_URL = "http://localhost:5000"


@dataclass
class IterationResult:
    status: int
    elapsed_ms: float
    detail: str


class PerformanceScenarioRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CP3-PerformanceRunner/1.0"})
        self.base_url = args.base_url.rstrip("/")

    # ------------------------------------------------------------------ Helpers
    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _require_ok(self, response: requests.Response, context: str) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"{context} failed ({response.status_code}): {response.text[:200]}")

    def _ensure_logged_in(self) -> None:
        # Quick heartbeat to see if we already have a valid session
        heartbeat = self.session.get(self._url("/"), timeout=self.args.timeout, allow_redirects=False)
        if heartbeat.status_code == 200:
            return

        login_payload = {
            "username": self.args.username,
            "password": self.args.password,
        }
        response = self.session.post(
            self._url("/login"),
            data=login_payload,
            timeout=self.args.timeout,
            allow_redirects=True,
        )
        if "Invalid username or password" in response.text:
            raise RuntimeError("Login failed: invalid credentials")
        self._require_ok(response, "Login")

    def _prepare_cart(self) -> None:
        payload = {
            "product_id": str(self.args.product_id),
            "quantity": str(self.args.quantity),
        }
        response = self.session.post(
            self._url("/add_to_cart"),
            data=payload,
            timeout=self.args.timeout,
        )
        self._require_ok(response, "Add to cart")

    def _checkout_once(self) -> IterationResult:
        self._ensure_logged_in()
        self._prepare_cart()

        start = time.perf_counter()
        response = self.session.post(
            self._url("/checkout"),
            data={"payment_method": self.args.payment_method},
            timeout=self.args.timeout,
            allow_redirects=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        detail = "ok"

        if response.status_code == 429:
            detail = "throttled"
        elif response.status_code >= 400:
            detail = "error"

        return IterationResult(
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            detail=detail,
        )

    # ---------------------------------------------------------------- Execution
    def run(self) -> List[IterationResult]:
        if self.args.concurrency <= 1:
            return self._run_serial()
        return self._run_concurrent()

    def _run_serial(self, prefix: str = "") -> List[IterationResult]:
        results: List[IterationResult] = []
        for idx in range(1, self.args.runs + 1):
            display_idx = f"{prefix}{idx}/{self.args.runs}"
            try:
                result = self._checkout_once()
                results.append(result)
                status_msg = f"{result.status} ({result.detail})"
                print(f"{display_idx} {status_msg} | {result.elapsed_ms:.1f} ms")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"{display_idx} ERROR: {exc}", file=sys.stderr)
                results.append(IterationResult(status=0, elapsed_ms=0.0, detail=f"exception: {exc}"))

            if self.args.delay and idx < self.args.runs:
                time.sleep(self.args.delay)

        return results

    def _run_concurrent(self) -> List[IterationResult]:
        total_results: List[IterationResult] = []
        per_worker = max(1, math.ceil(self.args.runs / self.args.concurrency))
        remaining = self.args.runs
        worker_specs = []
        for worker_id in range(1, self.args.concurrency + 1):
            worker_runs = min(per_worker, remaining)
            if worker_runs <= 0:
                break
            worker_specs.append((worker_id, worker_runs))
            remaining -= worker_runs

        if not worker_specs:
            return total_results

        def _run_worker(worker_id: int, worker_runs: int) -> List[IterationResult]:
            worker_args = copy.copy(self.args)
            worker_args.runs = worker_runs
            worker_args.concurrency = 1
            worker_runner = PerformanceScenarioRunner(worker_args)
            prefix = f"[worker {worker_id}] "
            print(f"{prefix}starting ({worker_runs} runs, delay={self.args.delay})")
            return worker_runner._run_serial(prefix=prefix)

        with ThreadPoolExecutor(max_workers=len(worker_specs)) as executor:
            futures = [
                executor.submit(_run_worker, worker_id, worker_runs)
                for worker_id, worker_runs in worker_specs
            ]
            for future in as_completed(futures):
                total_results.extend(future.result())

        return total_results


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * (percentile / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def summarize(results: List[IterationResult]) -> None:
    successes = [r for r in results if r.status == 200]
    throttled = [r for r in results if r.status == 429]
    failures = [r for r in results if r.status not in (0, 200, 429)]
    exceptions = [r for r in results if r.status == 0]
    latencies = sorted(r.elapsed_ms for r in successes)

    print("\n=== Performance Scenario Summary ===")
    print(f"Total attempts : {len(results)}")
    print(f"Completed      : {len(successes)}")
    print(f"Throttled (429): {len(throttled)}")
    print(f"Failures       : {len(failures)}")
    print(f"Exceptions     : {len(exceptions)}")
    if latencies:
        print(f"Avg latency    : {statistics.mean(latencies):.1f} ms")
        print(f"P95 latency    : {_percentile(latencies, 95):.1f} ms")
        print(f"Fastest / max  : {latencies[0]:.1f} ms / {latencies[-1]:.1f} ms")
    else:
        print("No successful checkouts to compute latency stats.")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fire rapid /checkout requests to exercise throttling metrics.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Application base URL (default: %(default)s)")
    parser.add_argument("--username", default="super_admin", help="User to authenticate as.")
    parser.add_argument("--password", default="super_admin_92587", help="Password for the user.")
    parser.add_argument(
        "--product-id",
        type=int,
        default=2,
        help="Product ID to add to cart each run (defaults to Mouse with high stock).",
    )
    parser.add_argument("--quantity", type=int, default=1, help="Quantity per checkout.")
    parser.add_argument("--runs", type=int, default=20, help="Number of checkout attempts to execute.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Optional delay (seconds) between attempts to fine-tune RPS.",
    )
    parser.add_argument(
        "--payment-method",
        choices=("Cash", "Card"),
        default="Cash",
        help="Payment method to submit with /checkout.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of parallel sessions to fire (set high to approximate burst RPS).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout (seconds) applied to each request.",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    runner = PerformanceScenarioRunner(args)
    results = runner.run()
    summarize(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

