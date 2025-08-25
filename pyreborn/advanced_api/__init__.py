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

# Simplified API components (removed builders, decorators, game actions)
from .async_client import AsyncClient, async_quick_connect

__all__ = [
    'AsyncClient',
    'async_quick_connect'
]