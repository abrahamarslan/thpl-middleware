"""In-memory ZohoClient double for engine/outbox tests.

Mimics the real client's surface (get/post/put/delete/paginate) and records
every call so tests can assert on outbound traffic. Canned responses are
keyed by (method, path).
"""

import uuid
from collections.abc import AsyncIterator

from app.modules.zoho.core.exceptions import ZohoNotFoundError
from app.modules.zoho.core.schemas import ZohoPageContext, ZohoResponse


def make_response(data, *, has_more: bool = False, page: int = 1) -> ZohoResponse:
    return ZohoResponse(
        request_id=f"test-{uuid.uuid4().hex[:8]}",
        http_status=200,
        zoho_code=0,
        message="success",
        data=data,
        page_context=ZohoPageContext(page=page, per_page=200, has_more_page=has_more),
        raw={},
    )


class FakeZohoClient:
    def __init__(self) -> None:
        #: (method, path) -> ZohoResponse | list[ZohoResponse] (paged) | Exception
        self.responses: dict[tuple[str, str], object] = {}
        self.calls: list[dict] = []

    def stub(self, method: str, path: str, response) -> None:
        self.responses[(method.upper(), path)] = response

    def stub_list(self, path: str, pages: list[list[dict]]) -> None:
        """Stub a paginated list endpoint from raw record pages."""
        responses = [
            make_response(page_data, has_more=(i < len(pages) - 1), page=i + 1)
            for i, page_data in enumerate(pages)
        ]
        self.stub("GET", path, responses)

    async def _resolve(self, method: str, path: str, **kwargs) -> ZohoResponse:
        self.calls.append({"method": method, "path": path, **kwargs})
        stubbed = self.responses.get((method, path))
        if stubbed is None:
            raise ZohoNotFoundError(f"no stub for {method} {path}")
        if isinstance(stubbed, Exception):
            raise stubbed
        return stubbed

    async def get(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        response = await self._resolve("GET", path, params=params)
        if isinstance(response, list):  # paged stub asked without paginate()
            page = (params or {}).get("page", 1)
            return response[page - 1]
        return response

    async def post(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return await self._resolve("POST", path, json=json, params=params)

    async def put(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return await self._resolve("PUT", path, json=json, params=params)

    async def delete(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        return await self._resolve("DELETE", path, params=params)

    async def paginate(
        self, path: str, *, params: dict | None = None, per_page: int = 200, max_pages: int | None = None
    ) -> AsyncIterator[ZohoResponse]:
        page = 1
        while True:
            response = await self.get(path, params={**(params or {}), "page": page, "per_page": per_page})
            yield response
            ctx = response.page_context
            if ctx is None or not ctx.has_more_page:
                return
            page += 1
