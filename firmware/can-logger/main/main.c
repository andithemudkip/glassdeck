// can-logger — listen-only CAN logger for the Husqvarna Svartpilen 401 (KTM 390
// platform). Reads frames from the TWAI peripheral and emits them as SLCAN
// (Lawicel ASCII) lines on stdout, which is routed to the ESP32-S3's built-in
// USB-Serial/JTAG controller.
//
// Hardware: ESP32-S3-DevKitC-1 + SN65HVD230 transceiver. See
// docs/decisions/0001..0004 and docs/hardware/can-adapter.md.
//
// Listen-only mode is mandatory for Phase 0..4 (project golden rule). The TWAI
// peripheral cannot ACK or transmit any frame in this mode.

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#include "driver/gpio.h"
// IDF 6.0 deprecates the legacy `driver/twai.h` in favour of the new
// `esp_twai.h` callback-based API. The legacy API is still shipped and works
// fine for this listen-only logger; migrating buys us nothing yet. Suppress
// only the one `#warning` so genuine -Werror=cpp issues elsewhere still trip.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcpp"
#include "driver/twai.h"
#pragma GCC diagnostic pop
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#ifndef LED_ENABLE
#define LED_ENABLE 1
#endif
#ifndef LED_GPIO
// DevKitC-1 v1.1 routes the on-board WS2812 to GPIO38. Older revisions used
// GPIO48 — override at build time with `-DLED_GPIO=48` if needed.
#define LED_GPIO 38
#endif

#if LED_ENABLE
#include "driver/rmt_tx.h"
#endif

#ifndef CAN_BITRATE_KBPS
#define CAN_BITRATE_KBPS 500
#endif

#define CAN_TX_PIN GPIO_NUM_4
#define CAN_RX_PIN GPIO_NUM_5

// Period between `# ...` SLCAN status comment lines emitted on the host stream.
#define STATUS_PERIOD_MS 2000

static const char HEX[] = "0123456789ABCDEF";

// Serializes writes to stdout so SLCAN frame lines and `#` status comment lines
// never interleave mid-character. Acquired by both the RX loop in app_main and
// the status_task below.
static SemaphoreHandle_t stdout_mutex;

static void write_locked(const char *buf, size_t n) {
    xSemaphoreTake(stdout_mutex, portMAX_DELAY);
    fwrite(buf, 1, n, stdout);
    xSemaphoreGive(stdout_mutex);
}

static const char *twai_state_str(twai_state_t s) {
    switch (s) {
        case TWAI_STATE_STOPPED:    return "stopped";
        case TWAI_STATE_RUNNING:    return "running";
        case TWAI_STATE_BUS_OFF:    return "bus_off";
        case TWAI_STATE_RECOVERING: return "recovering";
        default:                    return "unknown";
    }
}

#if LED_ENABLE
// Activity LED. The RX loop sets `rx_pulse = true` whenever a frame arrives;
// led_task wakes every 50 ms, reads-and-clears the flag, and lights a dim
// green pixel for that tick if any frame was seen. Net effect: visible flicker
// proportional to bus rate, with ~50 ms minimum on-time so even sparse traffic
// is human-perceptible. Bus dark → LED dark → wiring or bitrate is wrong.
//
// Drives the WS2812 directly with ESP-IDF's `rmt_tx` driver — no external
// component dependency. WS2812 wire format: per-bit, 0=400ns hi/850ns lo,
// 1=800ns hi/450ns lo, ≥50us low to latch. RMT resolution is 10 MHz (100 ns
// per tick), so the durations below are tick counts.

static rmt_channel_handle_t led_rmt;
static rmt_encoder_handle_t led_encoder;
static volatile bool rx_pulse;

static void led_init(void) {
    rmt_tx_channel_config_t chan_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = LED_GPIO,
        .mem_block_symbols = 64,
        .resolution_hz = 10 * 1000 * 1000,
        .trans_queue_depth = 2,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&chan_cfg, &led_rmt));

    rmt_bytes_encoder_config_t enc_cfg = {
        .bit0 = { .level0 = 1, .duration0 = 4, .level1 = 0, .duration1 = 9 },
        .bit1 = { .level0 = 1, .duration0 = 8, .level1 = 0, .duration1 = 5 },
        .flags.msb_first = 1,
    };
    ESP_ERROR_CHECK(rmt_new_bytes_encoder(&enc_cfg, &led_encoder));
    ESP_ERROR_CHECK(rmt_enable(led_rmt));
}

