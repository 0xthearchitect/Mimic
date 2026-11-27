"""The dashboard's HTTP side: aiohttp on the honeypot's own event loop.

Security model (docs/ARCHITECTURE.md §6): localhost by default, a per-start
access token exchanged for an HttpOnly cookie, Host and Origin checks, a
strict CSP, and no third-party requests.
"""
import asyncio
import hmac
import ipaddress
import secrets
from pathlib import Path
from typing import Optional, Set

from aiohttp import web

from core import blocklist
from core.config_schema import ConfigError
from dashboard.store import Store

STATIC = Path(__file__).parent / "static"
COOKIE = "mimic_session"
POLL_SECONDS = 1.0     # how often the JSONL files are tailed; also the max update rate

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; script-src 'self'; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Dashboard:
    def __init__(self, controller, host: str = "127.0.0.1", port: int = 8787,
                 store: Optional[Store] = None, token: Optional[str] = None):
        self.controller = controller
        self.host = host
        self.port = port
        self.store = store or Store()
        self.token = token or secrets.token_urlsafe(24)
        self._subscribers: Set[asyncio.Queue] = set()
        self._runner: Optional[web.AppRunner] = None
        self._poller: Optional[asyncio.Task] = None
        self.app = self._build_app()

    # --- app -----------------------------------------------------------------

    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[self._guard], client_max_size=256 * 1024)
        r = app.router
        r.add_get("/", self.index)
        r.add_get("/api/status", self.api_status)
        r.add_get("/api/stage", self.api_stage)
        r.add_get("/api/visitor/{ip}", self.api_visitor)
        r.add_get("/api/captures", self.api_captures)
        r.add_get("/api/config", self.api_config)
        r.add_put("/api/config", self.api_save_config)
        r.add_post("/api/start", self.api_start)
        r.add_post("/api/stop", self.api_stop)
        r.add_post("/api/block", self.api_block)
        r.add_post("/api/unblock", self.api_unblock)
        r.add_get("/api/events", self.api_events)
        r.add_static("/static", STATIC, follow_symlinks=False, show_index=False)
        return app

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/?token={self.token}"

    def _allowed_hosts(self) -> Set[str]:
        names = {"127.0.0.1", "localhost", "[::1]", self.host, f"[{self.host}]"}
        return {f"{n}:{self.port}" for n in names}

    @web.middleware
    async def _guard(self, request: web.Request, handler):
        # DNS rebinding: a hostile page can't make the browser send our Host header.
        if request.host not in self._allowed_hosts():
            return web.Response(status=421, text="Unknown host")

        # Exchange the one-time link for a cookie, then drop the token from the URL.
        token = request.query.get("token")
        if request.path == "/" and token is not None:
            if not hmac.compare_digest(token, self.token):
                return web.Response(status=403, text="Wrong token. Use the link printed in the terminal.")
            resp = web.Response(status=303, headers={"Location": "/", "Referrer-Policy": "no-referrer"})
            resp.set_cookie(COOKIE, self.token, httponly=True, samesite="Strict", path="/")
            return resp

        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), self.token):
            return web.Response(status=401, content_type="text/plain",
                                text="MIMIC dashboard: open the link printed in the terminal "
                                     "(it changes every time MIMIC starts).")

        # Cross-site requests: state changes must come from our own page.
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("Origin")
            if origin is None or origin.split("://", 1)[-1] not in self._allowed_hosts():
                return web.json_response({"error": "cross-origin request refused"}, status=403)

        resp = await handler(request)
        if resp.prepared:          # streams (SSE) set their own headers
            return resp
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # --- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        await self.store.call(self.store.ingest)
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        self._poller = asyncio.create_task(self._poll())
        if not _is_loopback(self.host):
            print("\n" + "!" * 70)
            print(f"[!] The dashboard is listening on {self.host}, not only on this machine.")
            print("[!] Anyone who can reach it and steals the link controls the honeypot.")
            print("[!] Prefer the default 127.0.0.1 and an SSH tunnel.")
            print("!" * 70)
        print(f"\n[OK] Dashboard: {self.url}\n")

    async def stop(self) -> None:
        if self._poller:
            self._poller.cancel()
        for q in list(self._subscribers):
            q.put_nowait(None)
        if self._runner:
            await self._runner.cleanup()
        await asyncio.get_running_loop().run_in_executor(None, self.store.close)

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                if await self.store.call(self.store.ingest):
                    self._notify("events")
            except Exception as e:  # never let a bad line stop the dashboard
                print(f"[!] Dashboard ingest error: {e}")

    def _notify(self, what: str) -> None:
        for q in list(self._subscribers):
            if q.empty():          # one pending notice is enough: the page re-fetches
                q.put_nowait(what)

    # --- handlers ------------------------------------------------------------

    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    async def api_status(self, request):
        status = self.controller.status()
        status["blocked"] = blocklist.all_blocked()
        return web.json_response(status)

    async def api_stage(self, request):
        s = self.store
        house, script, headline = await s.call(lambda: (s.house(), s.script(), s.headline()))
        return web.json_response({"house": house, "script": script, "headline": headline,
                                  "blocked": blocklist.all_blocked()})

    async def api_visitor(self, request):
        try:
            ip = blocklist.normalize(request.match_info["ip"])
        except ValueError:
            return web.json_response({"error": "not an IP address"}, status=400)
        rows = await self.store.call(self.store.visitor_events, ip)
        return web.json_response({"ip": ip, "events": rows, "blocked": blocklist.is_blocked(ip)})

    async def api_captures(self, request):
        return web.json_response(await self.store.call(self.store.captures))

    async def api_config(self, request):
        return web.json_response({"config": self.controller.config, "running": self.controller.running})

    async def api_save_config(self, request):
        body = await _json_body(request)
        config = body.get("config") if isinstance(body, dict) else None
        if not isinstance(config, dict):
            return web.json_response({"errors": ["Body must be {\"config\": {...}}"]}, status=400)
        try:
            self.controller.save_config(config)
        except ConfigError as e:
            return web.json_response({"errors": e.errors}, status=400)
        except RuntimeError as e:
            return web.json_response({"errors": [str(e)]}, status=409)
        return web.json_response({"ok": True})

    async def api_start(self, request):
        if self.controller.running:
            return web.json_response({"errors": ["Already running"]}, status=409)
        results = await self.controller.start_all_services()
        self._notify("status")
        return web.json_response({"running": self.controller.running, "results": results})

    async def api_stop(self, request):
        await self.controller.stop()
        self._notify("status")
        return web.json_response({"running": False})

    async def api_block(self, request):
        return await self._change_block(request, blocklist.block)

    async def api_unblock(self, request):
        return await self._change_block(request, blocklist.unblock)

    async def _change_block(self, request, action):
        body = await _json_body(request)
        try:
            ip = action(body.get("ip", "") if isinstance(body, dict) else "")
        except ValueError:
            return web.json_response({"errors": ["Not an IP address"]}, status=400)
        self._notify("status")
        return web.json_response({"ip": ip, "blocked": blocklist.all_blocked()})

    async def api_events(self, request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-store",
                                           "Content-Security-Policy": CSP,
                                           "X-Content-Type-Options": "nosniff"})
        await resp.prepare(request)
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(q)
        try:
            await resp.write(b"retry: 3000\n\n")
            while True:
                try:
                    what = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    await resp.write(b": keep-alive\n\n")
                    continue
                if what is None:
                    break
                await resp.write(f"event: changed\ndata: {what}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._subscribers.discard(q)
        return resp


async def _json_body(request):
    try:
        return await request.json()
    except ValueError:
        return None


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
