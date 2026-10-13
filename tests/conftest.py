import os

import pytest


def pytest_collection_modifyitems(config, items):
    have_rom = all(os.environ.get(k) for k in ("YOMIPLAY_TEST_CONTENT", "YOMIPLAY_TEST_CORE", "YOMIPLAY_TEST_BIOS_DIR"))
    live = os.environ.get("YOMIPLAY_LIVE_LLM") == "1"
    for item in items:
        if "rom" in item.keywords and not have_rom:
            item.add_marker(pytest.mark.skip(reason="no local core/BIOS/game configured"))
        if "live_llm" in item.keywords and not live:
            item.add_marker(pytest.mark.skip(reason="YOMIPLAY_LIVE_LLM not set"))
