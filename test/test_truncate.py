import sys
import tempfile
from pathlib import Path

# Use a test folder so we don't pollute the Pod too much
test_root_folder = Path("/data") / "test/"


def test_truncate_to_nothing_when_empty():
    new_text = "New text"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".txt") as temp_file:

        temp_file.truncate(0)
        temp_file.write(new_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == new_text


def test_truncate_to_nothing():
    old_text = "Original text"
    new_text = "New text"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".txt") as temp_file:
        temp_file.write(old_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == old_text

        temp_file.truncate(0)
        temp_file.write(new_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == new_text


def test_truncate_to_something():
    old_text = "Original text"
    new_text = "New text"
    truncate_size = 4
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".txt") as temp_file:
        temp_file.write(old_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == old_text

        temp_file.truncate(truncate_size)
        temp_file.write(new_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == old_text[:truncate_size] + new_text
