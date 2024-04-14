import asyncio
import json
from typing import Any

import structlog
import websockets

from http_exception import HTTPStatusCodeToException
from solid_activity import SolidActivity
from solid_request import SolidRequest
from solid_resource import Resource


class SolidWebsocket:
    @staticmethod
    def listen_for_notifications(requestor: SolidRequest, resource: Resource, websocket_event_loop: asyncio.AbstractEventLoop):

        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            response = requestor.request(
                "POST",
                "https://websocket.inrupt.com/",
                {"Content-Type": "application/json"},
                json.dumps({"topic": resource.uri}).encode(),
            )
            HTTPStatusCodeToException.raise_exception_for_failed_requests(response.status_code)
            topicSubscriptionInfo = response.json()

            # This is the key step to ensure the Coroutine gets run
            # If it's created on another thread it'll get deleted or blocked by fuselib work on those other threads
            asyncio.run_coroutine_threadsafe(SolidWebsocket._listen_for_websocket_responses(resource, topicSubscriptionInfo), websocket_event_loop)

    @staticmethod
    async def _listen_for_websocket_responses(resource: Resource, topicSubscriptionInfo: dict[str, Any]):
        logger = structlog.getLogger(SolidWebsocket.__name__)

        # with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
        logger.debug("Listening for notifications")
        async for websocket in websockets.connect(topicSubscriptionInfo["endpoint"], subprotocols=[topicSubscriptionInfo["subprotocol"]], ping_interval=50):
            async for message in websocket:
                try:
                    SolidActivity.parse_activity(resource, message)
                except:
                    logger.warning("Could not parse message", ws_message=message, exc_info=True)
                    pass
