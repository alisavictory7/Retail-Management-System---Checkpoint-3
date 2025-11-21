# src/tactics/availability.py
"""
Availability tactics implementation for Checkpoint 2.
Implements: Circuit Breaker, Graceful Degradation, Rollback, Retry, Removal from Service
"""

from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime, timezone, timedelta
import logging
import time
from sqlalchemy.orm import Session

from .base import (
    BaseCircuitBreaker,
    BaseRetry,
    BaseTactic,
    TacticState,
    CircuitBreakerState as BreakerState,
)
from ..models import (
    CircuitBreakerState as CircuitBreakerStateModel,
    OrderQueue,
    AuditLog,
    SystemMetrics,
)
from src.observability import increment_counter, observe_latency, record_event

logger = logging.getLogger(__name__)

class PaymentServiceCircuitBreaker(BaseCircuitBreaker):
    """Circuit breaker specifically for payment service"""
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        super().__init__("payment_service", config)
        self.db = db_session
        self.failure_threshold = self.config.get('failure_threshold', 5)
        self.timeout_duration = self.config.get('timeout_duration', 60)
        self.outage_started_at = None
        
        # Debug: Check if database session is valid
        if self.db is None:
            self.logger.warning("Circuit breaker initialized with None database session")
    
    def execute(self, payment_func: Callable, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute payment function with circuit breaker protection"""
        if not self.can_execute():
            self.log_metric("circuit_breaker_open", 1, {"service": "payment_service"})
            return False, "Payment service temporarily unavailable"
        
        try:
            result = payment_func(*args, **kwargs)
            self.record_success()
            try:
                self._update_db_state()
            except Exception as db_error:
                self.logger.warning(f"Failed to update circuit breaker state: {db_error}")
            return True, result
        except Exception as e:
            self.record_failure()
            try:
                self._update_db_state()
            except Exception as db_error:
                self.logger.warning(f"Failed to update circuit breaker state: {db_error}")
            self._log_failure(e)
            return False, str(e)
    
    def _update_db_state(self):
        """Update circuit breaker state in database"""
        if not self.db:
            self.logger.warning("No database session available for circuit breaker state update")
            return
            
        try:
            # Check if database session is still valid
            if not hasattr(self.db, 'query'):
                self.logger.warning("Database session is invalid (no query method)")
                return
                
            breaker = self.db.query(CircuitBreakerStateModel).filter_by(
                service_name=self.service_name
            ).first()
            
            if breaker:
                breaker.state = self.state.value
                breaker.failure_count = self.failure_count
                breaker.last_failure_time = self.last_failure_time
                breaker.next_attempt_time = self.next_attempt_time
                breaker.updated_at = datetime.now(timezone.utc)
            else:
                breaker = CircuitBreakerStateModel(
                    service_name=self.service_name,
                    state=self.state.value,
                    failure_count=self.failure_count,
                    last_failure_time=self.last_failure_time,
                    next_attempt_time=self.next_attempt_time,
                    failure_threshold=self.failure_threshold,
                    timeout_duration=self.timeout_duration
                )
                self.db.add(breaker)
            
            self.db.commit()
        except Exception as e:
            self.logger.error(f"Failed to update circuit breaker state: {e}")
            try:
                if self.db and hasattr(self.db, 'rollback'):
                    self.db.rollback()
            except Exception as rollback_error:
                self.logger.error(f"Failed to rollback database transaction: {rollback_error}")
    
    def _log_failure(self, error: Exception):
        """Log circuit breaker failure"""
        self.log_metric("circuit_breaker_failure", 1, {
            "service": "payment_service",
            "error": str(error)
        })

    def record_success(self):
        prev_state = self.state
        super().record_success()
        if self.outage_started_at:
            recovery_time = datetime.now(timezone.utc)
            mttr_seconds = (recovery_time - self.outage_started_at).total_seconds()
            if mttr_seconds >= 0:
                observe_latency("payment_circuit_mttr_seconds", mttr_seconds)
                increment_counter("payment_circuit_recoveries_total")
                record_event(
                    "payment_service_recovered",
                    {
                        "service": self.service_name,
                        "mttr_seconds": mttr_seconds,
                    },
                )
            self.outage_started_at = None
        if prev_state != self.state:
            record_event(
                "payment_circuit_state_change",
                {"service": self.service_name, "state": self.state.value},
            )

    def record_failure(self):
        prev_state = self.state
        super().record_failure()
        if self.state == BreakerState.OPEN and self.outage_started_at is None:
            self.outage_started_at = self.last_failure_time or datetime.now(timezone.utc)
            record_event(
                "payment_circuit_opened",
                {
                    "service": self.service_name,
                    "failure_count": self.failure_count,
                    "timeout_seconds": self.timeout_duration,
                },
            )
            increment_counter("payment_circuit_open_events_total")
        if prev_state != self.state:
            record_event(
                "payment_circuit_state_change",
                {"service": self.service_name, "state": self.state.value},
            )

class GracefulDegradationTactic(BaseTactic):
    """Graceful degradation for order processing during failures"""
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        super().__init__("graceful_degradation", config)
        self.db = db_session
        self.queue_name = "order_processing"
    
    def execute(self, order_data: Dict[str, Any], user_id: int) -> Tuple[bool, str]:
        """Execute graceful degradation by queuing orders"""
        try:
            start_time = time.perf_counter()
            # Create order queue entry
            queue_item = OrderQueue(
                saleID=order_data.get('sale_id'),
                userID=user_id,
                queue_type='payment_retry',
                priority=order_data.get('priority', 0),
                status='pending',
                scheduled_for=datetime.now(timezone.utc),
                max_attempts=3
            )
            
            self.db.add(queue_item)
            self.db.commit()
            
            self.log_metric("order_queued", 1, {
                "user_id": str(user_id),
                "queue_type": "payment_retry"
            })

            increment_counter("orders_accepted_total", labels={"mode": "queued"})
            duration_ms = (time.perf_counter() - start_time) * 1000
            observe_latency("order_processing_latency_ms", duration_ms, labels={"mode": "queued"})
            record_event(
                "order_queued_for_retry",
                {
                    "queue_id": queue_item.queueID,
                    "sale_id": queue_item.saleID,
                    "user_id": user_id,
                },
            )
            
            self._log_audit("order_queued", "Order", queue_item.queueID, 
                          user_id, "Order queued for retry processing")
            
            return True, "Order queued for processing"
            
        except Exception as e:
            self.logger.error(f"Failed to queue order: {e}")
            self.db.rollback()
            return False, f"Failed to queue order: {str(e)}"
    
    def _log_audit(self, action: str, entity_type: str, entity_id: int, 
                   user_id: int, description: str):
        """Log audit event"""
        try:
            audit = AuditLog(
                event_type="graceful_degradation",
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                action=action,
                new_values=json.dumps({"status": "queued"}),
                success=True,
                error_message=description
            )
            self.db.add(audit)
            self.db.commit()
        except Exception as e:
            self.logger.error(f"Failed to log audit: {e}")
    
    def validate_config(self) -> bool:
        """Validate graceful degradation configuration"""
        return self.db is not None and self.queue_name is not None

class RollbackTactic(BaseTactic):
    """Rollback tactic for transaction integrity"""
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        super().__init__("rollback", config)
        self.db = db_session
    
    def execute(self, transaction_func: Callable, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute transaction with rollback capability"""
        try:
            # Start transaction
            result = transaction_func(*args, **kwargs)
            self.db.commit()
            
            self.log_metric("transaction_success", 1, {"tactic": "rollback"})
            return True, result
            
        except Exception as e:
            # Rollback on failure
            self.db.rollback()
            self.logger.error(f"Transaction rolled back due to error: {e}")
            
            self.log_metric("transaction_rollback", 1, {
                "tactic": "rollback",
                "error": str(e)
            })
            
            return False, f"Transaction rolled back: {str(e)}"
    
    def validate_config(self) -> bool:
        """Validate rollback configuration"""
        return self.db is not None

class PaymentRetryTactic(BaseRetry):
    """Retry tactic specifically for payment operations"""
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        super().__init__(config)
        self.db = db_session
    
    def execute(self, payment_func: Callable, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute payment with retry logic"""
        try:
            result = self.execute_with_retry(payment_func, *args, **kwargs)
            self.log_metric("payment_retry_success", 1, {
                "tactic": "retry",
                "attempts": "successful"
            })
            return True, result
        except Exception as e:
            self.logger.error(f"Payment retry failed after {self.max_attempts} attempts: {e}")
            self.log_metric("payment_retry_failed", 1, {
                "tactic": "retry",
                "error": str(e)
            })
            return False, str(e)
    
    def validate_config(self) -> bool:
        """Validate retry configuration"""
        return super().validate_config() and self.db is not None

class RemovalFromServiceTactic(BaseTactic):
    """Removal from service for predictive fault mitigation"""
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        super().__init__("removal_from_service", config)
        self.db = db_session
        self.memory_threshold = config.get('memory_threshold', 80)  # 80% memory usage
        self.cpu_threshold = config.get('cpu_threshold', 90)  # 90% CPU usage
    
    def execute(self, worker_id: str, current_metrics: Dict[str, float]) -> Tuple[bool, str]:
        """Check if worker should be removed from service"""
        try:
            memory_usage = current_metrics.get('memory_usage', 0)
            cpu_usage = current_metrics.get('cpu_usage', 0)
            
            should_remove = (memory_usage > self.memory_threshold or 
                           cpu_usage > self.cpu_threshold)
            
            if should_remove:
                # Determine which resource caused the removal
                resource_type = []
                if memory_usage > self.memory_threshold:
                    resource_type.append("memory")
                if cpu_usage > self.cpu_threshold:
                    resource_type.append("cpu")
                
                resource_str = " and ".join(resource_type)
                
                self.log_metric("worker_removed", 1, {
                    "worker_id": worker_id,
                    "memory_usage": memory_usage,
                    "cpu_usage": cpu_usage
                })
                
                self._log_audit("worker_removed", "Worker", worker_id, 
                              None, f"Worker removed due to high {resource_str} usage")
                
                return True, f"Worker {worker_id} removed due to high {resource_str} usage"
            else:
                return False, "Worker operating normally"
                
        except Exception as e:
            self.logger.error(f"Error checking worker health: {e}")
            return False, f"Error checking worker health: {str(e)}"
    
    def _log_audit(self, action: str, entity_type: str, entity_id: str, 
                   user_id: Optional[int], description: str):
        """Log audit event"""
        try:
            audit = AuditLog(
                event_type="removal_from_service",
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                action=action,
                new_values=json.dumps({"status": "removed"}),
                success=True,
                error_message=description
            )
            self.db.add(audit)
            self.db.commit()
        except Exception as e:
            self.logger.error(f"Failed to log audit: {e}")
    
    def validate_config(self) -> bool:
        """Validate removal from service configuration"""
        return (0 <= self.memory_threshold <= 100 and 
                0 <= self.cpu_threshold <= 100 and 
                self.db is not None)

# Import json for audit logging
import json
