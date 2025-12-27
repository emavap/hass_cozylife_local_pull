"""Config flow for CozyLife Local integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class CozyLifeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CozyLife Local."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CozyLifeOptionsFlowHandler:
        """Get the options flow for this handler."""
        return CozyLifeOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="CozyLife Local", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("ips", default=""): str,
            }),
            description_placeholders={
                "ips": "IP addresses (comma separated)",
            },
        )


class CozyLifeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for CozyLife Local."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the config entry data with new IPs
            new_data = {**self.config_entry.data, "ips": user_input.get("ips", "")}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to pick up new devices
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Get current IPs from config
        current_ips = self.config_entry.data.get("ips", "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("ips", default=current_ips): str,
            }),
        )
