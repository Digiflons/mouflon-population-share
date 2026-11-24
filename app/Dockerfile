# Mouflon Population App image (MOUL-14, MOUL-15, MOUL-16, MOUL-17).
# - Built by the Home Assistant Supervisor on the Pi (aarch64) or by CI; never published.
# - No desktop interface, no training tools, no TensorFlow: BirdNET 2.4 runs on LiteRT,
#   Perch v2 (second opinion, MOUL-54) on ONNX Runtime.
# - Base image pinned by digest; Python packages installed from a hash-checked lock;
#   model files checked against models.lock.json; runs as an unprivileged user.
FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BIRDNET_APP_DATA=/opt/birdnet \
    MOUFLON_EXAMPLE=/opt/mouflon/example/soundscape-60s.flac \
    PYTHONPATH=/opt/mouflon/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --no-create-home --shell /usr/sbin/nologin mouflon

COPY requirements.lock /opt/mouflon/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /opt/mouflon/requirements.lock

COPY src /opt/mouflon/src
COPY models.lock.json /opt/mouflon/models.lock.json
RUN python -m mouflon_population.models download \
    && python -m mouflon_population.models verify --lock /opt/mouflon/models.lock.json \
    && chmod -R a+rX,go-w /opt/birdnet

COPY example /opt/mouflon/example
# Bird library (MOUL-42): drawings, reference songs, IUCN status. Never fetched at runtime.
COPY library /opt/mouflon/library
# Open-licence fonts (SIL OFL 1.1) for the e-ink demo screen (MOUL-56).
COPY fonts /opt/mouflon/fonts
# Cross-check data (MOUL-54, MOUL-55): Belgian GBIF weekly statistics, Perch name
# aliases and their manifest (sources, licences, citations). Never fetched at runtime.
COPY crosscheck /opt/mouflon/crosscheck
COPY run.sh /run.sh

ENTRYPOINT ["/run.sh"]
