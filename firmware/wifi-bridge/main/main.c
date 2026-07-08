// wifi-bridge — Phase 2+ untethered CAN capture + browser-served live view for
// the Husqvarna Svartpilen 401. See docs/decisions/0016-wifi-dev-capture-and-
// live-view.md and firmware/wifi-bridge/README.md for the full plan.
//
// State at milestone 5:
//   - WiFi soft-AP (SSID `bike-dash-<lower6 of MAC>`, WPA2 from wifi_secrets.h)
//   - GET  /         gzipped live-view HTML (bus-health header + raw ticker)
//   - GET  /health   JSON with uptime, TWAI health, frame counters, WS state
//   - POST /ota      raw firmware.bin → rollback-protected OTA update
//   - GET  /stream   WebSocket, one CAN frame per text message, SLCAN wire
//                    format (byte-identical to can-logger's USB-CDC output)
//
// USB-CDC stays as a diagnostic surface (SSID/password/IP + SLCAN frames still
// stream through for compatibility with capture.py / inventory_ids.py). WiFi
// via ESP-as-AP means the phone loses cellular while subscribed — accepted
// trade-off per ADR 0016 for the dev phase.

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdatomic.h>
#include <string.h>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_idf_version.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_psram.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "slcan.h"
#include "status_led.h"
#include "twai_lib.h"

#include "wifi_secrets.h"

#ifndef WIFI_AP_PASSWORD
#error "Copy main/wifi_secrets.h.example to main/wifi_secrets.h and set WIFI_AP_PASSWORD"
#endif

#ifndef CAN_BITRATE_KBPS
#define CAN_BITRATE_KBPS 500
#endif

#ifndef LED_GPIO
// ESP32-S3-DevKitC-1 on-board WS2812 — v1.0 (this bench) uses GPIO48, v1.1
// uses GPIO38. Override with `-DLED_GPIO=38` for a v1.1 board.
#define LED_GPIO GPIO_NUM_48
#endif

#define CAN_TX_PIN     GPIO_NUM_4
#define CAN_RX_PIN     GPIO_NUM_5
#define CAN_RX_QUEUE   256

// Period between `# ...` SLCAN status comment lines emitted on the host stream.
#define STATUS_PERIOD_MS 2000

// AP tuning. Channel 1 is the safe default; max_connection = 4 covers the dev
// use case (usually one phone + one laptop).
#define AP_CHANNEL     1
#define AP_MAX_CONN    4

// SSID built at boot from the wifi-softap MAC. "bike-dash-" (10) + 6 hex + NUL.
static char ap_ssid[32];

// Serializes writes to stdout so SLCAN frame lines, status comments, and
// WiFi/AP event lines never interleave mid-character.
static SemaphoreHandle_t stdout_mutex;

// Frames-seen counter, incremented in the RX loop and read from the /health
// handler on the httpd task. _Atomic uint64_t: plain volatile isn't atomic for
// 64-bit loads on Xtensa LX7, and a torn read on /health would report garbage.
static _Atomic uint64_t frames_seen = 0;

// WebSocket fan-out counters. Incremented in ws_tx_task / RX loop respectively;
// read on the httpd task in health_handler.
//   frames_ws_sent    — CAN frames delivered to ≥1 WS client
//   frames_ws_dropped — CAN frames the RX loop couldn't enqueue (WS queue full)
// Their sum is intentionally NOT equal to frames_seen: frames that dequeued
// with zero clients connected are neither sent nor dropped, they just fall
// out silently (the WS path is opportunistic; the ring buffer in milestone 4
// is what backs durable capture).
static _Atomic uint64_t frames_ws_sent = 0;
static _Atomic uint64_t frames_ws_dropped = 0;

// Handle promoted from local in http_server_start; ws_tx_task and
// health_handler both need it for httpd_get_client_list / send_frame_async.
static httpd_handle_t s_server;

// One SLCAN line, copied into the queue by the RX loop. 32-byte payload matches
// SLCAN_MAX_FRAME_BYTES (longest classic-CAN line is 27 bytes including \r).
typedef struct {
    uint8_t len;
    char    buf[SLCAN_MAX_FRAME_BYTES];
} ws_item_t;

// Depth 64 × ~40 bytes/item ≈ 2.5 KB total — a few 10s of ms of headroom at
// peak bike CAN rates. Drop-newest (xQueueSendToBack with 0 timeout) on full;
// see the milestone-3 plan for the ADR-alignment argument.
#define WS_TX_QUEUE_DEPTH 64
static QueueHandle_t ws_tx_q;

