from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from src.config import Config
from src.models import (
    User,
    Product,
    Sale,
    SaleItem,
    Payment,
    ReturnReason,
    ReturnRequestStatus,
    InspectionResult,
    RefundStatus,
)
from src.services.inventory_service import InventoryService
from src.services.refund_service import RefundService
from src.services.returns_service import ReturnsService


class _StubConfig:
    RETURN_WINDOW_DAYS = 30
    MAX_RETURN_ITEM_QUANTITY = 5
    RETURNS_REQUIRE_PHOTOS = False
    FEATURE_RETURNS_ENABLED = True
    RETURNS_MAX_PHOTOS = 20
    PAYMENT_REFUND_FAILURE_PROBABILITY = 0.0


class _StubPaymentService:
    def __init__(self, should_fail: bool = False, message: str = "failure"):
        self.should_fail = should_fail
        self.message = message
        self.calls = 0

    def refund(self, payment: Payment, amount: float):
        self.calls += 1
        if self.should_fail:
            return False, self.message, None
        return True, "Refund completed", f"REF-{payment.paymentID}-{self.calls}"


def _create_completed_sale(db_session, *, days_ago: int = 1):
    unique_suffix = uuid4().hex[:8]
    user = User(
        username=f"returns_test_user_{unique_suffix}",
        email=f"returns_test_{unique_suffix}@example.com",
    )
    user.passwordHash = "hashed"
    db_session.add(user)

    product = Product(
        name="Returnable Item",
        description="Test product",
        price=100.00,
        stock=5,
    )
    db_session.add(product)
    db_session.flush()

    sale = Sale()
    sale.userID = user.userID
    sale._sale_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    sale._totalAmount = 100.00
    sale._status = "completed"
    db_session.add(sale)
    db_session.flush()

    sale_item = SaleItem()
    sale_item.saleID = sale.saleID
    sale_item.productID = product.productID
    sale_item.quantity = 1
    sale_item._original_unit_price = 100.00
    sale_item._final_unit_price = 100.00
    sale_item._discount_applied = 0.00
    sale_item._shipping_fee_applied = 0.00
    sale_item._import_duty_applied = 0.00
    sale_item._subtotal = 100.00
    db_session.add(sale_item)

    payment = Payment()
    payment.saleID = sale.saleID
    payment.amount = 100.00
    payment.payment_type = "card"
    payment.type = "card"
    payment.status = "completed"
    db_session.add(payment)

    db_session.commit()
    return user, product, sale, sale_item, payment


def _build_returns_service(db_session, *, payment_should_fail: bool = False) -> ReturnsService:
    payment_service = _StubPaymentService(should_fail=payment_should_fail)
    inventory_service = InventoryService(db_session)
    refund_service = RefundService(
        db_session,
        payment_service=payment_service,
        inventory_service=inventory_service,
        config=_StubConfig,
    )
    return ReturnsService(
        db_session,
        config=_StubConfig,
        refund_service=refund_service,
        inventory_service=inventory_service,
    )


def test_returns_workflow_happy_path(db_session):
    _, product, sale, sale_item, _ = _create_completed_sale(db_session)
    service = _build_returns_service(db_session)

    success, message, request = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
        details="Screen flickers",
    )
    assert success, message
    assert request.status == ReturnRequestStatus.PENDING_AUTHORIZATION

    service.authorize_return(request.returnRequestID, approve=True, decision_notes="OK")
    db_session.refresh(request)
    assert request.status == ReturnRequestStatus.AUTHORIZED

    service.record_shipment(request.returnRequestID, carrier="DHL", tracking_number="TRACK123")
    db_session.refresh(request)
    assert request.status == ReturnRequestStatus.IN_TRANSIT

    service.mark_received(request.returnRequestID)
    db_session.refresh(request)
    assert request.status == ReturnRequestStatus.RECEIVED

    service.record_inspection(
        request.returnRequestID,
        inspected_by="QA Bot",
        result=InspectionResult.APPROVED,
        notes="Looks good",
    )
    db_session.refresh(request)
    assert request.status == ReturnRequestStatus.APPROVED

    success, message = service.initiate_refund(request.returnRequestID)
    assert success, message

    db_session.refresh(request)
    db_session.refresh(product)
    refund = request.refund

    assert request.status == ReturnRequestStatus.REFUNDED
    assert refund.status == RefundStatus.COMPLETED
    assert product.stock == 6  # inventory adjusted back


