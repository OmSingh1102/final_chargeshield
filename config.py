import os
import re
import yaml


class Config:
    """Configuration loader with YAML file support and environment variable interpolation."""

    _instance = None
    _data = {}

    ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config", "default.yaml"
            )
        self._load(config_path)

    def _load(self, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {}
        self._resolve_env_vars(self._data)

    def _resolve_env_vars(self, obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    obj[key] = self.ENV_VAR_PATTERN.sub(
                        lambda m: os.environ.get(m.group(1), m.group(0)), value
                    )
                else:
                    self._resolve_env_vars(value)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str):
                    obj[i] = self.ENV_VAR_PATTERN.sub(
                        lambda m: os.environ.get(m.group(1), m.group(0)), item
                    )
                else:
                    self._resolve_env_vars(item)

    def get(self, dotted_key, default=None):
        """Get a config value using dot notation. e.g. 'app.mode', 'providers.psp.active'"""
        keys = dotted_key.split(".")
        obj = self._data
        for key in keys:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default
        return obj

    def get_provider(self, adapter_type: str) -> str:
        """Get the active provider name for an adapter type.
        If app.mode is 'demo', always returns 'mock'."""
        if self.is_demo_mode():
            return "mock"
        return self.get(f"providers.{adapter_type}.active", "mock")

    def get_credentials(self, provider: str) -> dict:
        """Get credential dict for a provider, with env vars resolved."""
        return self.get(f"credentials.{provider}", {})

    def is_demo_mode(self) -> bool:
        return self.get("app.mode", "demo") == "demo"

    @property
    def database_url(self) -> str:
        return self.get("database.url", "sqlite:///chargeback.db")

    @classmethod
    def load(cls, config_path=None) -> "Config":
        """Load configuration (singleton)."""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton for testing."""
        cls._instance = None
