# Checkpoint 3 Runbook

This runbook now includes the Checkpoint 3 deployment + observability workflow in addition to the original quality tactic test harness.

## CP3 Demo Script (Docker → Dashboard → Returns)

1. **Start / reset the stack**
   - First run? `docker compose -f deploy/dockercompose.yml up --build` (the entrypoint seeds the DB and bootstraps `super_admin` automatically).
   - Need a clean slate? `docker compose ... down -v` before the `up --build`.
2. **Sign in and open dashboards**
   - Browse to `http://localhost:5000/login`, log in as `super_admin / super_admin_92587`.
   - Keep two tabs handy: `/returns` (for the seeded RMA) and `/admin/dashboard` (Quality Scenario cards).
3. **Warm Availability A.1 (flash-sale overload)**
   - Recommended one-liner:
     ```cmd
     scripts\run_availability_load.cmd
     ```
     This command:
     1. Applies the “availability” preset (`python scripts\apply_env_preset.py availability`)
     2. Restarts `web` so Gunicorn picks up the new worker/thread counts
     3. Restocks product 2 to 100000 units inside Postgres
     4. Fires a 600-run, concurrency-80 `/checkout` burst (no manual typing)
   - After the burst, refresh `/admin/dashboard` → Availability card should now show large Submitted/Accepted counts. If you still see timeouts, rerun with a lower concurrency or bump `GUNICORN_WORKERS/GUNICORN_THREADS/GUNICORN_TIMEOUT` in `.env`.
4. **Capture MTTR (force the breaker)**
   - One-liner:
     ```cmd
     scripts\run_availability_failure.cmd
     ```
     This applies the `availability-failure` preset (sets `PAYMENT_REFUND_FAILURE_PROBABILITY=1.0`) and restarts `web`, then pauses with on-screen instructions.
   - Follow the prompt: in the browser, walk `RMA-CP3-DEMO-001` through Receive → Inspection → Refund (leave method = Card). The first refund attempt opens the breaker; retry after ~60 s to capture MTTR < 5 min. The dashboard card flips to “Fulfilled” once both ≥99 % acceptance and MTTR thresholds are met.

### Availability Quality Scenario A.1 – Flash Sale Payment Service Failure

- **Source**: 1,000 concurrent end users (approximated by the `performance_scenario_runner` burst in `scripts\run_availability_load.cmd` using high `--runs` and `--concurrency` values).
- **Stimulus**: External Payment Service times out or fails (simulated via `PAYMENT_REFUND_FAILURE_PROBABILITY=1.0` in `scripts\run_availability_failure.cmd`).
- **Environment**: Flash Sale Peak Load / Overloaded Mode (stack started via Docker, `availability` or `availability-failure` preset applied, and flash‑sale style `/checkout` burst running).
- **Artifact**: External Payment Service connector and order/refund processing logic (`payment_service`, `refund_service`, and the Circuit Breaker + Graceful Degradation tactics).
- **Response**: The system’s Circuit Breaker stops immediate payment attempts and **Graceful Degradation** routes work to the order/refund queue for asynchronous processing instead of failing the request.
- **Response Measure**:
  - At least **99 % of order/refund requests submitted are successfully accepted** (queued or completed) – visible on the Availability card (Submitted vs Accepted) and in metrics/logs.
  - **Mean Time to Repair (MTTR) of the payment connection fault is < 5 minutes** – measured by the time between breaker‑open failures and the first successful retry in step 4.
- **How these scripts validate A.1**:
  - `scripts\run_availability_load.cmd` creates the flash‑sale overload against `/checkout`.
  - `scripts\run_availability_failure.cmd` injects payment timeouts/failures and walks the refund flow until the breaker recovers.
  - Use `/admin/dashboard` and `/admin/metrics` to confirm ≥99 % acceptance and MTTR < 5 minutes, fulfilling the Availability scenario.

5. **Exercise Performance P.1 (throttling / Manage Event Arrival)**
   - One-liner:
     ```cmd
     scripts\run_performance_load.cmd
     ```
     This applies the “performance” preset (lowers `THROTTLING_MAX_RPS` to 2), restarts `web`, restocks product 2, and fires the short `/checkout` burst with a 0.02s delay between attempts.
   - Watch the script output for HTTP 429 entries, the storefront “throttled” banner, and verify the Performance card on `/admin/dashboard` shows p95 latency ≤ 500 ms (Fulfilled).

