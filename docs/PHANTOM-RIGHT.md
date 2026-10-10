# Open issue: a Right that nobody pressed, in a netplay session

**Status: open, cause unknown.** Put aside on 2026-10-10 until the PCBs
arrive and a StickS3 can be moved freely between consoles. Nothing in the
games or the firmware was changed to work around it.

## What is seen

In a netplay session of `apps/drmario` or `apps/contra`, one player's
character takes a press of Right on the d-pad now and again with the
controller untouched. Both consoles show it, the session goes on, and it
never stops: about one press in 500 frames, with no rhythm to it (two in a
second, then none for ten).

## What is known

Every session so far has had the same two setups, so the first three lines
below cannot yet be told apart:

| | The setup with the presses | The setup without |
|---|---|---|
| Console | a real NES (two of them tried) | a MiSTer |
| nesp32 | the StickC Plus2, on its breadboard hat | the StickS3 |
| Controller | a real controller (two tried) | whatever the MiSTer has |

- **It follows that setup, not the role.** With the Plus2's console
  joining, player 2 has the presses; with it hosting, player 1 has them.
  The other console sent no change of buttons at all in either role.
- **The console sends them.** The firmware's log of the buttons it is
  given (below) has each press as one tick of exactly `01`, Right alone,
  and then `00`. So the relay and the network pass on what they are
  given, and the press is in the console's own buttons before they leave.
- **Two reads running agree on it.** The log was taken with a Dr. Mario
  ROM that read the controller twice in each tick and kept the last value
  on which both reads agreed. The presses came through as before: both
  reads, about 150 CPU cycles apart, had Right.
- **It is not the protocol's timetable.** The presses' ticks are not the
  delay report's (`40`, `c0`) nor the check tick (`ff`).
- **The link is sound.** No reply went unheard on either nesp32 ("0
  again"), and each heard one byte of noise a frame, which is the
  controller read and no more.
- **A local game on the same real NES has none**, with the nesp32 still
  in port 2.

A press that is exactly `01` is what a controller gives when its shift
register is one place further on than it should be: Right is the last
button read, and the register fills behind it with "pressed". With nothing
held that is all there is to see.

## What was ruled out

- **The games' session code and the firmware's relay.** Read through for
  anything that could put a button in the stream, or that differs between
  the two roles: nothing. The consoles' lockstep check would also end a
  session whose two games had different buttons, and it does not.
- **The serial routines.** They never read `$4016`, so they cannot clock
  the controller.
- **A single spoiled read**, a stray clock in one read of eight. Reading
  twice would have taken those out, and did not.
- **The hat pulling the strobe down for good**, as the 10 kΩ base resistor
  once did ([WIRING.md](WIRING.md)). That would show in a local game too.

## What is left

A session has two things a local game has not: the nesp32's radio busy
with sixty packets a second each way, beside the console and the
controller's cable, and the serial exchange on the strobe line in every
frame. The exchange never falls in the same time as the controller read.
So the radio is the suspect that is left, most likely by way of the
Plus2's breadboard and its long wires, and it is no more than a suspect:
noise that came and went would be expected to move the register two
places some of the time, and give `03`, and every press logged was `01`.

It is not known whether a StickS3 on a real NES has the presses, nor
whether the Plus2 on the MiSTer has.

## What to do next

1. **The StickS3 on the real NES and the Plus2 on the MiSTer**, in a
   session, both controllers untouched for a minute, with the log running.
   Presses on the real NES with the StickS3: it is the console in a
   session, with any nesp32. Presses on the MiSTer, or none anywhere: it
   is the Plus2's breadboard hat.
2. **The same with the PCB hat** in place of the breadboard, on whichever
   setup still has them.
3. **Hold Left on the controller that has the presses**, for a minute. A
   press logged as `05` is every button a place on (Left where Down
   should be, and Right filled in): the register was clocked once too
   often. One logged as `03` is Right set on its own, and not a shift at
   all.
4. If it is the console: OUT0 and the port's clock on a scope during the
   controller read, in a session and in a local game.

## The log

The buttons are logged only by a firmware built to log at the debug
level: `CONFIG_LOG_DEFAULT_LEVEL_DEBUG=y` in the board's `sdkconfig`
(`idf.py -B build-esp32s3 menuconfig`, Component config, Log, Default log
verbosity), which makes the rest of the log much longer too. The sessions
below were logged before that was so, when every firmware had it, as the
end of the line before.

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

From the session of 2026-10-10, the Plus2 joining:

```text
StickC Plus2  peer: player 2, delay 1, ... 714 frames, 7 late, 0 again; ... pad 4 b7:01 b8:00
StickS3       peer: player 1, delay 1, ... 722 frames, 15 late, 0 again; ... pad 0
StickC Plus2  peer: player 2, delay 1, ... 835 frames, 7 late, 0 again; ... pad 6 d1:01 d2:00
```

and hosting:

```text
StickC Plus2  peer: player 1 ... pad 4 a0:01 a1:00 c9:01 ca:00
StickS3       peer: player 2, ... 2730 frames, 253 late, 0 again; ... pad 0
```

## What was tried and taken out

Both games were changed to read the controller twice in each tick of a
session and to keep the last value on which the reads agreed, as Contra's
session already does while a sample plays. It made no difference on the
consoles, for the reason above, and was taken out again: neither game has
it.
