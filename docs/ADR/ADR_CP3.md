# ADR 0001 – Returns & Refunds Module

## Status
Accepted

## Context
Checkpoint 2 focused on flash sales and partner integrations. Customers could not request returns or refunds, and the administrators lacked the controls, tracking, and metrics expected in a production retail system. Checkpoint 3 therefore mandates a complete RMA (Return Merchandise Authorization) workflow plus observability of that workflow.

## Decision
Implement a dedicated Returns & Refunds module spanning persistence, services, UI, and observability:

### Workflow Alignment

| Stage | Description | Responsible |
| --- | --- | --- |
| 1. RMA Request Submission | Customer selects a completed order, chooses line items, reason, and uploads up to 20 photos. | Customer |
| 2. Validation & Authorization | Policy checks (return window, max quantity, duplicate prevention) followed by staff approval; RMA number issued. | Support / System |
| 3. Return Shipping | Customer ships the product referencing the RMA number; tracking logged. | Customer / Logistics |
| 4. Inspection & Diagnosis | Warehouse/QA inspects and records findings. | QA |
| 5. Disposition Decision | Approve, partial approve, or reject with notes. | QA / Warranty |
| 6. Refund / Replacement | Refund Service issues credit via the original payment reference and replenishes stock. | System |
| 7. Closure & Reporting | Customer notified, case closed, KPIs (RMA rate, cycle time) updated for the dashboard. | System |

### Domain Model Highlights
- `ReturnRequest` (status machine: PENDING_AUTHORIZATION → … → REFUNDED) keeps high-level case data and references the originating `Sale`.
- `ReturnItem`, `ReturnShipment`, `Inspection`, `Refund`, and the new `ReturnPhoto` table capture each stage.
- `ReturnsService` orchestrates status transitions, enforces policy rules (window, quantity, max 20 photos, allowed MIME types), and writes evidence files to `static/uploads/returns`.
- `RefundService` reuses `PaymentService` (and therefore the circuit breaker) to credit the customer; integration with `InventoryService` replenishes stock.

Implementation touched `src/models.py`, new migration scripts, seeds, templates, tests, and the admin/customer blueprints.

## Consequences
- **Positive**
  - RMA domain logic is isolated, testable, and observable.
  - Admins and customers share a single Flask blueprint with role-based routing.
  - Observability data (RMA count, cycle time) can drive SLO dashboards.
  - Manual refund channels (cash / store credit) are handled entirely inside the app, avoiding unnecessary gateway failures during partial approvals.
- **Negative**
  - Schema grows (six new tables) and requires new migrations/seeds.
  - File uploads demand additional configuration (allowed extensions, storage path).
  - More states to cover in tests, especially for partial approvals and duplicate requests.
  - Admin tooling must capture manual refund references so auditors can reconcile off-ledger payouts.

---

# ADR 0002 – Docker & Compose Deployment

## Status
Accepted

## Context
Running the CP2 stack required a local Python environment plus a manually started PostgreSQL instance. The grading rubric for CP3 demands a “single command” deployment plus reproducible data seeding.

## Decision
Containerize the project with the following components:

- `Dockerfile` builds a Python 3.12-slim image, installs dependencies, copies the repo, and starts Gunicorn.
- `/deploy/dockercompose.yml` orchestrates two services: `web` (Flask) and `db` (PostgreSQL 15). It wires environment variables, health checks, persistent volumes, and mounts SQL scripts (`db/init.sql`, migrations, seeds) via `/docker-entrypoint-initdb.d/`.
- `docker/entrypoint.sh` waits for the database (`docker/wait_for_db.py`), runs `scripts/bootstrap_super_admin.py`, then launches Gunicorn.

