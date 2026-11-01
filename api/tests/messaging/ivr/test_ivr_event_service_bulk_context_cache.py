"""`_bulk_context_cache` (ver ivr_event_service.py) debe quedar acotado en tamaño:
sin límite, un proceso de larga vida con muchas campañas IVR crecería sin fin."""

import uuid

from messaging.ivr.services.ivr_event_service import (
    _BULK_CONTEXT_CACHE_MAX_SIZE,
    BulkContext,
    _bulk_context_cache,
    _cache_bulk_context,
)


class TestBulkContextCache:
    def setup_method(self) -> None:
        _bulk_context_cache.clear()

    def teardown_method(self) -> None:
        _bulk_context_cache.clear()

    def test_evicts_oldest_entry_once_over_the_limit(self):
        for i in range(_BULK_CONTEXT_CACHE_MAX_SIZE):
            _cache_bulk_context(
                f"bulk-{i}", BulkContext(campaign_id=uuid.uuid4(), organization_id=None)
            )
        assert len(_bulk_context_cache) == _BULK_CONTEXT_CACHE_MAX_SIZE
        assert "bulk-0" in _bulk_context_cache

        _cache_bulk_context(
            "bulk-overflow", BulkContext(campaign_id=uuid.uuid4(), organization_id=None)
        )

        assert len(_bulk_context_cache) == _BULK_CONTEXT_CACHE_MAX_SIZE
        assert "bulk-0" not in _bulk_context_cache
        assert "bulk-overflow" in _bulk_context_cache
