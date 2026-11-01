# Sample code

Small, documented ROMs that each show one thing a nesp32 does, for a
developer to read, run, or copy into a program of their own. Each is
built with its own Makefile, and takes the protocol and the console's
library from this checkout.

| Sample | What it shows |
|---|---|
| [lobby](lobby) | A two-player game over the network: the lobby the netplay games have, then both players' controllers on both screens, in lockstep |

The protocol itself is in [`docs/PROTOCOL.md`](../docs/PROTOCOL.md), and
the console's library in its section 7.
