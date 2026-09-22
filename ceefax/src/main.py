import logging
import sys
import time

from .config import load_config
from .compiler import load_all_pages
from .carousel import run_carousel
from .hourly_ax25_audio import run_hourly_ax25_audio
from .transmitter import build_transmitter


def setup_logging(level: str):
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARN,
        "WARNING": logging.WARN,
        "ERROR": logging.ERROR,
    }
    logging.basicConfig(
        level=level_map.get(level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _prompt_tx_callsign(default_callsign: str) -> str:
    """
    Prompt for the AX.25 TX callsign for this run.
    Empty input keeps the default.
    """
    default_callsign = (default_callsign or "").strip().upper() or "N0CALL-1"
    while True:
        raw = input(f"Enter AX.25 TX callsign [{default_callsign}]: ").strip().upper()
        if not raw:
            return default_callsign
        # Very light validation: disallow whitespace.
        if " " in raw or "\t" in raw:
            print("Invalid callsign (contains whitespace). Try again.")
            continue
        return raw


def main():
    try:
        config = load_config()
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
    setup_logging(config.general.log_level)

    logging.info("Starting Ceefax Station Broadcast System")

    if config.general.mode.lower() == "ax25_audio":
        if config.radio.band == "hf":
            logging.info("Mode ax25_audio: hourly HF scheduler via modem73 %s", config.hf.mode)
        else:
            logging.info("Mode ax25_audio: hourly scheduler + AX.25 AFSK output")
        # Prompt for TX callsign at runtime (do not require editing config.toml).
        # Skip prompting in non-interactive environments so services don't hang.
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                config.ax25.callsign = _prompt_tx_callsign(config.ax25.callsign)
                logging.info("Using AX.25 TX callsign: %s", config.ax25.callsign)
        except (EOFError, KeyboardInterrupt):
            logging.info("TX callsign prompt cancelled; using config value: %s", config.ax25.callsign)
        run_hourly_ax25_audio(config)
        return

    logging.info("Loading pages from %s", config.general.page_dir)

    pages = load_all_pages(config.general.page_dir)
    if not pages:
        logging.error("No pages found in directory: %s", config.general.page_dir)
        sys.exit(1)

    logging.info("Loaded %d pages", len(pages))
    transmitter = build_transmitter(config)

    def transmit_callback(page, frame: bytes):
        logging.info("Transmitting page %s", page.page_id)
        transmitter.transmit_page(page, frame)

    try:
        run_carousel(
            pages=pages,
            transmit_callback=transmit_callback,
            page_duration_ms=config.carousel.page_duration_ms,
            loop_delay_ms=config.carousel.loop_delay_ms,
        )
    except KeyboardInterrupt:
        logging.info("Stopping Ceefax system (KeyboardInterrupt)")
        time.sleep(0.1)


if __name__ == "__main__":
    main()


