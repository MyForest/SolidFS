import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# Use a test folder so we don't pollute the Pod too much
test_root_folder = Path("/data") / "test/"


def test_create_and_remove_folder():
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        assert Path(temp_folder_name).exists()

    assert not Path(temp_folder_name).exists()


def test_create_and_remove_folder_with_interesting_name():
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name + "🦖") as temp_folder_name:
        assert Path(temp_folder_name).exists()
        # TODO: We could do with a way to access the server state without going through the code we're testing. This would allow us to verify it had really made the update we want.

    assert not Path(temp_folder_name).exists()


def test_create_and_remove_folder_with_interesting_intermediate_folder_names():

    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        temp_folder = Path(temp_folder_name)
        intermediate = temp_folder / "🦖"
        deep_subfolder = intermediate / "sub" / "🦢"
        deep_subfolder.mkdir(parents=True)

        assert intermediate.exists()
        assert deep_subfolder.exists()

    assert not deep_subfolder.exists()
    assert not intermediate.exists()


def test_create_and_remove_sub_folder():
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.TemporaryDirectory(dir=temp_folder_name, prefix=sys._getframe().f_code.co_name) as sub_folder:
            assert Path(temp_folder_name).exists()
            assert Path(sub_folder).exists()

    assert not Path(sub_folder).exists()
    assert not Path(temp_folder_name).exists()


def test_create_and_remove_deep_sub_folder_in_one_operation():
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        assert Path(temp_folder_name).exists()
        deep_subfolder = Path(temp_folder_name) / "deep" / "sub" / "folder"
        try:
            deep_subfolder.mkdir(parents=True)
            assert deep_subfolder.exists()
        finally:
            try:
                deep_subfolder.unlink()
            except:
                pass

    assert not deep_subfolder.exists()
    assert not Path(temp_folder_name).exists()


def test_create_and_remove_file():
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_file:
        assert Path(temp_file.name).exists()

    assert not Path(temp_file.name).exists()


def test_create_and_remove_file_in_folder():

    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.NamedTemporaryFile(dir=temp_folder_name, prefix=sys._getframe().f_code.co_name) as temp_file:
            assert Path(temp_file.name).exists()

        assert not Path(temp_file.name).exists()
    assert not Path(temp_folder_name).exists()


def test_create_and_remove_file_in_deep_subfolder():

    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        deep_subfolder = Path(temp_folder_name) / "deep" / "sub" / "folder"
        deep_subfolder.mkdir(parents=True)
        with tempfile.NamedTemporaryFile(dir=deep_subfolder, prefix=sys._getframe().f_code.co_name) as temp_file:
            assert deep_subfolder.exists()
            assert Path(temp_file.name).exists()

        assert not Path(temp_file.name).exists()
    assert not deep_subfolder.exists()
    assert not Path(temp_folder_name).exists()


def test_create_and_remove_file_with_interesting_name_in_deep_subfolder_with_interesting_name():

    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        temp_folder = Path(temp_folder_name)
        intermediate = temp_folder / "🦖"
        deep_subfolder = intermediate / "sub" / "🦢"
        deep_subfolder.mkdir(parents=True)
        with tempfile.NamedTemporaryFile(dir=deep_subfolder, prefix="🌳") as temp_file:
            assert deep_subfolder.exists()
            assert Path(temp_file.name).exists()

        assert not Path(temp_file.name).exists()
    assert not deep_subfolder.exists()
    assert not Path(temp_folder_name).exists()


def test_create_and_remove_file_with_content():

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(insert)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()

    assert content == insert


@pytest.mark.slow
def test_create_and_remove_file_with_repeated_content():

    insert = f"# {uuid.uuid4().hex}"
    repeats = 3 + int(4096 / len(insert))
    repeated_content = insert * repeats
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(repeated_content)
        temp_file.flush()

        with open(temp_file.name) as source:
            # NOTE: This is only reflecting the in-memory cache, not the server side content
            content = source.read()

    assert content == repeated_content


def test_create_and_remove_file_with_content_in_folder():

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.NamedTemporaryFile(dir=temp_folder_name, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
            temp_file.write(insert)
            temp_file.flush()

            with open(temp_file.name) as source:
                content = source.read()

    assert content == insert


def test_create_and_remove_file_with_content_in_sub_folder():

    insert = f"# {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(dir=test_root_folder, prefix=sys._getframe().f_code.co_name) as temp_folder_name:
        with tempfile.TemporaryDirectory(dir=temp_folder_name, prefix=sys._getframe().f_code.co_name) as sub_folder:
            with tempfile.NamedTemporaryFile(dir=sub_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
                temp_file.write(insert)
                temp_file.flush()

                with open(temp_file.name) as source:
                    content = source.read()

    assert content == insert


def test_create_and_remove_file_with_content_rewrite():

    insert_before = f"# {uuid.uuid4().hex}"
    insert_after = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(insert_before)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == insert_before

    with open(temp_file.name, "w+t", encoding="utf-8") as second_writable:

        second_writable.write(insert_after)
        second_writable.flush()

        with open(second_writable.name) as source:
            content = source.read()

    assert content == insert_after


@pytest.mark.append
def test_create_and_remove_file_with_content_append():

    insert_before = f"# {uuid.uuid4().hex}"
    insert_after = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(insert_before)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == insert_before

        with open(temp_file.name, "a+t", encoding="utf-8") as second_writable:

            second_writable.write(insert_after)
            second_writable.flush()

            with open(second_writable.name) as source:
                content = source.read()

    assert content == f"{insert_before}{insert_after}"


@pytest.mark.append
@pytest.mark.slow
def test_create_and_remove_file_with_content_appended_after_large_page():

    insert_before = f"# {uuid.uuid4().hex}"
    repeats = 3 + int(4096 / len(insert_before))
    repeated_content = insert_before * repeats
    insert_after = f"# {uuid.uuid4().hex}"
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(repeated_content)
        temp_file.flush()

        with open(temp_file.name, "a+t", encoding="utf-8") as second_writable:

            second_writable.write(insert_after)
            second_writable.flush()

            with open(second_writable.name) as source:
                content = source.read()

    assert content == f"{repeated_content}{insert_after}"


def test_create_and_remove_file_with_interesting_content():
    # https://www.kermitproject.org/utf8.html
    # https://emojipedia.org/bird
    insert = """¥ · £ · € · $ · ¢ · ₡ · ₢ · ₣ · ₤ · ₥ · ₦ · ₧ · ₨ · ₩ · ₪ · ₫ · ₭ · ₮ · ₯ · ₹
⠊⠀⠉⠁⠝⠀⠑⠁⠞⠀⠛⠇⠁⠎⠎⠀⠁⠝⠙⠀⠊⠞⠀⠙⠕⠑⠎⠝⠞⠀⠓⠥⠗⠞⠀⠍⠑ 
🐿️🦅🦉🐝💫🦆🕊️🐤🐥🐓🦕🦖🐧🦜🦢🦩🦇🦃🦚🐔✈️⛳🐈🐣🥚🦎🌳🪶😵‍💫🪺🪹
"""
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(insert)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()

    assert content == insert


def test_truncate_to_nothing_when_empty():
    new_text = "New text"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:

        temp_file.truncate(0)
        temp_file.write(new_text)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == new_text


def test_truncate_to_nothing():
    old_text = "Original text"
    new_text = "New text"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
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
    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
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


def test_replace_with_different_content_type():
    text_plain = "Plain text"
    text_html = "<html><head><title>HTML</title></head></html>"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl") as temp_file:
        temp_file.write(text_plain)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_plain

        temp_file.truncate(0)
        temp_file.write(text_html)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_html
