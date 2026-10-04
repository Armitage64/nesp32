"""Sampled sound off the console: the .pcm file and its bytes on the wire,
the converters from WAV and MP3, and the preview that renders what the
console's DAC does."""

import math
import os
import shutil
import subprocess
import types
import wave

import pytest

import mp32pcm
import pcm
import wav2pcm

ROOT = os.path.join(os.path.dirname(__file__), "..")


# --- the bytes ----------------------------------------------------------------------

def test_a_sample_is_the_byte_the_receiver_turns_into_its_level():
    assert all(pcm.raw_byte(pcm.wire_byte(raw)) == raw for raw in range(256))
    for level in range(pcm.LEVELS):
        assert pcm.raw_byte(pcm.sample_byte(level)) == level | pcm.MORE
        assert pcm.raw_byte(pcm.sample_byte(level, last=True)) == level
    assert pcm.decode(pcm.encode(range(128))) == list(range(128))
    assert pcm.raw_byte(pcm.LAST_BYTE[0]) == 0
    # A long low, as a zero byte at the link's own rate is, reads as a last byte.
    assert pcm.raw_byte(0x00) & pcm.MORE == 0 and set(pcm.FILLER) == {0}


def test_the_rates_are_a_byte_of_11_bits_at_whole_cycles_a_bit():
    assert [round(pcm.sample_rate(period)) for period in pcm.PERIODS] == [
        7748, 10169, 11622, 13559, 16271, 20338]
    assert pcm.baud(pcm.DEFAULT_PERIOD) == 111861 and pcm.DEFAULT_PERIOD in pcm.PERIODS
    assert list(pcm.PERIODS) == sorted(pcm.PERIODS, reverse=True)


def test_a_file_round_trips_with_its_title_and_rate():
    sound = pcm.Sound("Voices - Hello", 12, pcm.encode([0, 5, 127, 64]))
    data = sound.to_bytes()
    assert data[:8] == b"NPCM" + bytes((1, 12, 14, 0)) and data[8:22] == b"Voices - Hello"
    assert pcm.Sound.from_bytes(data) == sound
    assert sound.rate == pcm.PERIODS.index(12)
    # A second of samples is 60 of the stream's frames.
    second = pcm.Sound("", 16, bytes(round(pcm.sample_rate(16))))
    assert second.frames == 60 - 1 or second.frames == 60
    for bad in (b"", b"RIFF" + bytes(8), data[:7], b"NPCM\x02" + data[5:],
                b"NPCM\x01\x2f" + data[6:], data[:10]):
        with pytest.raises(ValueError):
            pcm.Sound.from_bytes(bad)


# --- the converters -------------------------------------------------------------------

def test_levels_are_chosen_through_the_dacs_curve():
    dac = wav2pcm.DAC
    assert all(low < high for low, high in zip(dac, dac[1:]))
    assert 0.63 < dac[127] / (127 * dac[1]) < 0.65     # the top is squeezed
    assert wav2pcm.nearest_level(0.0) == 0 and wav2pcm.nearest_level(1.0) == 127
    assert wav2pcm.nearest_level(-1.0) == 0 and wav2pcm.nearest_level(2.0) == 127
    # Half the output is well under half the levels' range.
    half = wav2pcm.nearest_level(0.5)
    assert half < 64 and abs(dac[half] - dac[127] / 2) <= (dac[half + 1] - dac[half - 1]) / 2
    for level in range(128):
        assert wav2pcm.nearest_level(dac[level] / dac[127]) == level


def test_a_sound_rises_from_level_0_and_falls_back_to_it():
    rate = pcm.sample_rate(16)
    levels = wav2pcm.to_levels(wav2pcm.tone(440, rate, 0.1), rate)
    ramp = int(rate * wav2pcm.RAMP_MS / 1000)
    assert levels[0] == 0 and levels[-1] == 0
    assert len(levels) == int(0.1 * rate) + 2 * ramp
    assert levels[:ramp] == sorted(levels[:ramp]) and levels[-ramp:] == sorted(levels[-ramp:])[::-1]
    assert max(levels) == 127 and min(levels[ramp:-ramp]) == 0     # as loud as fits
    assert wav2pcm.to_levels([], rate)[0] == 0                      # silence is a sound too
    assert set(wav2pcm.to_levels([0.0] * 10, rate)[ramp:-ramp]) == {wav2pcm.nearest_level(0.5)}


