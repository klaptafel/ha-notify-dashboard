"""Notify platform for Notify Dashboard.

Legacy BaseNotificationService — deliberately not the modern NotifyEntity,
since that one doesn't support `data`/`tag`/`target` (see design doc,
section 1.1).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import ATTR_DATA, ATTR_TITLE, BaseNotificationService
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import COMMAND_MESSAGES, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> "DashboardNotificationService":
    """Get the Notify Dashboard notification service."""
    return DashboardNotificationService(hass)


class DashboardNotificationService(BaseNotificationService):
    """Routes notify.dashboard calls to the notify_dashboard store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        store = self.hass.data[DOMAIN]["store"]
        title = kwargs.get(ATTR_TITLE)
        data = kwargs.get(ATTR_DATA) or {}

        # Command messages are instructions, not content — never store them.
        if message in COMMAND_MESSAGES:
            if message == "clear_notification":
                tag = data.get("tag")
                if tag:
                    await store.async_clear_by_tag(tag)
            else:
                _LOGGER.debug("Ignored command message '%s' (phone-specific)", message)
            return

        if data.get("live_update"):
            await store.async_upsert_live_activity(title=title, message=message, data=data)
        else:
            await store.async_add_notification(title=title, message=message, data=data)
