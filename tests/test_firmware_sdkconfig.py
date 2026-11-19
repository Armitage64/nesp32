"""The settings the firmware's ESP-IDF configuration has to keep, per release build.

Each of these was chosen and measured for the move to ESP-IDF 6 (#17, #92),
and each can go quietly: a line dropped or changed in sdkconfig.defaults*,
or an option ESP-IDF renames or stops knowing, which Kconfig passes over
(CONFIG_NEWLIB_NANO_FORMAT on 6.x, CONFIG_RINGBUF_IN_IRAM on 5.5).

- FreeRTOS and the ring buffer in IRAM, for the link task's path through a
  request (sdkconfig.defaults).
- On the ESP32-S3s, Mbed TLS's memory by malloc's rules, so its 16 KB record
  buffer goes to PSRAM: not internal only, which left the S3's heap short,
  and not PSRAM only, with which a board whose PSRAM does not answer does
  not start. Its 16 KB comes from SPIRAM_USE_MALLOC and
  SPIRAM_MALLOC_ALWAYSINTERNAL at 16384, ESP-IDF's defaults.
- On the StickC Plus2, Mbed TLS's memory as ESP-IDF leaves it: internal.
- TLS as a client only, without renegotiation, and only the elliptic curves
  in use.
- TLS 1.3 and variable buffer lengths off, as ESP-IDF leaves them: #92's
  reading of Mbed TLS 4.1.2's advisories relies on both.

Where a setting is one of a Kconfig choice, the choice's other members are
checked off too: in a defaults file a later member set to y wins.

Each build's settings are worked out as ESP-IDF does: the files of
SDKCONFIG_DEFAULTS in order, each followed by its .<target> file if there
is one, a later line winning (release.yml has the three builds). After a
build, firmware/build-<name>/sdkconfig, the configuration it was made with,
is checked as well: release.yml builds the firmware before it runs the
tests, and a build made here by deploy.sh or idf.py leaves one too. A build
directory that is not there is skipped, except on GitHub Actions, where
release.yml has just built all three: there it fails, so that a renamed
build directory cannot turn the check off.
"""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FIRMWARE = os.path.join(ROOT, "firmware")

# name: (target, SDKCONFIG_DEFAULTS), as .github/workflows/release.yml builds them
BUILDS = {
    "esp32s3": ("esp32s3", ["sdkconfig.defaults"]),
    "esp32s3-generic": ("esp32s3", ["sdkconfig.defaults", "sdkconfig.defaults.generic"]),
    "esp32": ("esp32", ["sdkconfig.defaults"]),
}

EVERY_BUILD = {
    "CONFIG_FREERTOS_IN_IRAM": "y",
    "CONFIG_RINGBUF_IN_IRAM": "y",
    "CONFIG_MBEDTLS_TLS_CLIENT_ONLY": "y",
    "CONFIG_MBEDTLS_TLS_SERVER_AND_CLIENT": "n",
    "CONFIG_MBEDTLS_TLS_SERVER_ONLY": "n",
    "CONFIG_MBEDTLS_SSL_RENEGOTIATION": "n",
    "CONFIG_MBEDTLS_SSL_PROTO_TLS1_3": "n",
    "CONFIG_MBEDTLS_SSL_VARIABLE_BUFFER_LENGTH": "n",
    # The rest of Mbed TLS's memory choice; the S3s and the Plus2 each pick
    # one of the other three below.
    "CONFIG_MBEDTLS_CUSTOM_MEM_ALLOC": "n",
    "CONFIG_MBEDTLS_IRAM_8BIT_MEM_ALLOC": "n",
    "CONFIG_MBEDTLS_ECP_DP_SECP256K1_ENABLED": "n",
    "CONFIG_MBEDTLS_ECP_DP_BP256R1_ENABLED": "n",
    "CONFIG_MBEDTLS_ECP_DP_BP384R1_ENABLED": "n",
    "CONFIG_MBEDTLS_ECP_DP_BP512R1_ENABLED": "n",
}
# On by ESP-IDF's default: the defaults files must not turn them off.
KEPT = {
    "CONFIG_MBEDTLS_ECP_DP_SECP256R1_ENABLED": "y",
    "CONFIG_MBEDTLS_ECP_DP_SECP384R1_ENABLED": "y",
    "CONFIG_MBEDTLS_ECP_DP_SECP521R1_ENABLED": "y",
    "CONFIG_MBEDTLS_ECP_DP_CURVE25519_ENABLED": "y",
}
S3 = {
    "CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC": "y",
    "CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC": "n",
    "CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC": "n",
    # The rest of the PSRAM access choice, whose SPIRAM_USE_MALLOC is kept below.
    "CONFIG_SPIRAM_USE_MEMMAP": "n",
    "CONFIG_SPIRAM_USE_CAPS_ALLOC": "n",
}
S3_KEPT = {  # ESP-IDF's defaults, which the S3's Mbed TLS setting relies on
    "CONFIG_SPIRAM_USE_MALLOC": "y",
    "CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL": "16384",
}
PLUS2 = {
    "CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC": "n",
    "CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC": "n",
}
PLUS2_KEPT = {"CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC": "y"}
# Off unless a defaults file turns them on: the members of a choice that are
# not its default, the default itself once another member is on, and the two
# options ESP-IDF leaves off. Every other option above is on by ESP-IDF's
# default, so it is off only where a defaults file says so.
OFF_BY_DEFAULT = {"CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC", "CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC",
                  "CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC", "CONFIG_MBEDTLS_CUSTOM_MEM_ALLOC",
                  "CONFIG_MBEDTLS_IRAM_8BIT_MEM_ALLOC",
                  "CONFIG_MBEDTLS_TLS_SERVER_AND_CLIENT", "CONFIG_MBEDTLS_TLS_SERVER_ONLY",
                  "CONFIG_SPIRAM_USE_MEMMAP", "CONFIG_SPIRAM_USE_CAPS_ALLOC",
                  "CONFIG_MBEDTLS_SSL_PROTO_TLS1_3", "CONFIG_MBEDTLS_SSL_VARIABLE_BUFFER_LENGTH"}

