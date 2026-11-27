"""The roots the firmware trusts: Mozilla's list, vendored in firmware/ca/cacert.pem.

Adapted from 1541ultimate's tests/lib/u64ctrl_ca_test.py (GPL-3.0).

The firmware's HTTPS checks servers against the root list its build embeds
(esp_crt_bundle_attach). ESP-IDF's own list lags Mozilla's: 6.0.3's, which
the StickC Plus2 is built with, still holds the three emSign roots removed
from NSS's source in October 2026. So every build embeds
firmware/ca/cacert.pem instead (sdkconfig.defaults): curl's copy of
Mozilla's list, with the roots in REMOVED cut out, pinned here by sha256
(CACERT_SHA256). Each of these is a quiet regression, and is checked:

- the defaults, or a build's sdkconfig, select ESP-IDF's list again, or turn
  off the cross-signed verification some of the servers need;
- the file is replaced by another, by an older one, or grows old;
- it loses a root the firmware's servers chain to, or holds a removed one;
- a build embedded something else (firmware/build-<name>, after a build, as
  release.yml leaves it before it runs the tests).

firmware/ca/refresh.py updates the file (firmware/ca/README.md); its own
checks are tested here without a network: against a fake curl.se, and
against a local `openssl s_server` when openssl is OpenSSL 3 or later.
"""

import base64
import datetime
import glob
import hashlib
import importlib.util
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_firmware_sdkconfig as sdkconfig  # noqa: E402

ROOT = os.path.dirname(HERE)
FIRMWARE = os.path.join(ROOT, "firmware")
CA_DIR = os.path.join(FIRMWARE, "ca")
CACERT = os.path.join(CA_DIR, "cacert.pem")
BUNDLE_PATH = "ca/cacert.pem"  # CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH, from the project, firmware/

# Certificate sha256 fingerprints.
REQUIRED = {  # the roots the firmware's servers (HOSTS) chain to, where the bundle's lookup stops
    "ISRG Root X1": "96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6",
    "ISRG Root X2": "69729b8e15a86efc177a57afb7171dfc64add28c2fca8cf1507e34453ccb1470",
    "DigiCert Global Root G2": "cb3ccbb76031e5e0138f8dd39a23f9de47ffc35e43c1144cea27d46a5ab1cb5f",
    "GTS Root R4": "349dfa4058c5e263123b398ae795573c4e1313c83fe68f93556cd5e8031b3c7d",
    "Amazon Root CA 1": "8ecde6884f3d87b1125ba31ac3fcb13d7016de7f57cc904fe1cb97c6ae98196e",
    "Go Daddy Root Certificate Authority - G2": "45140b3247eb9cc8c5b4f0d7b53091f73292089e6e5a63e2749dd3aca9198eda",
    "Sectigo Public Server Authentication Root R46":
        "7bb647a62aeeac88bf257aa522d01ffea395e0ab45c73f93f65654ec38f25a06",
}
REMOVED = {  # not in the store, though curl's copy may still hold them (it follows Mozilla's release branch)
    # removed from NSS for NSS 3.132: G3 in bug 2084101, after the compromise of eMudhra intermediate-certificate
    # keys (bug 2083449); C1 and C3 in bug 2083709, retired at eMudhra's request
    "emSign ECC Root CA - G3": "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "emSign Root CA - C1": "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f",
    "emSign ECC Root CA - C3": "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
    # Removed on NSS master only (2026-11-05). When curl's file no longer holds one of these, delete its line.
    # Bug 2085917 (NSS commit 0bc5fc37c2): Buypass Class 2 and 3 removed from NSS.
    "Buypass Class 2 Root CA": "9a114025197c5bb95d94e63d55cd43790847b646b23cdf11ada4a00eff15fb48",
    "Buypass Class 3 Root CA": "edf7ebbca27a2a384d387b7d4010c666e2edb4843e4c29b4ae1d5b9332e6b24d",
    # Bug 2088266 (99c6ac3f7c): Websites trust bit removed from QuoVadis Root CA 1 G3 and 3 G3.
    "QuoVadis Root CA 1 G3": "8a866fd1b276b57e578e921c65828a2bed58e9f2f288054134b7f1f4bfc9cc74",
    "QuoVadis Root CA 3 G3": "88ef81de202eb018452e43f864725cea5fbd1fc2d9d205730709c5d8b8690f46",
    # Bug 2085928 (ca6b9b0021): Websites trust bit removed from Certigna Root CA.
    "Certigna Root CA": "d48d3d23eedb50a459e55197601c27774b9d7b18c94d5a059511a10250b93168",
    # Bug 2017322 (0dae6498e1, fc168131f8): distrust-after 2026-04-15. The Baseline Requirements cap TLS certificates
    # at 200 days since 2026-03-15, so every certificate issued before that date has expired (by 2026-11-01);
    # keeping the root would only admit certificates Firefox refuses.
    "Izenpe.com": "2530cc8e98321502bad96f9b1fba1b099e2d299e0f4548bb914f363bc0d4531f",
}
# Roots Mozilla trusts only for certificates issued before a date (CKA_NSS_SERVER_DISTRUST_AFTER). mbedTLS cannot
# apply the date, so these also accept a certificate issued after it. Kept while a certificate issued before the date
# can still be valid: the Baseline Requirements cap TLS certificates at 200 days. Once the date plus
# MAX_CERT_DAYS has passed the test fails; move the line to REMOVED then.
MAX_CERT_DAYS = 200
DISTRUST_AFTER = {
    # Bug 2085912 (e5cb445f1f)
    "Autoridad de Certificacion Firmaprofesional CIF A62634068":
        ("57de0583efd2b26e0361da99da9df4648def7ee8441c3b728afa9bcde0f9b26a", "2026-08-06"),
    # Bug 2089115 (30e59d44dc)
    "emSign Root CA - G1": ("40f6af0346a99aa1cd1d555a4e9cce62c7f9634603ee406615833dc8c8d00367", "2026-11-16"),
    # Bug 2092662 (8c60e757c3, 2026-11-13): Websites trust bit restored with this date
    "DigiCert Trusted Root G4": ("552f7bdcf1a7af9e6ce672017f4f12abf77240c78e761ac203d1d9d20ac89988", "2026-09-14"),
}
# sha256 of the whole file: curl's cacert.pem with the roots of REMOVED cut out (curl's own file when it holds none).
# A refresh changes this, the date in ca/README.md and the lists above together.
CACERT_SHA256 = "91787cf04ecb352f74cc3bd18730f986d6238f83643db331a6c3f2b3f1d300c2"
MAX_AGE_DAYS = 365  # the list is refreshed at least yearly; offline, so CI needs no network
MIN_ROOTS = 100  # Mozilla's list has about 120; an empty or truncated file is not it

