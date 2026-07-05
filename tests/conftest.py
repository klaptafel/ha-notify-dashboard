"""Shared fixtures for notify_dashboard tests."""
from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.notify_dashboard.store import NotifyDashboardStore


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required so pytest-homeassistant-custom-component actually loads
    custom_components/notify_dashboard instead of only core-shipped domains.
    Without this, async_setup_component(hass, DOMAIN, ...) silently fails
    to find the integration in every test."""
    yield


@pytest.fixture
def mock_notify_target(hass):
    """Fake notify.* endpoint to assert mirror_dismiss_to forwarding.

    _async_mirror_clear calls hass.services.async_call("notify",
    "send_message", ..., target=...) — a plain service call, not an
    entity-service lookup, so a real fake NotifyEntity isn't needed. A state
    is set for notify.mobile_app too: _async_mirror_clear checks
    hass.states.get(entity_id) first (a real target service call against a
    nonexistent entity_id silently does nothing, no exception — the
    try/except around the actual call can't catch that case), so without
    this the mock would never even get called.
    """
    hass.states.async_set("notify.mobile_app", "unknown")
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
async def hass_http(hass):
    """Set up the real `http` component.

    _async_ensure_core calls hass.http.async_register_static_paths(...), so
    this is required for any test exercising it. `http` itself needs no
    packages beyond what homeassistant core already pulls in — unlike
    `frontend`, which additionally needs the separate `hass_frontend`
    package that isn't installable in this environment (confirmed: pip has
    no matching distribution for it here). Keep this fixture minimal — do
    not fold `frontend` into it.
    """
    await async_setup_component(hass, "http", {})
    return hass


@pytest.fixture
def frontend_extra_js_urls(hass):
    """Stand-in for the real `frontend` component's own internal state.

    _async_register_lovelace_resource's YAML-mode branch calls
    frontend.add_extra_js_url(hass, url), which just does
    hass.data["frontend_extra_module_url"].add(url) — that key is normally
    seeded by frontend's own async_setup, which we can't run for real here
    (see hass_http above). Pre-seeding it is a faithful stand-in for "the
    real frontend component happens to already be set up", not a mock of
    logic under test.
    """
    urls: set[str] = set()
    hass.data["frontend_extra_module_url"] = urls
    return urls


@pytest.fixture
def fake_lovelace_storage(hass):
    """Stand-in for hass.data["lovelace"] in storage-mode (UI-managed
    dashboards) — the branch _async_register_lovelace_resource takes when a
    real dashboard resources collection exists. Mirrors just the subset of
    lovelace.dashboard.ResourceStorageCollection's interface our code calls.
    """

    class _FakeResources:
        def __init__(self) -> None:
            self.items: list[dict] = []
            self._next_id = 1

        async def async_load(self) -> None:
            return None

        def async_items(self) -> list[dict]:
            return self.items

        async def async_create_item(self, data: dict) -> dict:
            item = {"id": str(self._next_id), **data}
            self._next_id += 1
            self.items.append(item)
            return item

        async def async_update_item(self, item_id: str, data: dict) -> None:
            for item in self.items:
                if item["id"] == item_id:
                    item.update(data)

    class _FakeLovelaceData:
        resource_mode = "storage"

        def __init__(self) -> None:
            self.resources = _FakeResources()

    data = _FakeLovelaceData()
    hass.data["lovelace"] = data
    return data


@pytest.fixture
def no_discovery(monkeypatch):
    """Patch out discovery.async_load_platform for __init__.py tests.

    _async_ensure_core fires this to load sensor.py via discovery — but
    since notify_dashboard's manifest declares frontend as a dependency,
    letting it run for real drags in a full frontend/websocket_api/lovelace
    bootstrap cascade that fails on the missing hass_frontend package (same
    root cause as hass_http/frontend_extra_js_urls above). That platform
    load is already covered directly in test_sensor.py; here we only need
    to confirm _async_ensure_core *asks* for it with the right arguments.
    """
    calls: list[tuple] = []

    async def _fake_async_load_platform(hass, component, platform, discovered, hass_config):
        calls.append((component, platform, discovered))

    monkeypatch.setattr(
        "custom_components.notify_dashboard.discovery.async_load_platform",
        _fake_async_load_platform,
    )
    return calls


@pytest.fixture
async def loaded_store(hass):
    """A loaded NotifyDashboardStore with its periodic cleanup timer
    guaranteed to be unsubscribed on teardown.

    async_track_time_interval re-arms itself recursively — if a test doesn't
    unsub before ending, the hass fixture's teardown fails the *next* test
    with a "lingering timer" assertion, not this one. Always go through this
    fixture instead of constructing a store directly in a test that needs
    the periodic timer.
    """
    store = NotifyDashboardStore(hass)
    await store.async_load()
    yield store
    store._unsub_periodic_cleanup()
