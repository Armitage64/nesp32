#!/usr/bin/env python3
"""Refreshes the root list the firmware trusts (firmware/ca/cacert.pem).

    python3 firmware/ca/refresh.py

Adapted from 1541ultimate's software/u64ctrl/ca/refresh.py (GPL-3.0).

Downloads curl's cacert.pem and the sha256 curl publishes next to it (HTTPS only, into memory), cuts out the roots
named in REMOVED (which curl may still ship), and changes nothing in the tree unless every check passes: the hash
matches, the file is PEM with at least MIN_ROOTS roots, it holds the roots the firmware's servers need and none in
REMOVED, it is not older than the committed list, and every server in HOSTS verifies against it (`openssl s_client
-CAfile`, and a certificate the server sends must be issued by a root of the list, the first of them up from the
leaf being where ESP-IDF's bundle stops). Then it replaces cacert.pem and updates the pinned sha256 in
tests/test_firmware_ca.py and the date in ca/README.md. It prints the roots added and removed: add the removed ones to
REMOVED in the test. Nothing downloaded is executed.

Needs only the standard library and OpenSSL 3 or later's `openssl` command (not LibreSSL, which macOS ships in
/usr/bin: `brew install openssl` and put it first in PATH). The sha256 curl publishes comes from the same server as
the file, so it shows the download was not corrupted, not that curl.se was honest; review the printed roots.
"""

import base64
import datetime
import hashlib
import http.client
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

URL = "https://curl.se/ca/cacert.pem"
MAX_BYTES = 4 * 1024 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TEST = os.path.join("tests", "test_firmware_ca.py")


class RefreshError(Exception):
    pass


