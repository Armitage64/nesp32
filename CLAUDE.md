# CLAUDE.md

Rules for Claude Code in this repository. How things are built, tested and
released is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and the skills
under `.claude/skills/`.

- **A pull request with a noteworthy change adds its line to
  `CHANGELOG.md`**, under **Unreleased**, in the same pull request: before
  it is opened, or in a commit right after, once its number is known. The
  sections and how to word a line are in
  [docs/RELEASING.md](docs/RELEASING.md), "The changelog".
- **Test before opening a pull request.** Nothing runs the tests on a pull
  request (the workflows run only for a release and the web site). Run
  `make test`, and `make test-apps APPS="<apps>"` for each program the
  change touches; a change to `firmware/components/nesp_services` can break
  any app's tests, since each runs its ROM against that code.
- **A new task starts on a new branch, from main as it is on GitHub:**
  `git fetch && git switch -c <name> origin/main`, not from whatever is
  checked out, and never main itself unless told to. Others work in the
  same checkout and may switch branches: run `git branch --show-current`
  right before each commit.
- **Commit only your own files.** No `git commit -a` or `git add -A`;
  commit with `git commit -- <paths>`, so files someone else has staged
  stay out. Before pushing, `git log origin/main..` shows commits of
  theirs that must not be dropped. A push to main that touches `web/`,
  `apps/*/dist/` or `tools/gen_web.py` puts the web site up again at
  once (`.github/workflows/web.yml`), drafts included.
- **Delete only branches that are merged and have no open pull request.**
  Other people push branches and pull requests here too.
- **Each to-do item is on one list.** `docs/TODO.md` has the hardware, the
  firmware, the link library, netplay's networking, PAL and the tools for
  development. Each program in `apps/` has its own in its README ("To do"
  or "Not done"), which links to TODO.md for an item of the firmware's
  rather than copying it.
- **Writing the docs:** call the product nesp32; "Stick" is only the M5
  board. Plain sentences, figures with what they were measured on, and
  what was tried on hardware told from what ran only in the simulation.
  A real NES and the MiSTer with SNAC differ electrically: a result on one
  is not a result on the other.
- **Ask first** before flashing a board on USB (it may be one being played
  or measured on; `firmware/deploy.sh watch` is safe), cutting a release,
  or pushing to main.
