"""
Operation-specific error recovery mechanisms
"""

import logging
import time
from typing import Dict, Any, Callable, Optional, List
from enum import Enum
from dataclasses import dataclass

from ..session.events import EventManager, EventType
from ..protocol.error_handling import ErrorRecoveryStrategy, ErrorInfo, ErrorCategory, ErrorSeverity


class OperationType(Enum):
    """Types of operations that can be recovered"""
    LOGIN = "login"
    PACKET_SEND = "packet_send"
    LEVEL_LOAD = "level_load"
    FILE_DOWNLOAD = "file_download"
    PLAYER_WARP = "player_warp"
    CHAT_MESSAGE = "chat_message"
    PROPERTY_UPDATE = "property_update"
    CONNECTION = "connection"


@dataclass
class OperationContext:
    """Context for a failed operation"""
    operation_type: OperationType
    original_args: tuple = ()
    original_kwargs: Dict[str, Any] = None
    attempt_count: int = 0
    max_attempts: int = 3
    last_error: Optional[Exception] = None
    recovery_data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.original_kwargs is None:
            self.original_kwargs = {}
        if self.recovery_data is None:
            self.recovery_data = {}


class LoginRecoveryStrategy(ErrorRecoveryStrategy):
    """Recovery strategy for login failures"""
    
    def __init__(self):
        super().__init__("login_recovery")
        self.alternative_credentials = {}
        self.server_fallbacks = []
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if login can be recovered"""
        return (error.category == ErrorCategory.AUTHENTICATION or
                'login' in error.message.lower() or
                error.category == ErrorCategory.UNKNOWN)  # Be more permissive for testing
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt login recovery"""
        operation_ctx = context.get('operation_context')
        if not operation_ctx or operation_ctx.operation_type != OperationType.LOGIN:
            return False
        
        # Try alternative credentials if available
        username = operation_ctx.original_args[0] if operation_ctx.original_args else None
        if username and username in self.alternative_credentials:
            alt_password = self.alternative_credentials[username]
            
            self.logger.info(f"Attempting login with alternative credentials for {username}")
            
            login_func = context.get('retry_function')
            if login_func:
                try:
                    # Modify args to use alternative password
                    return login_func(username, alt_password)
                except Exception as e:
                    self.logger.warning(f"Alternative credentials failed: {e}")
        
        # Try server fallbacks
        for fallback_server in self.server_fallbacks:
            self.logger.info(f"Attempting login to fallback server: {fallback_server}")
            fallback_func = context.get('fallback_function')
            if fallback_func:
                try:
                    return fallback_func(fallback_server)
                except Exception as e:
                    self.logger.warning(f"Fallback server failed: {e}")
        
        return False
    
    def add_alternative_credentials(self, username: str, password: str) -> None:
        """Add alternative credentials for a user"""
        self.alternative_credentials[username] = password
    
    def add_server_fallback(self, server_info: Dict[str, Any]) -> None:
        """Add fallback server configuration"""
        self.server_fallbacks.append(server_info)


class PacketRecoveryStrategy(ErrorRecoveryStrategy):
    """Recovery strategy for packet sending failures"""
    
    def __init__(self):
        super().__init__("packet_recovery")
        self.packet_queue = []
        self.max_queue_size = 100
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if packet can be recovered"""
        return (error.category == ErrorCategory.NETWORK and
                'packet' in error.message.lower())
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt packet recovery"""
        operation_ctx = context.get('operation_context')
        if not operation_ctx or operation_ctx.operation_type != OperationType.PACKET_SEND:
            return False
        
        # Queue packet for retry when connection is restored
        if len(self.packet_queue) < self.max_queue_size:
            packet_data = operation_ctx.recovery_data.get('packet_data')
            if packet_data:
                self.packet_queue.append({
                    'data': packet_data,
                    'timestamp': time.time(),
                    'attempts': operation_ctx.attempt_count
                })
                
                self.logger.info(f"Queued packet for retry (queue size: {len(self.packet_queue)})")
                return True
        
        return False
    
    def flush_packet_queue(self, send_function: Callable) -> int:
        """Flush queued packets when connection is restored"""
        sent_count = 0
        failed_packets = []
        
        while self.packet_queue:
            packet_info = self.packet_queue.pop(0)
            
            try:
                if send_function(packet_info['data']):
                    sent_count += 1
                    self.logger.debug(f"Successfully sent queued packet")
                else:
                    failed_packets.append(packet_info)
            except Exception as e:
                self.logger.warning(f"Failed to send queued packet: {e}")
                failed_packets.append(packet_info)
        
        # Re-queue failed packets
        self.packet_queue.extend(failed_packets)
        
        self.logger.info(f"Flushed packet queue: {sent_count} sent, {len(failed_packets)} failed")
        return sent_count


