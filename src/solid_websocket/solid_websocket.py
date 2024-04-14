import asyncio
import json
from threading import Thread
from typing import Any

import structlog
import websockets

from http_exception import HTTPStatusCodeToException
from solid_activity import SolidActivity
from solid_request import SolidRequest
from solid_resource import Resource

# Global state
websocket_loop = asyncio.new_event_loop()
"""A separate event loop for efficiently handling websockets"""


class SolidWebsocketDaemon(Thread):
    def __init__(self) -> None:
        """
        We need to allow fuselib to use it's own threads.
        We need to avoid putting anything on those threads that we want to ensure runs.
        By creating the event loop on another thread for Websockets we can use asyncio for websockets.
        This is more resource-friendly than creating a thread for each websocket.
        """
        super().__init__(
            None,
            SolidWebsocketDaemon.run_websocket_loop_forever,
            SolidWebsocketDaemon.__name__,
            args=[websocket_loop],
            daemon=True,
        )

    @staticmethod
    def run_websocket_loop_forever(websocket_loop: asyncio.AbstractEventLoop):
        """Associate the websocket event loop with the thread we've created for it and run the loop so it can process tasks"""
        asyncio.set_event_loop(websocket_loop)
        websocket_loop.run_forever()


class SolidWebsocket:
    @staticmethod
    def set_up_listener_for_notifications(requestor: SolidRequest, resource: Resource):
        # TODO: Should use discovery to find websocket endpoint
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
            # If it's created on the current thread it'll get deleted or blocked by fuselib work on those other threads
            asyncio.run_coroutine_threadsafe(
                SolidWebsocket._listen_for_websocket_responses(
                    resource,
                    topicSubscriptionInfo,
                ),
                websocket_loop,
            )

    @staticmethod
    async def _listen_for_websocket_responses(resource: Resource, topicSubscriptionInfo: dict[str, Any]):
        logger = structlog.getLogger(SolidWebsocket.__name__)

        logger.debug("Listening for notifications")
        async for websocket in websockets.connect(topicSubscriptionInfo["endpoint"], subprotocols=[topicSubscriptionInfo["subprotocol"]], ping_interval=50):
            async for message in websocket:
                try:
                    if isinstance(message, str):
                        SolidActivity.parse_activity(resource, message)
                except:
                    logger.warning("Could not parse message", ws_message=message, exc_info=True)
