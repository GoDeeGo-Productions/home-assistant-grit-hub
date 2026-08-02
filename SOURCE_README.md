# Imported source provenance

This file records the origin of the first sanitized source import. It is not the
current installation or architecture guide; see [README.md](README.md) for the
authoritative documentation.

The initial repository import was based on an older REST-only Home Assistant
custom-component export derived from a GRIT Swagger/OpenAPI catalogue. The
import retained the existing entity-platform layout and the broad endpoint
catalogue in `custom_components/grit_hub/const.py`, while removing
installation-specific values, arbitrary endpoint access, raw API attributes and
runtime artefacts.

The current committed integration is newer than that export. It adds a direct,
sanitized Paho MQTT client, mandatory MQTT setup readiness, bounded live-state
routing, MQTT-aware entity availability, reconfiguration and mocked unit tests.
The current runtime requires `paho-mqtt==2.1.0`; it does not depend on Home
Assistant's MQTT integration.

The endpoint catalogue remains imported/generated and intentionally has not
been broadly regenerated or reduced. Duplicated or unused routes should be
reviewed separately from packaging work.
