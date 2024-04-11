import os
from time import time

import requests
import structlog


class SolidAuthentication:
    def __init__(self):
        self.__logger = structlog.getLogger(self.__class__.__name__)
        self.cached_token_value = None
        self.cached_token_expiry = None

    def authenticate_with_client_credentials(self):

        if self.cached_token_expiry is None or time() > self.cached_token_expiry:

            # Obtain client credentials from environment variables
            client_id = os.environ.get("SOLIDFS_CLIENT_ID")
            client_secret = os.environ.get("SOLIDFS_CLIENT_SECRET")

            if client_id is None or client_secret is None:
                raise Exception("Please provide the 'SOLIDFS_CLIENT_ID' and 'SOLIDFS_CLIENT_SECRET' environment variables to use as credentials")

            token_url = os.environ.get("SOLIDFS_TOKEN_URL")
            if token_url is None:
                raise Exception("Please provide the 'SOLIDFS_TOKEN_URL' where the credentials should be sent to get a token")

            time_before_request = time()

            self.__logger.debug("Requesting access token", client_id=client_id, token_url=token_url, time_before_request=time_before_request)
            auth_response = requests.post(token_url, auth=(client_id, client_secret), data={"grant_type": "client_credentials"})

            if auth_response.status_code == 200:
                result = auth_response.json()
                self.cached_token_expiry = time_before_request + int(result["expires_in"])
                self.cached_token_value = result["access_token"]
                self.__logger.debug("Generated access token", expiry=self.cached_token_expiry, token_type=result.get("token_type"), scope=result.get("scope"))
            else:
                raise Exception(f"Authentication failed with error {auth_response.status_code}: {auth_response.text}")

        return self.cached_token_value
