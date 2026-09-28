"""Run the ingest consumer: `python -m ingest_consumer` (reads the environment contract)."""
import logging
import signal
import sys
import threading

from ingest_consumer.consumer import IngestConsumer
from ingest_consumer.settings import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK: Ctrl+Break on Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    IngestConsumer(Settings.from_env()).run(stop)


if __name__ == "__main__":
    main()