# The HTTPS servers the firmware and the programs on the cartridge name: the services' (firmware/), the update
# check's (main/update.c and nes/cart/update.inc), NPR's stations (apps/npr/tools/gen_screen.py) and the HTTPS sample
# program's (samplecode/https). refresh.py checks each against a new list. KUSC's address sends the fetch on to a
# numbered *.live.streamtheworld.com, which changes, so it is not here.
HOSTS = [
    "nesp32.retrobits.tv",
    "nesp32-rendezvous.retrobits.workers.dev",
    "npr-ice.streamguys1.com",
    "opendata.adsb.fi",
    "query.wikidata.org",
    "public.api.bsky.app",
    "api.open-meteo.com",
    "geocoding-api.open-meteo.com",
    "en.wikipedia.org",
    "fm939.wnyc.org",
    "stream.wqxr.org",
    "kexp-mp3-128.streamguys1.com",
    "playerservices.streamtheworld.com",
    "ais-sa8.cdnstream1.com",
    "kclustream.callutheran.edu",
    "kuvo-ice.streamguys1.com",
    "stream.radioparadise.com",
    "ice2.somafm.com",
    "raw.githubusercontent.com",
]
# Where test_hosts_are_every_https_server_the_firmware_and_npr_name looks: C, C++ and Python sources for any
# https:// address, and the NES programs' assembly (.s, .inc, .asm) for one inside a "string" (so not in a ; comment).
# Both match https:// in any case, and compare the host in lower case. An address built from parts ("https://" and a
# host elsewhere, or a %s) is not seen.
HOST_SOURCES = ["firmware/main", "firmware/components/nesp_services", "apps/npr/tools/gen_screen.py",
                "nes", "apps/*/nes", "apps/*/net", "samplecode/*/nes"]

PEM_BLOCK = re.compile(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.DOTALL)


def fingerprints(pem_text):
    return {hashlib.sha256(base64.b64decode("".join(block.split()))).hexdigest()
            for block in PEM_BLOCK.findall(pem_text)}


def expiry_problems(today, distrust_after=None):
    """The DISTRUST_AFTER roots whose last possible certificate (date + MAX_CERT_DAYS) has expired."""
    distrust_after = DISTRUST_AFTER if distrust_after is None else distrust_after
    problems = []
    for name, (_, date) in distrust_after.items():
        last = datetime.date.fromisoformat(date) + datetime.timedelta(days=MAX_CERT_DAYS)
        if today > last:
            problems.append(f"{name}: no certificate issued before its distrust-after date {date} is valid after {last}; "
                            "run firmware/ca/refresh.py and move it from DISTRUST_AFTER to REMOVED "
                            "(firmware/ca/README.md)")
    return problems


def list_problems(pem_text, required=None, removed=None):
    """What is wrong with a root list: the roots it lacks, the removed ones it holds."""
    required = REQUIRED if required is None else required
    removed = REMOVED if removed is None else removed
    seen = fingerprints(pem_text)
    problems = []
    if len(seen) < MIN_ROOTS:
        problems.append(f"only {len(seen)} certificates (expected at least {MIN_ROOTS})")
    problems += [f"lacks {name}" for name, fp in required.items() if fp not in seen]
    problems += [f"holds {name}, which is in REMOVED" for name, fp in removed.items() if fp in seen]
    if removed is REMOVED:
        problems += [f"lacks {name}, which DISTRUST_AFTER keeps" for name, (fp, _) in DISTRUST_AFTER.items()
                     if fp not in seen]
    return problems


