import argparse
import asyncio
import sys

from core.config_schema import ConfigError
from core.controller import MIMICController


async def run(config_path: str, dashboard: bool, host: str, port: int):
    controller = MIMICController(config_path)
    board = None
    try:
        if dashboard:
            # Imported here so headless mode never loads the web stack.
            from dashboard.server import Dashboard
            board = Dashboard(controller, host=host, port=port)
            await board.start()
            print("[*] The honeypot is stopped. Start it from the dashboard (Playbill).")
        else:
            await controller.start_all_services()
        print("\n[OK] Ctrl+C to quit\n")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Ctrl+C received")
    finally:
        print("[*] Shutting down MIMIC...")
        if controller.running:
            await controller.stop()
        if board:
            await board.stop()
        print("[OK] Shutdown complete")


def main():
    parser = argparse.ArgumentParser(description="MIMIC honeypot")
    parser.add_argument("-c", "--config", default="config/honeypot.yaml",
                        help="path to the YAML config (default: %(default)s)")
    parser.add_argument("--dashboard", action="store_true",
                        help="open the web dashboard instead of starting the services right away")
    parser.add_argument("--dashboard-host", default="127.0.0.1",
                        help="dashboard address (default: %(default)s - this machine only)")
    parser.add_argument("--dashboard-port", type=int, default=8787,
                        help="dashboard port (default: %(default)s)")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(run(args.config, args.dashboard, args.dashboard_host, args.dashboard_port))
    except ConfigError as e:
        print(f"[ERROR] {e}", flush=True)
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"[ERROR] Config file not found: {e.filename}", flush=True)
        sys.exit(2)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[+] Program ended")


if __name__ == "__main__":
    main()
