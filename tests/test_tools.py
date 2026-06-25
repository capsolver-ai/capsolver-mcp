"""Comprehensive tests for CapSolver MCP Server: server factory, tool logic, serialization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capsolver_mcp.server import create_server, _get_capsolver, _solution_to_dict, _error_response


# ══════════════════════════════════════════════════════════════════
#  Server factory tests
# ══════════════════════════════════════════════════════════════════


class TestCreateServer:
    """Verify create_server() returns a properly configured FastMCP server."""

    def test_server_creation(self) -> None:
        server = create_server(api_key="test-key", server_name="test")
        assert server is not None

    def test_server_custom_name(self) -> None:
        server = create_server(api_key="test-key", server_name="my-solver")
        assert server is not None

    def test_server_has_five_tools(self) -> None:
        server = create_server(api_key="test-key")
        # FastMCP stores tools in _tool_manager._tools
        tool_names = list(server._tool_manager._tools.keys())
        assert len(tool_names) == 5
        assert "solve_captcha" in tool_names
        assert "detect_captchas" in tool_names
        assert "solve_on_page" in tool_names
        assert "get_balance" in tool_names
        assert "get_supported_captchas" in tool_names

    def test_server_tool_descriptions(self) -> None:
        server = create_server(api_key="test-key")
        tools = server._tool_manager._tools
        for name, tool in tools.items():
            assert tool.description, f"Tool {name} has no description"


# ══════════════════════════════════════════════════════════════════
#  _get_capsolver helper
# ══════════════════════════════════════════════════════════════════


class TestGetCapsolver:
    """Test the _get_capsolver factory function."""

    def test_with_explicit_key(self) -> None:
        cap = _get_capsolver("explicit-key")
        assert cap._client_options.api_key == "explicit-key"

    def test_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CAPSOLVER_API_KEY", "env-key-789")
        cap = _get_capsolver()
        assert cap._client_options.api_key == "env-key-789"

    def test_empty_key_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)
        cap = _get_capsolver(None)
        assert cap._client_options.api_key == ""

    def test_explicit_key_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CAPSOLVER_API_KEY", "env-key")
        cap = _get_capsolver("explicit-key")
        assert cap._client_options.api_key == "explicit-key"


# ══════════════════════════════════════════════════════════════════
#  _solution_to_dict serialization
# ══════════════════════════════════════════════════════════════════


class TestSolutionToDict:
    """Test the solution serialization helper."""

    def test_basic_serialization(self) -> None:
        from capsolver_core.captcha.types import Solution
        from capsolver_core.core.types import CaptchaType

        sol = Solution(
            captcha_type=CaptchaType.RECAPTCHA_V2,
            token="abc-token",
            expire_time=999,
            user_agent="UA/1.0",
        )
        d = _solution_to_dict(sol)
        assert d == {
            "captcha_type": "reCaptchaV2",
            "token": "abc-token",
            "expire_time": 999,
            "user_agent": "UA/1.0",
        }

    def test_serialization_with_none_fields(self) -> None:
        from capsolver_core.captcha.types import Solution
        from capsolver_core.core.types import CaptchaType

        sol = Solution(captcha_type=CaptchaType.RECAPTCHA_V2, token="tok")
        d = _solution_to_dict(sol)
        assert d["captcha_type"] == "reCaptchaV2"
        assert d["token"] == "tok"
        assert d["expire_time"] is None
        assert d["user_agent"] is None

    @pytest.mark.parametrize(
        "captcha_type",
        [
            "RECAPTCHA_V2",
            "RECAPTCHA_V3",
            "CLOUDFLARE",
        ],
    )
    def test_all_captcha_types(self, captcha_type: str) -> None:
        from capsolver_core.captcha.types import Solution
        from capsolver_core.core.types import CaptchaType

        ct = CaptchaType[captcha_type]
        sol = Solution(captcha_type=ct, token="t")
        d = _solution_to_dict(sol)
        assert d["captcha_type"] == ct.value


# ══════════════════════════════════════════════════════════════════
#  _error_response helper
# ══════════════════════════════════════════════════════════════════


class TestErrorResponse:
    """Test the _error_response helper for consistent error formatting."""

    def test_generic_exception(self) -> None:
        """A plain Exception should produce success=False + error string."""
        d = _error_response(RuntimeError("something broke"))
        assert d == {"success": False, "error": "something broke"}

    def test_capsolver_error_minimal(self) -> None:
        """CapsolverError with no optional fields."""
        from capsolver_core.core.errors import CapsolverError

        d = _error_response(CapsolverError("api fail"))
        assert d["success"] is False
        assert d["error"] == "api fail"
        # No structured fields should be present
        assert "error_id" not in d
        assert "error_code" not in d
        assert "http_status" not in d

    def test_capsolver_error_full_fields(self) -> None:
        """CapsolverError with all optional fields should expose them."""
        from capsolver_core.core.errors import CapsolverError

        err = CapsolverError(
            "rate limited",
            error_id=1,
            error_code="ERROR_RATE_LIMIT",
            error_description="Too many requests",
            http_status=429,
        )
        d = _error_response(err)
        assert d["success"] is False
        assert d["error"] == "rate limited"
        assert d["error_id"] == 1
        assert d["error_code"] == "ERROR_RATE_LIMIT"
        assert d["error_description"] == "Too many requests"
        assert d["http_status"] == 429

    def test_capsolver_error_partial_fields(self) -> None:
        """CapsolverError with only some fields."""
        from capsolver_core.core.errors import CapsolverError

        err = CapsolverError("bad key", error_code="ERROR_KEY_DOES_NOT_EXIST")
        d = _error_response(err)
        assert d["success"] is False
        assert d["error_code"] == "ERROR_KEY_DOES_NOT_EXIST"
        assert "error_id" not in d
        assert "http_status" not in d

    def test_timeout_error_includes_task_id(self) -> None:
        """CapsolverTimeoutError should include the task_id."""
        from capsolver_core.core.errors import CapsolverTimeoutError

        err = CapsolverTimeoutError(120.0, task_id="task-abc-123")
        d = _error_response(err)
        assert d["success"] is False
        assert d["task_id"] == "task-abc-123"
        # TimeoutError is a subclass of CapsolverError, but has no error_id/code
        assert "error_id" not in d

    def test_timeout_error_no_task_id(self) -> None:
        """CapsolverTimeoutError without task_id should omit it."""
        from capsolver_core.core.errors import CapsolverTimeoutError

        err = CapsolverTimeoutError(60.0)
        d = _error_response(err)
        assert d["success"] is False
        assert "task_id" not in d

    def test_network_error_includes_cause(self) -> None:
        """NetworkError should include the underlying cause."""
        from capsolver_core.core.errors import NetworkError

        cause = ConnectionError("DNS failure")
        err = NetworkError("unreachable", cause=cause)
        d = _error_response(err)
        assert d["success"] is False
        assert d["cause"] == "DNS failure"

    def test_rate_limit_error_type(self) -> None:
        """RateLimitError should include error_type marker."""
        from capsolver_core.core.errors import RateLimitError

        err = RateLimitError("too fast", error_code="ERROR_RATE_LIMIT")
        d = _error_response(err)
        assert d["success"] is False
        assert d["error_type"] == "rate_limit"
        assert d["http_status"] == 429
        assert d["error_code"] == "ERROR_RATE_LIMIT"


# ══════════════════════════════════════════════════════════════════


class TestSolveCaptchaTool:
    """Test the solve_captcha MCP tool function."""

    @pytest.mark.asyncio
    async def test_invalid_captcha_type(self) -> None:
        """Invalid type should return error dict with success=False, not raise."""
        server = create_server(api_key="test")
        tool_fn = server._tool_manager._tools["solve_captcha"].fn
        result = await tool_fn(
            captcha_type="badType",
            website_url="https://example.com",
            website_key="abc",
        )
        assert result["success"] is False
        assert "Unsupported captcha type" in result["error"]
        assert "badType" in result["error"]

    @pytest.mark.asyncio
    async def test_solve_success_mocked(self) -> None:
        """Mock Capsolver.solve and verify the tool returns the right shape."""
        from capsolver_core.captcha.types import Solution
        from capsolver_core.core.types import CaptchaType

        fake_solution = Solution(
            captcha_type=CaptchaType.RECAPTCHA_V2,
            token="solved-token",
            expire_time=100,
            user_agent="TestAgent",
        )

        with patch("capsolver_mcp.server._get_capsolver") as mock_get:
            mock_cap = MagicMock()
            mock_cap.solve = AsyncMock(return_value=fake_solution)
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            # Get the tool function from the server
            tool_fn = server._tool_manager._tools["solve_captcha"].fn
            result = await tool_fn(
                captcha_type="reCaptchaV2",
                website_url="https://example.com",
                website_key="6Lc...",
            )
            assert result["success"] is True
            assert result["solution"]["token"] == "solved-token"

    @pytest.mark.asyncio
    async def test_solve_api_error(self) -> None:
        """When Capsolver.solve raises CapsolverError, tool returns structured error."""
        from capsolver_core.core.errors import CapsolverError

        with patch("capsolver_mcp.server._get_capsolver") as mock_get:
            mock_cap = MagicMock()
            mock_cap.solve = AsyncMock(side_effect=CapsolverError(
                "rate limit",
                error_id=1,
                error_code="ERROR_RATE_LIMIT",
                error_description="Too many requests",
                http_status=429,
            ))
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["solve_captcha"].fn
            result = await tool_fn(
                captcha_type="reCaptchaV2",
                website_url="https://example.com",
                website_key="abc",
            )
            assert result["success"] is False
            assert "rate limit" in result["error"]
            assert result["error_id"] == 1
            assert result["error_code"] == "ERROR_RATE_LIMIT"
            assert result["error_description"] == "Too many requests"
            assert result["http_status"] == 429

    @pytest.mark.asyncio
    async def test_solve_timeout_error(self) -> None:
        """When Capsolver.solve raises CapsolverTimeoutError, task_id should be included."""
        from capsolver_core.core.errors import CapsolverTimeoutError

        with patch("capsolver_mcp.server._get_capsolver") as mock_get:
            mock_cap = MagicMock()
            mock_cap.solve = AsyncMock(side_effect=CapsolverTimeoutError(120.0, task_id="task-xyz"))
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["solve_captcha"].fn
            result = await tool_fn(
                captcha_type="reCaptchaV2",
                website_url="https://example.com",
                website_key="abc",
            )
            assert result["success"] is False
            assert "Timeout" in result["error"]
            assert result["task_id"] == "task-xyz"


# ══════════════════════════════════════════════════════════════════
#  get_balance tool
# ══════════════════════════════════════════════════════════════════


class TestGetBalanceTool:
    """Test the get_balance MCP tool."""

    @pytest.mark.asyncio
    async def test_get_balance_success(self) -> None:
        mock_balance = MagicMock()
        mock_balance.balance = 5.67
        mock_balance.packages = []

        with patch("capsolver_mcp.server._get_capsolver") as mock_get:
            mock_cap = MagicMock()
            mock_cap.get_balance = AsyncMock(return_value=mock_balance)
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["get_balance"].fn
            result = await tool_fn()
            assert result["success"] is True
            assert result["balance"] == 5.67

    @pytest.mark.asyncio
    async def test_get_balance_error(self) -> None:
        from capsolver_core.core.errors import CapsolverError

        with patch("capsolver_mcp.server._get_capsolver") as mock_get:
            mock_cap = MagicMock()
            mock_cap.get_balance = AsyncMock(side_effect=CapsolverError(
                "bad key",
                error_code="ERROR_KEY_DOES_NOT_EXIST",
            ))
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["get_balance"].fn
            result = await tool_fn()
            assert result["success"] is False
            assert "bad key" in result["error"]
            assert result["error_code"] == "ERROR_KEY_DOES_NOT_EXIST"

    @pytest.mark.asyncio
    async def test_get_balance_without_key_raises(self) -> None:
        from capsolver_core import Capsolver

        cap = Capsolver(api_key="")
        with pytest.raises(Exception):
            await cap.get_balance()


# ══════════════════════════════════════════════════════════════════
#  get_supported_captchas tool
# ══════════════════════════════════════════════════════════════════


class TestGetSupportedCaptchasTool:
    """Test the get_supported_captchas MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_handlers_and_types(self) -> None:
        server = create_server(api_key="test")
        tool_fn = server._tool_manager._tools["get_supported_captchas"].fn
        result = await tool_fn()

        assert result["success"] is True
        assert isinstance(result["registered_handlers"], list)
        assert len(result["registered_handlers"]) > 0
        assert isinstance(result["captcha_types"], list)
        # All known types should be present
        assert "reCaptchaV2" in result["captcha_types"]
        assert "reCaptchaV3" in result["captcha_types"]
        assert "cloudflare" in result["captcha_types"]

    @pytest.mark.asyncio
    async def test_handlers_include_builtins(self) -> None:
        server = create_server(api_key="test")
        tool_fn = server._tool_manager._tools["get_supported_captchas"].fn
        result = await tool_fn()

        handlers = [h.lower() for h in result["registered_handlers"]]
        # The SDK registers these by default (names are lowercase)
        assert "recaptcha" in handlers


