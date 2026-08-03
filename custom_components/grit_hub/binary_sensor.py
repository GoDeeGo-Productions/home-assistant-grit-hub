"""Binary sensors for GRIT Hub."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from .api import obj_id
from .const import DEVICE_TYPES, DOMAIN
from .entity import GritHubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [
        GritHubOnlineBinarySensor(coordinator),
        GritHubInternetConnectivityBinarySensor(coordinator),
        GritHubPhysicalButtonsDisabledBinarySensor(coordinator),
        GritHubMqttConnectionBinarySensor(coordinator, entry.entry_id),
    ]
    for dev_type in DEVICE_TYPES:
        for dev in coordinator.data.get("devices", {}).get(dev_type, []):
            if obj_id(dev) is not None:
                entities.append(
                    GritHubDeviceMqttOnlineBinarySensor(
                        coordinator,
                        entry.entry_id,
                        dev_type,
                        dev,
                    )
                )
    async_add_entities(entities)


class GritHubOnlineBinarySensor(GritHubEntity, BinarySensorEntity):
    _attr_name = "Online"
    _attr_unique_id = "grit_hub_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class GritHubInternetConnectivityBinarySensor(
    GritHubEntity,
    BinarySensorEntity,
):
    _attr_name = "Internet Connectivity"
    _attr_unique_id = "grit_hub_internet_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        value = self.hub_data.get("connectedToInternet")
        return value if isinstance(value, bool) else None


class GritHubPhysicalButtonsDisabledBinarySensor(
    GritHubEntity,
    BinarySensorEntity,
):
    _attr_name = "Physical Hub Buttons Disabled"
    _attr_unique_id = "grit_hub_physical_buttons_disabled"
    _attr_icon = "mdi:gesture-tap-button"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        value = self.hub_data.get("disableHubButtons")
        return value if isinstance(value, bool) else None


class GritHubMqttConnectionBinarySensor(GritHubEntity, BinarySensorEntity):
    _attr_name = "MQTT Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"grit_hub_{entry_id}_mqtt_connected"

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.mqtt_connected


class GritHubDeviceMqttOnlineBinarySensor(GritHubEntity, BinarySensorEntity):
    _attr_name = "MQTT Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_type, device):
        super().__init__(coordinator, device_type, device)
        ident = obj_id(device)
        self._attr_unique_id = (
            f"grit_hub_{entry_id}_{device_type}_{ident}_mqtt_online"
        )

    @property
    def available(self) -> bool:
        return self.mqtt_online is not None

    @property
    def is_on(self) -> bool | None:
        return self.mqtt_online
