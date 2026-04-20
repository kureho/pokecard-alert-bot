import io
import json
import logging

from pokebot.logging_setup import setup_logging


def test_logger_emits_json_line():
    buf = io.StringIO()
    setup_logging(level="INFO", stream=buf)
    logger = logging.getLogger("pokebot.test")
    logger.info("hello %s", "world", extra={"monitor": "yodobashi"})
    line = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["msg"] == "hello world"
    assert payload["monitor"] == "yodobashi"
    assert "ts" in payload
