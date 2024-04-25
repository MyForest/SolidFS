import sys
import tempfile
import uuid

import pytest


@pytest.mark.append
@pytest.mark.slow
def x_no_append_test_create_and_remove_file_with_content_appended_after_large_page(test_root_path, page_size):

    insert_before = f"# {uuid.uuid4().hex}"
    repeats = 3 + int(page_size / len(insert_before))
    repeated_content = insert_before * repeats
    insert_after = f"# {uuid.uuid4().hex}"

    with tempfile.NamedTemporaryFile(dir=test_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".ttl", delete_on_close=False) as temp_file:
        to_remove = temp_file.name
        temp_file.write(repeated_content)
        temp_file.close()

        with open(temp_file.name, "a+t", encoding="utf-8") as second_writable:
            second_writable.write(insert_after)

        with open(second_writable.name) as source:
            content = source.read()

        assert content == f"{repeated_content}{insert_after}"


def test_create_and_remove_file_with_interesting_content(session_root_path):
    # https://www.kermitproject.org/utf8.html
    # https://emojipedia.org/bird
    insert = """¥ · £ · € · $ · ¢ · ₡ · ₢ · ₣ · ₤ · ₥ · ₦ · ₧ · ₨ · ₩ · ₪ · ₫ · ₭ · ₮ · ₯ · ₹
⠊⠀⠉⠁⠝⠀⠑⠁⠞⠀⠛⠇⠁⠎⠎⠀⠁⠝⠙⠀⠊⠞⠀⠙⠕⠑⠎⠝⠞⠀⠓⠥⠗⠞⠀⠍⠑ 
🐿️🦅🦉🐝💫🦆🕊️🐤🐥🐓🦕🦖🐧🦜🦢🦩🦇🦃🦚🐔✈️⛳🐈🐣🥚🦎🌳🪶😵‍💫🪺🪹
"""
    with tempfile.NamedTemporaryFile(dir=session_root_path, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8", suffix=".txt", delete_on_close=False) as temp_file:
        temp_file.write(insert)
        temp_file.close()

        with open(temp_file.name) as source:
            content = source.read()

        assert content == insert
