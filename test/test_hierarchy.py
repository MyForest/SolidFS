import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import structlog

path_parts = ["", " ", "simple", "\\", "🦖", "🦢🌳"]


@pytest.fixture(params=path_parts)
def prefix(request) -> str:
    return request.param


@pytest.fixture(params=path_parts)
def mid(request) -> str:
    return request.param


@pytest.fixture(params=path_parts)
def suffix(request) -> str:
    return request.param


@pytest.fixture()
def concatenated(prefix, mid, suffix) -> Path:

    folder_name = f"{prefix}{mid}{suffix}"
    if len(folder_name) == 0:
        pytest.skip("Not testing with a completely empty result")
    return Path(folder_name)


@pytest.fixture()
def list_of_paths(prefix, mid, suffix) -> list[Path]:

    segments = [prefix, mid, suffix]
    if 0 in [len(p) for p in segments]:
        pytest.skip("Not testing with an empty part")
    return [Path(segment) for segment in segments]


# TODO: We could do with a way to access the server state without going through the code we're testing. This would allow us to verify it had really made the update we want.


def test_subfolder(concatenated: Path):
    with structlog.contextvars.bound_contextvars(sub_folder=concatenated):
        concatenated.mkdir()


def test_nested(list_of_paths: list[Path]):
    with structlog.contextvars.bound_contextvars(paths=list_of_paths):
        intermediate = list_of_paths[0]
        deep_subfolder = Path(*list_of_paths)
        # Create
        deep_subfolder.mkdir(parents=True)

        assert intermediate.exists()
        assert deep_subfolder.exists()

        # Remove
        shutil.rmtree(intermediate)

        assert not deep_subfolder.exists()
        assert not intermediate.exists()


def test_file(concatenated: str):

    with structlog.contextvars.bound_contextvars(file_name=concatenated):
        file_path = Path(concatenated)
        file_path.touch()

        assert file_path.exists()

        file_path.unlink()

        assert not file_path.exists()


def test_file_in_folder(list_of_paths):

    folder = list_of_paths[0]
    file_name = Path(folder, "".join([str(p) for p in list_of_paths[1:]]))
    with structlog.contextvars.bound_contextvars(file_name=file_name, folder=folder):
        folder.mkdir(parents=True)
        file_name.touch()
        assert file_name.exists()

        file_name.unlink()
        assert not file_name.exists()


def test_file_in_deep_subfolder(list_of_paths: list[Path], concatenated: Path):

    folder = Path(*list_of_paths)
    deep_file = folder / concatenated
    with structlog.contextvars.bound_contextvars(deep_file=deep_file, folder=folder):
        folder.mkdir(parents=True)
        deep_file.touch()
        assert deep_file.exists()
        deep_file.unlink()
        assert not deep_file.exists()


def test_create_and_remove_file_with_content(session_root_path):

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=session_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False) as temp_file:
        temp_file.write(insert)
        temp_file.close()

        with open(temp_file.name) as source:
            content = source.read()

    assert content == insert


@pytest.mark.slow
def test_create_and_remove_file_with_repeated_content(session_root_path):

    insert = f"# {uuid.uuid4().hex}"
    repeats = 3 + int(4096 / len(insert))
    repeated_content = insert * repeats
    with tempfile.NamedTemporaryFile(dir=session_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False) as temp_file:
        temp_file.write(repeated_content)
        temp_file.close()

        with open(temp_file.name) as source:
            # NOTE: This is only reflecting the in-memory cache, not the server side content
            content = source.read()

    assert content == repeated_content


def test_create_and_remove_file_with_content_in_folder(session_root_path):

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(dir=session_root_path, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.NamedTemporaryFile(
            dir=temp_folder_name, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False
        ) as temp_file:
            temp_file.write(insert)
            temp_file.close()

            with open(temp_file.name) as source:
                content = source.read()

    assert content == insert


def test_create_and_remove_file_with_content_in_sub_folder(session_root_path):

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(dir=session_root_path, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.TemporaryDirectory(dir=temp_folder_name, prefix=sys._getframe().f_code.co_name) as sub_folder:
            with tempfile.NamedTemporaryFile(
                dir=sub_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False
            ) as temp_file:
                temp_file.write(insert)
                temp_file.close()

                with open(temp_file.name) as source:
                    content = source.read()

    assert content == insert


def test_create_and_remove_file_with_content_rewrite(session_root_path):

    insert_before = f"# {uuid.uuid4().hex}"
    insert_after = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=session_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False) as temp_file:
        temp_file.write(insert_before)
        temp_file.close()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == insert_before

    with open(temp_file.name, "w+t", encoding="utf-8") as second_writable:

        second_writable.write(insert_after)
        second_writable.close()

        with open(second_writable.name) as source:
            content = source.read()

    assert content == insert_after


@pytest.mark.append
def x_no_append_test_create_and_remove_file_with_content_append(test_root_path):

    insert_before = f"# {uuid.uuid4().hex}"
    insert_after = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=test_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False) as temp_file:
        temp_file.write(insert_before)
        temp_file.close()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == insert_before

        with open(temp_file.name, "a+t", encoding="utf-8") as second_writable:

            second_writable.write(insert_after)
            second_writable.close()

            with open(second_writable.name) as source:
                content = source.read()

    assert content == f"{insert_before}{insert_after}"
