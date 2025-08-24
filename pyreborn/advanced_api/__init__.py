#!/usr/bin/env python3
"""
High-Level API Module
=====================

This module provides high-level, easy-to-use APIs for PyReborn that go beyond
the basic client functionality. It includes:

- Fluent builder pattern for client configuration
- Async/await support for modern Python applications  
- Decorator-based event handling
- High-level game actions
- Query builders for data retrieval

These APIs are inspired by modern Python frameworks and the analysis of
modern software design patterns.
"""

# Core API components
from .builder import ClientBuilder, PresetBuilder, CompressionType, EncryptionGen, LogLevel
from .async_client import AsyncClient, async_quick_connect
from .decorators import EventDecorator, DecoratedClient, create_decorated_client, with_decorators
from .extensible_client import ExtensibleClient
from .game_actions import GameActions, enhance_with_actions, ActionResult, ActionResponse

__all__ = [
    'ClientBuilder',
    'PresetBuilder',
    'CompressionType', 
    'EncryptionGen',
    'LogLevel',
    'AsyncClient',
    'async_quick_connect',
    'EventDecorator',
    'DecoratedClient',
    'create_decorated_client',
    'with_decorators',
    'ExtensibleClient',
    'GameActions',
    'enhance_with_actions',
    'ActionResult',
    'ActionResponse'
]