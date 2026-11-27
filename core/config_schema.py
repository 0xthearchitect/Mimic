"""Validation for config/honeypot.yaml.

Checks the config up front and reports every problem at once, instead of
failing halfway through startup.
"""
from typing import Any, Dict, Iterable, List


class ConfigError(ValueError):
    """Raised when the honeypot config is invalid. ``errors`` lists each problem."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(errors))


def _check_type(errors: List[str], where: str, value: Any, expected: type, name: str):
    # bool is a subclass of int; don't accept True as a port number.
    if expected is int and isinstance(value, bool):
        errors.append(f"{where}: '{name}' must be a number, got {value!r}")
    elif not isinstance(value, expected):
        errors.append(f"{where}: '{name}' must be {expected.__name__}, got {value!r}")


def validate_config(config: Any, known_service_types: Iterable[str],
                    planned_service_types: Iterable[str] = ()) -> List[str]:
    """Return a list of human-readable problems; empty means valid.

    Planned types (offered in the UI but not implemented yet) are accepted
    here; the controller skips them with a warning.
    """
    planned = set(planned_service_types)
    known = sorted(known_service_types)
    errors: List[str] = []

    if not isinstance(config, dict):
        return ["config file is empty or not a YAML mapping"]

    for section in ("system", "options", "security"):
        if section in config and not isinstance(config[section], dict):
            errors.append(f"'{section}' must be a mapping")

    system = config.get("system") or {}
    if isinstance(system, dict):
        for key in ("username", "password", "hostname"):
            if key in system and not isinstance(system[key], str):
                errors.append(f"system: '{key}' must be text, got {system[key]!r}")

    options = config.get("options") or {}
    if isinstance(options, dict):
        if "any_auth" in options:
            _check_type(errors, "options", options["any_auth"], bool, "any_auth")
        if "brute_force_attempts" in options:
            n = options["brute_force_attempts"]
            _check_type(errors, "options", n, int, "brute_force_attempts")
            if isinstance(n, int) and not isinstance(n, bool) and n < 1:
                errors.append("options: 'brute_force_attempts' must be at least 1")

    services = config.get("services")
    if not services:
        errors.append("no services configured under 'services'")
        return errors
    if not isinstance(services, dict):
        errors.append("'services' must be a mapping of port -> service")
        return errors

    for port, svc in services.items():
        where = f"services['{port}']"
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            errors.append(f"{where}: port must be a number")
            port_int = None
        if port_int is not None and not 1 <= port_int <= 65535:
            errors.append(f"{where}: port must be between 1 and 65535")

        if not isinstance(svc, dict):
            errors.append(f"{where}: must be a mapping with at least 'type'")
            continue

        svc_type = svc.get("type")
        if not svc_type:
            errors.append(f"{where}: missing 'type' (one of: {', '.join(known)})")
        elif svc_type not in known and svc_type not in planned:
            errors.append(f"{where}: unknown type '{svc_type}' (one of: {', '.join(known)})")

        if "enabled" in svc:
            _check_type(errors, where, svc["enabled"], bool, "enabled")

    return errors


def check_config(config: Any, known_service_types: Iterable[str],
                 planned_service_types: Iterable[str] = ()) -> Dict[str, Any]:
    """Validate and return the config, or raise ConfigError."""
    errors = validate_config(config, known_service_types, planned_service_types)
    if errors:
        raise ConfigError(errors)
    return config