def test_resampling_keeps_a_tone_and_drops_what_the_rate_cannot_carry():
    rate = pcm.sample_rate(16)
    source = wav2pcm.tone(440, 44100, 0.2)
    out = wav2pcm.resample(source, 44100, rate)
    assert abs(len(out) - 0.2 * rate) <= 1
    direct = wav2pcm.tone(440, rate, 0.2)
    edge = 100
    assert max(abs(a - b) for a, b in zip(out[edge:-edge], direct[edge:-edge])) < 0.01
    # 8 kHz is over half of 10169: it would come back as a 2 kHz tone.
    gone = wav2pcm.resample(wav2pcm.tone(8000, 44100, 0.2), 44100, rate)
    assert max(abs(sample) for sample in gone[edge:-edge]) < 0.01
    # A decoder that already resampled is within a sample a second of the rate.
    assert wav2pcm.resample(source, round(rate), rate) == source


def write_wav(path, frames, channels, width, rate=22050):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(frames)


def tone_frames(hertz, rate, seconds, channels=1):
    return b"".join(int(20000 * math.sin(2 * math.pi * hertz * index / rate))
                    .to_bytes(2, "little", signed=True) * channels
                    for index in range(int(rate * seconds)))


def test_a_wav_is_read_as_one_channel_from_minus_1_to_1(tmp_path):
    path = tmp_path / "in.wav"
    stereo = b"".join(value.to_bytes(2, "little", signed=True)
                      for value in (16384, -16384, 32767, 32767, -32768, 0))
    write_wav(path, stereo, 2, 2)
    samples, rate = wav2pcm.read_wav(str(path))
    assert rate == 22050
    assert samples == pytest.approx([0.0, 32767 / 32768, -0.5])
    write_wav(path, bytes((0, 128, 255)), 1, 1)     # 8-bit WAV is unsigned
    assert wav2pcm.read_wav(str(path))[0] == pytest.approx([-1.0, 0.0, 127 / 128])


def test_wav2pcm_writes_a_file_for_the_rate_asked(tmp_path, capsys):
    source, output = tmp_path / "My Song.wav", tmp_path / "out.pcm"
    write_wav(source, tone_frames(300, 22050, 0.1), 1, 2)
    assert wav2pcm.main([str(source), str(output), "--period", "12"]) == 0
    sound = pcm.Sound.from_bytes(output.read_bytes())
    rate = pcm.sample_rate(12)
    assert (sound.title, sound.period) == ("My Song", 12)   # the title is the file's name
    assert abs(len(sound.samples) - (0.1 + 2 * wav2pcm.RAMP_MS / 1000) * rate) <= 3
    assert max(pcm.decode(sound.samples)) == 127
    assert "13559 a second" in capsys.readouterr().out
    assert wav2pcm.main([str(source), str(output), "--title", "Game - Track"]) == 0
    assert pcm.Sound.from_bytes(output.read_bytes()).title == "Game - Track"
    assert wav2pcm.main([str(source), str(output), "--seconds", "0.05"]) == 0
    short = pcm.decode(pcm.Sound.from_bytes(output.read_bytes()).samples)
    assert abs(len(short) - (0.05 + 2 * wav2pcm.RAMP_MS / 1000) * pcm.sample_rate(16)) <= 3
    assert short[-1] == 0 and max(short) == 127     # it still ends at rest, as loud as fits
    assert wav2pcm.main(["--tone", "440", str(output)]) == 0
    tone = pcm.Sound.from_bytes(output.read_bytes())
    assert (tone.title, tone.period) == ("440 Hz tone", pcm.DEFAULT_PERIOD)
    with pytest.raises(SystemExit):
        wav2pcm.main([str(output)])                 # neither a WAV nor a tone


# --- MP3 --------------------------------------------------------------------------------

def test_mp32pcm_has_a_decoder_write_a_wav_at_the_links_rate(tmp_path):
    """The decoder is a program on the computer. Here it is a stand-in that
    writes the WAV it was asked for, so the command is what is checked."""
    source = tmp_path / "Theme.mp3"
    source.write_bytes(b"not really an mp3")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        write_wav(command[-1], tone_frames(300, 10169, 0.2), 1, 2, rate=10169)
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    sound = mp32pcm.from_file(str(source), run=run, which=lambda name: name == "ffmpeg")
    assert commands[0][0] == "ffmpeg" and str(source) in commands[0]
    assert commands[0][commands[0].index("-ar") + 1] == "10169"
    assert commands[0][commands[0].index("-ac") + 1] == "1"
    assert (sound.title, sound.period) == ("Theme", pcm.DEFAULT_PERIOD)
    # The decoder resampled; nothing here did, so the length is its own.
    assert len(sound.samples) == 2033 + 2 * int(pcm.sample_rate(16) * wav2pcm.RAMP_MS / 1000)

    cut = mp32pcm.from_file(str(source), seconds=0.1, run=run, which=lambda name: name == "ffmpeg")
    assert len(cut.samples) == 1016 + 2 * int(pcm.sample_rate(16) * wav2pcm.RAMP_MS / 1000)
    del commands[1]
    mp32pcm.from_file(str(source), period=8, run=run, which=lambda name: name == "afconvert")
    assert commands[1][0] == "afconvert" and "LEI16@20338" in commands[1]
    assert commands[1][commands[1].index("-c") + 1] == "1"