def der_element(der, pos):
    """(start of content, end) of the DER element at pos."""
    length = der[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(der[pos:pos + count], "big")
        pos += count
    return pos, pos + length


def cert_fields(der):
    """(serial, signature algorithm, issuer, validity, subject, SubjectPublicKeyInfo) DER of a certificate."""
    pos = der_element(der, 0)[0]            # Certificate
    pos = der_element(der, pos)[0]          # tbsCertificate
    if der[pos] == 0xA0:                    # [0] version, absent in a v1 certificate
        pos = der_element(der, pos)[1]
    fields = []
    for _ in range(6):
        end = der_element(der, pos)[1]
        fields.append(der[pos:end])
        pos = end
    return tuple(fields)


def subject_and_key(der):
    """(subject, SubjectPublicKeyInfo) DER of a certificate: what a bundle stores of it."""
    fields = cert_fields(der)
    return fields[4], fields[5]


def embedded_problems(embedded, pem_text, whole_bundle):
    """What is wrong with the bytes a build embedded, against the roots of cacert.pem.

    Every root's subject and key must be in it. A whole x509_crt_bundle must also have exactly their size (4 bytes of
    header each, plus 2 or 4 per root for the count or the offset table of ESP-IDF 5 or 6), so no root of ESP-IDF's
    own list is in it. The removed roots are looked for by name, which a binary holds too.
    """
    pairs = [subject_and_key(base64.b64decode("".join(block.split()))) for block in PEM_BLOCK.findall(pem_text)]
    problems = [f"lacks {len(pairs) - sum(n + k in embedded for n, k in pairs)} of the {len(pairs)} roots of cacert.pem"
                ] if not all(n + k in embedded for n, k in pairs) else []
    if whole_bundle:
        body = sum(4 + len(n) + len(k) for n, k in pairs)
        if len(embedded) not in (body + 2, body + 4 * len(pairs)):
            problems.append(f"is {len(embedded)} bytes, not the {body + 2} or {body + 4 * len(pairs)} "
                            "of a bundle made from cacert.pem")
    problems += [f"holds {name}" for name in REMOVED if name.encode() in embedded]
    return problems


def age_problem(pem_text, today):
    """Why a list is too old, from the 'Mozilla as of' date in its header; None when it is not."""
    match = re.search(r"Certificate data from Mozilla as of: \w+ (\w+ +\d+) [\d:]+ (\d{4}) GMT", pem_text)
    if not match:
        return "has no 'Certificate data from Mozilla as of' header"
    date = datetime.datetime.strptime(f"{match.group(1)} {match.group(2)}", "%b %d %Y").date()
    if (today - date).days > MAX_AGE_DAYS:
        return (f"is Mozilla data of {date}, more than {MAX_AGE_DAYS} days old: "
                "run firmware/ca/refresh.py (firmware/ca/README.md)")
    return None


def selection_problems(build, found, generated):
    """Why a build's settings do not make it embed cacert.pem alone, verifying as the servers need."""
    problems = []
    for name in ("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_NONE", "CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE"):
        if found.get(name) != "y":
            problems.append(f"{build}: {name} is {found.get(name, 'not set')}, not y")
    if found.get("CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH") != BUNDLE_PATH:
        problems.append(f"{build}: CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH is "
                        f"{found.get('CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH')!r}, not {BUNDLE_PATH!r}")
    # Some servers send a chain whose top is issued by a root Mozilla no longer has (GlobalSign Root CA, Go Daddy
    # Class 2): the bundle finds the root lower down only with cross-signed verification, ESP-IDF's default.
    # And ESP-IDF's list of deprecated roots must not come back in.
    for name, value in (("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_CROSS_SIGNED_VERIFY", "y"),
                        ("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE", "y")):
        have = found.get(name, None if not generated else "n")
        if have not in ((value,) if generated else (value, None)):
            problems.append(f"{build}: {name} is {have}, not {value}")
    # The other two members of the bundle's choice: a later line turning one on would win over DEFAULT_NONE.
    for name in ("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_FULL", "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_CMN"):
        if found.get(name) == "y":
            problems.append(f"{build}: {name} is y, so ESP-IDF's list is embedded too")
    if found.get("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEPRECATED_LIST") == "y":
        problems.append(f"{build}: CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEPRECATED_LIST is y")
    if generated:
        roots = len(fingerprints(read(CACERT)))
        most = int(found.get("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_MAX_CERTS", "0"))
        if most < roots:
            problems.append(f"{build}: CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_MAX_CERTS is {most}, fewer than the "
                            f"{roots} roots")
    return problems


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def committed():
    with open(CACERT, "rb") as handle:
        return handle.read()


@pytest.mark.parametrize("build", sorted(sdkconfig.BUILDS))
def test_every_build_embeds_the_vendored_list(build):
    found = selection_problems(build, sdkconfig.defaults(build), generated=False)
    assert not found, "\n".join(found)
    assert os.path.isfile(os.path.join(FIRMWARE, BUNDLE_PATH))


SELECTION_MUTANTS = {
    "ESP-IDF's full list": "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_FULL=y",
    "ESP-IDF's common list": "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_CMN=y",
    "no custom list": "CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE=n",
    "another file": 'CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH="ca/other.pem"',
    "no cross-signed verification": "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_CROSS_SIGNED_VERIFY=n",
    "the deprecated roots": "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEPRECATED_LIST=y",
    "no bundle": "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=n",
}


@pytest.mark.parametrize("mutant", sorted(SELECTION_MUTANTS))
@pytest.mark.parametrize("build", sorted(sdkconfig.BUILDS))
def test_a_change_to_the_selection_is_caught(build, mutant):
    """A line added at the end of the last defaults file a build reads, so that it wins."""
    last = sdkconfig.defaults_files(build)[-1]
    text = read(os.path.join(FIRMWARE, last)) + "\n" + SELECTION_MUTANTS[mutant] + "\n"
    assert selection_problems(build, sdkconfig.defaults(build, {last: text}), generated=False), \
        "%s was not caught" % mutant


@pytest.mark.parametrize("build", sorted(sdkconfig.BUILDS))
def test_the_last_build_was_configured_with_it(build):
    path = os.path.join(FIRMWARE, "build-%s" % build, "sdkconfig")
    if not os.path.isfile(path):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("no firmware/build-%s/sdkconfig, where release.yml builds it: "
                        "has its -B directory changed?" % build)
        pytest.skip("no firmware/build-%s/sdkconfig: the firmware is not built here" % build)
    found = selection_problems(build, sdkconfig.settings(read(path)), generated=True)
    assert not found, "\n".join(found)


def test_the_list_is_the_pinned_one_with_the_roots_needed_and_none_removed():
    raw = committed()
    assert hashlib.sha256(raw).hexdigest() == CACERT_SHA256, \
        "cacert.pem is not the file CACERT_SHA256 pins (curl's cacert.pem without REMOVED); a refresh changes both"
    problems = list_problems(raw.decode("utf-8"))
    assert not problems, "; ".join(problems)


def test_the_list_is_less_than_a_year_old_and_an_older_one_is_caught():
    text = committed().decode("utf-8")
    problem = age_problem(text, datetime.date.today())
    assert not problem, "cacert.pem " + str(problem)
    assert age_problem(text, datetime.date.today() + datetime.timedelta(days=2 * MAX_AGE_DAYS))


def without(text, fingerprint):
    return PEM_BLOCK.sub(lambda block: "" if hashlib.sha256(base64.b64decode("".join(block.group(1).split())))
                         .hexdigest() == fingerprint else block.group(0), text)


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_a_list_that_lacks_a_root_the_servers_need_is_caught(name):
    text = committed().decode("utf-8")
    assert any(f"lacks {name}" in p for p in list_problems(without(text, REQUIRED[name])))


def test_a_list_that_holds_a_removed_root_is_caught():
    text = committed().decode("utf-8")
    # any root can stand in for a removed one once it is named as removed
    stand_in = {"stand-in": REQUIRED["ISRG Root X1"]}
    assert any("holds stand-in" in p for p in list_problems(text, removed=stand_in))


def test_the_distrust_after_roots_are_kept_until_their_last_certificate_can_expire():
    text = committed().decode("utf-8")
    name, (fp, _) = next(iter(DISTRUST_AFTER.items()))
    assert any(f"lacks {name}" in p for p in list_problems(without(text, fp)))
    problems = expiry_problems(datetime.date.today())
    assert not problems, "; ".join(problems)
    probe = {"probe": ("", "2026-01-01")}
    day = datetime.date(2026, 1, 1) + datetime.timedelta(days=MAX_CERT_DAYS)
    assert not expiry_problems(day, probe) and expiry_problems(day + datetime.timedelta(days=1), probe)
    assert len(expiry_problems(datetime.date(2030, 1, 1))) == len(DISTRUST_AFTER)


def hosts_named(path):
    """The https:// hosts a source file, or the files of a directory, name."""
    files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]
    named = set()
    for name in files:
        if name.endswith((".c", ".cpp", ".h", ".py")):
            # an address after "+" is a User-Agent's contact (the project's page), not a server it fetches from
            named |= {host.lower() for host in re.findall(r"(?<!\+)https://([A-Za-z0-9.-]+)", read(name),
                                                          re.IGNORECASE)}
        elif name.endswith((".s", ".inc", ".asm")):
            named |= {host.lower() for host in re.findall(r'"https://([A-Za-z0-9.-]+)', read(name), re.IGNORECASE)}
    return named


