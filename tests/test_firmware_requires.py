"""Every ESP-IDF component firmware/main includes a header of is in its REQUIRES.

ESP-IDF 6.0 stopped bringing esp_driver_uart in through driver, and main,
which had never asked for it by name, stopped building at link.c's
#include "driver/uart.h" (#90). A header that a component in main's
REQUIRES happens to bring in is one ESP-IDF can take away in its next
release, so each header main includes has to come from a component it
names itself, from one ESP-IDF gives every component, or from a managed
component in main/idf_component.yml.

HEADERS and STANDARD cover the headers main includes, and only those. An
include that is in none of the lists fails here, written with "" or <>,
so that a new one is looked up and added rather than passed over. No
ESP-IDF is needed to run this.

A component appended for the S3 only (`list(APPEND requires bt esp_hid)`)
counts here for every target, so one moved into that list is not caught.
"""

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FIRMWARE = os.path.join(ROOT, "firmware")
MAIN = os.path.join(FIRMWARE, "main")

# The component each header comes from, in ESP-IDF 6.0.3 and 6.1.1 alike:
# the component whose include path has it.
HEADERS = {
    "driver/uart.h": "esp_driver_uart",
    "esp_timer.h": "esp_timer",
    "esp_wifi.h": "esp_wifi",
    "esp_netif.h": "esp_netif",
    "esp_netif_sntp.h": "esp_netif",
    "esp_event.h": "esp_event",
    "nvs.h": "nvs_flash",
    "nvs_flash.h": "nvs_flash",
    "esp_http_client.h": "esp_http_client",
    "esp_crt_bundle.h": "mbedtls",
    "lwip/tcpip.h": "lwip",
    "lwip/sockets.h": "lwip",
    "lwip/dns.h": "lwip",
    "sys/socket.h": "lwip",  # lwip/port/esp32xx/include, not the C library's
    "esp_vfs_fat.h": "fatfs",
    "wear_levelling.h": "wear_levelling",
    "esp_partition.h": "esp_partition",
    "esp_app_desc.h": "esp_app_format",
    "nimble/nimble_port.h": "bt",
    "nimble/nimble_port_freertos.h": "bt",
    "host/ble_hs.h": "bt",
    "host/util/util.h": "bt",
    "esp_hidh.h": "esp_hid",
    # From the components ESP-IDF makes every component require
    # (tools/cmake/build.cmake, requires_common).
    "esp_log.h": "log",
    "freertos/FreeRTOS.h": "freertos",
    "freertos/task.h": "freertos",
    "freertos/queue.h": "freertos",
    "freertos/semphr.h": "freertos",
    "freertos/event_groups.h": "freertos",
    "esp_heap_caps.h": "heap",
    "esp_system.h": "esp_system",
    "esp_random.h": "esp_hw_support",
    "esp_clk_tree.h": "esp_hw_support",
    "esp_rom_sys.h": "esp_rom",
    "miniz.h": "esp_rom",
    "soc/rtc_cntl_struct.h": "soc",
}
COMMON = {"cxx", "esp_libc", "freertos", "esp_hw_support", "heap", "log", "soc", "hal",
          "esp_rom", "esp_common", "esp_system", "esp_stdio"}

# The C and C++ library's headers main includes: the toolchain's, or esp_libc's
# (stdio.h, time.h), which every component has.
STANDARD = {"cstdio", "cstring", "dirent.h", "errno.h", "fcntl.h", "inttypes.h", "stdbool.h",
            "stddef.h", "stdint.h", "stdio.h", "stdlib.h", "string.h", "strings.h",
            "sys/stat.h", "time.h", "unistd.h"}

# Headers of managed components, and the dependency in main/idf_component.yml.
MANAGED = {
    "M5Unified.h": "m5stack/m5unified",
    "tinyusb.h": "espressif/esp_tinyusb",
    "tinyusb_msc.h": "espressif/esp_tinyusb",
    "tinyusb_default_config.h": "espressif/esp_tinyusb",
}

# Made by the build: ESP-IDF's, nesp_core's, nesp_services' and main's own.
GENERATED = {"sdkconfig.h", "nesp_proto.h", "nesp_version.h", "nesp_logo.h"}

INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)[">]', re.MULTILINE)


def main_sources():
    return sorted(name for name in os.listdir(MAIN)
                  if name.endswith((".c", ".cpp", ".h")))


def includes(text):
    """(quoted, header) for each #include in a source."""
    return [(bracket == '"', header) for bracket, header in INCLUDE.findall(text)]


def local_headers():
    """The headers of this project's own: main's and the components' include/."""
    found = set(name for name in os.listdir(MAIN) if name.endswith(".h"))
    components = os.path.join(FIRMWARE, "components")
    for component in os.listdir(components):
        include = os.path.join(components, component, "include")
        for dirpath, _, names in os.walk(include):
            for name in names:
                found.add(os.path.relpath(os.path.join(dirpath, name), include))
    return found


def requires(cmake):
    """The components main asks for: set(requires ...) and every
    list(APPEND requires ...), the target-dependent ones included. Comments
    are left out, # and #[[ ]] alike; main's CMakeLists.txt has no # inside a
    string."""
    cmake = re.sub(r"#\[(=*)\[.*?\]\1\]", "", cmake, flags=re.DOTALL)
    cmake = re.sub(r"#[^\n]*", "", cmake)
    names = []
    for match in re.finditer(r"\b(?:set|list\s*\(\s*APPEND)\s*\(?\s*requires\b([^)]*)\)", cmake):
        names += match.group(1).split()
    return set(names)


def manifest_dependencies(text):
    """The dependency names in an idf_component.yml, read without a YAML library:
    the keys indented under `dependencies:`."""
    names = set()
    inside = False
    for line in text.splitlines():
        if re.match(r"^dependencies:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        match = re.match(r"^  ([\w./-]+):", line) if inside else None
        if match:
            names.add(match.group(1))
    return names


def problems(sources, cmake, manifest, local):
    """What is wrong with main's REQUIRES, for these sources: a list of messages."""
    required = requires(cmake) | COMMON
    managed = manifest_dependencies(manifest)
    found = []
    for name, text in sources:
        for _, header in includes(text):
            if header in HEADERS:
                component = HEADERS[header]
                if component not in required:
                    found.append("%s includes %s, from %s, which main/CMakeLists.txt "
                                 "does not require" % (name, header, component))
            elif header in MANAGED:
                if MANAGED[header] not in managed:
                    found.append("%s includes %s, from %s, which main/idf_component.yml "
                                 "does not list" % (name, header, MANAGED[header]))
            elif header not in STANDARD and header not in local and header not in GENERATED:
                found.append("%s includes %s, which is in none of this test's lists: "
                             "find the component it comes from and add it" % (name, header))
    return found


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def tree():
    sources = [(name, read(os.path.join(MAIN, name))) for name in main_sources()]
    return (sources, read(os.path.join(MAIN, "CMakeLists.txt")),
            read(os.path.join(MAIN, "idf_component.yml")), local_headers())


def test_main_requires_every_component_it_includes_from():
    found = problems(*tree())
    assert not found, "\n".join(found)


def test_the_uart_driver_is_found_missing_without_esp_driver_uart():
    """#90 again: main with esp_driver_uart taken out of its REQUIRES."""
    sources, cmake, manifest, local = tree()
    assert "esp_driver_uart" in requires(cmake)
    cut = re.sub(r"\besp_driver_uart\b", "", cmake)
    assert any("driver/uart.h" in problem for problem in problems(sources, cut, manifest, local))


@pytest.mark.parametrize("comment", ["# esp_partition\n", "#[[esp_partition]]",
                                     "#[=[\nesp_partition\n]=]"])
def test_a_component_commented_out_is_not_required(comment):
    """usb.c's esp_partition.h with esp_partition commented out of main's REQUIRES:
    CMake leaves it out, and the build still finds the header through wear_levelling."""
    sources, cmake, manifest, local = tree()
    assert re.search(r"\besp_partition\b", cmake)
    cut = re.sub(r"\besp_partition\b", comment, cmake, count=1)
    assert "esp_partition" not in requires(cut)
    assert any("usb.c includes esp_partition.h" in problem
               for problem in problems(sources, cut, manifest, local))


@pytest.mark.parametrize("line", ['#include "esp_ota_ops.h"', "#include <esp_ota_ops.h>"])
def test_a_header_from_an_unknown_component_is_not_passed_over(line):
    sources, cmake, manifest, local = tree()
    extra = [("new.c", line + "\n")]
    assert any("esp_ota_ops.h" in problem
               for problem in problems(sources + extra, cmake, manifest, local))


def test_a_managed_header_needs_its_dependency_in_the_manifest():
    sources, cmake, manifest, local = tree()
    cut = manifest.replace("m5stack/m5unified:", "m5stack/m5unified_gone:")
    assert any("M5Unified.h" in problem for problem in problems(sources, cmake, cut, local))


@pytest.mark.parametrize("header", sorted(set(HEADERS) | STANDARD))
def test_every_header_in_the_lists_is_one_main_includes(header):
    """HEADERS and STANDARD are of main's includes only: one it no longer has goes."""
    used = {h for _, text in tree()[0] for _, h in includes(text)}
    assert header in used, "%s is in this test's lists but main includes it no more" % header
