import requests
import structlog

from solid_authentication import SolidAuthentication


class SolidRequest:
    def __init__(self, session_identifier: str):
        self.__logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.__common_headers = {"x-request-id": session_identifier, "User-Agent": "SolidFS/v0.0.1"}
        self.__authentication = SolidAuthentication()

    def __get_auth_token(self):
        return self.__authentication.authenticate_with_client_credentials()

    def request(self, method: str, url: str, headers: dict[str, str] = {}, data: bytes | None = None) -> requests.Response:

        request_headers = (
            self.__common_headers
            | {
                "Authorization": f"Bearer {self.__get_auth_token()}",
            }
            | headers
        )

        with structlog.contextvars.bound_contextvars(method=method, url=url, headers_supplied=sorted(request_headers.keys())):

            self.__logger.debug("Sending request")

            response = requests.request(
                method,
                url,
                headers=request_headers,
                data=data,
            )

            self.__logger.debug("Response", headers_returned=sorted(response.headers.keys()), status_code=response.status_code)

        return response