static void write_locked(const char *buf, size_t n) {
    xSemaphoreTake(stdout_mutex, portMAX_DELAY);
    fwrite(buf, 1, n, stdout);
    xSemaphoreGive(stdout_mutex);
}

static void derive_ap_ssid(void) {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(ap_ssid, sizeof(ap_ssid), "bike-dash-%02x%02x%02x",
             mac[3], mac[4], mac[5]);
}

static void print_boot_header(void) {
    // `#`-prefixed and `\r`-terminated so the SLCAN parser downstream ignores
    // these lines cleanly, but they still render on `pio device monitor` for
    // the operator to copy the SSID/password into the phone.
    printf("# ---- wifi-bridge (milestone 5) ----\r\n");
    printf("# idf=%s\r\n", esp_get_idf_version());
    printf("# psram_bytes=%u\r\n", (unsigned)esp_psram_get_size());
    printf("# can_bitrate_kbps=%d can_tx=GPIO%d can_rx=GPIO%d mode=listen-only\r\n",
           CAN_BITRATE_KBPS, CAN_TX_PIN, CAN_RX_PIN);
    printf("# ap_ssid=%s\r\n", ap_ssid);
    printf("# ap_password=%s\r\n", WIFI_AP_PASSWORD);
    printf("# ap_ip=192.168.4.1\r\n");
}

// -----------------------------------------------------------------------------
// WiFi soft-AP
// -----------------------------------------------------------------------------

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data) {
    (void)arg;
    if (base != WIFI_EVENT) {
        return;
    }
    char line[96];
    int n = 0;
    if (id == WIFI_EVENT_AP_STACONNECTED) {
        wifi_event_ap_staconnected_t *ev = (wifi_event_ap_staconnected_t *)data;
        n = snprintf(line, sizeof(line),
                     "# ap_client_connected mac=%02x:%02x:%02x:%02x:%02x:%02x aid=%d\r\n",
                     ev->mac[0], ev->mac[1], ev->mac[2],
                     ev->mac[3], ev->mac[4], ev->mac[5], ev->aid);
    } else if (id == WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_event_ap_stadisconnected_t *ev = (wifi_event_ap_stadisconnected_t *)data;
        n = snprintf(line, sizeof(line),
                     "# ap_client_disconnected mac=%02x:%02x:%02x:%02x:%02x:%02x aid=%d reason=%u\r\n",
                     ev->mac[0], ev->mac[1], ev->mac[2],
                     ev->mac[3], ev->mac[4], ev->mac[5], ev->aid,
                     (unsigned)ev->reason);
    } else if (id == WIFI_EVENT_AP_START) {
        n = snprintf(line, sizeof(line), "# ap_started\r\n");
        status_led_set(STATUS_LED_WIFI_AP_NO_CLIENT);
    } else if (id == WIFI_EVENT_AP_STOP) {
        n = snprintf(line, sizeof(line), "# ap_stopped\r\n");
        status_led_set(STATUS_LED_ERROR);
    }
    if (n > 0) {
        if ((size_t)n >= sizeof(line)) n = sizeof(line) - 1;
        write_locked(line, (size_t)n);
    }
    // Ask the WiFi stack for the current client count instead of tracking it
    // ourselves — dodges "connect/disconnect race" and "spurious event during
    // reassociation" edge cases. Called only on AP events, which are rare.
    if (id == WIFI_EVENT_AP_STACONNECTED || id == WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_sta_list_t stas;
        memset(&stas, 0, sizeof(stas));
        if (esp_wifi_ap_get_sta_list(&stas) == ESP_OK) {
            status_led_set(stas.num > 0
                           ? STATUS_LED_WIFI_AP_CLIENT
                           : STATUS_LED_WIFI_AP_NO_CLIENT);
        }
    }
}

static void wifi_ap_init(void) {
    // NVS is required by esp_wifi_init for calibration + persisted config.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));

    wifi_config_t wifi_cfg = { 0 };
    strncpy((char *)wifi_cfg.ap.ssid, ap_ssid, sizeof(wifi_cfg.ap.ssid));
    wifi_cfg.ap.ssid_len = strlen(ap_ssid);
    strncpy((char *)wifi_cfg.ap.password, WIFI_AP_PASSWORD,
            sizeof(wifi_cfg.ap.password));
    wifi_cfg.ap.channel = AP_CHANNEL;
    wifi_cfg.ap.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_cfg.ap.max_connection = AP_MAX_CONN;
    wifi_cfg.ap.pmf_cfg.required = false;

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}

// -----------------------------------------------------------------------------
// HTTP server + / + /health + POST /ota
// -----------------------------------------------------------------------------

