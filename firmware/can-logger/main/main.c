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
//
// TWAI driver ownership and SLCAN framing live in firmware/lib/{twai,slcan}/,
// shared with firmware/wifi-bridge/.

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "slcan.h"
#include "status_led.h"
#include "twai_lib.h"

#ifndef LED_ENABLE
#define LED_ENABLE 1
#endif
#ifndef LED_GPIO
// ESP32-S3-DevKitC-1 on-board WS2812. v1.0 modules (what's on this bench)
// route it to GPIO48; the v1.1 refresh moved it to GPIO38. Override with
// `-DLED_GPIO=38` for a v1.1 board — the pin is the only difference.
#define LED_GPIO GPIO_NUM_48
#endif

#ifndef CAN_BITRATE_KBPS
#define CAN_BITRATE_KBPS 500
#endif

#define CAN_TX_PIN     GPIO_NUM_4
#define CAN_RX_PIN     GPIO_NUM_5
#define CAN_RX_QUEUE   256

// Period between `# ...` SLCAN status comment lines emitted on the host stream.
#define STATUS_PERIOD_MS 2000

// Serializes writes to stdout so SLCAN frame lines and `#` status comment lines
// never interleave mid-character. Acquired by both the RX loop in app_main and
// the status_task below.
static SemaphoreHandle_t stdout_mutex;

static void write_locked(const char *buf, size_t n) {
    xSemaphoreTake(stdout_mutex, portMAX_DELAY);
    fwrite(buf, 1, n, stdout);
    xSemaphoreGive(stdout_mutex);
}

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
        twai_lib_health_t h;
        if (twai_lib_health(&h) != ESP_OK) {
            continue;
        }
        int n = snprintf(
            line, sizeof(line),
            "# bus_err=%lu rx_missed=%lu rx_overrun=%lu state=%s\r",
            (unsigned long)h.bus_error_count,
            (unsigned long)h.rx_missed_count,
            (unsigned long)h.rx_overrun_count,
            twai_lib_state_str(h.state));
        if (n > 0) {
            if ((size_t)n >= sizeof(line)) n = sizeof(line) - 1;
            write_locked(line, (size_t)n);
        }
#if LED_ENABLE
        // BUS_OFF latches red; everything else stays on the CAN_ONLY base.
        // (RX-frame overlay is driven independently from the RX loop.)
        status_led_set(h.state == TWAI_STATE_BUS_OFF
                       ? STATUS_LED_ERROR
                       : STATUS_LED_CAN_ONLY);
#endif
    }
}

void app_main(void) {
    // Suppress IDF log output so it doesn't interleave with the SLCAN stream.
    esp_log_level_set("*", ESP_LOG_NONE);
    setvbuf(stdout, NULL, _IONBF, 0);

#if LED_ENABLE
    // Light yellow immediately so a dark pixel means "firmware didn't start."
    ESP_ERROR_CHECK(status_led_init(LED_GPIO));
    status_led_set(STATUS_LED_BOOT);
#endif

    twai_lib_config_t cfg = {
        .bitrate_kbps = CAN_BITRATE_KBPS,
        .rx_queue_len = CAN_RX_QUEUE,
        .tx_pin       = CAN_TX_PIN,
        .rx_pin       = CAN_RX_PIN,
    };
    ESP_ERROR_CHECK(twai_lib_start(&cfg));

#if LED_ENABLE
    status_led_set(STATUS_LED_CAN_ONLY);
#endif

    stdout_mutex = xSemaphoreCreateMutex();
    xTaskCreate(status_task, "twai_status", 3072, NULL, tskIDLE_PRIORITY + 1, NULL);

    char buf[SLCAN_MAX_FRAME_BYTES];
    twai_message_t msg;
    while (true) {
        if (twai_lib_receive(&msg, portMAX_DELAY)) {
            size_t n = slcan_format_frame(&msg, buf);
            write_locked(buf, n);
#if LED_ENABLE
            status_led_pulse_rx();
#endif
        }
    }
}
