import os

import cachecontrol
import requests
import structlog

from http_exception import HTTPStatusCodeToException
from observability.tracing import Tracing
from solid_authentication import SolidAuthentication
from solid_requestor import SolidRequestor, SolidResponse


class SolidRequest(SolidRequestor):
    def __init__(self, session_identifier: str):
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self._common_headers = {"Session-Identifier": session_identifier, "User-Agent": "SolidFS/v0.0.1"}
        self._authentication = SolidAuthentication(session_identifier)
        if os.environ.get("SOLIDFS_CONTENT_CACHING") == "1":
            self._logger.info(f"Using content caching", implementation=cachecontrol.CacheControl)
            self._session = cachecontrol.CacheControl(requests.Session())
        else:
            self._session = requests.Session()

    def _get_auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._authentication.authenticate_with_client_credentials()}",
        }

    def request(self, method: str, url: str, extra_headers: dict[str, str] = {}, data: bytes | None = None) -> SolidResponse:

        headers = self._common_headers | self._get_auth_headers() | Tracing.get_trace_headers() | extra_headers

        with structlog.contextvars.bound_contextvars(method=method, url=url, headers_supplied=sorted(headers.keys())):

            self._logger.debug("Sending request", accept=headers.get("Accept"))

            response = self._session.request(
                method,
                url,
                headers=headers,
                data=data,
            )

            content_size = len(response.content)
            content_length_header = headers.get("Content-Length")
            self._logger.debug(
                "Response",
                content_size=content_size,
                content_length_header=content_length_header,
                headers_returned=sorted(response.headers.keys()),
                status_code=response.status_code,
                response_fields=response.__attrs__,
            )

            # TODO: Sanitize server-generated exception to prevent attacks
            HTTPStatusCodeToException.raise_exception_for_failed_requests(response.status_code, response.text)

            return response