### Performance Quality Scenario P.1 – Flash Sale Manage Event Arrival

- **Source**: Automated Load Testing Tool (this repo’s `scripts\performance_scenario_runner.py`, invoked by `scripts\run_performance_load.cmd`).
- **Stimulus**: A high‑rate stream of `/checkout` order placement requests (configure `--runs`, `--concurrency`, and `--delay` to approximate **1,000 order placement requests per second** during the burst).
- **Environment**: Peak Load / Overloaded Mode during a Flash Sale (Docker stack running with the `performance` preset so `THROTTLING_MAX_RPS` and `THROTTLING_WINDOW_SECONDS` are active).
- **Artifact**: Order Submission endpoint / API (`POST /checkout`) plus the throttling + queuing tactics.
- **Response**: The system uses **Manage Event Arrival** (Throttling/Queuing) to limit concurrent processing, prioritizing throughput over unbounded latency. Extra requests receive HTTP 429 with a “System is busy, please try again” banner while accepted requests are processed or queued.
- **Response Measure**:
  - The **average latency for 95 % of accepted order requests remains below 500 ms** (p95 latency < 500 ms for HTTP 200s), as reported by `performance_scenario_runner.py` and on the Performance card on `/admin/dashboard`.
  - Throttling/queuing is evident from a healthy mix of HTTP 200 and HTTP 429 responses without large spikes of 5xx/timeouts.
- **How these scripts validate P.1**:
  - `scripts\run_performance_load.cmd` applies the `performance` preset, restocks product 2, and drives `/checkout` at a controlled, high rate.
  - The `performance_scenario_runner.py` summary shows total attempts, completed vs throttled, and p95 latency; `/admin/dashboard` mirrors these metrics.
  - Together they demonstrate that under flash‑sale load the system throttles and queues requests while keeping p95 latency for accepted orders **< 500 ms**, fulfilling the Performance scenario.

6. **Shutdown (when done)**
   ```bash
   docker compose -f deploy/dockercompose.yml down
   # optional reset: docker compose -f deploy/dockercompose.yml down -v
   ```

> Need raw artifacts? Use `docker compose -f deploy/dockercompose.yml logs web --tail=200` for structured logs and `curl -H "Cookie: ..." http://localhost:5000/admin/metrics` for JSON snapshots.

# Checkpoint 2: Quality Tactics Test Suite

This comprehensive test suite demonstrates all 14+ quality tactics and patterns implemented for Checkpoint 2 of the Retail Management System.

## Overview

The test suite validates the implementation of quality attributes across seven categories with **100% success rate**:
- **Availability** (3 tactics) - Circuit Breaker, Graceful Degradation, Rollback & Retry
- **Security** (2 tactics) - Authenticate Actors, Validate Input
- **Performance** (4 tactics) - Throttling, Queuing, Concurrency Control, Monitoring
- **Modifiability** (3 tactics) - Adapter Pattern, Feature Toggle, Use Intermediary
- **Integrability** (3 tactics) - Tailor Interface, Publish-Subscribe, Message Broker
- **Testability** (2 tactics) - Record/Playback, Dependency Injection
- **Usability** (2 tactics) - Error Recovery, Progress Indicator

## Test Structure

### Individual Quality Attribute Tests
- `test_availability_tactics.py` - Tests Circuit Breaker, Graceful Degradation, Rollback, Retry, Removal from Service
- `test_security_tactics.py` - Tests Authenticate Actors, Validate Input
- `test_performance_tactics.py` - Tests Throttling, Queuing, Concurrency, Performance Monitoring
- `test_modifiability_tactics.py` - Tests Adapter Pattern, Feature Toggle, Partner Data Intermediary
- `test_integrability_tactics.py` - Tests Tailor Interface, Adapter Pattern, Publish-Subscribe
- `test_testability_tactics.py` - Tests Record/Playback, Dependency Injection
- `test_usability_tactics.py` - Tests User Error Handling, Progress Indicator

