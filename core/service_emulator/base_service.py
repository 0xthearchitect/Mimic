import asyncio
import random
from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

from log_system import events

class BaseService(ABC):
    
    def __init__(self, port: int, config: Dict[str, Any]):
        self.port = port
        self.config = config
        self.name = config.get('name', 'Unknown Service')
        self.banner = config.get('banner', '')
        self.is_running = False
        self.connections = 0
        self.logger = logging.getLogger(f'service.{port}')
        self.server = None
        self.server_task = None
        
        self.service_type = config.get('type', 'generic').lower()

        self.response_delay = config.get('response_delay', {'min': 0.1, 'max': 1.0})
        self.error_rate = config.get('error_rate', 0.05)  # 5% error rate
        self.session_timeout = config.get('session_timeout', 300)
        
    async def start(self):
        self.is_running = True
        self.server = None
        self.logger.info(f"Starting {self.name} on port {self.port}")
        
        try:
            self.server = await asyncio.start_server(
                self.handle_connection,
                host='0.0.0.0',
                port=self.port,
                reuse_address=True
            )
            
            self.logger.info(f"{self.name} listening on port {self.port}")
            async with self.server:
                await self.server.serve_forever()
                
        except asyncio.CancelledError:
            self.logger.info(f"{self.name} cancelled")
        except Exception as e:
            self.logger.error(f"Failed to start {self.name}: {e}")
            raise
    
    async def stop(self):
        self.is_running = False
        self.logger.info(f"Stopping {self.name} on port {self.port}")
        if self.server:
            self.server.close()
            await self.server.wait_closed()
    
    @abstractmethod
    async def handle_connection(self, reader: asyncio.StreamReader, 
                               writer: asyncio.StreamWriter):
        pass
    
    def simulate_human_delay(self):
        if self.response_delay.get('random', True):
            delay = random.uniform(
                self.response_delay.get('min', 0.1),
                self.response_delay.get('max', 1.0)
            )
            return asyncio.sleep(delay)
        return asyncio.sleep(self.response_delay.get('fixed', 0.5))
    
    def should_generate_error(self) -> bool:
        return random.random() < self.error_rate
    
    def generate_error_response(self) -> str:
        errors = [
            "Connection timed out",
            "Protocol error",
            "Invalid command",
            "Access denied",
            "Service unavailable",
            "Internal server error"
        ]
        return random.choice(errors)
    
    # --- Event logging (schema: docs/LOG_FORMAT.md) ---------------------

    def log_event(self, event: str, ip: str, **fields):
        return events.emit(self.service_type, self.port, event, ip, **fields)

    def log_connection(self, ip: str):
        self.connections += 1
        self.logger.info(f"New connection from {ip} to {self.name}")
        self.log_event(events.CONNECTION, ip, connection_number=self.connections)

    def log_command(self, ip: str, command: str, **fields):
        self.logger.debug(f"Command from {ip}: {command}")
        self.log_event(events.COMMAND, ip, command=command, **fields)

    def log_login(self, ip: str, username: str, password: str, success: bool, **fields):
        self.logger.info(f"Login {'OK' if success else 'failed'} from {ip}: {username!r}")
        self.log_event(events.LOGIN_ATTEMPT, ip, username=username, password=password,
                       success=success, **fields)

    def get_fake_response(self, command: str) -> str:
        return f"Response to: {command}"