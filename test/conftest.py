import datetime
import logging
import os
from pathlib import Path
import shutil
from typing import Generator

import pytest


@pytest.fixture(scope="session")
def session_root_path() -> Path:
    """Try to avoid polluting the Pod too much by moving the test out of the way"""
    session_moment = datetime.datetime.now(datetime.UTC).isoformat()
    path_friendly_session_moment = session_moment.replace(":", "_").replace(" ", "_").replace("+", "_")
    root = Path("/data") / "test" / "SolidFS" / path_friendly_session_moment
    return root


@pytest.fixture(scope="function", autouse=True)
def change_directory_to_test_specific_folder(session_root_path: Path, request: pytest.FixtureRequest):
    test_function: str = request.node.name.replace("[", "_").replace("]", "_")
    test_specific_root = session_root_path / test_function
    try:
        os.makedirs(test_specific_root)
    except:
        print(f"Unable to create test root folder {test_specific_root}")
        raise
    old_cwd = os.getcwd()
    os.chdir(test_specific_root)
    yield test_specific_root
    os.chdir(old_cwd)

    try:
        # Will leave all the intermediate dirs in place that it created
        # Don't use removedirs because it might prune beyond what was created
        shutil.rmtree(test_specific_root)
    except:
        logging.warning(f"Unable to remove test root folder {test_specific_root}", exc_info=True)
        raise


@pytest.fixture(scope="package")
def page_size() -> int:
    """The size of chunks sent to and from the server. Notably this is used to ensure the tests send things bigger than one chunk."""
    return 131072
