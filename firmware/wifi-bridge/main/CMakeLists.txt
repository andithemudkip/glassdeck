idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_psram
        esp_wifi
        esp_netif
        esp_event
        esp_http_server
        esp_timer
        esp_hw_support
        nvs_flash
        app_update
        twai
        slcan
        status_led
)