def load_test(root=ROOT):
    """The test module: it holds MIN_ROOTS, REQUIRED, REMOVED, HOSTS and the PEM and DER helpers."""
    sys.path.insert(0, os.path.join(root, "tests"))
    spec = importlib.util.spec_from_file_location("test_firmware_ca", os.path.join(root, TEST))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HttpsOnly(urllib.request.HTTPRedirectHandler):
    """A redirect to anything but https is an error, as is a start URL that is not https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise RefreshError(f"{req.full_url} redirects to {newurl}, which is not https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    if urllib.parse.urlparse(url).scheme != "https":
        raise RefreshError(f"{url} is not an https URL")
    try:
        with urllib.request.build_opener(HttpsOnly).open(url, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
    except (OSError, http.client.HTTPException) as error:
        raise RefreshError(f"cannot download {url}: {error}") from error
    if len(data) > MAX_BYTES:
        raise RefreshError(f"{url} is larger than {MAX_BYTES} bytes")
    return data


def root_names(text, ca):
    """{certificate sha256: name} for the roots of a cacert.pem; the name is the line above each ==== underline."""
    names = {}
    for match in re.finditer(r"^(\S[^\n]*)\n=+\n(?:#[^\n]*\n)*(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
                             text, re.MULTILINE | re.DOTALL):
        names.update({fp: match.group(1) for fp in ca.fingerprints(match.group(2))})
    return names


BLOCK = re.compile(r"^\S[^\n]*\n=+\n(?:#[^\n]*\n)*-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n\n?",
                   re.MULTILINE | re.DOTALL)


def drop_removed(text, ca):
    """(text without the roots in REMOVED, [names of the roots dropped]).

    curl builds its file from Mozilla's release branch, which lags NSS master: a root deleted from master, or one
    that lost its Websites trust bit there, stays in curl's file for a release or more. REMOVED names them, and they
    are cut out here, block by block, so the rest of the file stays curl's, byte for byte.
    """
    dropped = []

    def keep(match):
        found = ca.fingerprints(match.group(0)) & set(ca.REMOVED.values())
        if found:
            dropped.append(match.group(0).split("\n", 1)[0])
        return "" if found else match.group(0)

    return BLOCK.sub(keep, text), dropped


def header_date(text):
    match = re.search(r"Certificate data from Mozilla as of: \w+ (\w+ +\d+) [\d:]+ (\d{4}) GMT", text)
    if not match:
        raise RefreshError("the file has no 'Certificate data from Mozilla as of' header")
    return datetime.datetime.strptime(f"{match.group(1)} {match.group(2)}", "%b %d %Y").date()


VERIFIED = re.compile(r"^\s*Verify return code: 0 \(ok\)\s*$", re.MULTILINE)


def judge_chain(host, output, returncode, roots_pem, ca):
    """Whether what `openssl s_client -showcerts` printed shows a server that the list verifies.

    The exit code must be 0 and a whole line must say `Verify return code: 0 (ok)`; a server's own names cannot make
    such a line, as s_client prints them after `s:` and `i:`. And ESP-IDF's bundle must find its root as mbedTLS
    asks for one: from the leaf up through the certificates the server sends, each one's issuer is looked for in the
    list first (CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_CROSS_SIGNED_VERIFY) and among the later certificates sent only
    when it is not there. So going up, a certificate whose issuer is a root of the list must come before the chain
    runs out; an unrelated certificate sent after the chain does not count. Returns the number of certificates sent.
    """
    if returncode != 0:
        raise RefreshError(f"{host}: openssl s_client failed (exit {returncode}); the chain does not verify "
                           "against the new list")
    if not VERIFIED.search(output):
        raise RefreshError(f"{host}: openssl does not report a verified chain against the new list")
    chain = [base64.b64decode("".join(block.split())) for block in ca.PEM_BLOCK.findall(output)]
    if not chain:
        raise RefreshError(f"{host}: openssl printed no certificates")
    subjects = {ca.cert_fields(base64.b64decode("".join(block.split())))[4] for block in ca.PEM_BLOCK.findall(roots_pem)}
    fields = [ca.cert_fields(der) for der in chain]
    at = 0
    while fields[at][2] not in subjects:
        parent = next((j for j in range(at + 1, len(fields)) if fields[j][4] == fields[at][2]), None)
        if parent is None or fields[at][2] == fields[at][4]:
            raise RefreshError(f"{host}: no certificate it sends, going up from the leaf, is issued by a root of the "
                               "new list before the chain ends; the firmware would refuse it")
        at = parent
    return len(chain)


def openssl_problem():
    """Why this openssl cannot be used, or None."""
    try:
        version = subprocess.run(["openssl", "version"], capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return "there is no openssl command; install OpenSSL 3 or later"
    found = re.match(r"OpenSSL (\d+)", version)
    if not found or int(found.group(1)) < 3:
        return (f"openssl is {version.strip() or 'unknown'}; this needs OpenSSL 3 or later (LibreSSL, which macOS "
                "ships, also trusts the system certificates and lacks -verify_hostname): brew install openssl, "
                "and put it first in PATH")
    return None


def check_server(host, pem_path, ca, port=443):
    """The server's chain verifies against the file alone (no system certificates), over TLS 1.2 as the firmware
    speaks it, as judge_chain says."""
    problem = openssl_problem()
    if problem:
        raise RefreshError(problem)
    result = subprocess.run(
        ["openssl", "s_client", "-tls1_2", "-connect", f"{host}:{port}", "-servername", host, "-CAfile", pem_path,
         "-no-CApath", "-no-CAstore", "-verify_return_error", "-verify_hostname", host, "-showcerts"],
        input="", capture_output=True, text=True, timeout=60, check=False)
    with open(pem_path, encoding="utf-8") as handle:
        return judge_chain(host, result.stdout, result.returncode, handle.read(), ca)


def refresh(root=ROOT, get=fetch, verify_server=check_server, out=sys.stdout):
    """Returns True when the tree changed. Raises RefreshError, leaving the tree as it was, if anything fails."""
    ca = load_test(root)
    ca_dir = os.path.join(root, "firmware", "ca")
    pem_path = os.path.join(ca_dir, "cacert.pem")
    test_path = os.path.join(root, TEST)
    readme_path = os.path.join(ca_dir, "README.md")

    data = get(URL)
    published = re.match(r"\s*([0-9a-f]{64})\b", get(URL + ".sha256").decode("ascii", "replace"))
    if not published or hashlib.sha256(data).hexdigest() != published.group(1):
        raise RefreshError("the downloaded cacert.pem does not match the sha256 curl publishes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RefreshError("the downloaded file is not UTF-8 text") from error
    text, dropped = drop_removed(text, ca)
    problems = ca.list_problems(text)
    if problems:
        raise RefreshError("the downloaded list is not usable: " + "; ".join(problems))
    new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()  # of the file as committed, without REMOVED
    date = header_date(text)

    with open(pem_path, "rb") as handle:
        old_bytes = handle.read()
    old_text = old_bytes.decode("utf-8")
    if date < header_date(old_text):
        raise RefreshError(f"the download is Mozilla data of {date}, older than the committed {header_date(old_text)}")
    too_old = ca.age_problem(text, datetime.date.today())
    old, new = root_names(old_text, ca), root_names(text, ca)
    changed = new_hash != hashlib.sha256(old_bytes).hexdigest()
    if changed and too_old:
        raise RefreshError(f"the download {too_old}")
    print(f"downloaded cacert.pem of {date}, {len(new)} roots, sha256 {new_hash}", file=out)
    for name in dropped:
        print(f"dropped: {name}  (in REMOVED; curl still ships it)", file=out)
    for fp in sorted(set(old) - set(new) - set(ca.REMOVED.values()), key=old.get):
        print(f"removed: {old[fp]}  (add {fp} to REMOVED)", file=out)
    for fp in sorted(set(new) - set(old), key=new.get):
        print(f"added:   {new[fp]}", file=out)

    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, "cacert.pem")
        with open(candidate, "w", encoding="utf-8") as handle:
            handle.write(text)
        for host in ca.HOSTS:
            count = verify_server(host, candidate, ca)
            print(f"{host}: verifies against the list ({count} certificates sent)", file=out)

    if not changed:
        print("no change", file=out)
        if too_old:
            print(f"upstream is unchanged, but the list {too_old.split(':')[0]}: the age limit needs a maintainer "
                  "decision (see ca/README.md)", file=out)
        return False

    with open(test_path, encoding="utf-8") as handle:
        test_text = handle.read()
    with open(readme_path, encoding="utf-8") as handle:
        readme = handle.read()
    test_new, pins = re.subn(r'^(CACERT_SHA256 = ")[0-9a-f]{64}(")', rf"\g<1>{new_hash}\g<2>", test_text, flags=re.MULTILINE)
    readme_new, dates = re.subn(r"of \d{4}-\d\d-\d\d \(\d+ roots\)", f"of {date} ({len(new)} roots)", readme)
    if pins != 1 or dates != 1:
        raise RefreshError("could not find CACERT_SHA256 in the test or the date line in ca/README.md; "
                           "nothing was changed")
    # Stage all three, then replace them; if a replace fails, the ones already replaced are put back.
    targets = [(test_path, test_new), (readme_path, readme_new), (pem_path, text)]
    originals = {}
    for path, _ in targets:
        with open(path, "rb") as handle:
            originals[path] = handle.read()
    staged = []
    done = []
    try:
        for path, content in targets:
            with open(path + ".new", "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            staged.append(path + ".new")
        for path, _ in targets:
            os.replace(path + ".new", path)
            done.append(path)
    except OSError as error:
        for path in done:
            with open(path, "wb") as handle:
                handle.write(originals[path])
        raise RefreshError(f"could not write the new files ({error}); the old ones were put back") from error
    finally:
        for leftover in staged:
            if os.path.exists(leftover):
                os.remove(leftover)
    print(f"updated ca/cacert.pem, CACERT_SHA256 in {TEST} and the date in ca/README.md", file=out)
    print(f"next: add the removed roots (above) to REMOVED, run {TEST}, and again after a firmware build", file=out)
    return True


def main():
    try:
        refresh()
    except (RefreshError, subprocess.SubprocessError, OSError, ValueError) as error:
        print(f"refresh: {error}; nothing was changed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
