// twai_lib — shared TWAI (CAN) driver wrapper for glassdeck firmware targets.
//
// Owns the ESP-IDF TWAI peripheral in listen-only mode. Consumers run their own
// read task on top of twai_lib_receive() and their own sinks (SLCAN → USB-CDC
// in can-logger; SLCAN → WebSocket + PSRAM ring in wifi-bridge).
//
// See docs/decisions/0002-twai-gpio-assignment.md for the pin choice.

#pragma once

// IDF 6.0 deprecates the legacy `driver/twai.h` in favour of the new
// `esp_twai.h` callback-based API. The legacy API is still shipped and works
// fine for listen-only. Suppress the one `#warning` so consumers don't have to
// repeat the pragma dance.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcpp"
#include "driver/twai.h"
#pragma GCC diagnostic pop

#include "driver/gpio.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t   bitrate_kbps;   // 500 or 250 — anything else returns ESP_ERR_INVALID_ARG
    uint32_t   rx_queue_len;   // driver RX queue depth (e.g. 256)
    gpio_num_t tx_pin;         // e.g. GPIO_NUM_4
    gpio_num_t rx_pin;         // e.g. GPIO_NUM_5
} twai_lib_config_t;

typedef struct {
    uint32_t     bus_error_count;
    uint32_t     rx_missed_count;
    uint32_t     rx_overrun_count;
    twai_state_t state;
} twai_lib_health_t;

// Install the TWAI driver in listen-only mode with the given config, then
// start it. Returns whatever twai_driver_install / twai_start returned, or
// ESP_ERR_INVALID_ARG on an unsupported bitrate.
esp_err_t twai_lib_start(const twai_lib_config_t *cfg);

// Block up to `timeout_ticks` for a frame. Returns true iff one was received.
// Thin wrapper around twai_receive().
bool twai_lib_receive(twai_message_t *out, TickType_t timeout_ticks);

// Snapshot the driver health counters + state. Wraps twai_get_status_info().
esp_err_t twai_lib_health(twai_lib_health_t *out);

// Stringify a twai_state_t for logging: "stopped" / "running" / "bus_off" /
// "recovering" / "unknown".
const char *twai_lib_state_str(twai_state_t s);
