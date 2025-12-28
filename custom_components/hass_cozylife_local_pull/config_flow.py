"""Config flow for CozyLife Local integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
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
        return CozyLifeOptionsFlowHandler()

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

    def __init__(self) -> None:
        """Initialize options flow."""
        self._ips: list[str] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show menu for managing IPs."""
        # Load current IPs from config
        current_ips = self.config_entry.data.get("ips", "")
        self._ips = [ip.strip() for ip in current_ips.split(",") if ip.strip()]

        return self.async_show_menu(
            step_id="init",
            menu_options=["add_ip", "remove_ip", "view_ips", "done"],
            description_placeholders={
                "current_count": str(len(self._ips)),
            },
        )

    async def async_step_add_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a new IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_ip = user_input.get("ip", "").strip()
            if new_ip:
                # Basic IP validation
                if self._is_valid_ip(new_ip):
                    if new_ip not in self._ips:
                        self._ips.append(new_ip)
                        await self._save_ips()
                        return await self.async_step_init()
                    else:
                        errors["ip"] = "ip_already_exists"
                else:
                    errors["ip"] = "invalid_ip"
            else:
                errors["ip"] = "ip_required"

        return self.async_show_form(
            step_id="add_ip",
            data_schema=vol.Schema({
                vol.Required("ip"): str,
            }),
            errors=errors,
        )

    async def async_step_remove_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove an IP address."""
        # Reload current IPs
        current_ips = self.config_entry.data.get("ips", "")
        self._ips = [ip.strip() for ip in current_ips.split(",") if ip.strip()]

        if not self._ips:
            return await self.async_step_init()

        if user_input is not None:
            ip_to_remove = user_input.get("ip")
            if ip_to_remove and ip_to_remove in self._ips:
                self._ips.remove(ip_to_remove)
                await self._save_ips()
            return await self.async_step_init()

        # Create selection from current IPs
        ip_options = {ip: ip for ip in self._ips}

        return self.async_show_form(
            step_id="remove_ip",
            data_schema=vol.Schema({
                vol.Required("ip"): vol.In(ip_options),
            }),
        )

    async def async_step_view_ips(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """View current IP addresses."""
        # Reload current IPs
        current_ips = self.config_entry.data.get("ips", "")
        self._ips = [ip.strip() for ip in current_ips.split(",") if ip.strip()]

        if user_input is not None:
            return await self.async_step_init()

        ip_list = "\n".join(f"• {ip}" for ip in self._ips) if self._ips else "No IPs configured"

        return self.async_show_form(
            step_id="view_ips",
            data_schema=vol.Schema({}),
            description_placeholders={
                "ip_list": ip_list,
            },
        )

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish the options flow."""
        return self.async_create_entry(title="", data={})

    async def _save_ips(self) -> None:
        """Save IPs to config entry and reload."""
        new_ips = ",".join(self._ips)
        new_data = {**self.config_entry.data, "ips": new_ips}
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )
        # Reload to pick up new devices
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Validate IP address format.

        Args:
            ip: The IP address string to validate.

        Returns:
            True if the IP is valid, False otherwise.
        """
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            # Reject empty parts and leading zeros (except "0" itself)
            if not part or (len(part) > 1 and part.startswith("0")):
                return False
            try:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            except ValueError:
                return False
        return True
