"""Service ownership and cleanup for a single local MCP runtime."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from capsolver_mcp.api import ApiClient
from capsolver_mcp.api.offline import OfflineProvider
from capsolver_mcp.catalog import Catalog
from capsolver_mcp.config import Settings
from capsolver_mcp.services.task_service import TaskService
from capsolver_mcp.services.official_catalog import OfficialCatalog
from capsolver_mcp.storage.task_store import TaskStore
from capsolver_mcp.security import CURRENT_OPERATOR

if TYPE_CHECKING:
    from capsolver_mcp.browser.session_manager import BrowserManager


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.allow_tasks = True
        self.allow_browser = True
        self.catalog = Catalog()
        self.official_catalog = OfficialCatalog(self.catalog)
        self._http: httpx.AsyncClient | None = None
        self._service: TaskService | None = None
        self._store: TaskStore | None = None
        self._api: ApiClient | None = None
        self._browser: BrowserManager | None = None
        self._browsers: dict[str, BrowserManager] = {}
        self._services: dict[str, TaskService] = {}
        self._resources: list[tuple[ApiClient, TaskStore, httpx.AsyncClient | None]] = []
        self.task_slots = asyncio.Semaphore(settings.max_parallel_tasks)

    @property
    def browser(self) -> BrowserManager:
        if not self.allow_browser:
            raise ValueError("Use a separate browser MCP; this server only handles the CapSolver API.")
        owner = CURRENT_OPERATOR.get()
        if owner not in self._browsers:
            from capsolver_mcp.browser.session_manager import BrowserManager

            self._browsers[owner] = BrowserManager(self)
        self._browser = self._browsers[owner]
        return self._browsers[owner]

    @property
    def service(self) -> TaskService:
        if not self.allow_tasks:
            raise ValueError("Browser mode cannot call the provider. Use the core MCP for task operations.")
        owner = CURRENT_OPERATOR.get()
        if owner not in self._services:
            if not self.settings.api_key:
                raise ValueError("Configure CAPSOLVER_API_KEY first.")
            if self.settings.offline:
                self._http = httpx.AsyncClient(transport=httpx.MockTransport(OfflineProvider()), trust_env=False)
            self._api = ApiClient(self.settings.api_key, client=self._http,
                                  get_token_timeout=self.settings.get_token_timeout)
            self._store = TaskStore() if self.settings.offline else TaskStore(self.settings.state_dir / "tasks.sqlite3")
            self._service = TaskService(self._api, self._store, account_key=self.settings.api_key, scope=owner)
            self._services[owner] = self._service
            self._resources.append((self._api, self._store, self._http))
        return self._services[owner]

    async def aclose(self) -> None:
        for browser in self._browsers.values():
            await browser.close()
        self._browsers.clear()
        self._browser = None
        for api, store, client in self._resources:
            await api.aclose()
            if client:
                await client.aclose()
            store.close()
        self._resources.clear()
        self._services.clear()
        self._service = None
        self._store = None
        self._api = None
        self._http = None
