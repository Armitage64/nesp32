# The roots the firmware trusts

`cacert.pem` is curl's copy of Mozilla's root list of 2026-11-05 (112 roots) without the roots in `REMOVED`
(see below); its sha256 is pinned in `tests/test_firmware_ca.py` (`CACERT_SHA256`). Every build embeds it in place
of ESP-IDF's own list (`sdkconfig.defaults`), and the firmware's HTTPS checks servers against it
(`esp_crt_bundle_attach`). ESP-IDF's list lags Mozilla's: 6.0.3's, which the StickC Plus2 is built with, still holds
the three emSign roots removed from NSS's source in October 2026: `emSign ECC Root CA - G3` after the compromise of
eMudhra intermediate-certificate keys (Mozilla bug 2083449), and `emSign Root CA - C1` and `emSign ECC Root CA - C3`,
retired at eMudhra's request (bug 2083709). 5.5.5's held them on every board. `emSign Root CA - G1` stays, because
Mozilla still ships it.

Against ESP-IDF's list the change is larger than those roots. Counted by certificate, 6.1.1's holds 34 roots this one
does not: 28 that curl's file has already dropped, among them DigiCert Global Root CA, the Entrust roots and
AffirmTrust's, and the six that `REMOVED` cuts (below). It lacks 4 that this one has. 6.0.3's holds 37 and lacks 5. So
an arbitrary https address now verifies as it would in Firefox, and a server that still relies on one of those older
roots is refused.

The approach, the test and `refresh.py` are 1541ultimate's (`software/u64ctrl/ca`, GPL-3.0), adapted.

## Roots curl still ships

curl builds its file from Mozilla's release branch, which lags NSS master. `REMOVED` in the test also names roots
that master has deleted (Buypass Class 2 and 3), no longer trusts for websites (QuoVadis Root CA 1 G3 and 3 G3,
Certigna Root CA) or distrusts after a date that has made all their certificates expire (Izenpe.com, whose
certificates issued before 2026-04-15 are all expired, because TLS certificates are capped at 200 days since
2026-03-15). `refresh.py` cuts them out of curl's file, and everything else stays curl's, byte for byte. Delete a
line of `REMOVED` once curl's file no longer holds the root.

`DISTRUST_AFTER` lists the roots Mozilla trusts only for certificates issued before a date (Firmaprofesional,
emSign Root CA - G1, DigiCert Trusted Root G4). mbedTLS cannot apply the date, so these also accept later
certificates. They stay while a certificate issued before the date can still be valid, which is the date plus 200
days (`MAX_CERT_DAYS`); the test fails after that, and the line moves to `REMOVED`.

## Chains

The firmware finds a server's root as mbedTLS asks ESP-IDF's bundle for one: from the leaf up through the
certificates the server sends, each one's issuer is looked for in this list before the rest of the chain
(`CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_CROSS_SIGNED_VERIFY`, ESP-IDF's default, on in 6.0.3 and 6.1.1 alike). So the
root is the first one found going up, not the issuer of the last certificate sent. Two of the servers depend on
that: `opendata.adsb.fi` sends GTS Root R4 cross-signed by GlobalSign Root CA, and
`playerservices.streamtheworld.com` sends Go Daddy Root G2 cross-signed by Go Daddy Class 2, two roots this list
does not have; their certificates are issued by GTS Root R4 and Go Daddy Root G2, which it does. `REQUIRED` in the
test holds the roots the firmware's servers stop at.

## Refresh

Run `python3 firmware/ca/refresh.py` (standard library and OpenSSL 3 or later's `openssl` command, not the LibreSSL
in macOS's `/usr/bin`; it needs the network). It downloads curl's file and its published sha256 (https only; the hash
shows the download is intact, not that curl.se is honest, so review the printed roots), cuts out the roots in
`REMOVED`, and changes nothing unless the hash matches, the file is not older than the committed one, it holds at
least `MIN_ROOTS` roots, including those in `REQUIRED`, and none in `REMOVED`, and every server in `HOSTS` (the
firmware's, NPR's stations and the HTTPS sample program's) verifies against it over TLS 1.2. Then it replaces
`cacert.pem`, updates `CACERT_SHA256` and the date above, and prints the roots added and removed. Review that output,
add the removed roots to `REMOVED` in `tests/test_firmware_ca.py`, and run that test (again after a firmware build,
when it also checks what the build embedded). The test also fails when the list is more than a year old
(`MAX_AGE_DAYS`), without needing the network.

The test fails on set dates unless `refresh.py` is run. With the list as committed, `make test` starts failing on
2027-02-23 (Firmaprofesional's distrust-after date, 2026-08-06, plus the 200 days of `MAX_CERT_DAYS`), then on
2027-04-03 (DigiCert Trusted Root G4) and on 2027-06-05 (emSign Root CA - G1), and on 2027-11-06 at the latest, when
the list is more than `MAX_AGE_DAYS` (365) days old. That is on purpose: run `refresh.py`, and move a
`DISTRUST_AFTER` root whose date has passed to `REMOVED`. The failure says which.

If the test fails only because the list is older than `MAX_AGE_DAYS` and `refresh.py` says "no change", Mozilla's data
has not changed for that long: confirm that with `refresh.py` (curl's copy is the committed one), then raise
`MAX_AGE_DAYS` in the test.

The firmware checks no revocation (no OCSP, CRL or CRLite) and no certificate dates (`CONFIG_MBEDTLS_HAVE_TIME_DATE`
is unset), so a root Mozilla removes stays trusted until a firmware with a newer list is flashed.
