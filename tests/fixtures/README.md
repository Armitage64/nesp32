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

`zip_90210.json` is [Zippopotam](https://zippopotam.us)'s answer for the
zip code 90210, and `openmeteo_90210.json` is
[Open-Meteo](https://open-meteo.com)'s for the weather at the place it
names, as WEATHER asks for it, both on 2026-10-13 and as they were sent.
Open-Meteo's data is under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
