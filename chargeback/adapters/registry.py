from chargeback.adapters.base import (
    BasePSPAdapter, BaseGatewayAdapter, BaseCRMAdapter,
    BaseCarrierAdapter, BaseRepositoryAdapter,
)


class AdapterRegistry:
    """Factory that resolves configured adapter instances by type and provider name."""

    _adapters = {
        "psp": {},
        "gateway": {},
        "crm": {},
        "carrier": {},
        "repository": {},
    }

    _instances = {}

    @classmethod
    def register(cls, adapter_type: str, provider_name: str, adapter_class):
        """Register an adapter class for a given type and provider."""
        if adapter_type not in cls._adapters:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        cls._adapters[adapter_type][provider_name] = adapter_class

    @classmethod
    def get(cls, adapter_type: str, provider_name: str = None, **kwargs):
        """Get an adapter instance. Uses config if provider_name not specified."""
        if provider_name is None:
            from config import Config
            config = Config.load()
            provider_name = config.get_provider(adapter_type)

        cache_key = f"{adapter_type}:{provider_name}"
        if cache_key not in cls._instances:
            if adapter_type not in cls._adapters:
                raise ValueError(f"Unknown adapter type: {adapter_type}")
            if provider_name not in cls._adapters[adapter_type]:
                raise ValueError(
                    f"No adapter registered for {adapter_type}/{provider_name}. "
                    f"Available: {list(cls._adapters[adapter_type].keys())}"
                )
            adapter_class = cls._adapters[adapter_type][provider_name]
            cls._instances[cache_key] = adapter_class(**kwargs)
        return cls._instances[cache_key]

    @classmethod
    def get_psp(cls, provider: str = None) -> BasePSPAdapter:
        return cls.get("psp", provider)

    @classmethod
    def get_gateway(cls, provider: str = None) -> BaseGatewayAdapter:
        return cls.get("gateway", provider)

    @classmethod
    def get_crm(cls, provider: str = None) -> BaseCRMAdapter:
        return cls.get("crm", provider)

    @classmethod
    def get_carrier(cls, provider: str = None) -> BaseCarrierAdapter:
        return cls.get("carrier", provider)

    @classmethod
    def get_repository(cls, provider: str = None) -> BaseRepositoryAdapter:
        return cls.get("repository", provider)

    @classmethod
    def reset(cls):
        """Clear cached instances. Useful for testing."""
        cls._instances.clear()

    @classmethod
    def available(cls, adapter_type: str) -> list:
        """List available provider names for an adapter type."""
        return list(cls._adapters.get(adapter_type, {}).keys())


def register_default_adapters():
    """Register all mock/default adapters."""
    from chargeback.adapters.psp.mock import MockPSPAdapter
    from chargeback.adapters.gateway.mock import MockGatewayAdapter
    from chargeback.adapters.crm.mock import MockCRMAdapter
    from chargeback.adapters.carrier.mock import MockCarrierAdapter

    AdapterRegistry.register("psp", "mock", MockPSPAdapter)
    AdapterRegistry.register("gateway", "mock", MockGatewayAdapter)
    AdapterRegistry.register("crm", "mock", MockCRMAdapter)
    AdapterRegistry.register("carrier", "mock", MockCarrierAdapter)
