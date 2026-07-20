"""Configuration layer - configuration management and module resolution."""
from scud_lgtu.infrastructure.config.config_loader import load
from scud_lgtu.infrastructure.config.module_resolver import ModuleResolver

__all__ = ['load', 'ModuleResolver']
