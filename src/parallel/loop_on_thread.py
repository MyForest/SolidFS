import asyncio
from threading import Thread


class LoopOnThread(Thread):
    def __init__(self) -> None:
        """
        We need to allow fuselib to use it's own threads.
        We need to avoid putting anything on those threads that we want to ensure runs.
        By creating the event loop on another thread we can use asyncio and event loops.
        This is more resource-friendly than creating a thread for each parallel thing.
        """

        self._loop = asyncio.new_event_loop()
        """A separate event loop serviced by this Thread"""

        # It's important it's a daemon so the app closes
        super().__init__(
            None,
            self._run_loop_forever,
            LoopOnThread.__name__,
            daemon=True,
        )

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def _run_loop_forever(self):
        """Associate the event loop with the thread we've created for it and run the loop so it can process tasks"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