// Live view is gzipped at build time (see main/CMakeLists.txt) and embedded as
// a binary blob via EMBED_FILES. The linker exposes it as two symbols bracketing
// the payload.
extern const uint8_t index_html_gz_start[] asm("_binary_index_html_gz_start");
extern const uint8_t index_html_gz_end[]   asm("_binary_index_html_gz_end");

static esp_err_t root_handler(httpd_req_t *req) {
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
    // Small file, cheap to re-fetch; avoid stale HTML surviving an OTA update.
    httpd_resp_set_hdr(req, "Cache-Control", "no-cache");
    const size_t len = (size_t)(index_html_gz_end - index_html_gz_start);
    return httpd_resp_send(req, (const char *)index_html_gz_start, len);
}

// Static, not on stack: HTTPD_DEFAULT_CONFIG.stack_size is 4 KB, so a 4 KB
// local buffer would blow the httpd task's stack. httpd is single-threaded per
// server, so no concurrent handler runs — no race on this buffer.
static char ota_recv_buf[4096];

static esp_err_t ota_handler(httpd_req_t *req) {
    // No auth beyond the WPA2 AP password. Rollback (§ sdkconfig.defaults)
    // covers "user pushed a broken image" better than a token would.

    const esp_partition_t *update = esp_ota_get_next_update_partition(NULL);
    if (update == NULL) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   "no update partition");
    }

    if (req->content_len <= 0) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                                   "empty body — POST the firmware.bin as the request body");
    }

    esp_ota_handle_t handle = 0;
    esp_err_t err = esp_ota_begin(update, OTA_SIZE_UNKNOWN, &handle);
    if (err != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   esp_err_to_name(err));
    }

    {
        char line[128];
        int n = snprintf(line, sizeof(line),
            "# ota_begin partition=%s size_hint=%d\r\n",
            update->label, req->content_len);
        if (n > 0) {
            if ((size_t)n >= sizeof(line)) n = sizeof(line) - 1;
            write_locked(line, (size_t)n);
        }
    }

    int remaining = req->content_len;
    while (remaining > 0) {
        int chunk = remaining < (int)sizeof(ota_recv_buf) ? remaining : (int)sizeof(ota_recv_buf);
        int r = httpd_req_recv(req, ota_recv_buf, chunk);
        if (r <= 0) {
            if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
            esp_ota_abort(handle);
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                       "recv failed");
        }
        err = esp_ota_write(handle, ota_recv_buf, r);
        if (err != ESP_OK) {
            esp_ota_abort(handle);
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                       esp_err_to_name(err));
        }
        remaining -= r;
    }

    err = esp_ota_end(handle);
    if (err != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   esp_err_to_name(err));
    }

    err = esp_ota_set_boot_partition(update);
    if (err != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   esp_err_to_name(err));
    }

    {
        char line[128];
        int n = snprintf(line, sizeof(line),
            "# ota_success partition=%s size=%d — restarting in 500ms\r\n",
            update->label, req->content_len);
        if (n > 0) {
            if ((size_t)n >= sizeof(line)) n = sizeof(line) - 1;
            write_locked(line, (size_t)n);
        }
    }

    httpd_resp_sendstr(req, "OK — restarting\n");

    // Give httpd time to flush the response before the reset kills the socket.
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;  // unreached
}

// Count active WebSocket clients on demand from the framework's session table,
// so there's no stored client state to keep in sync with disconnects.
static int count_ws_clients(void) {
    if (s_server == NULL) return 0;
    int fds[10];
    size_t nfds = sizeof(fds) / sizeof(fds[0]);
    if (httpd_get_client_list(s_server, &nfds, fds) != ESP_OK) return 0;
    int n = 0;
    for (size_t i = 0; i < nfds; i++) {
        if (httpd_ws_get_fd_info(s_server, fds[i]) == HTTPD_WS_CLIENT_WEBSOCKET) {
            n++;
        }
    }
    return n;
}

