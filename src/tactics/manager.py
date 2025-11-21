# src/tactics/manager.py
"""
Central manager for all quality tactics and patterns.
This module provides a unified interface for all 14+ tactics implemented
for Checkpoint 2 quality attributes.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging
import time
from sqlalchemy.orm import Session

# Import all tactic managers
from .availability import (
    PaymentServiceCircuitBreaker, GracefulDegradationTactic,
    RollbackTactic, PaymentRetryTactic, RemovalFromServiceTactic
)
from .security import SecurityManager
from .modifiability import ModifiabilityManager
from .performance import ThrottlingManager, OrderQueueManager, ConcurrencyManager, PerformanceMonitor
from .integrability import IntegrabilityManager
from .testability import TestabilityManager
from .usability import UsabilityManager
from src.observability import increment_counter, observe_latency, record_event

logger = logging.getLogger(__name__)

class QualityTacticsManager:
    """
    Central manager for all quality tactics and patterns.
    Provides a unified interface for implementing all 14+ tactics
    required for Checkpoint 2.
    """
    
    def __init__(self, db_session: Session, config: Dict[str, Any] = None):
        self.db = db_session
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Initialize all tactic managers
        self._initialize_managers()
        
        # Track active operations
        self.active_operations = {}
    
    def _initialize_managers(self):
        """Initialize all tactic managers"""
        try:
            # Availability tactics
            self.circuit_breaker = PaymentServiceCircuitBreaker(self.db, self.config.get('circuit_breaker', {}))
            self.graceful_degradation = GracefulDegradationTactic(self.db, self.config.get('graceful_degradation', {}))
            self.rollback = RollbackTactic(self.db, self.config.get('rollback', {}))
            self.retry = PaymentRetryTactic(self.db, self.config.get('retry', {}))
            self.removal_from_service = RemovalFromServiceTactic(self.db, self.config.get('removal_from_service', {}))
            
            # Security tactics
            self.security = SecurityManager(self.db, self.config.get('security', {}))
            
            # Modifiability tactics
            self.modifiability = ModifiabilityManager(self.db, self.config.get('modifiability', {}))
            
            # Performance tactics
            self.throttling = ThrottlingManager(self.db, self.config.get('throttling', {}))
            self.order_queue = OrderQueueManager(self.db, self.config.get('queue', {}))
            self.concurrency = ConcurrencyManager(self.db, self.config.get('concurrency', {}))
            self.performance_monitor = PerformanceMonitor(self.db, self.config.get('monitoring', {}))
            
            # Integrability tactics
            self.integrability = IntegrabilityManager(self.db, self.config.get('integrability', {}))
            
            # Testability tactics
            self.testability = TestabilityManager(self.db, self.config.get('testability', {}))
            
            # Usability tactics
            self.usability = UsabilityManager(self.config.get('usability', {}))
            
            self.logger.info("All quality tactic managers initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize tactic managers: {e}")
            raise
    
    # ==============================================
    # AVAILABILITY TACTICS
    # ==============================================
    
    def execute_with_circuit_breaker(self, service_func, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute function with circuit breaker protection"""
        return self.circuit_breaker.execute(service_func, *args, **kwargs)
    
    def queue_order_for_retry(self, order_data: Dict[str, Any], user_id: int) -> Tuple[bool, str]:
        """Queue order for retry processing (graceful degradation)"""
        return self.graceful_degradation.execute(order_data, user_id)
    
    def execute_with_rollback(self, transaction_func, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute transaction with rollback capability"""
        return self.rollback.execute(transaction_func, *args, **kwargs)
    
    def execute_with_retry(self, retry_func, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute function with retry logic"""
        return self.retry.execute(retry_func, *args, **kwargs)
    
    def check_worker_health(self, worker_id: str, metrics: Dict[str, float]) -> Tuple[bool, str]:
        """Check if worker should be removed from service"""
        return self.removal_from_service.execute(worker_id, metrics)
    
    # ==============================================
    # SECURITY TACTICS
    # ==============================================
    
    def authenticate_partner(self, api_key: str) -> Tuple[bool, str]:
        """Authenticate partner using API key"""
        return self.security.authenticate_partner(api_key)
    
    def validate_partner_data(self, data: Any) -> Tuple[bool, str]:
        """Validate partner data for security threats"""
        return self.security.validate_partner_data(data)
    
    def is_secure_operation(self, api_key: str, data: Any) -> Tuple[bool, str]:
        """Check if operation is secure (both auth and validation)"""
        return self.security.is_secure_operation(api_key, data)
    
    # ==============================================
    # MODIFIABILITY TACTICS
    # ==============================================
    
    def process_partner_data(self, data: str, partner_format: str = None) -> Tuple[bool, Dict[str, Any]]:
        """Process partner data using intermediary pattern"""
        return self.modifiability.process_partner_data(data, partner_format)
    
    def is_feature_enabled(self, feature_name: str, user_id: int = None) -> Tuple[bool, str]:
        """Check if feature is enabled"""
        return self.modifiability.is_feature_enabled(feature_name, user_id)
    
    def enable_feature(self, feature_name: str, rollout_percentage: int = 100, 
                      target_users: List[int] = None, updated_by: str = None) -> Tuple[bool, str]:
        """Enable a feature"""
        return self.modifiability.enable_feature(feature_name, rollout_percentage, target_users, updated_by)
    
    def disable_feature(self, feature_name: str, updated_by: str = None) -> Tuple[bool, str]:
        """Disable a feature"""
        return self.modifiability.disable_feature(feature_name, updated_by)
    
    # ==============================================
    # PERFORMANCE TACTICS
    # ==============================================
    
    def check_throttling(self, request_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Check if request should be throttled"""
        return self.throttling.execute(request_data)
    
    def enqueue_order(self, order_data: Dict[str, Any], priority: int = 0) -> Tuple[bool, str]:
        """Enqueue order for processing"""
        return self.order_queue.enqueue_order(order_data, priority)
    
    def dequeue_order(self) -> Optional[Dict[str, Any]]:
        """Dequeue highest priority order"""
        return self.order_queue.dequeue_order()
    
    def execute_with_concurrency_control(self, operation_func, *args, **kwargs) -> Tuple[bool, Any]:
        """Execute operation with concurrency control"""
        return self.concurrency.execute_with_lock(operation_func, *args, **kwargs)
    
    def collect_performance_metrics(self) -> Dict[str, Any]:
        """Collect performance metrics"""
        return self.performance_monitor.execute()
    
    # ==============================================
    # INTEGRABILITY TACTICS
    # ==============================================
    
    def adapt_data(self, adapter_name: str, data: Any) -> Tuple[bool, Any]:
        """Adapt data using specified adapter"""
        return self.integrability.adapt_data(adapter_name, data)
    
    def publish_message(self, topic: str, message: Dict[str, Any], message_type: str = "data_update") -> Tuple[bool, str]:
        """Publish message to topic"""
        return self.integrability.publish_message(topic, message, message_type)
    
    def setup_partner_integration(self, partner_id: int, api_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Setup integration for a new partner"""
        return self.integrability.setup_partner_integration(partner_id, api_config)
    
    # ==============================================
    # TESTABILITY TACTICS
    # ==============================================
    
    def run_test_with_recording(self, test_name: str, test_func) -> Tuple[bool, Dict[str, Any]]:
        """Run test with recording and playback capability"""
        return self.testability.run_test_with_recording(test_name, test_func)
    
    def playback_test(self, test_name: str) -> Tuple[bool, List[Dict[str, Any]]]:
        """Playback a recorded test"""
        return self.testability.playback_test(test_name)
    
    def get_available_tests(self) -> List[str]:
        """Get list of available recorded tests"""
        return self.testability.get_available_tests()
    
    # ==============================================
    # USABILITY TACTICS
    # ==============================================
    
    def handle_user_error(self, error_type: str, context: Dict[str, Any] = None) -> Tuple[bool, Dict[str, Any]]:
        """Handle user error with recovery guidance"""
        return self.usability.handle_user_error(error_type, context)
    
    def handle_payment_error(self, error_code: str, amount: float, payment_method: str) -> Tuple[bool, Dict[str, Any]]:
        """Handle payment-specific errors"""
        return self.usability.handle_payment_error(error_code, amount, payment_method)
    
    def start_progress_tracking(self, operation_id: str, operation_type: str, 
                               estimated_duration: int = None) -> Tuple[bool, str]:
        """Start progress tracking for an operation"""
        return self.usability.start_progress_tracking(operation_id, operation_type, estimated_duration)
    
    def update_progress(self, operation_id: str, progress: int, current_step: str = None) -> Tuple[bool, str]:
        """Update operation progress"""
        return self.usability.update_progress(operation_id, progress, current_step)
    
    def get_progress(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress for operation"""
        return self.usability.get_progress(operation_id)
    
    def complete_operation(self, operation_id: str, success: bool = True, error_message: str = None) -> Tuple[bool, str]:
        """Complete an operation"""
        return self.usability.complete_operation(operation_id, success, error_message)
    
    # ==============================================
    # COMPREHENSIVE OPERATION METHODS
    # ==============================================
    
    def process_flash_sale_order(self, order_data: Dict[str, Any], user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Process flash sale order with all quality tactics"""
        operation_id = f"flash_sale_{order_data.get('sale_id')}_{int(datetime.now().timestamp())}"
        
        try:
            order_start = time.perf_counter()
            # Start progress tracking
            self.start_progress_tracking(operation_id, "flash_sale_processing", 30)
            
            # Check throttling
            throttled, throttle_msg = self.check_throttling(order_data)
            if not throttled:
                return False, {"error": "Request throttled", "message": throttle_msg}
            
            self.update_progress(operation_id, 20, "Throttling check passed")
            increment_counter("orders_submitted_total", labels={"source": "flash_sale"})
            
            # Check feature toggle
            feature_enabled, feature_msg = self.is_feature_enabled("flash_sale_enabled", user_id)
            if not feature_enabled:
                return False, {"error": "Feature disabled", "message": feature_msg}
            
            self.update_progress(operation_id, 40, "Feature toggle check passed")
            
            # Process with circuit breaker and retry
            def process_payment():
                # Mock payment processing
                return {"status": "success", "transaction_id": f"TXN_{operation_id}"}
            
            success, result = self.execute_with_circuit_breaker(process_payment)
            if not success:
                # Queue for retry
                self.queue_order_for_retry(order_data, user_id)
                return False, {"error": "Payment failed", "message": "Order queued for retry"}
            
            self.update_progress(operation_id, 80, "Payment processed")
            
            # Complete operation
            self.complete_operation(operation_id, True)
            duration_ms = (time.perf_counter() - order_start) * 1000
            increment_counter("orders_accepted_total", labels={"mode": "completed"})
            observe_latency("order_processing_latency_ms", duration_ms, labels={"mode": "completed"})
            record_event(
                "order_completed",
                {
                    "operation_id": operation_id,
                    "sale_id": order_data.get("sale_id"),
                    "user_id": user_id,
                    "latency_ms": duration_ms,
                },
            )
            
            return True, {
                "status": "success",
                "operation_id": operation_id,
                "result": result
            }
            
        except Exception as e:
            self.complete_operation(operation_id, False, str(e))
            return False, {"error": "Processing failed", "message": str(e)}
    
    def process_partner_catalog_ingest(self, partner_id: int, data: str, api_key: str) -> Tuple[bool, Dict[str, Any]]:
        """Process partner catalog ingest with all quality tactics"""
        try:
            # Security: Authenticate and validate
            secure, security_msg = self.is_secure_operation(api_key, data)
            if not secure:
                return False, {"error": "Security check failed", "message": security_msg}
            
            # Modifiability: Process data with adapters
            success, processed_data = self.process_partner_data(data)
            if not success:
                return False, {"error": "Data processing failed", "message": "Invalid data format"}
            
            # Integrability: Publish message
            message = {
                "partner_id": partner_id,
                "data": processed_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            success, msg = self.publish_message(f"partner_{partner_id}_updates", message)
            if not success:
                return False, {"error": "Message publishing failed", "message": msg}
            
            return True, {
                "status": "success",
                "processed_items": len(processed_data.get('products', [])),
                "message": "Catalog ingest completed successfully"
            }
            
        except Exception as e:
            return False, {"error": "Ingest failed", "message": str(e)}
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status"""
        try:
            health = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "availability": {
                    "circuit_breaker_state": self.circuit_breaker.state.value,
                    "queue_size": self.order_queue.size(),
                    "active_operations": len(self.active_operations)
                },
                "performance": self.collect_performance_metrics(),
                "features": {
                    "flash_sale_enabled": self.is_feature_enabled("flash_sale_enabled")[0],
                    "partner_sync_enabled": self.is_feature_enabled("partner_sync_enabled")[0]
                },
                "security": {
                    "authentication_active": True,
                    "input_validation_active": True
                }
            }
            
            return health
            
        except Exception as e:
            self.logger.error(f"Failed to get system health: {e}")
            return {"error": str(e)}
    
    def validate_all_tactics(self) -> Dict[str, bool]:
        """Validate all implemented tactics"""
        validation_results = {}
        
        try:
            # Availability tactics
            validation_results["circuit_breaker"] = self.circuit_breaker.validate_config()
            validation_results["graceful_degradation"] = self.graceful_degradation.validate_config()
            validation_results["rollback"] = self.rollback.validate_config()
            validation_results["retry"] = self.retry.validate_config()
            validation_results["removal_from_service"] = self.removal_from_service.validate_config()
            
            # Security tactics
            validation_results["authenticate_actors"] = self.security.auth_tactic.validate_config()
            validation_results["validate_input"] = self.security.input_tactic.validate_config()
            
            # Modifiability tactics
            validation_results["data_intermediary"] = self.modifiability.data_intermediary.validate_config()
            
            # Performance tactics
            validation_results["throttling"] = self.throttling.validate_config()
            validation_results["order_queue"] = self.order_queue.validate_config()
            validation_results["concurrency"] = self.concurrency.validate_config()
            validation_results["performance_monitor"] = self.performance_monitor.validate_config()
            
            # Usability tactics
            validation_results["error_handler"] = self.usability.error_handler.validate_config()
            validation_results["progress_indicator"] = self.usability.progress_indicator.validate_config()
            
            return validation_results
            
        except Exception as e:
            self.logger.error(f"Tactic validation failed: {e}")
            return {"error": str(e)}
