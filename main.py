import argparse
import asyncio
import sys

from core.config_schema import ConfigError
from core.controller import MIMICController


async def main_simple(config_path: str):
    controller = MIMICController(config_path)
    try:
        await controller.start_all_services()
        print("\n[OK] Honeypot running -- Ctrl+C to stop\n")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Ctrl+C received")
    finally:
        print("[*] Shutting down MIMIC...")
        await controller.stop()
        print("[OK] Shutdown complete")


def main():
    parser = argparse.ArgumentParser(description="MIMIC honeypot (headless)")
    parser.add_argument("-c", "--config", default="config/honeypot.yaml",
                        help="path to the YAML config (default: %(default)s)")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main_simple(args.config))
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
