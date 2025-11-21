# Checkpoint 3 – Tests, SLOs, and Results

## Scope
- Demonstrate the new Returns & Refunds feature end-to-end (customer + admin) with policy enforcement, manual refund paths, and evidence uploads.
- Prove the Dockerized deployment plus observability stack meets the runtime proof requirements (structured logs, metrics endpoint, dashboard).
- Provide measurable evidence that the chosen quality scenarios (Availability A.1 and Performance P.1) still satisfy their SLOs in the CP3 environment.

## Test Execution Summary

| Layer | Command | Focus | Result / Evidence |
|-------|---------|-------|-------------------|
| Returns domain | `pytest tests/test_returns_service.py -v` | Workflow stages, policy windows, duplicate prevention, manual refund methods, photo limits | Pass – covers happy path + 7 negative cases validating policies |
| Returns HTTP flow | `pytest tests/test_returns_api.py -v` | Customer form render/submit, admin actions, template guards | Pass – ensures blueprint wiring and authentication gates |
| Observability metrics | `pytest tests/test_observability_metrics.py -v` | Counter/gauge accumulation, latency histogram math (p95) | Pass – prevents regressions in `/admin/metrics` snapshots |
| Business KPIs | `pytest tests/test_business_metrics.py -v` | Quarter bucketing, refund/RMA rollups, timezone handling, cycle time calc | Pass – validates dashboard KPIs (orders, refunds, avg cycle hours) |
| Quality scenarios (A.1, P.1, etc.) | `pytest tests/test_quality_scenario_validation.py -v` | Confirms ≥99 % success + <300 s MTTR plus other response measures | Pass – 14/14 scenarios fulfilled |
| Full scenario harness | `python comprehensive_quality_scenarios_test.py` | Standalone report showing 100 % compliance with response measures | Pass – see `docs/QUALITY_SCENARIO_VALIDATION_REPORT.md` |
| Demo / integration proof | `pytest tests/test_comprehensive_demo.py -v -s` | Executes flash sale, partner ingest, returns + refunds with instrumentation hooks | Pass – exercise used to warm dashboards before recording |

## CP3 SLOs (Runtime Evidence)

| Scenario | Target | Observed (Docker demo) | Evidence |
|----------|--------|------------------------|----------|
| **A.1 Availability** | ≥99 % order acceptance (completed or queued) & MTTR < 5 min while 1k RPS flash-sale traffic forces payment timeouts | 99.5 % success, 2 min MTTR | Metrics + logs captured in `docs/QUALITY_SCENARIO_VALIDATION_REPORT.md`; dashboard widget pulls from `orders_submitted_total`, `orders_accepted_total`, and `payment_circuit_mttr_seconds`. |
| **P.1 Performance** | p95 checkout latency < 500 ms during flash-sale spikes | 350 ms p95, 200 ms avg, throttled 17/20 requests | Metrics JSON from `/admin/metrics`, plus throttling banner screenshot referenced in the same report. |

## Runtime Artifacts

- **Structured logs** (`docker compose -f deploy/dockercompose.yml logs web`) show circuit breaker activity and refunds, e.g.:

```
{"timestamp":"2025-11-18T22:47:13.214Z","level":"WARNING","logger":"src.services.payment_service","message":"Refund attempt failed via circuit breaker","request_id":"b4a27a78-7f8d-45d7-9d2a-5d0d1c6a9134","path":"/admin/returns/201/refund","method":"POST","user_id":1,"reason":"Payment processor timeout"}
{"timestamp":"2025-11-18T22:47:13.220Z","level":"WARNING","logger":"src.services.refund_service","message":"Refund failed for return request 201","request_id":"b4a27a78-7f8d-45d7-9d2a-5d0d1c6a9134","path":"/admin/returns/201/refund","method":"POST","user_id":1}
```

- **Metrics snapshot** (`GET /admin/metrics`) after forcing failures and flash-sale load:

```
{
  "counters": {
    "refunds_failed_total": [{"labels": {}, "value": 1}],
    "http_requests_total": [
      {"labels": {"endpoint": "/checkout", "method": "POST", "status": "200"}, "value": 3},
      {"labels": {"endpoint": "/checkout", "method": "POST", "status": "429"}, "value": 17}
    ]
  },
  "histograms": {
    "http_request_latency_ms": [
      {"labels": {"endpoint": "/checkout", "method": "POST", "status": "429"}, "stats": {"count": 17, "avg": 8.4, "max": 19.7}}
    ],
    "order_processing_latency_ms": [
      {"labels": {}, "stats": {"count": 20, "p95": 350.0}}
    ]
  }
}
```

- **Dashboard evidence**: `/admin/dashboard` displays DB health, refunds/RMAs per day, refund success rate, and the Quality Scenario cards that compare live values against A.1 / P.1 targets.
- **Automation harness**: 
  - `python scripts/performance_scenario_runner.py --runs 1000 --delay 0 --concurrency 250 --product-id 2` approximates the 1,000 RPS flash-sale stimulus needed for Availability A.1 (watch acceptance % + MTTR on the dashboard).
  - `python scripts/performance_scenario_runner.py --runs 30 --delay 0.02 --product-id 2` produces the shorter throttling burst for Performance P.1.
  - Control sensitivity via `.env` (`THROTTLING_MAX_RPS`, `THROTTLING_WINDOW_SECONDS`).

## Reproducing the Demo

1. Copy/update `.env` (or use `env.example`), then run `docker compose -f deploy/dockercompose.yml up --build`.
2. Log in as `super_admin / super_admin_92587`. Promote additional users via `/admin/users` if needed.
3. Follow `docs/Runbook.md`:
   - `scripts\run_availability_load.cmd` → refresh `/admin/dashboard` to capture the ≥99 % acceptance portion of A.1.
   - `scripts\run_availability_failure.cmd` → follow the on-screen prompt to process the seeded RMA refund via **Card**; retry after ~60 s to log MTTR < 5 min.
   - `scripts\run_performance_load.cmd` → confirm p95 latency ≤ 500 ms on the Performance card.
   - Refresh `/admin/dashboard` after each script; both scenario tiles should show “Fulfilled” once the metrics populate.
4. Export logs/metrics if needed via `docker compose -f deploy/dockercompose.yml logs web --tail 200` and `curl -H "Cookie: ..." http://localhost:5000/admin/metrics`.

## References
- `README.md` – updated Quick Start, observability guidance, and documentation map.
- `docs/Runbook.md` – Docker → Dashboard → Returns walkthrough used by graders.
- `docs/QUALITY_SCENARIO_VALIDATION_REPORT.md` – detailed response-measure results, including observed percentages and latency/MTTR values.
- `docs/ADR/ADR_CP3.md` – decisions for Returns, Docker, observability, and resilience telemetry.

