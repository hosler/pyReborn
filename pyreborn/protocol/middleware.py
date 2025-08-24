"""
Event Middleware System - Provides hooks and processing pipeline for events
"""

import logging
from typing import Callable, Any, Dict, List, Optional
from abc import ABC, abstractmethod
from enum import Enum

from .events import Event, EventType


class MiddlewareResult(Enum):
    """Results that middleware can return"""
    CONTINUE = "continue"    # Continue processing with current event
    STOP = "stop"           # Stop processing pipeline (event is consumed)
    MODIFIED = "modified"   # Event was modified, continue with new event
    ERROR = "error"         # Error occurred, stop processing


class IEventMiddleware(ABC):
    """Interface for event middleware"""
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """Middleware priority (higher = processed first)"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Middleware name for identification"""
        pass
    
    @abstractmethod
    def can_process(self, event: Event) -> bool:
        """Check if this middleware can process the event"""
        pass
    
    @abstractmethod
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        """Process the event and return (result, modified_event)"""
        pass
    
    def on_error(self, event: Event, error: Exception, context: Dict[str, Any]) -> None:
        """Called when an error occurs during processing"""
        pass


class EventMiddlewarePipeline:
    """Manages event middleware pipeline"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._middleware: List[IEventMiddleware] = []
        self._sorted = True  # Track if middleware list is sorted
        
    def add_middleware(self, middleware: IEventMiddleware) -> None:
        """Add middleware to the pipeline"""
        self._middleware.append(middleware)
        self._sorted = False  # Mark as needing sort
        self.logger.debug(f"Added middleware: {middleware.name} (priority: {middleware.priority})")
    
    def remove_middleware(self, middleware: IEventMiddleware) -> bool:
        """Remove middleware from the pipeline"""
        try:
            self._middleware.remove(middleware)
            self.logger.debug(f"Removed middleware: {middleware.name}")
            return True
        except ValueError:
            return False
    
    def get_middleware(self, name: str) -> Optional[IEventMiddleware]:
        """Get middleware by name"""
        for middleware in self._middleware:
            if middleware.name == name:
                return middleware
        return None
    
    def clear_middleware(self) -> None:
        """Clear all middleware"""
        count = len(self._middleware)
        self._middleware.clear()
        self.logger.debug(f"Cleared {count} middleware")
    
    def process_event(self, event: Event, context: Dict[str, Any] = None) -> Optional[Event]:
        """Process event through middleware pipeline
        
        Returns:
            Modified event if processing should continue, None if event was consumed
        """
        if not self._middleware:
            return event
        
        # Ensure middleware is sorted by priority
        if not self._sorted:
            self._middleware.sort(key=lambda m: m.priority, reverse=True)
            self._sorted = True
        
        current_event = event
        processing_context = context or {}
        
        for middleware in self._middleware:
            try:
                # Check if middleware can process this event
                if not middleware.can_process(current_event):
                    continue
                
                # Process the event
                result, modified_event = middleware.process(current_event, processing_context)
                
                if result == MiddlewareResult.CONTINUE:
                    # Continue with original event
                    continue
                elif result == MiddlewareResult.MODIFIED:
                    # Continue with modified event
                    current_event = modified_event
                    continue
                elif result == MiddlewareResult.STOP:
                    # Stop processing, event consumed
                    self.logger.debug(f"Event consumed by middleware: {middleware.name}")
                    return None
                elif result == MiddlewareResult.ERROR:
                    # Error occurred, stop processing
                    self.logger.error(f"Middleware error in {middleware.name}")
                    return None
                
            except Exception as e:
                self.logger.error(f"Error in middleware {middleware.name}: {e}")
                try:
                    middleware.on_error(current_event, e, processing_context)
                except:
                    pass  # Ignore errors in error handler
                # Continue processing with other middleware
                continue
        
        return current_event
    
    def get_middleware_info(self) -> List[Dict[str, Any]]:
        """Get information about registered middleware"""
        return [
            {
                'name': mw.name,
                'priority': mw.priority,
                'type': type(mw).__name__
            }
            for mw in self._middleware
        ]


class LoggingMiddleware(IEventMiddleware):
    """Example middleware that logs all events"""
    
    def __init__(self, log_level: int = logging.DEBUG, include_data: bool = False):
        self.log_level = log_level
        self.include_data = include_data
        self.logger = logging.getLogger(f"{__name__}.LoggingMiddleware")
    
    @property
    def priority(self) -> int:
        return 1000  # High priority to log early
    
    @property
    def name(self) -> str:
        return "logging_middleware"
    
    def can_process(self, event: Event) -> bool:
        return True  # Can process all events
    
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        if self.include_data:
            self.logger.log(self.log_level, f"Event: {event.type} with data: {event.data}")
        else:
            self.logger.log(self.log_level, f"Event: {event.type}")
        
        return MiddlewareResult.CONTINUE, event
    
    def on_error(self, event: Event, error: Exception, context: Dict[str, Any]) -> None:
        self.logger.error(f"Error processing event {event.type}: {error}")


class FilterMiddleware(IEventMiddleware):
    """Middleware that can filter out events based on criteria"""
    
    def __init__(self, filter_func: Callable[[Event], bool], name: str = "filter_middleware"):
        self.filter_func = filter_func
        self._name = name
        self.logger = logging.getLogger(f"{__name__}.FilterMiddleware")
    
    @property
    def priority(self) -> int:
        return 900  # High priority to filter early
    
    @property
    def name(self) -> str:
        return self._name
    
    def can_process(self, event: Event) -> bool:
        return True
    
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        if self.filter_func(event):
            return MiddlewareResult.CONTINUE, event
        else:
            self.logger.debug(f"Filtered out event: {event.type}")
            return MiddlewareResult.STOP, event


class TransformMiddleware(IEventMiddleware):
    """Middleware that can transform events"""
    
    def __init__(self, transform_func: Callable[[Event], Event], 
                 event_types: List[EventType] = None, name: str = "transform_middleware"):
        self.transform_func = transform_func
        self.event_types = set(event_types) if event_types else None
        self._name = name
        self.logger = logging.getLogger(f"{__name__}.TransformMiddleware")
    
    @property
    def priority(self) -> int:
        return 500  # Medium priority
    
    @property
    def name(self) -> str:
        return self._name
    
    def can_process(self, event: Event) -> bool:
        if self.event_types:
            return event.type in self.event_types
        return True
    
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        try:
            transformed_event = self.transform_func(event)
            if transformed_event is not event:
                self.logger.debug(f"Transformed event: {event.type}")
                return MiddlewareResult.MODIFIED, transformed_event
            else:
                return MiddlewareResult.CONTINUE, event
        except Exception as e:
            self.logger.error(f"Error transforming event {event.type}: {e}")
            return MiddlewareResult.ERROR, event


class ConditionalMiddleware(IEventMiddleware):
    """Middleware that processes events based on conditions"""
    
    def __init__(self, condition_func: Callable[[Event, Dict[str, Any]], bool],
                 action_func: Callable[[Event, Dict[str, Any]], tuple[MiddlewareResult, Event]],
                 name: str = "conditional_middleware", priority: int = 100):
        self.condition_func = condition_func
        self.action_func = action_func
        self._name = name
        self._priority = priority
        self.logger = logging.getLogger(f"{__name__}.ConditionalMiddleware")
    
    @property
    def priority(self) -> int:
        return self._priority
    
    @property
    def name(self) -> str:
        return self._name
    
    def can_process(self, event: Event) -> bool:
        return True
    
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        if self.condition_func(event, context):
            return self.action_func(event, context)
        return MiddlewareResult.CONTINUE, event


class StatisticsMiddleware(IEventMiddleware):
    """Middleware that collects event statistics"""
    
    def __init__(self, name: str = "statistics_middleware"):
        self._name = name
        self.logger = logging.getLogger(f"{__name__}.StatisticsMiddleware")
        self.event_counts: Dict[EventType, int] = {}
        self.total_events = 0
        self.error_count = 0
    
    @property
    def priority(self) -> int:
        return 50  # Low priority to capture final statistics
    
    @property
    def name(self) -> str:
        return self._name
    
    def can_process(self, event: Event) -> bool:
        return True
    
    def process(self, event: Event, context: Dict[str, Any]) -> tuple[MiddlewareResult, Event]:
        self.total_events += 1
        self.event_counts[event.type] = self.event_counts.get(event.type, 0) + 1
        return MiddlewareResult.CONTINUE, event
    
    def on_error(self, event: Event, error: Exception, context: Dict[str, Any]) -> None:
        self.error_count += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get collected statistics"""
        return {
            'total_events': self.total_events,
            'error_count': self.error_count,
            'event_counts': dict(self.event_counts),
            'unique_event_types': len(self.event_counts)
        }
    
    def reset_statistics(self) -> None:
        """Reset all statistics"""
        self.event_counts.clear()
        self.total_events = 0
        self.error_count = 0