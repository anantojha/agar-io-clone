import json
import shutil
import subprocess
from pathlib import Path

import pytest

from server.protocol import decode_state, encode_state, pack_food

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

SAMPLE = dict(
    me=(2000.4, 1999.6, 123.2),
    view=1450.7,
    cells=[(7, 3, 100.2, 200.7, 26.84), (9, 4, 3999.9, 0.0, 848.0)],
    food=pack_food(10.0, 20.0, 5) + pack_food(3999.0, 3999.0, 0),
    viruses=[(500.0, 600.0, 60.0)],
    pellets=[(1.0, 2.0, 77)],
    names={3: "Ada", 4: "Zoë 🙂"},
    leaderboard=[("Ada", 1234), ("Zoë 🙂", 56)],
)


def test_round_trip_keeps_everything_to_the_precision_of_the_format():
    state = decode_state(encode_state(**SAMPLE))
    assert state["me"] == [2000, 2000, 123]
    assert state["v"] == 1451
    assert state["c"] == [[7, 3, 100, 201, 26.8], [9, 4, 4000, 0, 848.0]]
    assert state["f"] == [[10, 20, 5], [3999, 3999, 0]]
    assert state["vi"] == [[500, 600, 60.0]]
    assert state["e"] == [[1, 2, 77]]
    assert state["n"] == {3: "Ada", 4: "Zoë 🙂"}
    assert state["lb"] == [["Ada", 1234], ["Zoë 🙂", 56]]


def test_names_and_leaderboard_are_optional():
    state = decode_state(encode_state(me=(1, 2, 3), view=4, cells=[], food=b"", viruses=[], pellets=[]))
    assert "n" not in state and "lb" not in state
    assert state["c"] == [] and state["me"] == [1, 2, 3]


def test_an_empty_leaderboard_is_still_sent():
    state = decode_state(encode_state(me=(1, 2, 3), view=4, cells=[], food=b"", viruses=[], pellets=[],
                                      leaderboard=[]))
    assert state["lb"] == []


def test_out_of_range_values_are_clamped_not_fatal():
    data = encode_state(me=(-5, 99999, 1), view=1, cells=[(1, 1, -3, 70000, 1e9)], food=b"", viruses=[],
                        pellets=[])
    state = decode_state(data)
    assert state["me"][:2] == [0, 65535]
    assert state["c"][0][2:4] == [0, 65535]


def test_frame_is_much_smaller_than_json():
    cells = [(i, i % 7, 100 + i, 200 + i, 30.5) for i in range(30)]
    food = [(i * 3, i * 5, i % 8) for i in range(300)]
    binary = encode_state(me=(1000, 1000, 50), view=900, cells=cells, food=b"".join(pack_food(*f) for f in food),
                          viruses=[], pellets=[])
    as_json = json.dumps({"c": [list(c) for c in cells], "f": [list(f) for f in food]}, separators=(",", ":"))
    assert len(binary) < len(as_json) / 2


def test_garbage_type_is_rejected():
    with pytest.raises(ValueError):
        decode_state(b"\x09" + b"\x00" * 30)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_browser_decoder_reads_what_the_server_writes(tmp_path):
    """Runs client/protocol.js itself under node, so the two sides can't drift apart."""
    frame = tmp_path / "frame.bin"
    frame.write_bytes(encode_state(**SAMPLE))
    script = (
        "const fs=require('fs');const {decodeState}=require(process.argv[1]);"
        "const b=fs.readFileSync(process.argv[2]);"
        "const ab=b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);"
        "console.log(JSON.stringify(decodeState(ab)));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(CLIENT_DIR / "protocol.js"), str(frame)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    js_state = json.loads(result.stdout)
    py_state = decode_state(frame.read_bytes())
    py_state["n"] = {str(k): v for k, v in py_state["n"].items()}  # JSON object keys are strings
    assert js_state == py_state
