import os
from time import time

import requests
import structlog

from http_exception import HTTPStatusCodeException, UnauthorizedException
from observability.tracing import Tracing


class SolidAuthentication:
    def __init__(self, session_identifier: str):
        self.__logger = structlog.getLogger(self.__class__.__name__)
        self.cached_token_value = None
        self.cached_token_expiry = None
        self.__common_headers = {"Session-Identifier": session_identifier, "User-Agent": "SolidFS/v0.0.1"}

    def authenticate_with_client_credentials(self) -> str | None:

        # CSS docs: https://communitysolidserver.github.io/CommunitySolidServer/6.x/usage/client-credentials/

        if self.cached_token_expiry is None or time() > self.cached_token_expiry:

            # Obtain client credentials from environment variables
            client_id = os.environ.get("SOLIDFS_CLIENT_ID", "")
            if len(client_id) == 0:
                self.__logger.info("No authentication will be used because `SOLIDFS_CLIENT_ID` was not supplied")
                return None
            client_secret = os.environ.get("SOLIDFS_CLIENT_SECRET")

            if client_secret is None:
                raise Exception("Please provide the 'SOLIDFS_CLIENT_SECRET' environment variable to use as credentials")

            token_url = os.environ.get("SOLIDFS_TOKEN_URL")
            if token_url is None:
                raise Exception("Please provide the 'SOLIDFS_TOKEN_URL' where the credentials should be sent to get a token")

            time_before_request = time()
            headers = self.__common_headers | Tracing.get_trace_headers()
            self.__logger.debug("Requesting access token", client_id=client_id, token_url=token_url, time_before_request=time_before_request)
            auth_response = requests.post(token_url, headers=headers, auth=(client_id, client_secret), data={"grant_type": "client_credentials"})

            match auth_response.status_code:
                case 200:
                    result = auth_response.json()
                    self.cached_token_expiry = time_before_request + int(result["expires_in"])
                    self.cached_token_value = result["access_token"]
                    self.__logger.debug("Generated access token", expiry=self.cached_token_expiry, token_type=result.get("token_type"), scope=result.get("scope"))
                case 401:
                    raise UnauthorizedException(auth_response.text)
                case _:
                    raise HTTPStatusCodeException(auth_response.status_code, auth_response.text)

        return self.cached_token_value
