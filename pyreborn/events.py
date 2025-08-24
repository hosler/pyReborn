#!/usr/bin/env python3
"""
PyReborn Events
===============

Simple event system for PyReborn. 
"""

# Re-export the event system with simplified imports
from .core.events import EventType

# Make them available at the top level
__all__ = ['EventType']