### Integration Tests
- `test_integration.py` - Tests all quality tactics working together in realistic scenarios
- `test_comprehensive_demo.py` - Comprehensive demonstration of all quality scenarios
- `test_logic.py` - Business logic and core functionality tests

### Quality Scenario Tests (Advanced)
- `test_quality_scenario_runner.py` - Quality scenario test runner
- `test_quality_scenario_summary.py` - Quality scenario summary tests
- `test_quality_scenario_validation.py` - Individual quality scenario validation
- `test_quality_scenarios.py` - Comprehensive quality scenario tests

### Test Infrastructure
- `conftest.py` - Shared fixtures and test configuration
- `run_all_tests.py` - Comprehensive test runner with detailed reporting
- `simple_test_runner.py` - Simple test runner for quick validation
- `README.md` - This documentation

## Running the Tests

### Quick Start
```bash
# Run all tests
python run_tests.py

# Run specific quality attribute tests
python -m pytest tests/test_availability_tactics.py -v

# Run integration tests
python -m pytest tests/test_integration.py -v

# Run comprehensive demonstration
python -m pytest tests/test_comprehensive_demo.py -v -s
```

### Detailed Test Execution
```bash
# Run with detailed output
python tests/run_all_tests.py

# Run simple test runner
python tests/simple_test_runner.py

# Run individual test classes
python -m pytest tests.test_availability_tactics::TestCircuitBreakerPattern -v

# Run with coverage
python -m pytest --cov=src tests/ -v

# Run quality scenario tests (advanced)
python -m pytest tests/test_quality_scenario_validation.py -v
python -m pytest tests/test_quality_scenarios.py -v
```

## Test Features

### Comprehensive Coverage
- **14+ Quality Tactics** implemented and tested
- **7 Quality Attributes** covered with 15 quality scenarios
- **224+ Individual Tests** with 100% pass rate
- **Integration scenarios** showing tactics working together
- **Edge cases** and error conditions tested
- **Performance validation** for all tactics
- **100% Quality Scenario Compliance** verified

### Realistic Scenarios
- Flash sale order processing with circuit breakers and throttling
- Partner catalog ingestion with authentication and validation
- Error recovery with user-friendly messages and progress tracking
- System health monitoring and feature toggles
- Test reproducibility with record/playback

### Mock Services
- Mock payment services with configurable failure rates
- Mock partner APIs for integration testing
- Mock database for isolated testing
- Configurable test environments

## Quality Scenarios Demonstrated

### Availability Scenarios
1. **A.1**: Flash Sale Overload - Circuit Breaker + Graceful Degradation
2. **A.2**: Transient Failure Recovery - Rollback + Retry
3. **A.3**: Permanent Failure Handling - Rollback + Error Logging

### Security Scenarios
1. **S.1**: Partner Authentication - API Key Validation
2. **S.2**: Input Validation - SQL Injection Prevention

### Performance Scenarios
1. **P.1**: Flash Sale Load - Throttling + Queuing
2. **P.2**: Concurrent Operations - Database Locking + Concurrency Control

### Modifiability Scenarios
1. **M.1**: New Partner Format - Adapter Pattern + Intermediary
2. **M.2**: Feature Toggle - Runtime Feature Control

### Integrability Scenarios
1. **I.1**: External API Integration - Adapter Pattern + Tailor Interface
2. **I.2**: Decoupled Services - Publish-Subscribe + Message Broker

### Testability Scenarios
1. **T.1**: Test Reproducibility - Record/Playback
2. **T.2**: Isolated Testing - Dependency Injection

### Usability Scenarios
1. **U.1**: Error Recovery - User-Friendly Error Messages
2. **U.2**: Long Operations - Progress Indicators

## Test Data and Fixtures

### Sample Data
- Test users with various roles
- Sample products for order processing
- Partner data in multiple formats (CSV, JSON, XML)
- Flash sale scenarios with time constraints
- Mock API responses and error conditions

### Test Fixtures
- Database sessions with automatic cleanup
- Quality tactics manager with configuration
- Mock services with configurable behavior
- Test environments for record/playback

