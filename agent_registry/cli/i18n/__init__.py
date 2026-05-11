"""
CLI Internationalization (i18n) Module

Simple YAML-based i18n system for CLI messages.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class I18n:
    """
    Internationalization manager for CLI
    
    Features:
        - YAML-based language files
        - Dot-notation key access (e.g., 'cli.intro')
        - Default language fallback
        - Dynamic language switching
    """
    
    _instance: Optional['I18n'] = None
    _lang_dir: Path = Path(__file__).parent
    _current_lang: str = 'en'
    _translations: Dict[str, Dict[str, Any]] = {}
    _loaded: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self._load_language('en')
            self._loaded = True
    
    @classmethod
    def set_language(cls, lang: str) -> None:
        """Switch to a different language"""
        cls._current_lang = lang
        cls()._load_language(lang)
    
    @classmethod
    def get_language(cls) -> str:
        """Get current language code"""
        return cls._current_lang
    
    def _load_language(self, lang: str) -> None:
        """Load language file from YAML"""
        lang_file = self._lang_dir / f'{lang}.yaml'
        
        if not lang_file.exists():
            if lang != 'en':
                lang_file = self._lang_dir / 'en.yaml'
                if not lang_file.exists():
                    return
            else:
                return
        
        if not HAS_YAML:
            return
        
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                self._translations[lang] = yaml.safe_load(f) or {}
        except Exception:
            self._translations[lang] = {}
    
    @classmethod
    def get(cls, key: str, default: Optional[str] = None) -> str:
        """
        Get translation by dot-notation key
        
        Args:
            key: Dot-notation key (e.g., 'cli.intro', 'errors.not_found')
            default: Default value if key not found
        
        Returns:
            Translated string or default/key itself
        """
        instance = cls()
        
        translations = instance._translations.get(instance._current_lang, {})
        
        parts = key.split('.')
        value = translations
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        
        if value is None and instance._current_lang != 'en':
            value = cls._get_from_lang('en', key)
        
        if value is None:
            return default if default is not None else key
        
        return str(value)
    
    @classmethod
    def _get_from_lang(cls, lang: str, key: str) -> Optional[str]:
        """Get translation from specific language"""
        instance = cls()
        translations = instance._translations.get(lang, {})
        
        parts = key.split('.')
        value = translations
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        
        return str(value) if value is not None else None
    
    @classmethod
    def format(cls, key: str, **kwargs) -> str:
        """
        Get translation with variable interpolation
        
        Args:
            key: Translation key
            **kwargs: Variables to interpolate
        
        Returns:
            Formatted string
        """
        template = cls.get(key)
        
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template


def t(key: str, default: Optional[str] = None) -> str:
    """Shorthand for I18n.get()"""
    return I18n.get(key, default)


def tf(key: str, **kwargs) -> str:
    """Shorthand for I18n.format()"""
    return I18n.format(key, **kwargs)