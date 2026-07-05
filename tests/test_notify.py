"""Tests for the legacy notify platform (DashboardNotificationService)."""
from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.notify_dashboard.const import DOMAIN
from custom_components.notify_dashboard.notify import (
    DashboardNotificationService,
    async_get_service,
)


async def test_async_get_service_returns_bound_service(hass):
    service = await async_get_service(hass, {})
    assert isinstance(service, DashboardNotificationService)
    assert service.hass is hass


def _service_with_mock_store(hass):
    mock_store = AsyncMock()
    hass.data[DOMAIN] = {"store": mock_store}
    return DashboardNotificationService(hass), mock_store


async def test_regular_message_adds_notification(hass):
    service, mock_store = _service_with_mock_store(hass)
    await service.async_send_message("hello", title="Hi", data={"tag": "t1"})
    mock_store.async_add_notification.assert_awaited_once_with(
        title="Hi", message="hello", data={"tag": "t1"}
    )
    mock_store.async_upsert_live_activity.assert_not_called()


async def test_live_update_upserts_live_activity(hass):
    service, mock_store = _service_with_mock_store(hass)
    await service.async_send_message("50%", title="Job", data={"tag": "t1", "live_update": True})
    mock_store.async_upsert_live_activity.assert_awaited_once_with(
        title="Job", message="50%", data={"tag": "t1", "live_update": True}
    )
    mock_store.async_add_notification.assert_not_called()


async def test_clear_notification_with_tag_clears_by_tag(hass):
    service, mock_store = _service_with_mock_store(hass)
    await service.async_send_message("clear_notification", data={"tag": "t1"})
    mock_store.async_clear_by_tag.assert_awaited_once_with("t1")
    mock_store.async_add_notification.assert_not_called()
    mock_store.async_upsert_live_activity.assert_not_called()


async def test_clear_notification_without_tag_does_nothing(hass):
    service, mock_store = _service_with_mock_store(hass)
    await service.async_send_message("clear_notification", data={})
    mock_store.async_clear_by_tag.assert_not_called()
    mock_store.async_add_notification.assert_not_called()


async def test_other_command_messages_are_dropped(hass):
    service, mock_store = _service_with_mock_store(hass)
    for command in ("TTS", "delete_alert", "remove_channel"):
        await service.async_send_message(command, data={"tag": "t1"})
    mock_store.async_add_notification.assert_not_called()
    mock_store.async_upsert_live_activity.assert_not_called()
    mock_store.async_clear_by_tag.assert_not_called()