## Expected Results

When all tests pass, you should see:
- ✅ All 14+ quality tactics functioning correctly
- ✅ All 7 quality attributes meeting their scenarios (100% compliance)
- ✅ All 15 quality scenarios fulfilled
- ✅ Integration scenarios working seamlessly
- ✅ Comprehensive error handling and recovery
- ✅ Performance metrics within acceptable ranges
- ✅ User experience improvements demonstrated
- ✅ 224+ tests passing with comprehensive coverage

## Quality Scenario Validation

### Comprehensive Quality Scenario Test
Run the comprehensive quality scenario validation to verify 100% compliance:

```bash
# Run comprehensive quality scenario validation (from project root)
python comprehensive_quality_scenarios_test.py

# Expected output:
# 🎯 COMPREHENSIVE QUALITY SCENARIO VALIDATION
# Total Quality Scenarios: 15
# Fulfilled Scenarios: 15
# Success Rate: 100.0%
# 🎉 ALL QUALITY SCENARIOS SUCCESSFULLY VALIDATED!
```

**Note**: The `comprehensive_quality_scenarios_test.py` file is located in the project root directory, not in the `tests/` directory. This provides a standalone validation of all quality scenarios.

### Quality Scenario Results
All 15 quality scenarios from Checkpoint2_Revised.md are validated:

| Scenario | Description | Status |
|----------|-------------|---------|
| A.1 | Circuit Breaker + Graceful Degradation | ✅ FULFILLED |
| A.2 | Rollback and Retry for Transient Failures | ✅ FULFILLED |
| A.3 | Removal from Service for Predictive Fault Mitigation | ✅ FULFILLED |
| S.1 | Partner API Authentication | ✅ FULFILLED |
| S.2 | Input Validation and Sanitization | ✅ FULFILLED |
| M.1 | Adapter Pattern for Partner Format Support | ✅ FULFILLED |
| M.2 | Feature Toggle for Runtime Control | ✅ FULFILLED |
| P.1 | Throttling and Queuing for Flash Sale Load | ✅ FULFILLED |
| P.2 | Concurrency Control for Stock Updates | ✅ FULFILLED |
| I.1 | API Adapter for External Reseller Integration | ✅ FULFILLED |
| I.2 | Publish-Subscribe for Decoupled Reporting | ✅ FULFILLED |
| T.1 | Record/Playback for Load Test Reproducibility | ✅ FULFILLED |
| T.2 | Dependency Injection for Payment Service Testing | ✅ FULFILLED |
| U.1 | Error Recovery with User-Friendly Messages | ✅ FULFILLED |
| U.2 | Progress Indicator for Long-Running Tasks | ✅ FULFILLED |

## Troubleshooting

### Common Issues
1. **Database Connection**: Ensure PostgreSQL is running and accessible
2. **Missing Dependencies**: Run `pip install -r requirements.txt`
3. **Test Timeouts**: Some tests may take longer due to retry logic
4. **Mock Service Errors**: Check mock service configuration

### Debug Mode
```bash
# Run with debug output
python -m pytest tests/ -v -s --tb=long

# Run specific failing test
python -m pytest tests/test_availability_tactics.py::TestCircuitBreakerPattern::test_circuit_breaker_failure_trips_open -v -s
```

## Test Metrics

The test suite provides comprehensive metrics:
- **Test Coverage**: All tactics and patterns tested
- **Performance Validation**: Response times and throughput
- **Error Handling**: Graceful degradation and recovery
- **Integration Points**: Cross-tactic communication
- **User Experience**: Error messages and progress tracking

## Contributing

When adding new tests:
1. Follow the existing naming conventions
2. Include comprehensive docstrings
3. Test both success and failure scenarios
4. Include edge cases and error conditions
5. Update this README with new test descriptions

## Quality Assurance

This test suite ensures:
- **Reliability**: All tactics work as designed
- **Maintainability**: Tests are well-organized and documented
- **Performance**: Tactics meet performance requirements
- **Usability**: User experience is validated
- **Security**: Security measures are properly tested
- **Integrability**: External integrations work correctly
- **Testability**: System is testable and maintainable