## Consequences
- **Positive**
  - `docker compose -f deploy/dockercompose.yml up --build` spins up the whole stack with demo data (including an authorized RMA) in < 2 minutes.
  - Container boundaries mirror the deployment diagram used in documentation.
  - Easier to reset the database (`docker compose ... down -v`) and rerun scenarios for grading.
  - Timezone-sensitive dashboards consume `Config.DEFAULT_TIMEZONE`, so reviewers can align charts to their locale by editing `.env`.
- **Negative**
  - Contributors must have Docker installed; local-only SQLite workflows are no longer the default.
  - Compose logs need to be tailed to view structured logs; novices may find debugging inside containers harder without guidance.

---

# ADR 0003 – Observability & Admin Dashboard

## Status
Accepted

## Context
Checkpoint 3 requires structured logging, metrics, and a human-readable admin dashboard. Prior to this change the system only printed ad-hoc messages to stdout.

## Decision
Introduce a lightweight observability platform (`src/observability/`):

- JSON logging with correlation IDs via Flask `before_request`/`after_request` hooks (`logging_config.py`).
- In-memory metrics engine (`metrics.py`) supporting counters, gauges, histograms (with rolling p95), and events; exported via `/admin/metrics`.
- Business metrics helpers (`business_metrics.py`) that compute quarter windows, orders/refunds per day, RMA rate, and RMA cycle time.
- `/admin/dashboard` renders Tailwind cards/charts, including database health, HTTP latency tables, RMA KPIs, and the newly added quality scenario widgets for A.1 and P.1.

## Consequences
- **Positive**
  - Admins can validate SLOs without querying the DB: success rate, MTTR, latency, returns, refunds, HTTP metrics, and event stream are all surfaced in one place.
  - Observability tests (`tests/test_observability_metrics.py`, `tests/test_business_metrics.py`) prevent regressions in the histogram/p95 calculations.
  - Documentation/runbook now includes explicit steps (“generate fresh traffic before reading the dashboard”) to ensure the charts reflect live data.
  - Charts now bucket orders/refunds/RMAs in the configured local timezone, preventing the “same-day refunds split into two dates” issue.
- **Negative**
  - Metrics live in-process; a restart resets counters (acceptable for CP3 but not for production).
  - Logging volume increases slightly because every request is now structured and correlated.

---

# ADR 0004 – Resilience & Quality Scenario Telemetry (A.1 & P.1)

## Status
Accepted

## Context
Checkpoint 2 implemented circuit breaker, throttling, and queueing tactics, but CP3 demands runtime evidence (“metrics and logs displayed in the dashboard”) that two chosen scenarios remain satisfied:

- **A.1 Availability** – 99 % of order requests must be accepted (completed or queued) and MTTR for payment faults must remain < 5 minutes.
- **P.1 Performance** – 95 % of accepted order requests must complete in < 500 ms under flash-sale load.

## Decision
- Extend the checkout and flash-sale code paths to emit counters (`orders_submitted_total`, `orders_accepted_total`), latency histograms (`order_processing_latency_ms`), and MTTR histograms (`payment_circuit_mttr_seconds`).
- When the payment circuit breaker opens or closes, log structured events (`payment_circuit_opened`, `payment_service_recovered`) and feed them into the dashboard widget.
- Queue manager and graceful degradation tactics now increment the acceptance counter even when requests are routed to the queue, satisfying the “accepted = queued or completed” clause.
- The dashboard compares live values to the thresholds and visually indicates whether each scenario is “Fulfilled” or “Needs Attention.”

## Consequences
- **Positive**
  - Scenario evidence is observable without digging through the database—only `/admin/dashboard` is needed.
  - The same metrics power the automated quality scenario tests, ensuring regressions surface quickly.
  - Manual refund paths record successes without touching the payment gateway, while card/original methods still exercise the circuit breaker so A.1 telemetry remains meaningful.
- **Negative**
  - Additional instrumentation slightly increases the CPU cost of checkout paths.
  - MTTR accuracy depends on generating realistic traffic (hence the explicit runbook instructions to create load before reading the dashboard).
