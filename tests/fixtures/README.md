# Test fixtures

`nes_trimmed.json` is a reply from Wikipedia's API, as nes-wiki's
`tools/wiki_preview.py --save` writes one, for the search "Nintendo
Entertainment System" on 2026-10-04, with the extract cut down to a few
paragraphs: the lead, one section, and two paragraphs with characters
outside ASCII (Cyrillic and the yen sign). The rest is as the API sent it.

The text is from the English Wikipedia article
[Nintendo Entertainment System](https://en.wikipedia.org/wiki/Nintendo_Entertainment_System),
by its contributors, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

`klax_adsbfi.json` is a reply from [adsb.fi](https://adsb.fi)'s open data
API for the aircraft within ten nautical miles of Los Angeles
International, as RADAR asks for them: 43 aircraft, some of them on the
ground, some with no callsign and some with no altitude.

`tone_1khz.mp3` is the stream TUNER's tests play: four seconds of a 1 kHz
tone at half of full scale, the same in both channels, as MP3 at 96 kbps
and 32 kHz in joint stereo, which is how NPR's stream comes. It was made
with LAME 3.100 (the `lameenc` Python package, quality 2) from samples
worked out in Python; nothing in the tests needs an encoder. LAME scales
what it is given by 0.95, so the tone a decoder gets back is at 0.475.

`openmeteo_90210.json` is [Open-Meteo](https://open-meteo.com)'s answer
for the weather at Beverly Hills, in degrees F, as WEATHER asks for it,
on 2026-10-13, and `openmeteo_dublin.json` its answer for Dublin, Ireland,
in degrees C, on 2026-11-23. The `geo_*.json` files are Open-Meteo's
geocoding's answers, on 2026-11-23, as WEATHER asks (`count=1`): for
`90210` in the United States, `PORTLAND, ME`, `DUBLIN, IRELAND`,
`WASHINGTON` (2.4 KB, with its 255 zip codes) and `NOWHERE, XQ` (no
results). All are as they were sent. Open-Meteo's data is under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), the geocoding's
from [GeoNames](https://www.geonames.org).

`nes-radar-server/` is the source of nes-radar's server as it was at
0.4.4, the last release with one, on its `legacy/ftdi-0.4.x` branch
(commit `ba14bd5`, the files in `server/src` that `nes_radar_server.py`
imports), unchanged. RADAR's tests hold the service's scenes to what this
code makes of the same reply from adsb.fi; nothing else uses it. The ROM's
records are the same from 0.5.0, which has no server. It is k6lcm's, from
[nes-radar](https://github.com/k6lcm/nes-radar), under the
[GPL-3.0](https://github.com/k6lcm/nes-radar/blob/legacy/ftdi-0.4.x/LICENSE),
as nesp32 is.

`bsky_feed.json` is a reply from Bluesky's public API
(`app.bsky.feed.getAuthorFeed`) for the handle `bsky.app`, as BSKY asks
for it, on 2026-10-18, cut down to eight of its items: Bluesky's own posts
and its reposts of others', with curly quotes, dashes, newlines and counts
in the thousands. Bluesky's own posts are as the API sent them, less the
lists of replies it hid (`threadgate`) and the mentions' account IDs. Every
other account in it, the reposted ones and the ones Bluesky quotes, is
made up: a handle under `example.com`, made-up text, and IDs that point at
nothing. Their shape and counts are as the API sent them, and one handle is
longer than a line.
