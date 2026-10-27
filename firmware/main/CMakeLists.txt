set(sources "main.cpp" "link.c" "radio.c" "fetch.c" "store.c" "conn.c" "usb.c" "keyboard.c")
set(requires nesp_core nesp_services driver esp_wifi esp_netif esp_event nvs_flash esp_timer
             esp_http_client mbedtls lwip fatfs wear_levelling esp_rom)
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
# A StickS3's sdkconfig made before it had Bluetooth keeps it off, as the
# defaults are read only for what an sdkconfig does not yet have.
if(NOT CMAKE_BUILD_EARLY_EXPANSION AND IDF_TARGET STREQUAL "esp32s3"
   AND NOT CONFIG_BT_NIMBLE_ENABLED)
    message(FATAL_ERROR "This sdkconfig has Bluetooth off, as it was made before the "
                        "nesp32 had a keyboard. Delete it (firmware/build-esp32s3/sdkconfig) "
                        "and build again, and it is made afresh from sdkconfig.defaults.")
endif()
