"""
Event Manager
============

Handles all PyReborn event subscriptions and callbacks.
Extracted from main game class for cleaner architecture.
"""

import logging
from typing import Callable, Dict

from pyreborn.core.events import EventType

logger = logging.getLogger(__name__)


class EventManager:
    """Manages event subscriptions and callbacks"""
    
    def __init__(self, client):
        self.client = client
        self.callbacks: Dict[EventType, Callable] = {}
        
    def setup_callbacks(self, callbacks: Dict[EventType, Callable]):
        """Setup event callbacks"""
        self.callbacks = callbacks
        
    def subscribe_all(self):
        """Subscribe to all configured events"""
        if not self.client:
            return
            
        events = self.client.events
        
        for event_type, callback in self.callbacks.items():
            events.subscribe(event_type, callback)
            
        logger.debug(f"Subscribed to {len(self.callbacks)} events")
        
    def unsubscribe_all(self):
        """Unsubscribe from all events"""
        if not self.client:
            return
            
        events = self.client.events
        
        for event_type, callback in self.callbacks.items():
            events.unsubscribe(event_type, callback)
            
        logger.debug(f"Unsubscribed from {len(self.callbacks)} events")