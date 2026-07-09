set(INDEX_HTML     "${CMAKE_CURRENT_LIST_DIR}/index.html")
set(INDEX_MERGED   "${CMAKE_CURRENT_BINARY_DIR}/index.merged.html")
set(INDEX_HTML_GZ  "${CMAKE_CURRENT_BINARY_DIR}/index.html.gz")
set(INDEX_DEPS     "${CMAKE_CURRENT_BINARY_DIR}/index.deps")

# Repo root is four dirs up: main/ → wifi-bridge/ → firmware/ → repo-root.
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
set(GEN_SCRIPT    "${REPO_ROOT}/scripts/gen_wifi_bridge_index.py")
set(SIGNALS_YAML  "${REPO_ROOT}/docs/signals/signals.yaml")

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
# The pipeline runs at configure time in two eager steps:
#   1. gen_wifi_bridge_index.py reads signals.yaml + index.html, injects the
#      confirmed-signals JS block, writes index.merged.html.
#   2. gzip -9 -n produces index.html.gz from the merged HTML. `-n` strips the
#      gzip mtime header so identical inputs → identical binary, which makes
#      `POST /ota` a no-op when nothing changed.
#
# `CMAKE_CONFIGURE_DEPENDS` on all three inputs (template, schema, codegen
# script) forces a reconfigure — and therefore a fresh regeneration — whenever
# any of them change, so the edit-and-reflash loop stays fast.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    set_property(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
            "${INDEX_HTML}" "${SIGNALS_YAML}" "${GEN_SCRIPT}")

    # A malformed schema surfaces here: load_signals() raises SchemaError with
    # the offending entry index, the Python script exits non-zero, and CMake
    # FATAL_ERRORs the build with the child's stderr attached — that's the
    # M6 "signals.yaml parses cleanly at build time" CI check.
    #
    # --deps-file catches every `/* __INCLUDE: */` partial resolved during
    # codegen. We append that list to CMAKE_CONFIGURE_DEPENDS below so editing
    # a partial (styles.css, state.js, …) reconfigures and regenerates.
    execute_process(
        COMMAND python3 ${GEN_SCRIPT}
            --template  ${INDEX_HTML}
            --schema    ${SIGNALS_YAML}
            --out       ${INDEX_MERGED}
            --deps-file ${INDEX_DEPS}
        RESULT_VARIABLE _gen_rc
        ERROR_VARIABLE  _gen_err
    )
    if(NOT _gen_rc EQUAL 0)
        message(FATAL_ERROR
            "signals.yaml → index.html codegen failed (rc=${_gen_rc}):\n${_gen_err}")
    endif()

    if(EXISTS "${INDEX_DEPS}")
        file(STRINGS "${INDEX_DEPS}" _index_partials)
        if(_index_partials)
            set_property(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
                APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_index_partials})
        endif()
    endif()

    execute_process(
        COMMAND gzip -9 -n -c ${INDEX_MERGED}
        OUTPUT_FILE ${INDEX_HTML_GZ}
        RESULT_VARIABLE _gzip_rc
    )
    if(NOT _gzip_rc EQUAL 0)
        message(FATAL_ERROR "gzip failed for ${INDEX_MERGED} (rc=${_gzip_rc})")
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