def test_refund_failure_keeps_request_approved(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    service = _build_returns_service(db_session, payment_should_fail=True)

    success, _, request = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.OTHER,
    )
    assert success

    service.authorize_return(request.returnRequestID, approve=True)
    service.record_shipment(request.returnRequestID, carrier="UPS", tracking_number="FAIL-123")
    service.mark_received(request.returnRequestID)
    service.record_inspection(
        request.returnRequestID,
        inspected_by="QA Bot",
        result=InspectionResult.APPROVED,
    )

    success, message = service.initiate_refund(request.returnRequestID)
    assert not success
    assert "failure" in message.lower()

    db_session.refresh(request)
    refund = request.refund
    assert request.status == ReturnRequestStatus.APPROVED
    assert refund.status == RefundStatus.FAILED


def test_return_request_outside_policy_window(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session, days_ago=60)
    service = _build_returns_service(db_session)

    success, message, _ = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.WRONG_ITEM,
    )
    assert not success
    assert "window" in message.lower()


def test_return_request_quantity_cannot_exceed_purchased(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    service = _build_returns_service(db_session)

    success, _, _ = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
    )
    assert success

    success2, message2, _ = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
    )
    assert not success2
    assert "already have return requests" in message2


def _create_approved_return_request(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    service = _build_returns_service(db_session)
    success, _, request = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
    )
    assert success
    service.authorize_return(request.returnRequestID, approve=True)
    service.record_shipment(request.returnRequestID, carrier="DHL", tracking_number="TRACK")
    service.mark_received(request.returnRequestID)
    service.record_inspection(
        request.returnRequestID,
        inspected_by="QA Team",
        result=InspectionResult.APPROVED,
    )
    return request.returnRequestID, service


def test_manual_refund_methods_complete_without_gateway(db_session):
    return_id, service = _create_approved_return_request(db_session)
    success, message = service.initiate_refund(return_id, method="STORE_CREDIT")
    assert success, message


def test_original_method_aliases_to_payment_channel(db_session):
    original_probability = Config.PAYMENT_REFUND_FAILURE_PROBABILITY
    Config.PAYMENT_REFUND_FAILURE_PROBABILITY = 0.0
    try:
        return_id, service = _create_approved_return_request(db_session)
        success, message = service.initiate_refund(return_id, method="ORIGINAL_METHOD")
        assert success, message
    finally:
        Config.PAYMENT_REFUND_FAILURE_PROBABILITY = original_probability


def test_create_return_request_stores_uploaded_photos(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    service = _build_returns_service(db_session)
    photos = [f"uploads/returns/test_photo_{i}.jpg" for i in range(3)]

    success, _, request = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
        photos=photos,
    )
    assert success
    db_session.refresh(request)
    assert len(request.photos) == 3
    assert request.photos[0].file_path == photos[0]


def test_photos_are_limited_to_configured_max(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    original_max = _StubConfig.RETURNS_MAX_PHOTOS
    _StubConfig.RETURNS_MAX_PHOTOS = 5
    service = _build_returns_service(db_session)
    photos = [f"https://example.com/photo-{i}.jpg" for i in range(10)]
    try:
        success, _, request = service.create_return_request(
            sale_id=sale.saleID,
            customer_id=sale.userID,
            items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
            reason=ReturnReason.DAMAGED,
            photos=photos,
        )
        assert success
        db_session.refresh(request)
        assert len(request.photos) == 5
    finally:
        _StubConfig.RETURNS_MAX_PHOTOS = original_max


def test_failed_sales_are_not_eligible(db_session):
    _, _, sale, sale_item, payment = _create_completed_sale(db_session)
    # Simulate a failure by marking the payment as failed and removing any successful ones
    payment.status = "failed"
    db_session.commit()
    service = _build_returns_service(db_session)

    success, message, _ = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
    )

    assert not success
    assert "not eligible" in message.lower()


def test_manual_refund_blocked_when_failure_mode(db_session):
    original_probability = _StubConfig.PAYMENT_REFUND_FAILURE_PROBABILITY
    _StubConfig.PAYMENT_REFUND_FAILURE_PROBABILITY = 1.0
    try:
        return_id, service = _create_approved_return_request(db_session)
        success, message = service.initiate_refund(return_id, method="STORE_CREDIT")
        assert not success
        assert "manual refund methods" in message.lower()
    finally:
        _StubConfig.PAYMENT_REFUND_FAILURE_PROBABILITY = original_probability


def test_sales_without_positive_quantities_are_filtered(db_session):
    _, _, sale, sale_item, _ = _create_completed_sale(db_session)
    sale_item.quantity = 0
    db_session.commit()

    service = _build_returns_service(db_session)
    success, message, _ = service.create_return_request(
        sale_id=sale.saleID,
        customer_id=sale.userID,
        items=[{"sale_item_id": sale_item.saleItemID, "quantity": 1}],
        reason=ReturnReason.DAMAGED,
    )
    assert not success
    assert "cannot return more units than were purchased" in message.lower()