SET = re.compile(r"^(CONFIG_\w+)=(.*)$")
UNSET = re.compile(r"^#\s*(CONFIG_\w+) is not set\s*$")


def settings(text, into=None):
    """CONFIG_NAME -> value of a defaults file or an sdkconfig: "n" for one
    that is not set, the value without quotes otherwise."""
    found = {} if into is None else into
    for line in text.splitlines():
        line = line.strip()
        match = SET.match(line) or UNSET.match(line)
        if match:
            found[match.group(1)] = match.group(2).strip('"') if match.re is SET else "n"
    return found


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def defaults_files(build):
    """The defaults files a build reads, in order, as ESP-IDF finds them."""
    target, listed = BUILDS[build]
    files = []
    for name in listed:
        files.append(name)
        if os.path.isfile(os.path.join(FIRMWARE, "%s.%s" % (name, target))):
            files.append("%s.%s" % (name, target))
    return files


def defaults(build, texts=None):
    """The settings the defaults files give a build. texts: name -> text, to
    check other contents than the files'."""
    found = {}
    for name in defaults_files(build):
        text = texts[name] if texts and name in texts else read(os.path.join(FIRMWARE, name))
        settings(text, found)
    return found


def wanted(build):
    """(what must be so, what ESP-IDF's defaults give and must not be changed)"""
    must = dict(EVERY_BUILD)
    kept = dict(KEPT)
    if BUILDS[build][0] == "esp32s3":
        must.update(S3)
        kept.update(S3_KEPT)
    else:
        must.update(PLUS2)
        kept.update(PLUS2_KEPT)
    return must, kept


def problems(build, found, generated):
    """What is wrong with a build's settings. In the defaults files an option
    left to ESP-IDF is absent; in a generated sdkconfig every one is there."""
    must, kept = wanted(build)
    wrong = []
    for name, value in must.items():
        have = found.get(name, "n" if generated else None)
        if have is None and value == "n" and name in OFF_BY_DEFAULT:
            continue
        if have != value:
            wrong.append("%s: %s is %s, not %s" % (build, name, have or "not set", value))
    for name, value in kept.items():
        have = found.get(name)
        if generated:
            if have != value:
                wrong.append("%s: %s is %s, not %s" % (build, name, have or "not there", value))
        elif have is not None and have != value:
            wrong.append("%s: %s is set to %s, where ESP-IDF's %s is relied on"
                         % (build, name, have, value))
    return wrong


@pytest.mark.parametrize("build", sorted(BUILDS))
def test_the_defaults_files_give_each_build_its_settings(build):
    found = problems(build, defaults(build), generated=False)
    assert not found, "\n".join(found)


@pytest.mark.parametrize("build", sorted(BUILDS))
def test_the_last_build_was_made_with_them(build):
    path = os.path.join(FIRMWARE, "build-%s" % build, "sdkconfig")
    if not os.path.isfile(path):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("no firmware/build-%s/sdkconfig, where release.yml builds it: "
                        "has its -B directory changed?" % build)
        pytest.skip("no firmware/build-%s/sdkconfig: the firmware is not built here" % build)
    found = problems(build, settings(read(path)), generated=True)
    assert not found, "%s:\n%s" % (os.path.relpath(path, ROOT), "\n".join(found))


