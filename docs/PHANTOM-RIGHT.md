# A Right that nobody pressed, in a netplay session

**Status: found and mended in `apps/drmario` on 2026-10-12. `apps/contra`
is still to be looked at.** The music's drums are samples, and on a real
NES the fetch of a sample's byte that falls on a read of the controller
reads it once more. A session read its controller once, and took what it
was given.

## What was seen

In a netplay session of `apps/drmario` or `apps/contra`, one player's
character took a press of Right on the d-pad now and again with the
controller untouched. Both consoles showed it, the session went on, and it
never stopped: about one press in 300 frames, with no rhythm to it (two in
a second, then none for ten).

## The cause

The NES's sample channel takes each byte of a sample from the cartridge by
stopping the CPU for a few cycles. If the CPU is stopped in the cycle that
reads `$4016`, the read is made again when it goes on, and the controller
has been clocked twice for the one bit the game takes. That button is
lost, every button after it comes a place early, and Right, the last one
read, is whatever the controller's register has behind its eight buttons:
pressed.

Dr. Mario's music has drums, and they are samples (`bra_DFEF` and
`bra_DA58` in the disassembly's bank FF start the channel). The game's
own routine reads the controllers twice and compares them, for this. A
session's read, `session_read_pad` in `apps/drmario/net/session.inc`, read
once: its comment, and the README, say the game never plays a sample.

So it was never the nesp32, the hat, the radio or the network. It needed a
real NES, music with drums, and a routine that reads once.

## What showed it

- **It followed the real NES, not the nesp32 and not the role.** With the
  StickC Plus2 and the StickS3 exchanged, the presses stayed on the real
  NES. Two real NES consoles and two controllers had it; the MiSTer, with
  a real controller on its SNAC port, never did.
- **The console sent them.** The firmware's log of the buttons it is given
  (below) had each press as one tick and then the true buttons again.
- **The register was clocked once too often.** With nothing held a press
  was `01`. With Left held it was `05`, fifteen times of fifteen: Left
  where Down should be, and Right filled in behind. Never `03`, so Right
  was not set on its own.
- **The clock too many came at no fixed place in the read.** With A held,
  five presses were `81` and one was `01`. A is the first button read, so
  it is lost only when the first read is the one made twice.
- **With the music off there were none**: 7,244 frames of a session and
  not one, where there would have been about 24.
- **With the controller read twice while a sample plays there are none**,
  music on: 10,766 frames and not one, where there would have been about
  35.

## What misled

- **"A local game on the same real NES has none."** It has none because
  the game's own routine reads twice. It was taken to mean that a session
  did something to the console that a local game did not, and the radio
  and the serial exchange were suspected on the strength of it.
- **"Two reads running agreed on it."** A Dr. Mario ROM that read twice in
  each tick of a session was tried on 2026-10-10 and reported to make no
  difference. That does not agree with what is now known, and it is not
  known what went wrong with that test: it was not tried for long.
- **The rate.** One transmission of the radio in each frame, falling
  anywhere in it, would land in the controller read about once in 200
  frames. That was near enough to one press in 300 to look like evidence.
- **The transmit power.** A StickS3 at 2 dBm had one press in 7,109 frames
  and then 13 in 7,125. The power had nothing to do with either.
- **A test that could not fail.** A firmware that kept the radio as busy
  as a session, in a local game, had no presses. The local game reads
  twice, so it would have had none whatever the radio did.

## What was done

`session_read_pad` asks the sample channel whether it has bytes still to
fetch (`$4015`, bit 4). If it has, the controller is read twice, and if
the reads differ the buttons are as they were the last time both were
alike. If it has not, it is read once, as before. The two reads are done
in less time than there is between two fetches at the fastest rate the
game uses, so no more than one of them is spoiled. The channel is asked
before the first read and not after it, because the fetch that spoils a
read may be the sample's last.

When the reads differ, that tick has the buttons of the tick before. A
press that begins in such a tick is a frame late.

## What is left

- **Contra.** Its session already reads twice while a sample plays
  (`net_read_pad` in `apps/contra/net/net.inc`), and was said to have the
  presses all the same. It asks the channel after the first read, which
  misses a read spoiled by a sample's last fetch, and that would be rare.
  Nothing on 2026-10-12 was tried with Contra: a session with the log
  running, nothing held, is the first thing to do.
- **The MiSTer** did not show it, with a real controller on its SNAC
  port. Why is not known, and it is not a console to look for this kind of
  thing on.
- **Dr. Mario's drums.** The netplay ROM leaves the samples' data out
  for the room, in the belief that the game never plays a sample, so its
  drums play two empty pages. Its README, its `docs/PROTOCOL.md` and the
  comments in `net/session.inc` and `patches/bank_FF.patch` now say so.
- **The serial exchange** loses cycles to the same fetches, which the
  README says it does not. A reply that is misheard is not asked for again
  in the same frame, on the same belief.

## The log

The buttons are logged only by a firmware built to log at the debug
level: `CONFIG_LOG_DEFAULT_LEVEL_DEBUG=y` in the board's `sdkconfig`
(`idf.py -B build-esp32s3 menuconfig`, Component config, Log, Default log
verbosity), which makes the rest of the log much longer too.

With it, `firmware/deploy.sh watch` prints a line for each nesp32 every
two seconds of a session, after the one that begins `peer: player`:

```text
peer: pad 18 6d:01 6e:00
```

`pad 18` is how often this console's buttons have changed in the session,
and each pair after it is a change since the last line: the tick's low
byte, and the buttons the console sent for it (`01` Right, `02` Left, `04`
Down, `08` Up, `10` Start, `20` Select, `40` B, `80` A). A console nobody
touches has `pad 0` and no pairs. The tick that carries a console's digest
is left out.

From the sessions of 2026-10-12, the StickS3 on the real NES and joining,
with nothing held, with Left held and with A held:

```text
StickS3  peer: pad 2 76:01 77:00
StickS3  peer: pad 37 65:05 66:02 c3:05 c4:02
StickS3  peer: pad 107 9a:81 9b:80
StickS3  peer: pad 109 48:01 49:80
```

In about 18,900 frames there were 58 presses: 37 with nothing held, all
`01`; 15 with Left held, all `05`; 6 with A held, five `81` and one `01`.
