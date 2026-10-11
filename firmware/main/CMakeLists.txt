idf_component_register(SRCS "main.cpp" "link.c" "radio.c" "fetch.c" "store.c" "conn.c" "usb.c"
                       INCLUDE_DIRS "."
                       REQUIRES nesp_core nesp_services driver esp_wifi esp_netif esp_event
                                nvs_flash esp_timer esp_http_client mbedtls lwip fatfs
                                wear_levelling esp_rom)

# The airports RADAR knows, packed from nes-radar's own data (the submodule
# in third_party) and built into the firmware: about 120 KB.
set(NESP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
set(AIRPORT_DATA "${NESP_ROOT}/third_party/nes-radar/server/src/data")
set(AIRPORTS "${CMAKE_CURRENT_BINARY_DIR}/airports.bin")
if(NOT EXISTS "${AIRPORT_DATA}/airports_cache.json")
    message(FATAL_ERROR "no nes-radar in third_party: git submodule update --init third_party/nes-radar")
endif()
add_custom_command(
    OUTPUT "${AIRPORTS}"
    COMMAND ${PYTHON} "${NESP_ROOT}/tools/gen_airports.py" "${AIRPORTS}" "${AIRPORT_DATA}"
    DEPENDS "${NESP_ROOT}/tools/gen_airports.py" "${AIRPORT_DATA}/airports_cache.json"
    COMMENT "airports.bin from nes-radar's airports")
add_custom_target(nesp_airports DEPENDS "${AIRPORTS}")
target_add_binary_data(${COMPONENT_LIB} "${AIRPORTS}" BINARY DEPENDS nesp_airports)
