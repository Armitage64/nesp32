set(sources "main.cpp" "link.c" "radio.c" "fetch.c" "store.c" "conn.c" "usb.c")
# A measurement of decoding a radio station (spike.c), for idf.py -D NESP_SPIKE=1.
if(NESP_SPIKE)
    list(APPEND sources "spike.c")
endif()
idf_component_register(SRCS ${sources}
                       INCLUDE_DIRS "."
                       REQUIRES nesp_core nesp_services driver esp_wifi esp_netif esp_event
                                nvs_flash esp_timer esp_http_client mbedtls lwip fatfs
                                wear_levelling esp_rom)
if(NESP_SPIKE)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE NESP_SPIKE=1)
endif()
