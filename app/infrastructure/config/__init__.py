"""Пакет app.infrastructure.config."""
from app.infrastructure.config.config_loader import load
from app.infrastructure.config.module_resolver import ModuleResolver

__all__ = ['ModuleResolver', 'load']
