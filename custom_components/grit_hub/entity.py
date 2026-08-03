"""Entity helpers for GRIT Hub."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import obj_id, obj_name
from .const import DOMAIN
from .coordinator import MQTT_STATE_KEY

DIAGNOSTIC_ATTRIBUTE_KEYS = ("status", "state", "mode")


class GritHubEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_type: str | None = None, device: dict[str, Any] | None = None) -> None:
        super().__init__(coordinator)
        self.device_type = device_type
        self.device = device or {}
        self._device_id = obj_id(self.device) if self.device else "hub"

    @property
    def device_info(self) -> DeviceInfo:
        if self.device_type and self._device_id != "hub":
            return DeviceInfo(
                identifiers={(DOMAIN, self.device_type, str(self._device_id))},
                name=obj_name(self.device, self.device_type.title()),
                manufacturer="GRIT Automation",
                model=self.device_type,
            )
        hub = self.hub_data
        name = hub.get("displayName") or hub.get("name") or "GRIT Hub"
        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, "hub")},
            "name": name,
            "manufacturer": "GRIT Automation",
            "model": "GRIT Hub",
        }
        version = hub.get("hubVersion")
        if isinstance(version, str):
            info["sw_version"] = version
        return DeviceInfo(**info)

    @property
    def hub_data(self) -> dict[str, Any]:
        """Return the coordinator's strictly sanitized hub data."""
        return self.coordinator.hub_data

    @property
    def current_device(self) -> dict[str, Any]:
        if not self.device_type or self._device_id == "hub":
            return {}
        for item in self.coordinator.data.get("devices", {}).get(self.device_type, []):
            if str(obj_id(item)) == str(self._device_id):
                return item
        return self.device

    @property
    def mqtt_state(self) -> dict[str, Any]:
        """Return only the coordinator's sanitized per-device MQTT state."""
        state = self.current_device.get(MQTT_STATE_KEY)
        return state if isinstance(state, dict) else {}

    @property
    def mqtt_online(self) -> bool | None:
        """Return the strict sanitized online state when it is known."""
        online = self.mqtt_state.get("online")
        return online if isinstance(online, bool) else None

    @property
    def live_available(self) -> bool:
        """Return conservative availability for live controllable entities."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.mqtt_connected
            and self.mqtt_online is not False
        )

    @property
    def diagnostic_attributes(self) -> dict[str, str | int | float | bool]:
        """Return a small allowlist of scalar, non-sensitive device state."""
        attributes: dict[str, str | int | float | bool] = {}
        for key in DIAGNOSTIC_ATTRIBUTE_KEYS:
            value = self.current_device.get(key)
            if isinstance(value, str) and len(value) <= 64:
                attributes[key] = value
            elif isinstance(value, (int, float, bool)):
                attributes[key] = value
        return attributes