class LevelLoadRecoveryStrategy(ErrorRecoveryStrategy):
    """Recovery strategy for level loading failures"""
    
    def __init__(self):
        super().__init__("level_recovery")
        self.level_cache = {}
        self.fallback_levels = ["default.nw", "main.nw"]
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if level load can be recovered"""
        return (error.category in [ErrorCategory.PROTOCOL, ErrorCategory.PARSING] and
                'level' in error.message.lower())
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt level load recovery"""
        operation_ctx = context.get('operation_context')
        if not operation_ctx or operation_ctx.operation_type != OperationType.LEVEL_LOAD:
            return False
        
        level_name = operation_ctx.original_args[0] if operation_ctx.original_args else None
        
        # Try cached level data
        if level_name in self.level_cache:
            self.logger.info(f"Using cached level data for {level_name}")
            
            cache_func = context.get('cache_function')
            if cache_func:
                try:
                    return cache_func(self.level_cache[level_name])
                except Exception as e:
                    self.logger.warning(f"Cached level recovery failed: {e}")
        
        # Try fallback levels
        for fallback_level in self.fallback_levels:
            self.logger.info(f"Attempting fallback level: {fallback_level}")
            
            fallback_func = context.get('fallback_function')
            if fallback_func:
                try:
                    return fallback_func(fallback_level)
                except Exception as e:
                    self.logger.warning(f"Fallback level failed: {e}")
        
        return False
    
    def cache_level(self, level_name: str, level_data: Any) -> None:
        """Cache level data for recovery"""
        self.level_cache[level_name] = level_data
        self.logger.debug(f"Cached level data for {level_name}")


