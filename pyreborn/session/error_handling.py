"""
Comprehensive error handling system for PyReborn
"""

import logging
import traceback
import time
from typing import Dict, List, Optional, Any, Callable, Type
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict, deque

from ..session.events import EventManager, EventType


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories"""
    NETWORK = "network"
    PROTOCOL = "protocol"
    PARSING = "parsing"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class ErrorInfo:
    """Information about an error occurrence"""
    timestamp: float
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    exception: Optional[Exception] = None
    context: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    recovery_attempted: bool = False
    recovery_successful: bool = False


class ErrorRecoveryStrategy:
    """Base class for error recovery strategies"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(__name__)
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if this strategy can handle the error"""
        raise NotImplementedError
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt to recover from the error"""
        raise NotImplementedError


class RetryStrategy(ErrorRecoveryStrategy):
    """Retry operation with exponential backoff"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 10.0):
        super().__init__("retry")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_counts: Dict[str, int] = defaultdict(int)
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if we should retry this error"""
        # Don't retry critical errors or authentication failures
        if error.severity == ErrorSeverity.CRITICAL:
            return False
        if error.category == ErrorCategory.AUTHENTICATION:
            return False
        
        # Check retry count
        error_key = f"{error.category.value}:{error.message[:50]}"
        return self.retry_counts[error_key] < self.max_retries
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt recovery by retrying the operation"""
        error_key = f"{error.category.value}:{error.message[:50]}"
        attempt = self.retry_counts[error_key] + 1
        
        # Calculate delay
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        
        self.logger.info(f"Retrying operation (attempt {attempt}/{self.max_retries}) "
                        f"after {delay:.1f}s delay: {error.message}")
        
        time.sleep(delay)
        
        # Increment retry count
        self.retry_counts[error_key] = attempt
        
        # Get retry function from context
        retry_func = context.get('retry_function')
        if retry_func:
            try:
                result = retry_func()
                if result:
                    # Reset retry count on success
                    self.retry_counts[error_key] = 0
                    return True
            except Exception as e:
                self.logger.warning(f"Retry attempt failed: {e}")
        
        return False


class FallbackStrategy(ErrorRecoveryStrategy):
    """Fallback to alternative approach"""
    
    def __init__(self):
        super().__init__("fallback")
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if fallback is available"""
        return error.category in [ErrorCategory.PROTOCOL, ErrorCategory.PARSING]
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt recovery using fallback approach"""
        fallback_func = context.get('fallback_function')
        if fallback_func:
            try:
                self.logger.info(f"Attempting fallback recovery for: {error.message}")
                result = fallback_func()
                return result is not None
            except Exception as e:
                self.logger.warning(f"Fallback recovery failed: {e}")
        
        return False


class IgnoreStrategy(ErrorRecoveryStrategy):
    """Ignore non-critical errors"""
    
    def __init__(self):
        super().__init__("ignore")
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if error can be safely ignored"""
        return error.severity == ErrorSeverity.LOW
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Recovery by ignoring the error"""
        self.logger.debug(f"Ignoring low-severity error: {error.message}")
        return True


class ErrorHandler:
    """Comprehensive error handling system"""
    
    def __init__(self, event_manager: EventManager):
        self.events = event_manager
        self.logger = logging.getLogger(__name__)
        
        # Error tracking
        self.error_history: deque = deque(maxlen=1000)
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.last_errors: Dict[str, float] = {}
        
        # Recovery strategies
        self.recovery_strategies: List[ErrorRecoveryStrategy] = [
            RetryStrategy(),
            FallbackStrategy(),
            IgnoreStrategy()
        ]
        
        # Error handlers by category
        self.category_handlers: Dict[ErrorCategory, List[Callable]] = defaultdict(list)
        
        # Circuit breaker state
        self.circuit_breakers: Dict[str, Dict[str, Any]] = {}
        
    def add_recovery_strategy(self, strategy: ErrorRecoveryStrategy) -> None:
        """Add a custom recovery strategy"""
        self.recovery_strategies.insert(0, strategy)  # Insert at front for priority
        self.logger.debug(f"Added recovery strategy: {strategy.name}")
    
    def register_category_handler(self, category: ErrorCategory, handler: Callable[[ErrorInfo], None]) -> None:
        """Register a handler for specific error category"""
        self.category_handlers[category].append(handler)
        self.logger.debug(f"Registered handler for category: {category.value}")
    
    def handle_error(self, exception: Exception, category: ErrorCategory = ErrorCategory.UNKNOWN,
                    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                    context: Dict[str, Any] = None) -> bool:
        """Handle an error with recovery attempts"""
        
        context = context or {}
        
        # Create error info
        error = ErrorInfo(
            timestamp=time.time(),
            category=category,
            severity=severity,
            message=str(exception),
            exception=exception,
            context=context.copy(),
            stack_trace=traceback.format_exc()
        )
        
        # Track error
        self.error_history.append(error)
        error_key = f"{category.value}:{str(exception)[:50]}"
        self.error_counts[error_key] += 1
        self.last_errors[error_key] = error.timestamp
        
        # Log error
        self._log_error(error)
        
        # Check circuit breaker
        if self._is_circuit_broken(error_key):
            self.logger.warning(f"Circuit breaker open for: {error_key}")
            self._emit_error_event(error)
            return False
        
        # Run category-specific handlers
        for handler in self.category_handlers[category]:
            try:
                handler(error)
            except Exception as e:
                self.logger.error(f"Error in category handler: {e}")
        
        # Attempt recovery
        recovery_successful = self._attempt_recovery(error, context)
        
        error.recovery_attempted = True
        error.recovery_successful = recovery_successful
        
        # Update circuit breaker
        self._update_circuit_breaker(error_key, recovery_successful)
        
        # Emit error event
        self._emit_error_event(error)
        
        return recovery_successful
    
    def handle_packet_error(self, packet_data: bytes, exception: Exception,
                           context: Dict[str, Any] = None) -> bool:
        """Handle packet processing errors specifically"""
        
        context = context or {}
        context['packet_data'] = packet_data[:100]  # First 100 bytes for debugging
        context['packet_length'] = len(packet_data)
        
        # Determine category and severity
        if "decrypt" in str(exception).lower():
            category = ErrorCategory.NETWORK
            severity = ErrorSeverity.HIGH
        elif "parse" in str(exception).lower() or "unpack" in str(exception).lower():
            category = ErrorCategory.PARSING
            severity = ErrorSeverity.MEDIUM
        elif "protocol" in str(exception).lower():
            category = ErrorCategory.PROTOCOL
            severity = ErrorSeverity.MEDIUM
        else:
            category = ErrorCategory.UNKNOWN
            severity = ErrorSeverity.MEDIUM
        
        return self.handle_error(exception, category, severity, context)
    
    def handle_connection_error(self, exception: Exception, context: Dict[str, Any] = None) -> bool:
        """Handle connection-related errors"""
        return self.handle_error(exception, ErrorCategory.NETWORK, ErrorSeverity.HIGH, context)
    
    def handle_authentication_error(self, exception: Exception, context: Dict[str, Any] = None) -> bool:
        """Handle authentication errors"""
        return self.handle_error(exception, ErrorCategory.AUTHENTICATION, ErrorSeverity.HIGH, context)
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics"""
        now = time.time()
        recent_errors = [e for e in self.error_history if now - e.timestamp < 300]  # Last 5 minutes
        
        stats = {
            'total_errors': len(self.error_history),
            'recent_errors': len(recent_errors),
            'error_counts_by_category': {},
            'error_counts_by_severity': {},
            'recovery_success_rate': 0.0,
            'circuit_breakers': len([cb for cb in self.circuit_breakers.values() if cb.get('state') == 'open'])
        }
        
        # Count by category and severity
        for error in self.error_history:
            category = error.category.value
            severity = error.severity.value
            
            stats['error_counts_by_category'][category] = stats['error_counts_by_category'].get(category, 0) + 1
            stats['error_counts_by_severity'][severity] = stats['error_counts_by_severity'].get(severity, 0) + 1
        
        # Calculate recovery success rate
        recovery_attempts = [e for e in self.error_history if e.recovery_attempted]
        if recovery_attempts:
            successful_recoveries = [e for e in recovery_attempts if e.recovery_successful]
            stats['recovery_success_rate'] = len(successful_recoveries) / len(recovery_attempts)
        
        return stats
    
    def clear_error_history(self) -> None:
        """Clear error history and reset counters"""
        self.error_history.clear()
        self.error_counts.clear()
        self.last_errors.clear()
        self.circuit_breakers.clear()
        self.logger.info("Error history cleared")
    
    def _attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt recovery using available strategies"""
        
        for strategy in self.recovery_strategies:
            if strategy.can_recover(error):
                try:
                    if strategy.attempt_recovery(error, context):
                        self.logger.info(f"Successfully recovered using strategy: {strategy.name}")
                        return True
                except Exception as e:
                    self.logger.error(f"Recovery strategy {strategy.name} failed: {e}")
        
        return False
    
    def _log_error(self, error: ErrorInfo) -> None:
        """Log error with appropriate level"""
        
        if error.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(f"[{error.category.value.upper()}] {error.message}")
        elif error.severity == ErrorSeverity.HIGH:
            self.logger.error(f"[{error.category.value.upper()}] {error.message}")
        elif error.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(f"[{error.category.value.upper()}] {error.message}")
        else:
            self.logger.debug(f"[{error.category.value.upper()}] {error.message}")
        
        # Log stack trace for high severity errors
        if error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL] and error.stack_trace:
            self.logger.debug(f"Stack trace:\n{error.stack_trace}")
    
    def _emit_error_event(self, error: ErrorInfo) -> None:
        """Emit error event"""
        self.events.emit(EventType.ERROR_OCCURRED, {
            'category': error.category.value,
            'severity': error.severity.value,
            'message': error.message,
            'timestamp': error.timestamp,
            'recovery_attempted': error.recovery_attempted,
            'recovery_successful': error.recovery_successful,
            'context': error.context
        })
    
    def _is_circuit_broken(self, error_key: str) -> bool:
        """Check if circuit breaker is open for this error type"""
        circuit = self.circuit_breakers.get(error_key)
        if not circuit:
            return False
        
        if circuit['state'] == 'open':
            # Check if we should try half-open
            if time.time() - circuit['last_failure'] > circuit.get('timeout', 60):
                circuit['state'] = 'half-open'
                return False
            return True
        
        return False
    
    def _update_circuit_breaker(self, error_key: str, recovery_successful: bool) -> None:
        """Update circuit breaker state"""
        
        if error_key not in self.circuit_breakers:
            self.circuit_breakers[error_key] = {
                'state': 'closed',
                'failure_count': 0,
                'last_failure': 0,
                'threshold': 5,
                'timeout': 60
            }
        
        circuit = self.circuit_breakers[error_key]
        
        if recovery_successful:
            # Reset on success
            circuit['failure_count'] = 0
            circuit['state'] = 'closed'
        else:
            # Increment failure count
            circuit['failure_count'] += 1
            circuit['last_failure'] = time.time()
            
            # Open circuit if threshold exceeded
            if circuit['failure_count'] >= circuit['threshold']:
                circuit['state'] = 'open'
                self.logger.warning(f"Circuit breaker opened for: {error_key}")


# Decorator for error handling
def handle_errors(category: ErrorCategory = ErrorCategory.UNKNOWN, 
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                 fallback_result: Any = None,
                 retry_function: Callable = None):
    """Decorator to automatically handle errors in functions"""
    
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Try to get error handler from first argument (usually self)
                error_handler = None
                if args and hasattr(args[0], 'error_handler'):
                    error_handler = args[0].error_handler
                elif args and hasattr(args[0], 'events'):
                    # Create ad-hoc error handler
                    error_handler = ErrorHandler(args[0].events)
                
                if error_handler:
                    context = {
                        'function': func.__name__,
                        'args': str(args)[:100],
                        'kwargs': str(kwargs)[:100]
                    }
                    
                    if retry_function:
                        context['retry_function'] = lambda: retry_function(*args, **kwargs)
                    
                    success = error_handler.handle_error(e, category, severity, context)
                    if success:
                        # Try the function again if recovery was successful
                        try:
                            return func(*args, **kwargs)
                        except Exception:
                            pass  # Fall through to fallback
                
                # If no error handler or recovery failed, return fallback
                return fallback_result
        
        return wrapper
    return decorator