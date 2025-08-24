"""
Connection resilience system with auto-reconnect and error recovery
"""

import time
import logging
import threading
from typing import Optional, Callable, Dict, Any
from enum import Enum
from dataclasses import dataclass

from ..session.events import EventManager, EventType
from ..config.client_config import ClientConfig


class ConnectionState(Enum):
    """Connection state enumeration"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class ReconnectStrategy(Enum):
    """Reconnection strategy types"""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_INTERVAL = "fixed_interval"
    IMMEDIATE = "immediate"


@dataclass
class ReconnectPolicy:
    """Reconnection policy configuration"""
    enabled: bool = True
    max_attempts: int = 5
    strategy: ReconnectStrategy = ReconnectStrategy.EXPONENTIAL_BACKOFF
    initial_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    reset_on_success: bool = True


@dataclass
class ConnectionHealthMetrics:
    """Connection health tracking metrics"""
    connection_attempts: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    reconnection_attempts: int = 0
    total_downtime: float = 0.0
    last_connection_time: Optional[float] = None
    last_disconnection_time: Optional[float] = None
    average_connection_duration: float = 0.0


class ConnectionResilientManager:
    """Manages connection resilience and auto-reconnect functionality"""
    
    def __init__(self, config: ClientConfig, event_manager: EventManager):
        self.config = config
        self.events = event_manager
        self.logger = logging.getLogger(__name__)
        
        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.connection_callback: Optional[Callable[[], bool]] = None
        self.disconnect_callback: Optional[Callable[[], None]] = None
        
        # Reconnection management
        self.reconnect_policy = ReconnectPolicy()
        self.reconnect_thread: Optional[threading.Thread] = None
        self.reconnect_stop_event = threading.Event()
        self.current_attempt = 0
        
        # Health metrics
        self.metrics = ConnectionHealthMetrics()
        
        # Event subscriptions
        self.events.subscribe(EventType.DISCONNECTED, self._on_disconnected)
        self.events.subscribe(EventType.CONNECTION_FAILED, self._on_connection_failed)
        
    def set_connection_callbacks(self, connect_func: Callable[[], bool], 
                               disconnect_func: Callable[[], None]) -> None:
        """Set connection and disconnection callback functions"""
        self.connection_callback = connect_func
        self.disconnect_callback = disconnect_func
    
    def set_reconnect_policy(self, policy: ReconnectPolicy) -> None:
        """Update reconnection policy"""
        self.reconnect_policy = policy
        self.logger.info(f"Updated reconnect policy: {policy}")
    
    def start_connection(self) -> bool:
        """Start initial connection with resilience"""
        if self.state in [ConnectionState.CONNECTING, ConnectionState.RECONNECTING]:
            self.logger.warning("Connection already in progress")
            return False
        
        self.state = ConnectionState.CONNECTING
        self.metrics.connection_attempts += 1
        
        if self._attempt_connection():
            self._on_connection_success()
            return True
        else:
            self._on_connection_failure()
            return False
    
    def stop_connection(self) -> None:
        """Stop connection and disable auto-reconnect"""
        self.logger.info("Stopping connection and disabling auto-reconnect")
        
        # Stop reconnection attempts
        self._stop_reconnect_thread()
        
        # Disconnect if connected
        if self.state == ConnectionState.CONNECTED:
            self._perform_disconnect()
        
        self.state = ConnectionState.DISCONNECTED
    
    def force_reconnect(self) -> bool:
        """Force immediate reconnection attempt"""
        self.logger.info("Forcing immediate reconnection")
        
        # Stop any existing reconnection
        self._stop_reconnect_thread()
        
        # Disconnect if connected
        if self.state == ConnectionState.CONNECTED:
            self._perform_disconnect()
        
        # Reset attempt counter for immediate retry
        self.current_attempt = 0
        return self._start_reconnection()
    
    def get_connection_state(self) -> ConnectionState:
        """Get current connection state"""
        return self.state
    
    def get_metrics(self) -> ConnectionHealthMetrics:
        """Get connection health metrics"""
        return self.metrics
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy"""
        if self.state != ConnectionState.CONNECTED:
            return False
        
        # Check if we've had too many recent failures
        if self.metrics.failed_connections > 0:
            success_rate = self.metrics.successful_connections / (
                self.metrics.successful_connections + self.metrics.failed_connections
            )
            return success_rate > 0.7  # 70% success rate threshold
        
        return True
    
    def _attempt_connection(self) -> bool:
        """Attempt to establish connection"""
        if not self.connection_callback:
            self.logger.error("No connection callback set")
            return False
        
        try:
            self.logger.debug("Attempting connection...")
            start_time = time.time()
            
            success = self.connection_callback()
            
            if success:
                self.metrics.last_connection_time = time.time()
                connection_time = time.time() - start_time
                self.logger.info(f"Connection established in {connection_time:.2f}s")
                return True
            else:
                self.logger.warning("Connection attempt failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Connection attempt error: {e}")
            return False
    
    def _perform_disconnect(self) -> None:
        """Perform disconnection"""
        if self.disconnect_callback:
            try:
                self.disconnect_callback()
            except Exception as e:
                self.logger.error(f"Disconnect error: {e}")
        
        if self.metrics.last_connection_time:
            duration = time.time() - self.metrics.last_connection_time
            # Update average connection duration
            total_connections = self.metrics.successful_connections
            if total_connections > 0:
                self.metrics.average_connection_duration = (
                    (self.metrics.average_connection_duration * (total_connections - 1) + duration) 
                    / total_connections
                )
    
    def _on_connection_success(self) -> None:
        """Handle successful connection"""
        self.state = ConnectionState.CONNECTED
        self.metrics.successful_connections += 1
        
        # Reset attempt counter on successful connection
        if self.reconnect_policy.reset_on_success:
            self.current_attempt = 0
        
        self.events.emit(EventType.CONNECTED, {
            'attempt': self.current_attempt,
            'metrics': self.metrics
        })
        
        self.logger.info("Connection established successfully")
    
    def _on_connection_failure(self) -> None:
        """Handle connection failure"""
        self.state = ConnectionState.FAILED
        self.metrics.failed_connections += 1
        
        self.events.emit(EventType.CONNECTION_FAILED, {
            'attempt': self.current_attempt,
            'metrics': self.metrics
        })
        
        # Start reconnection if enabled
        if self.reconnect_policy.enabled:
            self._start_reconnection()
    
    def _on_disconnected(self, event) -> None:
        """Handle disconnection event"""
        if self.state == ConnectionState.CONNECTED:
            self.metrics.last_disconnection_time = time.time()
            self.logger.warning("Connection lost - starting reconnection")
            
            if self.reconnect_policy.enabled:
                self._start_reconnection()
    
    def _on_connection_failed(self, event) -> None:
        """Handle connection failed event"""
        self.logger.debug(f"Connection failed event received: {event}")
    
    def _start_reconnection(self) -> bool:
        """Start reconnection thread"""
        if self.reconnect_thread and self.reconnect_thread.is_alive():
            self.logger.debug("Reconnection already in progress")
            return False
        
        if self.current_attempt >= self.reconnect_policy.max_attempts:
            self.logger.error(f"Max reconnection attempts ({self.reconnect_policy.max_attempts}) exceeded")
            self.state = ConnectionState.FAILED
            return False
        
        self.state = ConnectionState.RECONNECTING
        self.reconnect_stop_event.clear()
        
        self.reconnect_thread = threading.Thread(
            target=self._reconnection_loop,
            name="ConnectionReconnect",
            daemon=True
        )
        self.reconnect_thread.start()
        
        return True
    
    def _stop_reconnect_thread(self) -> None:
        """Stop reconnection thread"""
        if self.reconnect_thread and self.reconnect_thread.is_alive():
            self.reconnect_stop_event.set()
            self.reconnect_thread.join(timeout=5.0)
            if self.reconnect_thread.is_alive():
                self.logger.warning("Reconnection thread did not stop gracefully")
    
    def _reconnection_loop(self) -> None:
        """Reconnection loop running in separate thread"""
        self.logger.info("Starting reconnection loop")
        
        while (not self.reconnect_stop_event.is_set() and 
               self.current_attempt < self.reconnect_policy.max_attempts):
            
            self.current_attempt += 1
            self.metrics.reconnection_attempts += 1
            
            # Calculate delay based on strategy
            delay = self._calculate_reconnect_delay()
            
            self.logger.info(f"Reconnection attempt {self.current_attempt}/{self.reconnect_policy.max_attempts} "
                           f"in {delay:.1f}s")
            
            # Wait for delay (with early exit if stopped)
            if self.reconnect_stop_event.wait(delay):
                break
            
            # Attempt reconnection
            if self._attempt_connection():
                self._on_connection_success()
                return
            else:
                self.logger.warning(f"Reconnection attempt {self.current_attempt} failed")
        
        # All attempts failed
        if self.current_attempt >= self.reconnect_policy.max_attempts:
            self.logger.error("All reconnection attempts failed")
            self.state = ConnectionState.FAILED
            self.events.emit(EventType.CONNECTION_FAILED, {
                'reason': 'max_attempts_exceeded',
                'attempts': self.current_attempt
            })
    
    def _calculate_reconnect_delay(self) -> float:
        """Calculate reconnection delay based on strategy"""
        if self.reconnect_policy.strategy == ReconnectStrategy.IMMEDIATE:
            return 0.0
        
        elif self.reconnect_policy.strategy == ReconnectStrategy.FIXED_INTERVAL:
            return self.reconnect_policy.initial_delay
        
        elif self.reconnect_policy.strategy == ReconnectStrategy.LINEAR_BACKOFF:
            delay = self.reconnect_policy.initial_delay * self.current_attempt
            return min(delay, self.reconnect_policy.max_delay)
        
        elif self.reconnect_policy.strategy == ReconnectStrategy.EXPONENTIAL_BACKOFF:
            delay = self.reconnect_policy.initial_delay * (
                self.reconnect_policy.backoff_multiplier ** (self.current_attempt - 1)
            )
            return min(delay, self.reconnect_policy.max_delay)
        
        else:
            return self.reconnect_policy.initial_delay
    
    def cleanup(self) -> None:
        """Clean up resources"""
        self.logger.debug("Cleaning up connection resilience manager")
        
        # Unsubscribe from events
        self.events.unsubscribe(EventType.DISCONNECTED, self._on_disconnected)
        self.events.unsubscribe(EventType.CONNECTION_FAILED, self._on_connection_failed)
        
        # Stop reconnection
        self._stop_reconnect_thread()
        
        # Disconnect if connected
        if self.state == ConnectionState.CONNECTED:
            self._perform_disconnect()