def test_hosts_are_every_https_server_the_firmware_and_npr_name():
    named = set()
    for source in HOST_SOURCES:
        for path in sorted(glob.glob(os.path.join(ROOT, source))):
            named |= hosts_named(path)
    assert named, "no https:// address found in %s" % HOST_SOURCES
    assert sorted(named - set(HOSTS)) == [], "servers refresh.py does not check: add them to HOSTS"
    assert sorted(set(HOSTS) - named) == [], "HOSTS names servers nothing uses any more"


def test_the_readme_names_only_servers_in_hosts():
    # A server firmware/ca/README.md names (`a.b.c`: two dots or more, so not a file such as `cacert.pem`) is one the
    # firmware still uses, so the README's account of the chains does not outlive a server dropped from HOSTS.
    named = set(re.findall(r"`([a-z0-9-]+(?:\.[a-z0-9-]+){2,})`", read(os.path.join(CA_DIR, "README.md"))))
    assert named, "the README names no server: has this check's pattern gone stale?"
    assert sorted(named - set(HOSTS)) == [], "firmware/ca/README.md names servers not in HOSTS"


def test_an_address_in_c_is_found_in_any_case(tmp_path):
    source = tmp_path / "probe.c"
    source.write_text('const char *a = "HTTPS://Api.Example.org/x";\n'
                      'const char *agent = "nesp32 (+https://contact.example.org/)";\n')
    assert hosts_named(str(source)) == {"api.example.org"}