static esp_err_t health_handler(httpd_req_t *req) {
    twai_lib_health_t h = { 0 };
    twai_lib_health(&h);

    uint64_t uptime_ms = (uint64_t)(esp_timer_get_time() / 1000);
    uint64_t seen       = atomic_load_explicit(&frames_seen, memory_order_relaxed);
    uint64_t ws_sent    = atomic_load_explicit(&frames_ws_sent, memory_order_relaxed);
    uint64_t ws_dropped = atomic_load_explicit(&frames_ws_dropped, memory_order_relaxed);

    wifi_sta_list_t stas;
    memset(&stas, 0, sizeof(stas));
    esp_wifi_ap_get_sta_list(&stas);

    // Emit literal `null` when no client is connected — `0 dBm` is a valid
    // signal reading, so a numeric fallback would be actively misleading.
    char rssi_str[8];
    if (stas.num > 0) {
        snprintf(rssi_str, sizeof(rssi_str), "%d", stas.sta[0].rssi);
    } else {
        strcpy(rssi_str, "null");
    }

    char body[384];
    int n = snprintf(body, sizeof(body),
        "{"
        "\"uptime_ms\":%llu,"
        "\"twai_state\":\"%s\","
        "\"twai_bus_err\":%lu,"
        "\"twai_rx_missed\":%lu,"
        "\"twai_rx_overrun\":%lu,"
        "\"frames_seen\":%llu,"
        "\"ap_clients\":%d,"
        "\"ap_client_rssi_dbm\":%s,"
        "\"ws_clients\":%d,"
        "\"frames_ws_sent\":%llu,"
        "\"frames_ws_dropped\":%llu"
        "}",
        (unsigned long long)uptime_ms,
        twai_lib_state_str(h.state),
        (unsigned long)h.bus_error_count,
        (unsigned long)h.rx_missed_count,
        (unsigned long)h.rx_overrun_count,
        (unsigned long long)seen,
        stas.num,
        rssi_str,
        count_ws_clients(),
        (unsigned long long)ws_sent,
        (unsigned long long)ws_dropped);

    if (n < 0 || (size_t)n >= sizeof(body)) {
        return httpd_resp_send_500(req);
    }

    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, body, n);
}

// -----------------------------------------------------------------------------
// WebSocket /stream — one-way broadcast of SLCAN frames
// -----------------------------------------------------------------------------

// Called only for inbound DATA frames from a client (the framework handles the
// upgrade handshake itself; PING/CLOSE are auto-handled with
// handle_ws_control_frames=false). One-way stream — we don't consume the
// client's data. Drain what came in so the socket cursor advances and
// subsequent frames stay aligned, then return.
static esp_err_t stream_ws_handler(httpd_req_t *req) {
    // Handshake path: framework completes the upgrade response, we just OK it.
    if (req->method == HTTP_GET) {
        return ESP_OK;
    }
    httpd_ws_frame_t f = { 0 };
    esp_err_t err = httpd_ws_recv_frame(req, &f, 0);
    if (err != ESP_OK || f.len == 0) {
        return ESP_OK;
    }
    uint8_t discard[64];
    if (f.len > sizeof(discard)) f.len = sizeof(discard);
    f.payload = discard;
    httpd_ws_recv_frame(req, &f, sizeof(discard));
    return ESP_OK;
}

// Drains ws_tx_q and fans each frame out to every active WS client tracked by
// the framework. Runs at priority +3 so it sits above status_task (+1) / the
// main-task RX loop (+0) and below the httpd task (+5) — drains quickly, never
// starves the HTTP server. httpd_ws_send_frame_async is blocking on the socket
// send (bounded by cfg.send_wait_timeout, which we set to 1 s in
// http_server_start), so a stuck client can stall the sender for at most 1 s
// per stuck send call.
static void ws_tx_task(void *arg) {
    (void)arg;
    ws_item_t item;
    int fds[10];
    size_t nfds;
    httpd_ws_frame_t f = {
        .final = true,
        .fragmented = false,
        .type = HTTPD_WS_TYPE_TEXT,
    };
    while (xQueueReceive(ws_tx_q, &item, portMAX_DELAY) == pdPASS) {
        if (s_server == NULL) continue;
        f.payload = (uint8_t *)item.buf;
        f.len     = item.len;
        nfds = sizeof(fds) / sizeof(fds[0]);
        if (httpd_get_client_list(s_server, &nfds, fds) != ESP_OK) continue;
        bool any_sent = false;
        for (size_t i = 0; i < nfds; i++) {
            if (httpd_ws_get_fd_info(s_server, fds[i]) != HTTPD_WS_CLIENT_WEBSOCKET) continue;
            if (httpd_ws_send_frame_async(s_server, fds[i], &f) == ESP_OK) {
                any_sent = true;
            }
        }
        if (any_sent) {
            atomic_fetch_add_explicit(&frames_ws_sent, 1, memory_order_relaxed);
        }
    }
}