# Each change these tests are for, made to the defaults files' text, must be caught.
MUTANTS = {
    "the S3s on PSRAM only": ("esp32s3", "sdkconfig.defaults.esp32s3",
                               "CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC=y",
                               "CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC=y"),
    "the S3s on internal only": ("esp32s3-generic", "sdkconfig.defaults.esp32s3",
                                  "CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC=y", ""),
    "the Plus2 by malloc's rules": ("esp32", "sdkconfig.defaults.esp32", None,
                                     "CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC=y"),
    "FreeRTOS in flash": ("esp32", "sdkconfig.defaults", "CONFIG_FREERTOS_IN_IRAM=y", ""),
    "the ring buffer in flash": ("esp32s3", "sdkconfig.defaults", "CONFIG_RINGBUF_IN_IRAM=y", ""),
    "a TLS server": ("esp32", "sdkconfig.defaults", "CONFIG_MBEDTLS_TLS_CLIENT_ONLY=y", ""),
    "renegotiation": ("esp32s3", "sdkconfig.defaults", "CONFIG_MBEDTLS_SSL_RENEGOTIATION=n", ""),
    "Brainpool P-256 back": ("esp32s3", "sdkconfig.defaults",
                             "CONFIG_MBEDTLS_ECP_DP_BP256R1_ENABLED=n", ""),
    "secp256k1 back": ("esp32", "sdkconfig.defaults",
                       "CONFIG_MBEDTLS_ECP_DP_SECP256K1_ENABLED=n", ""),
    "P-384 turned off": ("esp32", "sdkconfig.defaults", None,
                         "CONFIG_MBEDTLS_ECP_DP_SECP384R1_ENABLED=n"),
    "PSRAM out of malloc": ("esp32s3", "sdkconfig.defaults.esp32s3", None,
                            "CONFIG_SPIRAM_USE_CAPS_ALLOC=y\nCONFIG_SPIRAM_USE_MALLOC=n"),
    "a lower malloc limit": ("esp32s3-generic", "sdkconfig.defaults.generic", None,
                             "CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=4096"),
    # A later member of a choice wins, with the earlier one's line still there.
    "a TLS server and client after the client": ("esp32", "sdkconfig.defaults", None,
                                                 "CONFIG_MBEDTLS_TLS_SERVER_AND_CLIENT=y"),
    "a TLS server only after the client": ("esp32s3", "sdkconfig.defaults", None,
                                           "CONFIG_MBEDTLS_TLS_SERVER_ONLY=y"),
    "the S3s on custom memory after malloc's rules": (
        "esp32s3", "sdkconfig.defaults.esp32s3", None, "CONFIG_MBEDTLS_CUSTOM_MEM_ALLOC=y"),
    "the Plus2 on custom memory": ("esp32", "sdkconfig.defaults.esp32", None,
                                   "CONFIG_MBEDTLS_CUSTOM_MEM_ALLOC=y"),
    "PSRAM by heap_caps only after malloc": ("esp32s3-generic", "sdkconfig.defaults.esp32s3",
                                             None, "CONFIG_SPIRAM_USE_CAPS_ALLOC=y"),
    "TLS 1.3": ("esp32s3", "sdkconfig.defaults", None, "CONFIG_MBEDTLS_SSL_PROTO_TLS1_3=y"),
    "variable buffer lengths": ("esp32", "sdkconfig.defaults", None,
                                "CONFIG_MBEDTLS_SSL_VARIABLE_BUFFER_LENGTH=y"),
}


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_a_change_to_a_setting_is_caught(mutant):
    build, name, old, new = MUTANTS[mutant]
    text = read(os.path.join(FIRMWARE, name))
    if old is None:
        changed = text + "\n" + new + "\n"
    else:
        assert old in text, "%s has no %r any more: update this mutant" % (name, old)
        changed = text.replace(old, new)
    assert problems(build, defaults(build, {name: changed}), generated=False), \
        "%s was not caught" % mutant


def test_a_missing_build_fails_on_github_actions(monkeypatch, tmp_path):
    """release.yml builds all three before the tests: a build not there is a fault."""
    monkeypatch.setattr(sys.modules[__name__], "FIRMWARE", str(tmp_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(pytest.fail.Exception):
        test_the_last_build_was_made_with_them("esp32")


def test_a_missing_build_is_skipped_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules[__name__], "FIRMWARE", str(tmp_path))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(pytest.skip.Exception):
        test_the_last_build_was_made_with_them("esp32")
