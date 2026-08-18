from __future__ import annotations

from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1

class RouteCache:
    """Persistent cache for ORS route summaries."""

    def __init__(self, hass, entry_id):
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"ha_voetbal_nl.route_cache.{entry_id}",
        )
        self._data = {}

    async def async_load(self):
        stored = await self._store.async_load()
        self._data = stored if isinstance(stored, dict) else {}

    @staticmethod
    def make_key(origin_lat, origin_lon, destination_lat, destination_lon):
        # Five decimals is ~1 metre and stable enough to avoid float noise.
        return (
            f"{float(origin_lat):.5f},{float(origin_lon):.5f}>"
            f"{float(destination_lat):.5f},{float(destination_lon):.5f}"
        )

    def get(self, key):
        value = self._data.get(key)
        return value if isinstance(value, dict) else None

    def set(self, key, value):
        self._data[key] = dict(value)

    async def async_save(self):
        await self._store.async_save(self._data)
