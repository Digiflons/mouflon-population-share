#!/bin/sh
# Starts the App without admin rights (MOUL-15): prepares the data folder as root,
# then drops to the unprivileged "mouflon" user with no capabilities.
set -eu
install -d -o mouflon -g mouflon -m 0700 /data/mouflon
if [ -f /data/options.json ]; then
  chgrp mouflon /data/options.json
  chmod 0640 /data/options.json
fi
exec setpriv --reuid=mouflon --regid=mouflon --clear-groups \
  --inh-caps=-all --bounding-set=-all --no-new-privs \
  python -m mouflon_population
