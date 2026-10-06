idf_component_register(SRCS "main.cpp" "link.c" "radio.c"
                       INCLUDE_DIRS "."
                       REQUIRES nesp_core nesp_services driver esp_wifi esp_netif esp_event
                                nvs_flash esp_timer)
