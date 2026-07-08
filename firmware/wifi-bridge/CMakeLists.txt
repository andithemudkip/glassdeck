cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../lib/twai"
    "${CMAKE_CURRENT_LIST_DIR}/../lib/slcan"
    "${CMAKE_CURRENT_LIST_DIR}/../lib/status_led"
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(wifi-bridge)
