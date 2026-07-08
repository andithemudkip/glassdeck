// status_led — WS2812 (on-board) status LED driver with a small state model.
//
// One RGB pixel, one voice for two truths: the base color says "what surfaces
// are up" (CAN driver + WiFi AP + client), a brief green overlay says "a CAN
// frame just arrived." On a healthy bus the overlay dominates and the pixel
// looks solid green; when the bus is dark the base color shows through.
//
// Palette (kept dim — the DevKitC-1 pixel is bright enough at 4/255 to see
// across a room; higher values are annoying in a dark garage):
//
//   BOOT                yellow   — driver init hasn't returned yet
//   CAN_ONLY            green    — TWAI up, no wireless surface (can-logger)
//   WIFI_AP_NO_CLIENT   blue     — SoftAP up, phone/laptop hasn't joined
//   WIFI_AP_CLIENT      cyan     — at least one client on the AP
//   ERROR               red      — TWAI bus_off or driver failure
//
// The library owns an RMT TX channel + a 20 Hz render task. All setters are
// safe to call from any task or ISR-safe context (they only mutate atomics).
//
// Consumers wire it in three places:
//   status_led_init(GPIO_NUM_48)      // once, before status_led_set
//   status_led_set(...)               // whenever the surface state changes
//   status_led_pulse_rx()             // per CAN frame received

#pragma once

#include "driver/gpio.h"
#include "esp_err.h"

typedef enum {
    STATUS_LED_BOOT = 0,
    STATUS_LED_CAN_ONLY,
    STATUS_LED_WIFI_AP_NO_CLIENT,
    STATUS_LED_WIFI_AP_CLIENT,
    STATUS_LED_ERROR,
} status_led_state_t;

// Install the WS2812 driver on `gpio` and spawn the render task. Idempotent:
// second call is a no-op. Returns the underlying RMT error on failure.
esp_err_t status_led_init(gpio_num_t gpio);

// Set the base color. Cheap — writes an atomic; the render task picks it up on
// its next 50 ms tick.
void status_led_set(status_led_state_t s);

// Signal one CAN frame arrived. Overlays bright green on the next render tick
// (the pulse re-arms every tick, so continuous traffic reads as solid green).
void status_led_pulse_rx(void);
