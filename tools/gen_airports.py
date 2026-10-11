#!/usr/bin/env python3
"""Pack nes-radar's airports into the table the nesp32 looks them up in.

    tools/gen_airports.py airports.bin [nes-radar's server/src/data]

The data is nes-radar's own, from OurAirports: airports_cache.json, and a
file for each airport in airports/ that says otherwise, as its server reads
them. The table is a record of 12 bytes for each airport whose code is four
letters, in the order of the codes:

    the four letters, the latitude and the longitude

the two as whole millionths of a degree, four bytes each, low byte first.
radar.c's nesp_radar_airport finds one by halving. The file is rewritten
only if its contents changed.
"""

import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "third_party", "nes-radar", "server", "src", "data")
RECORD = struct.Struct("<4sii")


def load(data=DATA):
    """{code: (latitude, longitude)} in degrees, of every airport with a
    code of four letters."""
    with open(os.path.join(data, "airports_cache.json"), encoding="utf-8") as handle:
        airports = {str(code).upper(): (float(place[0]), float(place[1]))
                    for code, place in json.load(handle)["airports"].items()}
    others = os.path.join(data, "airports")
    for name in sorted(os.listdir(others)) if os.path.isdir(others) else ():
        if name.endswith(".json"):
            with open(os.path.join(others, name), encoding="utf-8") as handle:
                place = json.load(handle)
            airports[name[:-5].upper()] = (float(place["lat"]), float(place["lon"]))
    return {code: place for code, place in airports.items()
            if len(code) == 4 and code.isascii() and code.isalpha()}


def pack(airports):
    return b"".join(RECORD.pack(code.encode("ascii"), round(latitude * 1e6),
                                round(longitude * 1e6))
                    for code, (latitude, longitude) in sorted(airports.items()))


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    airports = load(*argv[2:3])
    if len(airports) < 1000:
        print("only %d airports: not written" % len(airports), file=sys.stderr)
        return 1
    table = pack(airports)
    try:
        with open(argv[1], "rb") as handle:
            if handle.read() == table:
                return 0
    except FileNotFoundError:
        pass
    with open(argv[1], "wb") as handle:
        handle.write(table)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