def test_an_address_in_nes_assembly_is_found_and_one_in_a_comment_is_not(tmp_path):
    source = tmp_path / "probe.inc"
    source.write_text('; see https://comment.example.org/ for this\n'
                      'probe_url: .byte "https://api.example.org/"\n'
                      'other_url: .byte "HTTPS://Other.Example.org/"\n')
    assert hosts_named(str(source)) == {"api.example.org", "other.example.org"}


@pytest.mark.parametrize("check", ["test_the_last_build_was_configured_with_it",
                                   "test_the_bundle_the_last_build_embedded_is_the_list"])
def test_a_missing_build_fails_on_github_actions_and_is_skipped_elsewhere(check, monkeypatch, tmp_path):
    """release.yml builds all three before the tests: there a build that is not there is a fault."""
    monkeypatch.setattr(sys.modules[__name__], "FIRMWARE", str(tmp_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(pytest.fail.Exception):
        globals()[check]("esp32")
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(pytest.skip.Exception):
        globals()[check]("esp32")


def bundle_of(text, offsets):
    """An x509_crt_bundle made from a list: ESP-IDF 5's layout (a count), or 6's (an offset table)."""
    pairs = [subject_and_key(base64.b64decode("".join(block.split()))) for block in PEM_BLOCK.findall(text)]
    entries = [len(n).to_bytes(2, "little") + len(k).to_bytes(2, "little") + n + k for n, k in pairs]
    if not offsets:
        return pairs, entries, len(pairs).to_bytes(2, "little") + b"".join(entries)
    position, table = 4 * len(entries), b""
    for entry in entries:
        table += position.to_bytes(4, "little")
        position += len(entry)
    return pairs, entries, table + b"".join(entries)


@pytest.mark.parametrize("offsets", [False, True], ids=["ESP-IDF 5 layout", "ESP-IDF 6 layout"])
def test_the_embedded_check_accepts_the_lists_bundle_and_refuses_others(offsets):
    text = committed().decode("utf-8")
    pairs, _, bundle = bundle_of(text, offsets)
    assert not embedded_problems(bundle, text, True)
    longer = bundle + b"\0\0\0\0" + pairs[0][0] + b"x" + pairs[0][1]
    assert embedded_problems(longer, text, True), "a bundle with an extra root was accepted"
    first = PEM_BLOCK.search(text).group(0)
    shorter = bundle_of(text.replace(first, "", 1), offsets)[2]
    assert embedded_problems(shorter, text, True), "a bundle without a root was accepted"
    assert any("holds emSign ECC Root CA - G3" in p
               for p in embedded_problems(bundle + b"emSign ECC Root CA - G3", text, False))


@pytest.mark.parametrize("build", sorted(sdkconfig.BUILDS))
def test_the_bundle_the_last_build_embedded_is_the_list(build):
    directory = os.path.join(FIRMWARE, "build-%s" % build)
    bundle = os.path.join(directory, "esp-idf", "mbedtls", "x509_crt_bundle")
    binary = os.path.join(directory, "nesp32.bin")
    source = bundle if os.path.isfile(bundle) else binary if os.path.isfile(binary) else None
    if source is None:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("no firmware/build-%s/nesp32.bin, where release.yml builds it: "
                        "has its -B directory changed?" % build)
        pytest.skip("no firmware/build-%s/nesp32.bin: the firmware is not built here" % build)
    with open(source, "rb") as handle:
        embedded = handle.read()
    problems = embedded_problems(embedded, committed().decode("utf-8"), source == bundle)
    assert not problems, os.path.relpath(source, ROOT) + " " + "; ".join(problems)


# refresh.py, without a network.

def load_refresh(source=None):
    """refresh.py as a module; `source` is a (mutated) copy of its text."""
    path = os.path.join(CA_DIR, "refresh.py")
    spec = importlib.util.spec_from_file_location("firmware_ca_refresh", path)
    module = importlib.util.module_from_spec(spec)
    if source is None:
        spec.loader.exec_module(module)
    else:
        exec(compile(source, path, "exec"), module.__dict__)
    return module


def pem_of(der):
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----\n"


def mozilla_date(text, date):
    return text.replace(text[text.index("as of: ") + 7:text.index(" GMT")], date.strftime("%a %b %d 13:32:40 %Y"))


class Tree:
    """refresh.py run against a fake curl.se, on a temporary copy of the files it reads and writes."""

    FILES = ("firmware/ca/cacert.pem", "firmware/ca/README.md", "tests/test_firmware_ca.py")
    READ = ("tests/test_firmware_sdkconfig.py",)

    def __init__(self, refresh):
        self.refresh = refresh

    def run(self, get, verify=lambda host, pem, ca: 4, pem=None):
        tree = tempfile.mkdtemp()
        try:
            for relative in self.FILES + self.READ:
                os.makedirs(os.path.join(tree, os.path.dirname(relative)), exist_ok=True)
                shutil.copy(os.path.join(ROOT, relative), os.path.join(tree, relative))
            if pem is not None:
                Path(tree, self.FILES[0]).write_text(pem)
            files = [os.path.join(tree, relative) for relative in self.FILES]
            before = [Path(f).read_bytes() for f in files]
            out = io.StringIO()
            try:
                result, error = self.refresh.refresh(tree, get, verify, out), None
            except self.refresh.RefreshError as exc:
                result, error = None, str(exc)
            stray = [f for f in os.listdir(os.path.dirname(files[0])) if f.endswith(".new")]
            return types.SimpleNamespace(result=result, error=error, out=out.getvalue(), before=before,
                                         after=[Path(f).read_bytes() for f in files], stray=stray)
        finally:
            shutil.rmtree(tree)


def served(data, listed=None):
    data = data.encode() if isinstance(data, str) else data
    digest = listed or hashlib.sha256(data).hexdigest()
    return lambda url: data if url.endswith(".pem") else (digest + "  cacert.pem\n").encode()


@pytest.fixture
def refresh_setup():
    refresh = load_refresh()
    text = committed().decode("utf-8")
    date = refresh.header_date(text)
    later = date + datetime.timedelta(days=40)
    names = refresh.root_names(text, sys.modules[__name__])
    victim = next(fp for fp in names if fp not in REQUIRED.values()
                  and fp not in {fp for fp, _ in DISTRUST_AFTER.values()})
    name = names[victim]
    block = re.search(r"^" + re.escape(name) + r"\n=+\n(?:#[^\n]*\n)*-----BEGIN CERTIFICATE-----.*?"
                      r"-----END CERTIFICATE-----\n", text, re.MULTILINE | re.DOTALL)
    assert block, f"could not find the block of {name} in cacert.pem; this test needs updating"
    newer = mozilla_date(text.replace(block.group(0), ""), later)
    assert newer != text and refresh.header_date(newer) == later
    return types.SimpleNamespace(refresh=refresh, tree=Tree(refresh), text=text, date=date, later=later,
                                 names=names, victim=victim, name=name, block=block.group(0), newer=newer)


def untouched(outcome):
    return outcome.before == outcome.after and not outcome.stray


def test_refresh_refuses_a_download_that_does_not_match_its_hash(refresh_setup):
    s = refresh_setup
    wrong = s.tree.run(served(s.newer, "0" * 64))
    assert wrong.error and "does not match" in wrong.error and untouched(wrong)


def test_refresh_refuses_a_truncated_list(refresh_setup):
    s = refresh_setup
    few = s.tree.run(served("".join(s.text.splitlines(True)[:1200])))
    assert few.error and untouched(few)


def test_refresh_refuses_a_list_without_a_root_the_servers_need(refresh_setup):
    s = refresh_setup
    missing = s.tree.run(served(without(s.newer, REQUIRED["GTS Root R4"])))
    assert missing.error and "GTS Root R4" in missing.error and untouched(missing)


def test_refresh_refuses_an_older_list(refresh_setup):
    s = refresh_setup
    older = s.tree.run(served(mozilla_date(s.text, s.date - datetime.timedelta(days=30))))
    assert older.error and "older" in older.error and untouched(older)


def test_refresh_refuses_a_list_a_server_does_not_verify_against(refresh_setup):
    s = refresh_setup

    def refuse(host, pem, ca):
        raise s.refresh.RefreshError(f"{host}: the chain does not verify against the new list")
    server = s.tree.run(served(s.newer), refuse)
    assert server.error and untouched(server)


def test_refresh_checks_every_host(refresh_setup):
    s = refresh_setup
    seen = []
    s.tree.run(served(s.newer), lambda host, pem, ca: seen.append(host) or 3)
    assert seen == HOSTS


def test_refresh_takes_a_good_list_and_updates_the_three_places(refresh_setup):
    s = refresh_setup
    done = s.tree.run(served(s.newer))
    assert done.result is True and not done.error, done.error
    new_hash = hashlib.sha256(s.newer.encode()).hexdigest()
    assert done.after[0] == s.newer.encode()
    assert f'CACERT_SHA256 = "{new_hash}"'.encode() in done.after[2]
    assert f"of {s.later} ({len(s.names) - 1} roots)".encode() in done.after[1]
    assert not done.stray
    assert f"removed: {s.name}" in done.out and "added:" not in done.out, done.out


def test_refresh_cuts_a_removed_root_curl_still_ships_and_pins_the_cut_list(refresh_setup, monkeypatch):
    s = refresh_setup
    ca = types.ModuleType("ca_with_removed")
    ca.__dict__.update(sys.modules[__name__].__dict__)
    ca.REMOVED = {**REMOVED, s.name: s.victim}
    monkeypatch.setattr(s.refresh, "load_test", lambda root=None: ca)
    later_text = mozilla_date(s.text, s.later)
    cut_text = later_text.replace(s.block + "\n", "")
    assert cut_text != later_text and cut_text.count("\n\n\n") == later_text.count("\n\n\n")
    cut = s.tree.run(served(later_text))
    assert cut.result is True and not cut.error and cut.after[0] == cut_text.encode(), cut.error
    cut_hash = hashlib.sha256(cut_text.encode()).hexdigest()
    assert f'CACERT_SHA256 = "{cut_hash}"'.encode() in cut.after[2]
    assert hashlib.sha256(later_text.encode()).hexdigest().encode() not in cut.after[2]
    assert f"dropped: {s.name}" in cut.out and f"removed: {s.name}" not in cut.out
    assert f"({len(s.names) - 1} roots)".encode() in cut.after[1]


def test_refresh_reports_an_unchanged_list(refresh_setup):
    s = refresh_setup
    same = s.tree.run(served(s.text))
    assert same.result is False and "no change" in same.out and untouched(same)


def test_refresh_says_when_an_unchanged_list_has_passed_the_age_limit(refresh_setup):
    s = refresh_setup
    stale = mozilla_date(s.text, datetime.date.today() - datetime.timedelta(days=MAX_AGE_DAYS + 30))
    aged = s.tree.run(served(stale), pem=stale)
    assert aged.result is False and "age limit needs a maintainer decision" in aged.out and untouched(aged)


def test_refresh_fetches_https_only():
    refresh = load_refresh()
    for url in ("http://curl.se/ca/cacert.pem", "ftp://curl.se/ca/cacert.pem"):
        with pytest.raises(refresh.RefreshError):
            refresh.fetch(url)
    handler = refresh.HttpsOnly()
    request = refresh.urllib.request.Request("https://curl.se/ca/cacert.pem")
    for target in ("http://example.org/cacert.pem", "ftp://example.org/cacert.pem"):
        with pytest.raises(refresh.RefreshError):
            handler.redirect_request(request, None, 302, "Found", {}, target)
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/cacert.pem") is not None
    used = []

    class Spy:
        def open(self, *args, **kwargs):
            raise OSError("no network in this test")

    real = refresh.urllib.request.build_opener
    refresh.urllib.request.build_opener = lambda *handlers: used.extend(handlers) or Spy()
    try:
        with pytest.raises(refresh.RefreshError):
            refresh.fetch("https://curl.se/ca/cacert.pem")
    finally:
        refresh.urllib.request.build_opener = real
    assert refresh.HttpsOnly in used


def der(tag, content):
    """A DER element."""
    length = len(content)
    if length < 0x80:
        head = bytes([length])
    else:
        size = length.to_bytes((length.bit_length() + 7) // 8, "big")
        head = bytes([0x80 | len(size)]) + size
    return bytes([tag]) + head + content


def der_name(cn):
    """A Name of one CN."""
    attribute = der(0x30, der(0x06, bytes.fromhex("550403")) + der(0x0C, cn.encode()))
    return der(0x30, der(0x31, attribute))


def fake_cert(issuer, subject):
    """The DER of a certificate with these names and nothing that can be verified: enough for cert_fields."""
    tbs = (der(0xA0, der(0x02, b"\x02")) + der(0x02, b"\x01") + der(0x30, der(0x06, bytes.fromhex("2a8648ce3d040302")))
           + issuer + der(0x30, b"") + subject + der(0x30, b""))
    return der(0x30, der(0x30, tbs) + der(0x30, b"") + der(0x03, b"\x00"))


def chain_cases(refresh, text):
    """What judge_chain must say about what `openssl s_client -showcerts` printed (made up here); a list of what it
    got wrong."""
    ca = sys.modules[__name__]
    ders = [base64.b64decode("".join(block.split())) for block in PEM_BLOCK.findall(text)]
    x1 = next(d for d in ders if hashlib.sha256(d).hexdigest() == REQUIRED["ISRG Root X1"])
    reduced = "".join(pem_of(d) for d in ders if d != x1)       # a list that lacks the issuer of X1
    ok = "Certificate chain\n" + pem_of(x1) + "---\n    Verify return code: 0 (ok)\n"
    spoof = ("Certificate chain\n 0 s:CN = Verify return code: 0 (ok)\n   i:CN = x\n" + pem_of(x1)
             + "---\n    Verify return code: 18 (self-signed certificate)\n")

    def verdict(output, code, roots):
        try:
            refresh.judge_chain("host", output, code, roots, ca)
        except refresh.RefreshError as exc:
            return str(exc)
        except Exception as exc:                # a guard taken out can make it crash: that is a refusal too
            return "crashed: %r" % exc
        return None

    wrong = []
    if verdict(ok, 0, text):
        wrong.append("a verified chain issued by a root of the list was refused")
    if not verdict(ok, 1, text):
        wrong.append("a non-zero openssl exit code was ignored")
    if not verdict(spoof, 1, text) or not verdict(spoof, 0, text):
        wrong.append("a server name that spells the verify line was believed")
    if not verdict("Certificate chain\n" + pem_of(x1), 0, text):
        wrong.append("a chain without the verify line was accepted")
    if not verdict("Verify return code: 0 (ok)\n", 0, text):
        wrong.append("a chain without certificates was accepted")
    if "before the chain ends" not in (verdict(ok, 0, reduced) or ""):
        wrong.append("a chain no certificate of which is issued by a root of the list was accepted")
    # an unknown CA's certificate, then an unrelated one whose issuer IS in the list: no parent for the first
    unknown = next(d for d in ders if d != x1 and hashlib.sha256(d).hexdigest() not in REQUIRED.values())
    no_unknown = "".join(pem_of(d) for d in ders if d != unknown)
    trailing = "Certificate chain\n" + pem_of(unknown) + pem_of(x1) + "---\n    Verify return code: 0 (ok)\n"
    if "before the chain ends" not in (verdict(trailing, 0, no_unknown) or ""):
        wrong.append("an unrelated trailing certificate hid a chain the firmware would refuse")
    if verdict(trailing, 0, text):
        wrong.append("a chain of a root of the list followed by another root was refused")
    # ESP-IDF's cross-signed verification: a certificate issued by a root of the list (made up here, as a child
    # of X1), sent with X1 cross-signed by a CA the list lacks. The top of the chain is not issued by a root of the
    # list, but the lowest certificate is, and the firmware stops there, so it verifies.
    x1_subject = cert_fields(x1)[4]
    child = fake_cert(issuer=x1_subject, subject=der_name("intermediate"))
    x1_cross = fake_cert(issuer=cert_fields(unknown)[4], subject=x1_subject)
    cross = "Certificate chain\n" + pem_of(child) + pem_of(x1_cross) + "---\n    Verify return code: 0 (ok)\n"
    if verdict(cross, 0, no_unknown):
        wrong.append("a chain whose lowest certificate is issued by a root of the list was refused")
    # and one whose lowest certificate's issuer is not in the list, nor sent: refused
    orphan = fake_cert(issuer=der_name("nobody"), subject=der_name("leaf"))
    if "before the chain ends" not in (verdict("Certificate chain\n" + pem_of(orphan) + pem_of(x1_cross)
                                               + "---\n    Verify return code: 0 (ok)\n", 0, no_unknown) or ""):
        wrong.append("a leaf whose issuer is neither a root of the list nor sent was accepted")
    return wrong


def test_the_server_check_refuses_a_spoofed_result_a_failed_exit_and_a_chain_the_list_does_not_issue():
    wrong = chain_cases(load_refresh(), committed().decode("utf-8"))
    assert not wrong, "; ".join(wrong)


GUARDS = (("    if returncode != 0:\n", "    if False:\n"),
          ("    if not VERIFIED.search(output):\n", "    if False:\n"),
          ("        if parent is None or fields[at][2] == fields[at][4]:\n", "        if False:\n"),
          ("    while fields[at][2] not in subjects:\n", "    while False:\n"))


@pytest.mark.parametrize("guard,off", GUARDS, ids=[g.strip() for g, _ in GUARDS])
def test_each_guard_of_the_server_check_is_needed(guard, off):
    with open(os.path.join(CA_DIR, "refresh.py"), encoding="utf-8") as handle:
        source = handle.read()
    assert source.count(guard) == 1, f"could not find {guard.strip()!r} in refresh.py; this test needs updating"
    assert chain_cases(load_refresh(source.replace(guard, off)), committed().decode("utf-8")), \
        f"the cases still pass without {guard.strip()!r}"


def test_check_server_against_a_local_openssl_s_server(tmp_path):
    """check_server against a real `openssl s_server` with a throwaway CA, when this openssl can do it."""
    refresh = load_refresh()
    problem = refresh.openssl_problem()
    if problem:
        pytest.skip("openssl s_client was not run against a local server: " + problem)
    tmp = str(tmp_path)

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=tmp, check=True, capture_output=True, timeout=60)

    def serve(cn, chain):
        """Starts s_server for a leaf with this CN, sending the leaf and `chain`; returns (process, port)."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        openssl("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", "leaf.key",
                "-out", "leaf.csr", "-subj", f"/CN={cn}", "-addext", "subjectAltName=DNS:localhost")
        openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
                "-out", "leaf.pem", "-days", "2", "-copy_extensions", "copy")
        server = subprocess.Popen(["openssl", "s_server", "-accept", f"127.0.0.1:{port}", "-cert", "leaf.pem", "-key",
                                   "leaf.key", *(["-cert_chain", chain] if chain else []), "-quiet"], cwd=tmp,
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        return server, port

    openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout",
            "ca.key", "-out", "ca.pem", "-subj", "/CN=Test Root", "-days", "2",
            "-addext", "basicConstraints=critical,CA:TRUE")
    shutil.copy(CACERT, os.path.join(tmp, "committed.pem"))
    outcomes = {}
    for label, cn, chain, roots in (("ok", "localhost", "ca.pem", "ca.pem"),
                                    ("unknown CA", "localhost", "ca.pem", "committed.pem"),
                                    ("spoofed name", "Verify return code: 0 (ok)", "ca.pem", "committed.pem")):
        server, port = serve(cn, chain)
        try:
            try:
                refresh.check_server("localhost", os.path.join(tmp, roots), sys.modules[__name__], port=port)
                outcomes[label] = None
            except refresh.RefreshError as exc:
                outcomes[label] = str(exc)
        finally:
            server.kill()
            server.wait()
    assert not outcomes["ok"], "a server whose chain the list verifies was refused: " + str(outcomes["ok"])
    assert outcomes["unknown CA"], "check_server accepted a server with an unknown CA"
    assert outcomes["spoofed name"], "check_server accepted a server with a spoofed name"
