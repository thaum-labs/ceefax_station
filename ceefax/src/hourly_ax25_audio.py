from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from .ax25_audio import build_ax25_audio_plan, write_ax25_audio_wav_and_or_stdout
from .compiler import load_all_pages
from .config import AppConfig
from .playback import play_wav_file
from .update_all import prime_user_settings


def _next_hour_local(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _sleep_until(target: datetime) -> None:
    """
    Sleep until target (local time), with a short-tick loop for good alignment.
    """
    while True:
        now = datetime.now()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.25))


def run_hourly_ax25_audio(
    config: AppConfig,
    *,
    refresh_lead_seconds: int | None = None,
    carousel_loops: int | None = None,
    play: bool = False,
    play_loops: int = 1,
    play_device: str | None = None,
    play_player: str | None = None,
) -> None:
    """
    Hourly scheduler:
      - refresh pages before the hour
      - start emitting AX.25 AFSK exactly on the hour
      - transmit a full 3× carousel as one continuous WAV/PCM stream
    """
    ax = config.ax25
    au = config.audio

    if not ax.callsign:
        raise ValueError("ax25.callsign must be set for ax25_audio mode")

    while True:
        now = datetime.now()
        hour = _next_hour_local(now)
        lead = ax.refresh_lead_seconds if refresh_lead_seconds is None else int(refresh_lead_seconds)
        refresh_at = hour - timedelta(seconds=max(0, lead))

        # Refresh window
        if datetime.now() < refresh_at:
            logging.info("Next cycle: refresh at %s, TX at %s", refresh_at, hour)
            _sleep_until(refresh_at)
        else:
            # If we're already inside the refresh window, refresh immediately.
            logging.info("Within refresh window; refreshing now for TX at %s", hour)

        # Prime cached settings so update_all won't prompt.
        # Frequency is optional but we set it to "" to avoid interactive prompts.
        prime_user_settings(callsign=ax.callsign, frequency="", auto_location=True)

        # Refresh feeds/pages (writes JSON pages on disk).
        try:
            from .update_all import update_all

            update_all()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Refresh failed: %s", exc)

        # Load latest pages
        pages = load_all_pages(config.general.page_dir)
        if not pages:
            logging.error("No pages found after refresh in %s", config.general.page_dir)
            # Wait for next hour rather than busy-looping
            _sleep_until(hour)
            continue

        loops_in_wav = ax.loops_per_hour if carousel_loops is None else int(carousel_loops)
        plan = build_ax25_audio_plan(
            pages=pages,
            loops=max(1, loops_in_wav),
            dest_callsign=ax.dest_callsign,
            src_callsign=ax.callsign,
            max_info_bytes=ax.max_info_bytes,
        )

        # Ensure we start exactly at the hour; if refresh overran, skip to next hour.
        now2 = datetime.now()
        if now2 >= hour:
            logging.warning(
                "Refresh/build overran hour boundary (%s >= %s); skipping TX this hour",
                now2,
                hour,
            )
            continue

        logging.info(
            "Prepared TX: %d pages, %d fragments, %d UI frames. Waiting for %s",
            plan.pages,
            plan.fragments,
            len(plan.ui_frames),
            hour,
        )
        _sleep_until(hour)

        wav_name = hour.strftime(f"ceefax_ax25_hourly_{max(1, loops_in_wav)}x_%Y%m%d_%H00.wav")
        logging.info("Starting AX.25 AFSK TX now (%s)", hour)

        wav_path = write_ax25_audio_wav_and_or_stdout(
            plan=plan,
            sample_rate=au.sample_rate,
            symbol_rate=au.symbol_rate,
            frequency_mark=au.frequency_mark,
            frequency_space=au.frequency_space,
            amplitude=au.amplitude,
            preamble_flags=ax.preamble_flags,
            inter_frame_flags=ax.inter_frame_flags,
            postamble_flags=ax.postamble_flags,
            output_dir=config.general.output_dir,
            output_mode=au.output,
            wav_basename=wav_name,
        )
        logging.info("Wrote AX.25 audio WAV: %s", wav_path)

        if play:
            try:
                logging.info(
                    "Playing WAV (%dx): %s",
                    max(1, int(play_loops)),
                    wav_path,
                )
                play_wav_file(
                    wav_path,
                    loops=max(1, int(play_loops)),
                    player=play_player,
                    device=play_device,
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception("Playback failed (continuing scheduler): %s", exc)

