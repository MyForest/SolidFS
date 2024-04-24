import datetime
import os
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture(scope="package")
def test_root_path() -> Generator[Path, None, None]:
    """Try to avoid polluting the Pod too much by moving the test out of the way"""
    session_moment = datetime.datetime.now(datetime.UTC).isoformat()
    path_friendly_session_moment = session_moment.replace(":", "_").replace(" ", "_").replace("+", "_")
    root = Path("/data") / "test" / "SolidFS" / path_friendly_session_moment
    try:
        os.makedirs(root)
    except:
        print(f"Unable to create root folder {root}")
        raise
    yield root

    try:
        # Will leave all the intermediate dirs in place that it created
        # Don't use removedirs because it might prune beyond what was created
        os.rmdir(root)
    except:
        print(f"Unable to remove root folder {root}")
        raise


@pytest.fixture(scope="package")
def page_size() -> int:
    """The size of chunks sent to and from the server. Notably this is used to ensure the tests send things bigger than one chunk."""
    return 131072
