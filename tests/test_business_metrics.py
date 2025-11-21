import math
from datetime import datetime, timezone

import pytest

from src.database import Base, SessionLocal, engine
from src.models import (
    User,
    Sale,
    SaleItem,
    OrderQueue,
    Payment,
    ReturnRequest,
    Refund,
    FailedPaymentLog,
    ReturnReason,
    ReturnRequestStatus,
    RefundStatus,
    RefundMethod,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.observability import business_metrics as bm
from src.observability.business_metrics import (
    generate_quarter_windows,
    select_quarter_window,
    compute_orders_metrics,
    compute_refund_metrics,
    compute_rma_summary,
    QuarterWindow,
)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def session():
    db = SessionLocal()
    try:
        db.query(Refund).delete()
        db.query(ReturnRequest).delete()
        db.query(Payment).delete()
        db.query(SaleItem).delete()
        db.query(OrderQueue).delete()
        db.query(Sale).delete()
        db.query(FailedPaymentLog).delete()
        db.query(User).delete()
        db.commit()
        yield db
    finally:
        db.close()


def _seed_user(db):
    user = User(username="kpi_user", email="kpi@example.com", passwordHash="hash", role="customer")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_generate_quarter_windows_starts_2025():
    windows = generate_quarter_windows(now=datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert windows[0].key == "2025-Q1"
    assert windows[-1].key == "2050-Q4"


def test_select_quarter_window_defaults_to_latest():
    windows = [
        QuarterWindow(
            key="2025-Q1",
            label="Q1 2025",
            year=2025,
            quarter=1,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 4, 1, tzinfo=timezone.utc),
        ),
        QuarterWindow(
            key="2025-Q2",
            label="Q2 2025",
            year=2025,
            quarter=2,
            start=datetime(2025, 4, 1, tzinfo=timezone.utc),
            end=datetime(2025, 7, 1, tzinfo=timezone.utc),
        ),
    ]
    selected = select_quarter_window(windows, None)
    assert selected.key == "2025-Q2"
    explicit = select_quarter_window(windows, "2025-Q1")
    assert explicit.key == "2025-Q1"


def test_compute_orders_metrics_counts_only_selected_quarter(session):
    user = _seed_user(session)
    sale_in = Sale(
        userID=user.userID,
        sale_date=datetime(2025, 1, 15, tzinfo=timezone.utc),
        totalAmount=100,
        status="completed",
    )
    sale_in_two = Sale(
        userID=user.userID,
        sale_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
        totalAmount=50,
        status="completed",
    )
    sale_out = Sale(
        userID=user.userID,
        sale_date=datetime(2025, 4, 3, tzinfo=timezone.utc),
        totalAmount=30,
        status="completed",
    )
    session.add_all([sale_in, sale_in_two, sale_out])
    session.commit()

    windows = generate_quarter_windows(now=datetime(2025, 5, 1, tzinfo=timezone.utc))
    window = select_quarter_window(windows, "2025-Q1")
    metrics = compute_orders_metrics(session, window, now=datetime(2025, 3, 31, tzinfo=timezone.utc))

    assert metrics["total"] == 2
    assert metrics["series_max"] >= 1
    if metrics["series"]:
        assert math.isclose(metrics["mean_per_day"] * len(metrics["series"]), metrics["total"], rel_tol=1e-6)


def test_compute_refund_metrics_only_completed_refunds(session):
    user = _seed_user(session)
    sale = Sale(
        userID=user.userID,
        sale_date=datetime(2025, 1, 20, tzinfo=timezone.utc),
        totalAmount=200,
        status="completed",
    )
    session.add(sale)
    session.commit()

    payment = Payment(
        saleID=sale.saleID,
        payment_date=datetime(2025, 1, 21, tzinfo=timezone.utc),
        amount=200,
        status="captured",
        payment_type="card",
    )
    session.add(payment)
    session.commit()

    request = ReturnRequest(
        saleID=sale.saleID,
        customerID=user.userID,
        status=ReturnRequestStatus.AUTHORIZED,
        reason=ReturnReason.DAMAGED,
        details="defect",
    )
    session.add(request)
    session.commit()

    completed = Refund(
        returnRequestID=request.returnRequestID,
        paymentID=payment.paymentID,
        amount=50,
        method=RefundMethod.CARD,
        status=RefundStatus.COMPLETED,
        created_at=datetime(2025, 1, 25, tzinfo=timezone.utc),
    )
    pending = Refund(
        returnRequestID=request.returnRequestID,
        paymentID=payment.paymentID,
        amount=40,
        method=RefundMethod.CARD,
        status=RefundStatus.PENDING,
        created_at=datetime(2025, 1, 28, tzinfo=timezone.utc),
    )
    session.add_all([completed, pending])
    session.commit()

    windows = generate_quarter_windows(now=datetime(2025, 5, 1, tzinfo=timezone.utc))
    window = select_quarter_window(windows, "2025-Q1")
    metrics = compute_refund_metrics(session, window, now=datetime(2025, 3, 31, tzinfo=timezone.utc))

    assert metrics["total"] == 1
    assert metrics["series_max"] == 1
    assert metrics["mean_per_day"] <= 1


def test_refund_metrics_group_same_local_day(session):
    try:
        new_tz = ZoneInfo("Asia/Baku")
    except ZoneInfoNotFoundError:
        pytest.skip("tzdata not available for Asia/Baku on this platform")
    original_tz = bm._LOCAL_TZ
    try:
        bm._LOCAL_TZ = new_tz
        user = _seed_user(session)
        sale = Sale(
            userID=user.userID,
            sale_date=datetime(2025, 11, 19, 10, tzinfo=timezone.utc),
            totalAmount=200,
            status="completed",
        )
        session.add(sale)
        session.commit()

        payment = Payment(
            saleID=sale.saleID,
            payment_date=datetime(2025, 11, 19, tzinfo=timezone.utc),
            amount=200,
            status="captured",
            payment_type="card",
        )
        session.add(payment)
        session.commit()

        request = ReturnRequest(
            saleID=sale.saleID,
            customerID=user.userID,
            status=ReturnRequestStatus.REFUNDED,
            reason=ReturnReason.DAMAGED,
            details="key issue",
        )
        session.add(request)
        session.commit()

        refunds = [
            Refund(
                returnRequestID=request.returnRequestID,
                paymentID=payment.paymentID,
                amount=50,
                method=RefundMethod.CARD,
                status=RefundStatus.COMPLETED,
                created_at=datetime(2025, 11, 19, 0, 30, tzinfo=timezone.utc),
            ),
            Refund(
                returnRequestID=request.returnRequestID,
                paymentID=payment.paymentID,
                amount=30,
                method=RefundMethod.CARD,
                status=RefundStatus.COMPLETED,
                created_at=datetime(2025, 11, 19, 23, 45, tzinfo=timezone.utc),
            ),
        ]
        session.add_all(refunds)
        session.commit()

        windows = generate_quarter_windows(now=datetime(2025, 11, 25, tzinfo=timezone.utc))
        window = select_quarter_window(windows, "2025-Q4")
        metrics = compute_refund_metrics(session, window)

        assert metrics["total"] == 1
        non_zero_days = [point for point in metrics["series"] if point["count"]]
        assert len(non_zero_days) == 1
        assert non_zero_days[0]["count"] == 2
    finally:
        bm._LOCAL_TZ = original_tz


def test_compute_rma_summary_cycle_time(session):
    user = _seed_user(session)
    sale = Sale(
        userID=user.userID,
        sale_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
        totalAmount=150,
        status="completed",
    )
    session.add(sale)
    session.commit()

    request = ReturnRequest(
        saleID=sale.saleID,
        customerID=user.userID,
        status=ReturnRequestStatus.REFUNDED,
        reason=ReturnReason.DAMAGED,
        created_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        updated_at=datetime(2025, 1, 7, tzinfo=timezone.utc),
    )
    session.add(request)
    session.commit()

    windows = generate_quarter_windows(now=datetime(2025, 5, 1, tzinfo=timezone.utc))
    window = select_quarter_window(windows, "2025-Q1")
    summary = compute_rma_summary(session, window)

    assert summary["count"] == 1
    assert math.isclose(summary["avg_cycle_hours"], 48.0, rel_tol=1e-6)