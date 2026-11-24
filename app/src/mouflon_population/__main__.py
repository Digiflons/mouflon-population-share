"""Entry point of the App: ``python -m mouflon_population``."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from mouflon_population import __version__, config, i18n, masking
from mouflon_population.birdlog import BirdLog
from mouflon_population.ha import HomeAssistant
from mouflon_population.mqtt_publisher import PahoTransport, Publisher

log = logging.getLogger("mouflon_population")

OPTIONS = Path(os.environ.get("MOUFLON_OPTIONS", "/data/options.json"))
DATA_DIR = Path(os.environ.get("MOUFLON_DATA_DIR", "/data/mouflon"))
EXAMPLE = Path(
    os.environ.get("MOUFLON_EXAMPLE", "/opt/mouflon/example/soundscape-60s.flac")
)


def _broker(home: HomeAssistant):
    from mouflon_population.ha import MqttBroker

    host = os.environ.get("MOUFLON_MQTT_HOST")
    if host:
        return MqttBroker(
            host, int(os.environ.get("MOUFLON_MQTT_PORT", "1883")), "", ""
        )
    return home.mqtt_broker()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    masking.install()
    log.info("Mouflon Population %s starting", __version__)

    try:
        settings = config.load(OPTIONS, DATA_DIR)
    except (OSError, ValueError) as error:
        log.error("Settings problem: %s", error)
        return 2
    i18n.configure(settings.language)

    home = HomeAssistant()
    broker = _broker(home)
    if broker is None:
        log.error("No MQTT broker: install and start the Mosquitto App, then restart")
        return 3
    masking.register_secret(broker.password)

    from mouflon_population.analytics import AnalyticsStore
    from mouflon_population.library import MEDIA_DIR, Library

    library = Library()
    library.install_songs()

    if settings.demo_mode:
        return _run_demo(settings, home, broker, library)

    from mouflon_population.detector import (
        BirdnetPredictor,
        FilteringDetector,
        species_for_location,
    )
    from mouflon_population.local_check import CROSSCHECK_DIR, LocalObservations
    from mouflon_population.models import app_data
    from mouflon_population.second_opinion import PERCH_DIR, SecondOpinion, load_aliases
    from mouflon_population.service import Service

    predictor = BirdnetPredictor(settings.language)
    second_opinion = None
    if settings.second_opinion:
        second_opinion = SecondOpinion(
            app_data() / PERCH_DIR,
            load_aliases(CROSSCHECK_DIR),
            agree_score=settings.perch_agreement,
        )
        second_opinion.start()
    else:
        log.info("Second opinion (Perch) turned off in the settings")
    # Down to the silent-check threshold; the service splits the bands.
    detector = FilteringDetector(predictor, settings.silent_check_min)
    transport = PahoTransport(
        broker.host, broker.port, broker.username, broker.password, broker.ssl
    )
    birdlog = BirdLog(settings.data_dir / "birdlog.sqlite", settings.log_retention_days)
    service = Service(
        settings,
        detector,
        Publisher(transport),
        birdlog,
        home,
        EXAMPLE,
        species_lookup=lambda lat, lon, week: species_for_location(
            lat, lon, week, settings.language
        ),
        library=library,
        analytics=None
        if settings.test_mode
        else AnalyticsStore(settings.data_dir / "analytics.sqlite"),
        export_dir=MEDIA_DIR / "exports",
        second_opinion=second_opinion,
        local_observations=LocalObservations.load(CROSSCHECK_DIR),
    )
    transport.on_connect(service.announce)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if settings.test_mode:
        log.info("Test mode: replaying the bundled recording, cameras are not used")
    try:
        service.run(stop)
    finally:
        transport.close()
        predictor.close()
        birdlog.close()
    log.info("Stopped")
    return 0


def _run_demo(settings, home, broker, library) -> int:
    from mouflon_population.demo import DemoRunner

    transport = PahoTransport(
        broker.host, broker.port, broker.username, broker.password, broker.ssl
    )
    runner = DemoRunner(settings, Publisher(transport), home, library=library)
    transport.on_connect(runner.announce)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        runner.run(stop)
    finally:
        transport.close()
    log.info("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
