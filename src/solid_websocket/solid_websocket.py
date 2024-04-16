import asyncio
import json
import os
from typing import Any

import structlog
import websockets

from http_exception import HTTPStatusCodeToException
from parallel.loop_on_thread import LoopOnThread
from solid_activity import SolidActivity
from solid_requestor import SolidRequestor
from solid_resource import Resource

# Global state
websocket_daemon = LoopOnThread()
"""A separate event loop for efficiently handling websockets"""


class SolidWebsocket:
    @staticmethod
    def set_up_listener_for_notifications(requestor: SolidRequestor, resource: Resource):
        # TODO: Should use discovery to find websocket endpoint
        if os.environ.get("SOLIDFS_ENABLE_WEBSOCKET_NOTIFICATIONS") != "1":
            return
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
                websocket_daemon.loop,
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
