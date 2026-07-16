"""Pytest configuration for scud_lgtu tests."""
import sys
import os

# Add the parent directory to the path so we can import scud_lgtu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