def test_mp32pcm_says_what_is_wrong(tmp_path, capsys):
    source = tmp_path / "Theme.mp3"
    source.write_bytes(b"not really an mp3")
    with pytest.raises(ValueError, match="no decoder"):
        mp32pcm.from_file(str(source), which=lambda name: None)
    failed = types.SimpleNamespace(returncode=1, stderr="bad header\n", stdout="")
    with pytest.raises(ValueError, match="ffmpeg could not decode it: bad header"):
        mp32pcm.from_file(str(source), run=lambda command, **kwargs: failed,
                          which=lambda name: name == "ffmpeg")
    assert mp32pcm.main([str(tmp_path / "missing.mp3"), str(tmp_path / "out.pcm")]) == 1
    assert "no such file" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("afconvert"), reason="needs macOS's afconvert")
def test_mp32pcm_with_the_real_decoder(tmp_path, capsys):
    """afconvert writes no MP3, so the compressed file here is AAC; it is
    the same command either way."""
    wav, compressed, output = tmp_path / "in.wav", tmp_path / "Song.m4a", tmp_path / "out.pcm"
    write_wav(wav, tone_frames(440, 44100, 0.5, channels=2), 2, 2, rate=44100)
    subprocess.run(["afconvert", "-f", "mp4f", "-d", "aac", str(wav), str(compressed)], check=True)
    assert mp32pcm.main([str(compressed), str(output), "--period", "10"]) == 0
    sound = pcm.Sound.from_bytes(output.read_bytes())
    assert (sound.title, sound.period) == ("Song", 10)
    assert abs(len(sound.samples) / pcm.sample_rate(10) - 0.54) < 0.1
    levels = pcm.decode(sound.samples)
    assert levels[0] == 0 and levels[-1] == 0 and max(levels) == 127
    # It is still the tone: about 440 crossings of the middle a second, each way.
    middle = wav2pcm.nearest_level(0.5)
    body = levels[1000:-1000]
    crossings = sum((a < middle) != (b < middle) for a, b in zip(body, body[1:]))
    assert abs(crossings / (len(body) / pcm.sample_rate(10)) - 880) < 60
    assert "16271 a second" in capsys.readouterr().out


# --- the preview ------------------------------------------------------------------------

needs_cc65 = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed")


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    build = tmp_path_factory.mktemp("pcm_preview")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=ROOT, check=True)
    return build


@needs_cc65
def test_the_preview_is_what_the_stream_routine_writes(build):
    import pcm_preview

    sound = wav2pcm.convert(wav2pcm.tone(440, 44100, 0.1), 44100, 16)
    writes = pcm_preview.dac_writes(str(build / "jukebox_link.nes"),
                                    str(build / "jukebox_link.labels"), sound)
    assert [level for _, level in writes] == pcm.decode(sound.samples) + [0]
    samples = pcm_preview.render(writes)
    seconds = len(sound.samples) / pcm.sample_rate(16)
    assert abs(len(samples) - seconds * pcm_preview.WAV_RATE) <= 2
    full = int(pcm_preview.FULL * 32767)
    assert samples[0] == -full and min(samples) == -full and max(samples) == full
    # The ramps aside it is the tone: about 44 crossings of the middle in 0.1 s.
    body = samples[int(0.03 * pcm_preview.WAV_RATE):-int(0.03 * pcm_preview.WAV_RATE)]
    crossings = sum((a < 0) != (b < 0) for a, b in zip(body, body[1:]))
    assert abs(crossings - 2 * 440 * len(body) / pcm_preview.WAV_RATE) <= 3


@needs_cc65
def test_the_preview_tool_writes_a_wav_of_the_first_seconds(build, tmp_path, capsys):
    import pcm_preview

    source, output = tmp_path / "in.pcm", tmp_path / "out.wav"
    source.write_bytes(wav2pcm.convert(wav2pcm.tone(440, 44100, 0.3), 44100, 8).to_bytes())
    assert pcm_preview.main([str(source), str(output), "--build", str(build),
                             "--seconds", "0.1"]) == 0
    with wave.open(str(output), "rb") as handle:
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (
            1, 2, pcm_preview.WAV_RATE)
        assert abs(handle.getnframes() - 0.1 * pcm_preview.WAV_RATE) < 50
    assert "2034 samples played" in capsys.readouterr().out
