"""For every test here, tests/ and each program's and sample's own: the
longest first.

Run on every core (make test, make test-apps), a few tests take a minute
or more, and one that starts last, or behind another on the same worker,
is what the whole run waits for. So each test's time is kept in pytest's
cache, and the next run starts with the longest, handed out one at a time
(--dist load --maxschedchunk 1) so that each goes to a worker of its own.
Tests with no time yet come first, in the order they were written.
"""

KEY = "nesp32/durations"
times = {}      # this run's: setup, call and teardown, by test


def pytest_collection_modifyitems(config, items):
    cache = getattr(config, "cache", None)
    if cache is None:
        return
    durations = cache.get(KEY, {})
    items.sort(key=lambda item: -durations.get(item.nodeid, float("inf")))
    # --dist load hands each worker its first two tests at once, when
    # there are at least two a worker: the two longest would be one
    # worker's, one after the other. So each worker's first two are one of
    # the longest and one of the shortest, and the rest go one at a time.
    workers = getattr(config, "workerinput", {}).get("workercount", 0)
    if workers and len(items) >= 2 * workers:
        longest, shortest = items[:workers], items[-workers:]
        items[:] = ([item for pair in zip(longest, shortest) for item in pair]
                    + items[workers:-workers])


def pytest_runtest_logreport(report):
    times[report.nodeid] = times.get(report.nodeid, 0.0) + report.duration


def pytest_sessionfinish(session):
    # Kept by the process that ran them all, not by each worker.
    config = session.config
    cache = getattr(config, "cache", None)
    if cache is None or not times or hasattr(config, "workerinput"):
        return
    durations = cache.get(KEY, {})
    durations.update(times)
    cache.set(KEY, durations)
