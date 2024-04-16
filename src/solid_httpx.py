import asyncio
import os

import hishel
import httpx
import structlog

from http_exception import HTTPStatusCodeToException
from observability.tracing import Tracing
from solid_authentication import SolidAuthentication
from solid_requestor import SolidRequestor, SolidResponse, requestor_daemon


class SolidHTTPX(SolidRequestor):
    def __init__(self, session_identifier: str):
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self._common_headers = {"Session-Identifier": session_identifier, "User-Agent": "SolidFS/v0.0.1"}
        self._authentication = SolidAuthentication(session_identifier)
        limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
        if os.environ.get("SOLIDFS_CONTENT_CACHING") == "1":
            self._logger.info(f"Using content caching", implementation=hishel.AsyncCacheClient)
            self._client: httpx.AsyncClient = hishel.AsyncCacheClient(limits=limits, http2=True)
        else:
            self._client = httpx.AsyncClient(limits=limits, http2=True)

    def _get_auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._authentication.authenticate_with_client_credentials()}",
        }

    def request(self, method: str, url: str, extra_headers: dict[str, str] = {}, data: bytes | None = None) -> SolidResponse:

        headers = self._common_headers | self._get_auth_headers() | Tracing.get_trace_headers() | extra_headers

        with structlog.contextvars.bound_contextvars(method=method, url=url, headers_supplied=sorted(headers.keys())):

            self._logger.debug("Sending request")

            f = asyncio.run_coroutine_threadsafe(
                self._client.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                ),
                requestor_daemon.loop,
            )
            response = f.result()
            # , response_fields=response.__attrs__
            self._logger.debug("Response", headers_returned=sorted(response.headers.keys()), status_code=response.status_code)

            HTTPStatusCodeToException.raise_exception_for_failed_requests(response.status_code)

            return response
