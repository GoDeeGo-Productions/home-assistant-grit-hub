## Summary

Describe the concrete problem and the smallest focused change.

## State authority and risk

State which REST endpoint, MQTT message type, entity, and confirmation boundary
are affected. Explain physical-operation and privacy impact. If protocol
semantics changed, link a redacted evidence matrix without including live IDs,
secrets, or raw captures.

## Validation

List the deterministic network-free tests and static checks run. Confirm whether
HACS and Hassfest CI were run.

## Checklist

- [ ] Existing runtime behavior is preserved unless the change is explicitly justified.
- [ ] No optimistic command state or weakened confirmation was introduced.
- [ ] Concurrency, timeouts, cancellation, disconnect, and unload remain bounded.
- [ ] Tests use fake clients and fabricated data; they contact no live system or equipment.
- [ ] No credentials, private addresses, identifiers, personal data, raw payloads, logs, diagnostics, or private references are included.
- [ ] Logging is bounded and contains no secrets, endpoints, complete topics, IDs, payloads, or response bodies.
- [ ] Documentation and localization match any user-visible behavior change.
- [ ] Python, JSON/YAML, unit, diff, and sensitive-value checks pass.