static void led_set(uint8_t r, uint8_t g, uint8_t b) {
    // WS2812 expects bytes in G,R,B order.
    uint8_t pixel[3] = { g, r, b };
    rmt_transmit_config_t tx_cfg = { .loop_count = 0 };
    rmt_transmit(led_rmt, led_encoder, pixel, sizeof(pixel), &tx_cfg);
    rmt_tx_wait_all_done(led_rmt, -1);
}

static void led_task(void *arg) {
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(50));
        bool active = rx_pulse;
        rx_pulse = false;
        if (active) {
            led_set(0, 8, 0);
        } else {
            led_set(0, 0, 0);
        }
    }
}
#endif

// Periodically emit driver health as a SLCAN comment line. python-can's SLCAN
// driver ignores any line whose first character isn't t/T/r/R, so these are
// safe to mix into the stream. `pio device monitor` shows them inline.
//
//   # bus_err=N rx_missed=M rx_overrun=K state=running\r
//
// On a healthy bus everything stays at zero. Growing `bus_err` with zero frames
// is the bitrate-mismatch signature; growing `rx_missed`/`rx_overrun` means the
// host can't keep up with USB-CDC drain.
static void status_task(void *arg) {
    (void)arg;
    char line[128];
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(STATUS_PERIOD_MS));
        twai_status_info_t s;
        if (twai_get_status_info(&s) != ESP_OK) {
            continue;
        }
        int n = snprintf(
            line, sizeof(line),
            "# bus_err=%lu rx_missed=%lu rx_overrun=%lu state=%s\r",
            (unsigned long)s.bus_error_count,
            (unsigned long)s.rx_missed_count,
            (unsigned long)s.rx_overrun_count,
            twai_state_str(s.state));
        if (n > 0) {
            if ((size_t)n > sizeof(line)) n = sizeof(line);
            write_locked(line, (size_t)n);
        }
    }
}

// Format one TWAI frame as a SLCAN (Lawicel) line into `out`. Returns the
// number of bytes written. `out` must be at least 28 bytes.
//
//   t<3-hex id><1-hex dlc><2-hex per data byte>\r       (11-bit data frame)
//   T<8-hex id><1-hex dlc><2-hex per data byte>\r       (29-bit data frame)
//   r / R                                                (remote-request)
static size_t format_slcan(const twai_message_t *msg, char *out) {
    size_t i = 0;
    char type;
    if (msg->extd) {
        type = msg->rtr ? 'R' : 'T';
    } else {
        type = msg->rtr ? 'r' : 't';
    }
    out[i++] = type;

    if (msg->extd) {
        for (int shift = 28; shift >= 0; shift -= 4) {
            out[i++] = HEX[(msg->identifier >> shift) & 0xF];
        }
    } else {
        out[i++] = HEX[(msg->identifier >> 8) & 0xF];
        out[i++] = HEX[(msg->identifier >> 4) & 0xF];
        out[i++] = HEX[(msg->identifier >> 0) & 0xF];
    }

    uint8_t dlc = msg->data_length_code & 0xF;
    out[i++] = HEX[dlc];

    if (!msg->rtr) {
        uint8_t n = dlc > 8 ? 8 : dlc;
        for (uint8_t b = 0; b < n; b++) {
            out[i++] = HEX[(msg->data[b] >> 4) & 0xF];
            out[i++] = HEX[msg->data[b] & 0xF];
        }
    }

    out[i++] = '\r';
    return i;
}

void app_main(void) {
    // Suppress IDF log output so it doesn't interleave with the SLCAN stream.
    esp_log_level_set("*", ESP_LOG_NONE);
    setvbuf(stdout, NULL, _IONBF, 0);

    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
        CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
    g_config.rx_queue_len = 256;

#if CAN_BITRATE_KBPS == 500
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
#elif CAN_BITRATE_KBPS == 250
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_250KBITS();
#else
#error "CAN_BITRATE_KBPS must be 500 or 250"
#endif

    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    ESP_ERROR_CHECK(twai_driver_install(&g_config, &t_config, &f_config));
    ESP_ERROR_CHECK(twai_start());

    stdout_mutex = xSemaphoreCreateMutex();
    xTaskCreate(status_task, "twai_status", 3072, NULL, tskIDLE_PRIORITY + 1, NULL);

#if LED_ENABLE
    led_init();
    xTaskCreate(led_task, "led", 2048, NULL, tskIDLE_PRIORITY + 1, NULL);
#endif

    // Largest classic-CAN SLCAN line: T + 8 id + 1 dlc + 16 data + \r = 27.
    char buf[32];
    twai_message_t msg;
    while (true) {
        if (twai_receive(&msg, portMAX_DELAY) == ESP_OK) {
            size_t n = format_slcan(&msg, buf);
            write_locked(buf, n);
#if LED_ENABLE
            rx_pulse = true;
#endif
        }
    }
}