static void http_server_start(void) {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    // Headroom for one WS subscriber + occasional /health hits + rare /ota
    // and room for a second WS client (phone + laptop). Framework reserves 3
    // internally so effective ceiling is 7 concurrent app connections.
    cfg.max_open_sockets = 10;
    // Bound the ws_tx_task stall if a WS peer's TCP send blocks. Default is
    // 5 s which is much too long for a 3000-fps stream — a broken client
    // would stall the sender and the RX loop's queue fills fast.
    cfg.send_wait_timeout = 1;
    ESP_ERROR_CHECK(httpd_start(&s_server, &cfg));

    static const httpd_uri_t root_uri = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = root_handler,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &root_uri));

    static const httpd_uri_t health_uri = {
        .uri = "/health",
        .method = HTTP_GET,
        .handler = health_handler,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &health_uri));

    static const httpd_uri_t ota_uri = {
        .uri = "/ota",
        .method = HTTP_POST,
        .handler = ota_handler,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &ota_uri));

    static const httpd_uri_t stream_uri = {
        .uri = "/stream",
        .method = HTTP_GET,
        .handler = stream_ws_handler,
        .user_ctx = NULL,
        .is_websocket = true,
        .handle_ws_control_frames = false,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &stream_uri));
}

// -----------------------------------------------------------------------------
// TWAI status task (SLCAN comment line, same shape as can-logger)
// -----------------------------------------------------------------------------

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
        // BUS_OFF latches red. Any other state hands control back to whatever
        // wifi_event_handler last set (AP-no-client / AP-client / ap_started),
        // so a transient TWAI blip doesn't nuke the WiFi surface indication.
        if (h.state == TWAI_STATE_BUS_OFF) {
            status_led_set(STATUS_LED_ERROR);
        }
    }
}

// -----------------------------------------------------------------------------

void app_main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    stdout_mutex = xSemaphoreCreateMutex();
    ws_tx_q = xQueueCreate(WS_TX_QUEUE_DEPTH, sizeof(ws_item_t));

    // Yellow means "we booted, nothing else is up yet." Colors flip as each
    // surface comes online: green (TWAI up, no wifi yet) → blue (AP up, no
    // client) → cyan (client joined). Red is BUS_OFF or AP_STOP.
    ESP_ERROR_CHECK(status_led_init(LED_GPIO));
    status_led_set(STATUS_LED_BOOT);

    derive_ap_ssid();
    print_boot_header();

    twai_lib_config_t cfg = {
        .bitrate_kbps = CAN_BITRATE_KBPS,
        .rx_queue_len = CAN_RX_QUEUE,
        .tx_pin       = CAN_TX_PIN,
        .rx_pin       = CAN_RX_PIN,
    };
    ESP_ERROR_CHECK(twai_lib_start(&cfg));
    status_led_set(STATUS_LED_CAN_ONLY);

    // Retroactive milestone-1 sanity check on the wire — proves the TWAI init
    // succeeded even before any bike frames arrive.
    {
        const char *ok = "# twai_started state=running\r\n";
        write_locked(ok, strlen(ok));
    }

    xTaskCreate(status_task, "twai_status", 3072, NULL, tskIDLE_PRIORITY + 1, NULL);

    wifi_ap_init();
    http_server_start();

    // Sender task starts after http_server_start so s_server is populated.
    // (It guards for NULL anyway — this is just tidier.)
    xTaskCreate(ws_tx_task, "ws_tx", 3072, NULL, tskIDLE_PRIORITY + 3, NULL);

    // New firmware has proven it can reach WiFi + HTTP up. Cancel any pending
    // OTA rollback verdict — this build is now the committed one. Safe to call
    // unconditionally: returns ESP_ERR_INVALID_STATE (ignored) if we weren't
    // in pending-verify state (e.g. first flash via USB, not from OTA).
    esp_ota_mark_app_valid_cancel_rollback();

    char buf[SLCAN_MAX_FRAME_BYTES];
    twai_message_t msg;
    while (true) {
        if (twai_lib_receive(&msg, portMAX_DELAY)) {
            size_t n = slcan_format_frame(&msg, buf);
            write_locked(buf, n);
            atomic_fetch_add_explicit(&frames_seen, 1, memory_order_relaxed);
            status_led_pulse_rx();

            // Fan out to WS clients via the sender task. Drop-newest on queue
            // full — bumps frames_ws_dropped for the "capture degraded"
            // signal on /health.
            ws_item_t slot;
            slot.len = (uint8_t)n;
            memcpy(slot.buf, buf, n);
            if (xQueueSendToBack(ws_tx_q, &slot, 0) != pdPASS) {
                atomic_fetch_add_explicit(&frames_ws_dropped, 1,
                                         memory_order_relaxed);
            }
        }
    }
}
