set(INDEX_HTML    "${CMAKE_CURRENT_LIST_DIR}/index.html")
set(INDEX_HTML_GZ "${CMAKE_CURRENT_BINARY_DIR}/index.html.gz")

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

# Embed the live-view HTML (gzipped) into the firmware image. Done here rather
# than via the `EMBED_FILES` shorthand because PlatformIO's SCons wrapper scans
# sources at CMake configure time and doesn't run ninja's custom-command chain
# first — so both the `.gz` and the ESP-IDF-generated `.S` must exist on disk
# before `idf_component_register` returns. Mirrors what `espidf.py` does
# internally for mbedtls's certificate bundle.
#
# `-n` strips gzip's mtime header so identical HTML → identical binary, which
# makes `POST /ota` a no-op when nothing changed. `CMAKE_CONFIGURE_DEPENDS`
# forces a reconfigure (and therefore a fresh gzip) whenever `index.html`
# changes, so the edit-and-reflash loop stays fast.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    set_property(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${INDEX_HTML}")

    execute_process(
        COMMAND gzip -9 -n -c ${INDEX_HTML}
        OUTPUT_FILE ${INDEX_HTML_GZ}
        RESULT_VARIABLE _gzip_rc
    )
    if(NOT _gzip_rc EQUAL 0)
        message(FATAL_ERROR "gzip failed for ${INDEX_HTML} (rc=${_gzip_rc})")
    endif()

    idf_build_get_property(_idf_path IDF_PATH)
    idf_build_get_property(_build_dir BUILD_DIR)
    set(INDEX_HTML_GZ_S "${_build_dir}/index.html.gz.S")
    execute_process(
        COMMAND ${CMAKE_COMMAND}
            -D DATA_FILE=${INDEX_HTML_GZ}
            -D SOURCE_FILE=${INDEX_HTML_GZ_S}
            -D FILE_TYPE=BINARY
            -P "${_idf_path}/tools/cmake/scripts/data_file_embed_asm.cmake"
        RESULT_VARIABLE _asm_rc
    )
    if(NOT _asm_rc EQUAL 0)
        message(FATAL_ERROR "embed .S generation failed for ${INDEX_HTML_GZ} (rc=${_asm_rc})")
    endif()

    target_sources(${COMPONENT_LIB} PRIVATE ${INDEX_HTML_GZ_S})
endif()