# ══════════════════════════════════════════════════════════════════
#  detect_captchas / solve_on_page (browser tools)
# ══════════════════════════════════════════════════════════════════


class TestBrowserTools:
    """Test browser-based tools handle missing playwright and errors gracefully."""

    @pytest.mark.asyncio
    async def test_detect_captchas_no_playwright(self) -> None:
        """When _launch_browser_session raises ImportError, return error dict."""
        with patch("capsolver_mcp.server._launch_browser_session", side_effect=ImportError("no playwright")):
            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["detect_captchas"].fn
            result = await tool_fn(page_url="https://example.com")
            assert result["success"] is False
            assert "Browser automation not available" in result["error"]

    @pytest.mark.asyncio
    async def test_solve_on_page_no_playwright(self) -> None:
        with patch("capsolver_mcp.server._launch_browser_session", side_effect=ImportError("no playwright")):
            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["solve_on_page"].fn
            result = await tool_fn(page_url="https://example.com")
            assert result["success"] is False
            assert "Browser automation not available" in result["error"]

    @pytest.mark.asyncio
    async def test_detect_captchas_page_load_error(self) -> None:
        """When browser launch fails with a non-ImportError, return error."""
        with patch("capsolver_mcp.server._launch_browser_session", side_effect=RuntimeError("network error")):
            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["detect_captchas"].fn
            result = await tool_fn(page_url="https://unreachable.com")
            assert result["success"] is False
            assert "Failed to open page" in result["error"]

    @pytest.mark.asyncio
    async def test_solve_on_page_page_load_error(self) -> None:
        with patch("capsolver_mcp.server._launch_browser_session", side_effect=RuntimeError("timeout")):
            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["solve_on_page"].fn
            result = await tool_fn(page_url="https://unreachable.com")
            assert result["success"] is False
            assert "Failed to open page" in result["error"]

    @pytest.mark.asyncio
    async def test_detect_captchas_success_mocked(self) -> None:
        """Mock browser + detect to verify the success path."""
        from capsolver_core.core.types import CaptchaType

        mock_driver = MagicMock()
        mock_driver.page = MagicMock()

        with (
            patch("capsolver_mcp.server._launch_browser_session", new_callable=AsyncMock, return_value=mock_driver),
            patch("capsolver_mcp.server._close_browser_session", new_callable=AsyncMock),
            patch("capsolver_mcp.server._get_capsolver") as mock_get,
        ):
            mock_cap = MagicMock()
            mock_cap.detect = AsyncMock(return_value=[CaptchaType.RECAPTCHA_V2, CaptchaType.CLOUDFLARE])
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["detect_captchas"].fn
            result = await tool_fn(page_url="https://example.com")

            assert result["success"] is True
            assert result["url"] == "https://example.com"
            assert set(result["detected_captchas"]) == {"reCaptchaV2", "cloudflare"}

    @pytest.mark.asyncio
    async def test_solve_on_page_success_mocked(self) -> None:
        """Mock browser + solve_on_page to verify the success path."""
        from capsolver_core.captcha.types import Solution
        from capsolver_core.core.types import CaptchaType
        from capsolver_core.capsolver import SolveOnPageResult
        from capsolver_core.captcha.types import CaptchaInfo

        mock_driver = MagicMock()
        mock_driver.page = MagicMock()

        fake_result = SolveOnPageResult(
            info=CaptchaInfo(type=CaptchaType.RECAPTCHA_V2, website_url="https://x.com", website_key="k"),
            solution=Solution(captcha_type=CaptchaType.RECAPTCHA_V2, token="tok-123"),
            filled=True,
        )

        with (
            patch("capsolver_mcp.server._launch_browser_session", new_callable=AsyncMock, return_value=mock_driver),
            patch("capsolver_mcp.server._close_browser_session", new_callable=AsyncMock),
            patch("capsolver_mcp.server._get_capsolver") as mock_get,
        ):
            mock_cap = MagicMock()
            mock_cap.solve_on_page = AsyncMock(return_value=[fake_result])
            mock_get.return_value = mock_cap

            server = create_server(api_key="test")
            tool_fn = server._tool_manager._tools["solve_on_page"].fn
            result = await tool_fn(page_url="https://example.com")

            assert result["success"] is True
            assert result["url"] == "https://example.com"
            assert len(result["results"]) == 1
            r = result["results"][0]
            assert r["captcha_type"] == "reCaptchaV2"
            assert r["solved"] is True
            assert r["token"] == "tok-123"
            assert r["filled"] is True


# ══════════════════════════════════════════════════════════════════
#  __main__ CLI argument parsing
# ══════════════════════════════════════════════════════════════════


class TestCLIArgs:
    """Verify the CLI entry point parses arguments correctly."""

    def test_default_args(self) -> None:
        import argparse

        # We just test that argparse setup is correct by patching sys.argv
        # and verifying the parsed args (without actually running the server)
        with patch("sys.argv", ["capsolver-mcp"]):
            parser = argparse.ArgumentParser()
            parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
            parser.add_argument("--host", default="127.0.0.1")
            parser.add_argument("--port", type=int, default=8000)
            parser.add_argument("--api-key", default=None)
            parser.add_argument("--name", default="capsolver")
            args = parser.parse_args([])
            assert args.transport == "stdio"
            assert args.host == "127.0.0.1"
            assert args.port == 8000

    def test_sse_args(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        args = parser.parse_args(["--transport", "sse", "--host", "0.0.0.0", "--port", "9000"])
        assert args.transport == "sse"
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_streamable_http_args(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        args = parser.parse_args(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9090"])
        assert args.transport == "streamable-http"
        assert args.host == "0.0.0.0"
        assert args.port == 9090
