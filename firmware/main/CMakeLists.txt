set(sources "main.cpp" "link.c" "radio.c" "fetch.c" "store.c" "conn.c" "usb.c" "keyboard.c")
set(requires nesp_core nesp_services driver esp_wifi esp_netif esp_event nvs_flash esp_timer
             esp_http_client mbedtls lwip fatfs wear_levelling esp_rom esp_app_format)
# Bluetooth, for a keyboard (keyboard.c), on the board that has LE. The
# requirements are worked out before the configuration is read, so this
# goes by the target.
if(IDF_TARGET STREQUAL "esp32s3")
    list(APPEND requires bt esp_hid)
endif()
# A measurement of decoding a radio station (spike.c), for idf.py -D NESP_SPIKE=1.
if(NESP_SPIKE)
    list(APPEND sources "spike.c")
endif()
idf_component_register(SRCS ${sources}
                       INCLUDE_DIRS "."
                       REQUIRES ${requires})
if(NESP_SPIKE)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE NESP_SPIKE=1)
endif()
# The logo shown at start (nesp_logo.h), from the one the NES programs show.
set(NESP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
set(logo_gen "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY "${logo_gen}")
target_include_directories(${COMPONENT_LIB} PRIVATE "${logo_gen}")
add_custom_command(
    OUTPUT "${logo_gen}/nesp_logo.h"
    COMMAND ${PYTHON} "${NESP_ROOT}/tools/gen_logo.py" "${logo_gen}"
    DEPENDS "${NESP_ROOT}/nes/lib/logo.py" "${NESP_ROOT}/tools/gen_logo.py"
            "${NESP_ROOT}/tools/gen_web.py"
    COMMENT "nesp_logo.h from nes/lib/logo.py")
add_custom_target(nesp_logo DEPENDS "${logo_gen}/nesp_logo.h")
add_dependencies(${COMPONENT_LIB} nesp_logo)
# A StickS3's sdkconfig made before it had Bluetooth keeps it off, as the
# defaults are read only for what an sdkconfig does not yet have.
if(NOT CMAKE_BUILD_EARLY_EXPANSION AND IDF_TARGET STREQUAL "esp32s3"
   AND NOT CONFIG_BT_NIMBLE_ENABLED)
    message(FATAL_ERROR "This sdkconfig has Bluetooth off, as it was made before the "
                        "nesp32 had a keyboard. Delete it (firmware/build-esp32s3/sdkconfig) "
                        "and build again, and it is made afresh from sdkconfig.defaults.")
endif()
