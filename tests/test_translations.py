"""Guards against strings.json/translations/en.json drifting apart.

HA's runtime translation loader (homeassistant.helpers.translation) never
reads strings.json directly for a custom integration — only
translations/<lang>.json. strings.json is what hassfest/HACS validate and
what a human reads as the canonical source, but without a matching
translations/en.json, English users see raw keys like "mirror_dismiss_to"
in the UI instead of any label at all (confirmed: an integration with a
translations/ directory but no en.json in it resolves to a completely
empty English translation set, not a strings.json fallback).
"""
import json
from pathlib import Path

from homeassistant.helpers import translation

INTEGRATION_DIR = Path("custom_components/notify_dashboard")


def test_strings_json_and_en_json_match():
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    en = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text())
    assert strings == en


async def test_english_config_and_options_translations_resolve(hass):
    config = await translation.async_get_translations(
        hass, "en", "config", integrations={"notify_dashboard"}
    )
    assert (
        config["component.notify_dashboard.config.step.user.data.mirror_dismiss_to"]
        == "Also clear notifications on"
    )

    options = await translation.async_get_translations(
        hass, "en", "options", integrations={"notify_dashboard"}
    )
    assert (
        options["component.notify_dashboard.options.step.init.data.mirror_dismiss_to"]
        == "Also clear notifications on"
    )
