import asyncio
import importlib
import shutil
from pathlib import Path
from typing import Any, Dict, NamedTuple

import yaml

from core.config_schema import check_config
from core.security_layer import SecurityLayer
from log_system.session_logger import SessionLogger


class ServiceSpec(NamedTuple):
    module: str
    cls: str
    needs_security: bool = False


# Service registry: config "type" -> emulator class.
# To add a service: create it in core/service_emulator/ and register it here.
SERVICE_REGISTRY: Dict[str, ServiceSpec] = {
    "ssh": ServiceSpec("core.service_emulator.ssh_emulator", "SSHService", needs_security=True),
    "ftp": ServiceSpec("core.service_emulator.ftp_emulator", "FTPService"),
    "http": ServiceSpec("core.service_emulator.http_emulator", "HTTPService"),
    "mysql": ServiceSpec("core.service_emulator.mysql_emulator", "MySQLService"),
    "telnet": ServiceSpec("core.service_emulator.telnet_emulator", "TelnetService"),
}

# Offered by the visual configurator but not implemented yet: skipped with a warning.
PLANNED_SERVICES = {"rdp"}

EXAMPLE_CONFIG = Path("config/honeypot.example.yaml")


class MIMICController:
    def __init__(self, config_path: str = "config/honeypot.yaml"):
        self.config = self.load_config(config_path)
        self.security = SecurityLayer(self.config.get('security', {}))
        self.logger = SessionLogger()
        self.services = {}
        self.running = False

    def load_config(self, path: str) -> Dict[str, Any]:
        config_path = Path(path)
        if not config_path.exists() and EXAMPLE_CONFIG.exists():
            shutil.copyfile(EXAMPLE_CONFIG, config_path)
            print(f"[*] No {config_path} found - created it from {EXAMPLE_CONFIG}")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return check_config(config, SERVICE_REGISTRY, PLANNED_SERVICES)

    def build_service_config(self, service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Service config plus the global identity/options every emulator may use."""
        system = self.config.get('system', {}) or {}
        options = self.config.get('options', {}) or {}
        security = self.config.get('security', {}) or {}

        config = dict(service_config)
        config.update({
            'hostname': system.get('hostname', 'ubuntu-server'),
            'username': system.get('username', 'admin'),
            'password': system.get('password', 'admin123'),
            'os_template': system.get('os_template', 'Ubuntu'),
            'any_auth': options.get('any_auth', True),
            'human_patterns': options.get('human_patterns', True),
            'brute_force_attempts': options.get('brute_force_attempts', 1),
            'security_enabled': security.get('enabled', True),
        })
        if config.get('type') == 'ssh' and 'enable_scp' in config:
            config['scp_redirect_port'] = 2222
            config['sftp_redirect_port'] = 2223
        return config

    def create_service(self, port: int, service_config: Dict[str, Any]):
        service_type = service_config.get('type', '')
        spec = SERVICE_REGISTRY[service_type]
        service_cls = getattr(importlib.import_module(spec.module), spec.cls)
        config = self.build_service_config(service_config)
        if spec.needs_security:
            return service_cls(port, config, self.security)
        return service_cls(port, config)

    async def start_service(self, port: int, service_config: Dict):
        service_type = service_config.get('type', 'generic')

        if service_type in PLANNED_SERVICES:
            print(f"[!] {service_type} on port {port} is not implemented yet - skipped")
            return

        try:
            service = self.create_service(port, service_config)
            service.server_task = asyncio.create_task(service.start())
            self.services[port] = service
            print(f"[OK] Started {service_type} on port {port}")
        except ImportError as e:
            print(f"[!] Failed to load service {service_type}: {e}")
        except Exception as e:
            print(f"[!] Error starting service {service_type}: {e}")

    async def start_all_services(self):
        enabled_services = {
            port: config for port, config in self.config['services'].items()
            if config.get('enabled', True)
        }

        print(f"[*] Found {len(enabled_services)} service(s) to start")

        for port, config in enabled_services.items():
            port_int = int(port)
            if self.security.validate_port(port_int):
                await self.start_service(port_int, config)
                await asyncio.sleep(0.1)

        self.running = True
        print("\n[OK] MIMIC Honeypot READY\n")

    async def stop(self):
        print("\n[*] Stopping services...")

        for port, service in self.services.items():
            if service.server_task and not service.server_task.done():
                service.server_task.cancel()

        await asyncio.sleep(0.2)

        stop_tasks = []
        for port, service in self.services.items():
            if hasattr(service, 'stop'):
                stop_tasks.append(service.stop())

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.services.clear()
        self.running = False
        print("[OK] All services stopped")
