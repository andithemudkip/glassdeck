#include "status_led.h"

#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>

#include "driver/rmt_tx.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// WS2812 wire format: per-bit, 0=400ns hi/850ns lo, 1=800ns hi/450ns lo,
// ≥50us low to latch. RMT resolution is 10 MHz (100 ns per tick), so the
// durations below are tick counts.
#define WS2812_RES_HZ (10 * 1000 * 1000)

// Render period. 50 ms is fast enough for CAN-rx flicker to look continuous
// under load and slow enough that base-color transitions aren't jittery.
#define RENDER_PERIOD_MS 50

static rmt_channel_handle_t s_rmt;
static rmt_encoder_handle_t s_enc;
static bool s_initialized;

// Atomics so ISR-safe setters don't need a lock.
static _Atomic int      s_state = STATUS_LED_BOOT;
static _Atomic bool     s_rx_pulse;

static void write_pixel(uint8_t r, uint8_t g, uint8_t b) {
    // WS2812 expects G,R,B byte order.
    uint8_t pixel[3] = { g, r, b };
    rmt_transmit_config_t tx_cfg = { .loop_count = 0 };
    rmt_transmit(s_rmt, s_enc, pixel, sizeof(pixel), &tx_cfg);
    rmt_tx_wait_all_done(s_rmt, -1);
}

// Base color per logical state. All values kept in the low single digits — the
// on-board pixel is a diffused surface-mount WS2812 with no lens, so a "4" is
// clearly visible from across a room and a "16" is uncomfortable in the dark.
static void base_color(status_led_state_t s, uint8_t *r, uint8_t *g, uint8_t *b) {
    switch (s) {
        case STATUS_LED_BOOT:              *r = 4; *g = 3; *b = 0; return;  // yellow
        case STATUS_LED_CAN_ONLY:          *r = 0; *g = 3; *b = 0; return;  // green
        case STATUS_LED_WIFI_AP_NO_CLIENT: *r = 0; *g = 0; *b = 6; return;  // blue
        case STATUS_LED_WIFI_AP_CLIENT:    *r = 0; *g = 4; *b = 4; return;  // cyan
        case STATUS_LED_ERROR:             *r = 12; *g = 0; *b = 0; return; // red
        default:                           *r = 0; *g = 0; *b = 0; return;
    }
}

static void render_task(void *arg) {
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(RENDER_PERIOD_MS));

        status_led_state_t st = (status_led_state_t)atomic_load_explicit(
            &s_state, memory_order_relaxed);
        bool pulse = atomic_exchange_explicit(&s_rx_pulse, false, memory_order_relaxed);

        uint8_t r, g, b;
        base_color(st, &r, &g, &b);

        // RX pulse overrides base with bright green. At full bike CAN rate the
        // pulse re-arms every tick, so the pixel looks solid green under load
        // and drops back to the base color the moment the bus goes quiet.
        // ERROR wins over the pulse — a lit-red pixel is the whole point.
        if (pulse && st != STATUS_LED_ERROR) {
            r = 0; g = 16; b = 0;
        }

        write_pixel(r, g, b);
    }
}

esp_err_t status_led_init(gpio_num_t gpio) {
    if (s_initialized) return ESP_OK;

    rmt_tx_channel_config_t chan_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = gpio,
        .mem_block_symbols = 64,
        .resolution_hz = WS2812_RES_HZ,
        .trans_queue_depth = 2,
    };
    esp_err_t err = rmt_new_tx_channel(&chan_cfg, &s_rmt);
    if (err != ESP_OK) return err;

    rmt_bytes_encoder_config_t enc_cfg = {
        .bit0 = { .level0 = 1, .duration0 = 4, .level1 = 0, .duration1 = 9 },
        .bit1 = { .level0 = 1, .duration0 = 8, .level1 = 0, .duration1 = 5 },
        .flags.msb_first = 1,
    };
    err = rmt_new_bytes_encoder(&enc_cfg, &s_enc);
    if (err != ESP_OK) return err;

    err = rmt_enable(s_rmt);
    if (err != ESP_OK) return err;

    s_initialized = true;
    xTaskCreate(render_task, "status_led", 2048, NULL, tskIDLE_PRIORITY + 1, NULL);
    return ESP_OK;
}

void status_led_set(status_led_state_t s) {
    atomic_store_explicit(&s_state, (int)s, memory_order_relaxed);
}

void status_led_pulse_rx(void) {
    atomic_store_explicit(&s_rx_pulse, true, memory_order_relaxed);
}
