"""End-to-end check (MOUL-32): the App's detections appear as Home Assistant entities.

Run by CI after `docker compose up`. Onboards a throw-away Home Assistant, connects
its MQTT integration to the test broker, then waits for the bird entities and event.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HA = "http://127.0.0.1:8123"
CLIENT_ID = f"{HA}/"
DEADLINE_S = 600


def call(method, path, body=None, token=None, form=False):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    request = urllib.request.Request(HA + path, data, headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        print(
            f"{method} {path} -> {error.code}: {error.read().decode(errors='replace')}"
        )
        raise


def wait_for_ha():
    start = time.time()
    while time.time() - start < DEADLINE_S:
        try:
            call("GET", "/api/onboarding")
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(3)
    sys.exit("Home Assistant did not start")


def onboard():
    user = call(
        "POST",
        "/api/onboarding/users",
        {
            "client_id": CLIENT_ID,
            "name": "E2E",
            "username": "e2e",
            "password": "e2e-throwaway-password",
            "language": "en",
        },
    )
    tokens = call(
        "POST",
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": user["auth_code"],
            "client_id": CLIENT_ID,
        },
        form=True,
    )
    return tokens["access_token"]


def wait_until_running(token):
    start = time.time()
    while time.time() - start < DEADLINE_S:
        try:
            if call("GET", "/api/config", token=token).get("state") == "RUNNING":
                return
        except urllib.error.URLError:
            pass
        time.sleep(3)
    sys.exit("Home Assistant did not finish starting")


def fill(schema):
    """Answer a config-flow form: our broker, and every other field's default."""
    answer = {}
    for field in schema:
        name = field["name"]
        if name == "broker":
            answer[name] = "mosquitto"
        elif name == "port":
            answer[name] = 1883
        elif field.get("type") == "expandable":
            answer[name] = fill(field.get("schema", []))
        elif "default" in field:
            answer[name] = field["default"]
        elif field.get("selector", {}).get("boolean") is not None:
            answer[name] = False
        elif field.get("selector", {}).get("select"):
            first = field["selector"]["select"]["options"][0]
            answer[name] = first["value"] if isinstance(first, dict) else first
    return answer


def connect_mqtt(token):
    flow = call("POST", "/api/config/config_entries/flow", {"handler": "mqtt"}, token)
    for _ in range(4):
        print(f"MQTT flow step: {json.dumps(flow)}")
        kind = flow.get("type")
        if kind == "create_entry":
            return
        path = f"/api/config/config_entries/flow/{flow['flow_id']}"
        if kind == "menu":
            options = flow.get("menu_options", [])
            choice = "broker" if "broker" in options else options[0]
            flow = call("POST", path, {"next_step_id": choice}, token)
            continue
        if kind != "form":
            sys.exit(f"Unexpected MQTT flow step: {flow}")
        answer = fill(flow.get("data_schema", []))
        flow = call("POST", path, answer, token)
    sys.exit(f"MQTT set-up failed: {flow}")


def state(token, entity_id):
    try:
        return call("GET", f"/api/states/{entity_id}", token=token)
    except urllib.error.HTTPError:
        return None


def main():
    wait_for_ha()
    token = onboard()
    wait_until_running(token)
    connect_mqtt(token)
    wanted = {
        "event.mouflon_population_bird_detected": None,
        "sensor.mouflon_population_last_bird": None,
        "sensor.mouflon_population_species_today": None,
        "binary_sensor.mouflon_population_test_recording_listening": None,
        "image.mouflon_population_last_bird_drawing": None,
        "event.mouflon_population_rare_bird": None,
        "image.mouflon_population_screen_last_bird": None,
        "button.mouflon_population_export_analytics": None,
    }
    start = time.time()
    while time.time() - start < DEADLINE_S:
        for entity_id in wanted:
            wanted[entity_id] = state(token, entity_id)
        event = wanted["event.mouflon_population_bird_detected"]
        last = wanted["sensor.mouflon_population_last_bird"]
        if (
            event
            and event["attributes"].get("event_type") == "bird_detected"
            and last
            and last["state"] not in ("unknown", "unavailable")
            and all(wanted.values())
            and wanted["sensor.mouflon_population_species_today"]["attributes"].get(
                "species"
            )
        ):
            print("Home Assistant entities created and updated:")
            for entity_id, value in wanted.items():
                print(f"  {entity_id} = {value['state']}")
            print(f"  last bird attributes: {json.dumps(last['attributes'])}")
            assert "audio" not in json.dumps(event).lower()
            return 0
        time.sleep(5)
    print(json.dumps(wanted, indent=2, default=str))
    sys.exit("Bird entities did not appear in Home Assistant")


if __name__ == "__main__":
    sys.exit(main())