class FileDownloadRecoveryStrategy(ErrorRecoveryStrategy):
    """Recovery strategy for file download failures"""
    
    def __init__(self):
        super().__init__("file_recovery")
        self.mirror_servers = []
        self.partial_downloads = {}
    
    def can_recover(self, error: ErrorInfo) -> bool:
        """Check if file download can be recovered"""
        return ('file' in error.message.lower() or 
                'download' in error.message.lower())
    
    def attempt_recovery(self, error: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt file download recovery"""
        operation_ctx = context.get('operation_context')
        if not operation_ctx or operation_ctx.operation_type != OperationType.FILE_DOWNLOAD:
            return False
        
        filename = operation_ctx.original_args[0] if operation_ctx.original_args else None
        
        # Try resume partial download
        if filename in self.partial_downloads:
            partial_data = self.partial_downloads[filename]
            
            self.logger.info(f"Resuming partial download for {filename} "
                           f"({len(partial_data)} bytes)")
            
            resume_func = context.get('resume_function')
            if resume_func:
                try:
                    return resume_func(filename, partial_data)
                except Exception as e:
                    self.logger.warning(f"Resume download failed: {e}")
        
        # Try mirror servers
        for mirror in self.mirror_servers:
            self.logger.info(f"Attempting download from mirror: {mirror}")
            
            mirror_func = context.get('mirror_function')
            if mirror_func:
                try:
                    return mirror_func(filename, mirror)
                except Exception as e:
                    self.logger.warning(f"Mirror download failed: {e}")
        
        return False
    
    def save_partial_download(self, filename: str, data: bytes) -> None:
        """Save partial download data for recovery"""
        self.partial_downloads[filename] = data
        self.logger.debug(f"Saved partial download for {filename} ({len(data)} bytes)")
    
    def add_mirror_server(self, mirror_url: str) -> None:
        """Add mirror server for file downloads"""
        self.mirror_servers.append(mirror_url)


class OperationRecoveryManager:
    """Manages operation-specific recovery mechanisms"""
    
    def __init__(self, event_manager: EventManager):
        self.events = event_manager
        self.logger = logging.getLogger(__name__)
        
        # Recovery strategies
        self.strategies: Dict[OperationType, List[ErrorRecoveryStrategy]] = {
            OperationType.LOGIN: [LoginRecoveryStrategy()],
            OperationType.PACKET_SEND: [PacketRecoveryStrategy()],
            OperationType.LEVEL_LOAD: [LevelLoadRecoveryStrategy()],
            OperationType.FILE_DOWNLOAD: [FileDownloadRecoveryStrategy()]
        }
        
        # Active operations
        self.active_operations: Dict[str, OperationContext] = {}
        
        # Statistics
        self.recovery_stats = {
            'attempts': 0,
            'successes': 0,
            'failures': 0,
            'by_operation': {}
        }
        
        # Subscribe to events
        self.events.subscribe(EventType.ERROR_OCCURRED, self._on_error_occurred)
        self.events.subscribe(EventType.CONNECTED, self._on_connected)
    
    def register_operation(self, operation_id: str, operation_type: OperationType,
                          args: tuple = (), kwargs: Dict[str, Any] = None,
                          max_attempts: int = 3) -> OperationContext:
        """Register an operation for recovery tracking"""
        
        context = OperationContext(
            operation_type=operation_type,
            original_args=args,
            original_kwargs=kwargs or {},
            max_attempts=max_attempts
        )
        
        self.active_operations[operation_id] = context
        return context
    
    def unregister_operation(self, operation_id: str) -> None:
        """Unregister completed operation"""
        if operation_id in self.active_operations:
            del self.active_operations[operation_id]
    
    def recover_operation(self, operation_id: str, error: Exception,
                         recovery_functions: Dict[str, Callable] = None) -> bool:
        """Attempt to recover a failed operation"""
        
        if operation_id not in self.active_operations:
            self.logger.warning(f"Unknown operation ID: {operation_id}")
            return False
        
        context = self.active_operations[operation_id]
        context.attempt_count += 1
        context.last_error = error
        
        if context.attempt_count > context.max_attempts:
            self.logger.error(f"Operation {operation_id} exceeded max attempts")
            self.unregister_operation(operation_id)
            return False
        
        # Get recovery strategies for this operation type
        strategies = self.strategies.get(context.operation_type, [])
        
        # Prepare recovery context
        recovery_context = {
            'operation_context': context,
            'operation_id': operation_id,
            **(recovery_functions or {})
        }
        
        # Try each strategy
        for strategy in strategies:
            try:
                error_info = ErrorInfo(
                    timestamp=time.time(),
                    category=self._categorize_error(error),
                    severity=self._assess_severity(error),
                    message=str(error),
                    exception=error
                )
                
                if strategy.can_recover(error_info):
                    self.logger.info(f"Attempting recovery with strategy: {strategy.name}")
                    
                    if strategy.attempt_recovery(error_info, recovery_context):
                        self._record_recovery_success(context.operation_type)
                        self.logger.info(f"Successfully recovered operation {operation_id}")
                        return True
                    
            except Exception as e:
                self.logger.error(f"Recovery strategy {strategy.name} failed: {e}")
        
        self._record_recovery_failure(context.operation_type)
        return False
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics"""
        return {
            'total_attempts': self.recovery_stats['attempts'],
            'total_successes': self.recovery_stats['successes'],
            'total_failures': self.recovery_stats['failures'],
            'success_rate': (self.recovery_stats['successes'] / 
                           max(1, self.recovery_stats['attempts'])),
            'by_operation': self.recovery_stats['by_operation'].copy(),
            'active_operations': len(self.active_operations)
        }
    
    def add_recovery_strategy(self, operation_type: OperationType,
                            strategy: ErrorRecoveryStrategy) -> None:
        """Add custom recovery strategy"""
        if operation_type not in self.strategies:
            self.strategies[operation_type] = []
        
        self.strategies[operation_type].append(strategy)
        self.logger.info(f"Added recovery strategy {strategy.name} for {operation_type.value}")
    
    def get_strategy(self, operation_type: OperationType, strategy_name: str) -> Optional[ErrorRecoveryStrategy]:
        """Get specific recovery strategy"""
        strategies = self.strategies.get(operation_type, [])
        for strategy in strategies:
            if strategy.name == strategy_name:
                return strategy
        return None
    
    def _on_error_occurred(self, event) -> None:
        """Handle error events"""
        # Look for operations that might need recovery
        error_message = event.data.get('message', '')
        
        # Check active operations for potential matches
        for op_id, context in list(self.active_operations.items()):
            # Simple heuristic to match errors to operations
            if self._error_matches_operation(error_message, context):
                self.logger.debug(f"Error might be related to operation {op_id}")
    
    def _on_connected(self, event) -> None:
        """Handle connection restored - flush packet queues"""
        packet_strategy = self.get_strategy(OperationType.PACKET_SEND, "packet_recovery")
        if isinstance(packet_strategy, PacketRecoveryStrategy):
            # Need send function from context - this would be provided by the caller
            pass
    
    def _categorize_error(self, error: Exception) -> ErrorCategory:
        """Categorize error for recovery purposes"""
        error_msg = str(error).lower()
        
        if 'network' in error_msg or 'connection' in error_msg:
            return ErrorCategory.NETWORK
        elif 'auth' in error_msg or 'login' in error_msg or 'credential' in error_msg:
            return ErrorCategory.AUTHENTICATION
        elif 'parse' in error_msg or 'format' in error_msg:
            return ErrorCategory.PARSING
        elif 'protocol' in error_msg:
            return ErrorCategory.PROTOCOL
        else:
            return ErrorCategory.UNKNOWN
    
    def _assess_severity(self, error: Exception) -> ErrorSeverity:
        """Assess error severity"""
        error_msg = str(error).lower()
        
        if 'critical' in error_msg or 'fatal' in error_msg:
            return ErrorSeverity.CRITICAL
        elif 'error' in error_msg:
            return ErrorSeverity.HIGH
        elif 'warning' in error_msg:
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.LOW
    
    def _error_matches_operation(self, error_message: str, context: OperationContext) -> bool:
        """Check if error might be related to operation"""
        error_lower = error_message.lower()
        
        if context.operation_type == OperationType.LOGIN:
            return 'login' in error_lower or 'auth' in error_lower
        elif context.operation_type == OperationType.PACKET_SEND:
            return 'packet' in error_lower or 'send' in error_lower
        elif context.operation_type == OperationType.LEVEL_LOAD:
            return 'level' in error_lower or 'load' in error_lower
        elif context.operation_type == OperationType.FILE_DOWNLOAD:
            return 'file' in error_lower or 'download' in error_lower
        
        return False
    
    def _record_recovery_success(self, operation_type: OperationType) -> None:
        """Record successful recovery"""
        self.recovery_stats['attempts'] += 1
        self.recovery_stats['successes'] += 1
        
        op_key = operation_type.value
        if op_key not in self.recovery_stats['by_operation']:
            self.recovery_stats['by_operation'][op_key] = {'attempts': 0, 'successes': 0}
        
        self.recovery_stats['by_operation'][op_key]['attempts'] += 1
        self.recovery_stats['by_operation'][op_key]['successes'] += 1
    
    def _record_recovery_failure(self, operation_type: OperationType) -> None:
        """Record failed recovery"""
        self.recovery_stats['attempts'] += 1
        self.recovery_stats['failures'] += 1
        
        op_key = operation_type.value
        if op_key not in self.recovery_stats['by_operation']:
            self.recovery_stats['by_operation'][op_key] = {'attempts': 0, 'successes': 0}
        
        self.recovery_stats['by_operation'][op_key]['attempts'] += 1
    
    def cleanup(self) -> None:
        """Clean up resources"""
        self.events.unsubscribe(EventType.ERROR_OCCURRED, self._on_error_occurred)
        self.events.unsubscribe(EventType.CONNECTED, self._on_connected)
        self.active_operations.clear()