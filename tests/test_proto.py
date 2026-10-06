"""The protocol's definition, and the three files written from it."""

import os

import gen_proto
import nesp_proto as p


def test_the_definition_reads_the_same_without_a_toml_library():
    # ESP-IDF's Python may have none; the firmware's build then reads
    # proto/nesp.toml with gen_proto's own few lines.
    assert gen_proto.load_plainly(gen_proto.SOURCE) == gen_proto.load()


def test_the_three_files_hold_the_same_numbers():
    build = os.environ["NESP_BUILD"]
    values = dict(gen_proto.constants(gen_proto.load()))
    assert values["NESP_BAUD"] == 85227 and values["NESP_FRAME_MAX"] == 134
    header, include = {}, {}
    with open(os.path.join(build, "nesp_proto.h")) as handle:
        for line in handle:
            if line.startswith("#define NESP_") and len(line.split()) == 3:
                _, name, value = line.split()
                header[name] = int(value, 0)
    with open(os.path.join(build, "nesp_proto.inc")) as handle:
        for line in handle:
            if line.startswith("NESP_"):
                name, _, value = line.split()
                include[name] = int(value.replace("$", "0x"), 0)
    assert header == include == values
    assert all(getattr(p, name) == value for name, value in values.items())


def test_no_two_services_and_no_two_ops_of_one_share_a_number():
    proto = gen_proto.load()
    ids = [body["id"] for body in proto["services"].values()]
    assert len(set(ids)) == len(ids)
    for body in proto["services"].values():
        ops = list(body.get("ops", {}).values())
        assert len(set(ops)) == len(ops)
    errors = [value for name, value in proto["status"].items()
              if name not in ("OK", "ATTENTION", "ERROR")]
    assert len(set(errors)) == len(errors) and all(value & 0x80 for value in errors)
    assert not any(value & proto["status"]["ATTENTION"] for value in errors)
