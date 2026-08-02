"""Entity helpers for GRIT Hub."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import obj_id, obj_name
from .const import DOMAIN

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
        return DeviceInfo(identifiers={(DOMAIN, "hub")}, name="GRIT Hub", manufacturer="GRIT Automation")

    @property
    def current_device(self) -> dict[str, Any]:
        if not self.device_type or self._device_id == "hub":
            return {}
        for item in self.coordinator.data.get("devices", {}).get(self.device_type, []):
            if str(obj_id(item)) == str(self._device_id):
                return item
        return self.device

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
