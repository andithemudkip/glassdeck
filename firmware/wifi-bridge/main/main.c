// wifi-bridge — Phase 2+ untethered CAN capture + browser-served live view for
// the Husqvarna Svartpilen 401. See docs/decisions/0016-wifi-dev-capture-and-
// live-view.md and firmware/wifi-bridge/README.md for the full plan.
//
// State at milestone 5:
//   - WiFi soft-AP (SSID `glassdeck-<lower6 of MAC>`, WPA2 from wifi_secrets.h)
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
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
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

// SSID built at boot from the wifi-softap MAC. "glassdeck-" (10) + 6 hex + NUL.
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
// out silently (the WS path is opportunistic; the ring is what backs durable
// capture).
static _Atomic uint64_t frames_ws_sent = 0;
static _Atomic uint64_t frames_ws_dropped = 0;

// Ring writer overwrites the oldest slot when full (ADR 0018 § Storage
// architecture — drop-oldest). Counter increments per overwritten live slot;
// surfaced on /health as the "capture degraded" signal for the ring path,
// same intent as frames_ws_dropped for the WS path.
static _Atomic uint64_t frames_ring_dropped = 0;

// Handle promoted from local in http_server_start; ws_tx_task and
// health_handler both need it for httpd_get_client_list / send_frame_async.
static httpd_handle_t s_server;

// One SLCAN line, copied into the queue by the RX loop. Grows to
// SLCAN_MAX_LINE_BYTES (M4) so the on-device (<sec>.<us>) timestamp prefix
// fits alongside the SLCAN payload. ts_us is the same esp_timer_get_time()
// stamp the ring keys on — the WS sender doesn't use it directly, but the
// same shape lets the RX loop write ring + queue slots from one struct.
typedef struct {
    int64_t ts_us;
    uint8_t len;
    char    buf[SLCAN_MAX_LINE_BYTES];
} ws_item_t;

// Depth 64 × ~64 bytes/item ≈ 4 KB total — a few 10s of ms of headroom at
// peak bike CAN rates. Drop-newest (xQueueSendToBack with 0 timeout) on full;
// see the milestone-3 plan for the ADR-alignment argument.
#define WS_TX_QUEUE_DEPTH 64
static QueueHandle_t ws_tx_q;

// -----------------------------------------------------------------------------
// PSRAM gap-fill ring (ADR 0018)
// -----------------------------------------------------------------------------
// ~512 KB of PSRAM covering ~27 s at 300 fps with the (sec.us) prefix. Purpose
// is *not* to be the primary capture sink (that's the browser's OPFS, ADR 0018
// § Storage architecture) — it's a short-lived backstop so the browser can
// splice over WS disconnects via GET /capture?since=<ts_us>.
//
// Producer: the app_main RX loop (single writer).
// Consumers: /capture GET handler (0..N, but each takes an index snapshot
// upfront and iterates on its own copy, so a running writer never blocks it).
// A tiny portMUX around the head advance keeps writer + snapshot atomic
// without ever holding the lock across the payload memcpy.
typedef struct {
    int64_t ts_us;
    uint8_t len;
    char    buf[SLCAN_MAX_LINE_BYTES];
} ring_slot_t;

#define RING_SLOTS  8192  // ~512 KB, ~27 s @ 300 fps with the ts prefix

static ring_slot_t         *s_ring;         // heap_caps_malloc'd into PSRAM
static portMUX_TYPE         s_ring_mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t             s_ring_head;    // next write index [0, RING_SLOTS)
static uint64_t             s_ring_writes;  // total frames written (monotonic)

// Grab a consistent snapshot of the ring's state under the spinlock. The
// caller iterates on `first_ts_us` -> `last_ts_us` in ring order using the
// returned head + writes count; slots overwritten mid-response are just
// skipped by the timestamp filter (drop-oldest matches ADR 0018).
typedef struct {
    uint32_t head;
    uint64_t writes;
    int64_t  earliest_ts_us;   // 0 if ring is empty
    int64_t  latest_ts_us;     // 0 if ring is empty
} ring_snapshot_t;

static void ring_snapshot(ring_snapshot_t *out) {
    portENTER_CRITICAL(&s_ring_mux);
    out->head    = s_ring_head;
    out->writes  = s_ring_writes;
    portEXIT_CRITICAL(&s_ring_mux);
    if (out->writes == 0) {
        out->earliest_ts_us = 0;
        out->latest_ts_us   = 0;
        return;
    }
    // Earliest live slot is either index 0 (not yet wrapped) or the one right
    // after head (wrapped — head points at the oldest surviving entry).
    uint32_t earliest_idx = (out->writes <= RING_SLOTS)
        ? 0
        : (out->head % RING_SLOTS);
    uint32_t latest_idx = (out->head + RING_SLOTS - 1) % RING_SLOTS;
    out->earliest_ts_us = s_ring[earliest_idx].ts_us;
    out->latest_ts_us   = s_ring[latest_idx].ts_us;
}

// Copy `len` bytes into the next ring slot, tagged with `ts_us`. Bumps
// frames_ring_dropped when the slot being overwritten held a live frame.
static void ring_write(int64_t ts_us, const char *buf, size_t len) {
    if (s_ring == NULL || len == 0 || len > SLCAN_MAX_LINE_BYTES) return;
    portENTER_CRITICAL(&s_ring_mux);
    uint32_t idx = s_ring_head;
    bool overwriting = (s_ring_writes >= RING_SLOTS);
    s_ring_head = (idx + 1) % RING_SLOTS;
    s_ring_writes++;
    portEXIT_CRITICAL(&s_ring_mux);
    // Payload copy happens outside the spinlock — the slot at `idx` is owned
    // by this writer between the head advance and the next wrap (RING_SLOTS
    // frames from now). A concurrent snapshot may observe the pre-copy bytes
    // for this slot; that's benign — the SLCAN parse on the other side just
    // drops a malformed line, matching drop-oldest semantics.
    s_ring[idx].ts_us = ts_us;
    s_ring[idx].len   = (uint8_t)len;
    memcpy(s_ring[idx].buf, buf, len);
    if (overwriting) {
        atomic_fetch_add_explicit(&frames_ring_dropped, 1, memory_order_relaxed);
    }
}

static void write_locked(const char *buf, size_t n) {
    xSemaphoreTake(stdout_mutex, portMAX_DELAY);
    fwrite(buf, 1, n, stdout);
    xSemaphoreGive(stdout_mutex);
}

static void derive_ap_ssid(void) {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(ap_ssid, sizeof(ap_ssid), "glassdeck-%02x%02x%02x",
             mac[3], mac[4], mac[5]);
}

static void print_boot_header(void) {
    // `#`-prefixed and `\r`-terminated so the SLCAN parser downstream ignores
    // these lines cleanly, but they still render on `pio device monitor` for
    // the operator to copy the SSID/password into the phone.
    printf("# ---- wifi-bridge (milestone 6/M4) ----\r\n");
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

    uint64_t uptime_ms   = (uint64_t)(esp_timer_get_time() / 1000);
    uint64_t seen        = atomic_load_explicit(&frames_seen, memory_order_relaxed);
    uint64_t ws_sent     = atomic_load_explicit(&frames_ws_sent, memory_order_relaxed);
    uint64_t ws_dropped  = atomic_load_explicit(&frames_ws_dropped, memory_order_relaxed);
    uint64_t ring_dropped = atomic_load_explicit(&frames_ring_dropped, memory_order_relaxed);

    ring_snapshot_t snap;
    ring_snapshot(&snap);

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

    char body[512];
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
        "\"frames_ws_dropped\":%llu,"
        "\"frames_ring_dropped\":%llu,"
        "\"ring_earliest_ts_us\":%lld,"
        "\"ring_latest_ts_us\":%lld"
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
        (unsigned long long)ws_dropped,
        (unsigned long long)ring_dropped,
        (long long)snap.earliest_ts_us,
        (long long)snap.latest_ts_us);

    if (n < 0 || (size_t)n >= sizeof(body)) {
        return httpd_resp_send_500(req);
    }

    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, body, n);
}

// -----------------------------------------------------------------------------
// GET /capture?since=<ts_us> — gap-fill ring dump (ADR 0018 § /capture protocol)
// -----------------------------------------------------------------------------
//
// Streams every ring entry with ts > since, in ring order, as chunked SLCAN
// with the same (<sec>.<us>) prefix as /stream. When since precedes the ring's
// earliest surviving entry (i.e. the ring wrapped over the requested window),
// the response carries an X-Bike-Gap-Ms header quantifying the unrecoverable
// slice; the browser writes a matching `# GAP <ms>` marker into OPFS.
//
// Bare GET /capture (no `since`) dumps the whole current ring — handy for
// `curl 192.168.4.1/capture` ad-hoc inspection.

// Parse a decimal int64 from the query string. Returns true on success.
static bool parse_int64_query(httpd_req_t *req, const char *key, int64_t *out) {
    size_t qlen = httpd_req_get_url_query_len(req);
    if (qlen == 0) return false;
    char qbuf[64];
    if (qlen >= sizeof(qbuf)) qlen = sizeof(qbuf) - 1;
    if (httpd_req_get_url_query_str(req, qbuf, sizeof(qbuf)) != ESP_OK) return false;
    char vbuf[32];
    if (httpd_query_key_value(qbuf, key, vbuf, sizeof(vbuf)) != ESP_OK) return false;
    char *end = NULL;
    long long v = strtoll(vbuf, &end, 10);
    if (end == vbuf) return false;
    *out = (int64_t)v;
    return true;
}

static esp_err_t capture_handler(httpd_req_t *req) {
    int64_t since = 0;
    bool has_since = parse_int64_query(req, "since", &since);

    if (s_ring == NULL) {
        // Ring allocation failed at boot. Report empty with a gap header
        // covering the whole requested window if a `since` was supplied.
        if (has_since) {
            int64_t now = esp_timer_get_time();
            char hdr[24];
            int64_t gap_ms = (now > since) ? (now - since) / 1000 : 0;
            snprintf(hdr, sizeof(hdr), "%lld", (long long)gap_ms);
            httpd_resp_set_hdr(req, "X-Bike-Gap-Ms", hdr);
        }
        httpd_resp_set_type(req, "text/plain; charset=utf-8");
        return httpd_resp_send(req, "", 0);
    }

    ring_snapshot_t snap;
    ring_snapshot(&snap);

    // Set gap header BEFORE any body chunks — httpd headers latch on the
    // first httpd_resp_send_chunk call.
    if (has_since && snap.writes > 0 && since < snap.earliest_ts_us) {
        int64_t gap_us = snap.earliest_ts_us - since;
        char hdr[24];
        snprintf(hdr, sizeof(hdr), "%lld", (long long)(gap_us / 1000));
        httpd_resp_set_hdr(req, "X-Bike-Gap-Ms", hdr);
    }

    httpd_resp_set_type(req, "text/plain; charset=utf-8");
    // Discourage intermediate caches — the ring content changes every RX frame.
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");

    if (snap.writes == 0) {
        return httpd_resp_send(req, "", 0);
    }

    // Iterate from earliest surviving slot forward to (head - 1). The set of
    // live indices is [earliest_idx .. earliest_idx + live_count) mod RING.
    uint32_t live_count = (snap.writes < RING_SLOTS)
        ? (uint32_t)snap.writes
        : RING_SLOTS;
    uint32_t start_idx = (snap.head + RING_SLOTS - live_count) % RING_SLOTS;

    for (uint32_t i = 0; i < live_count; i++) {
        uint32_t idx = (start_idx + i) % RING_SLOTS;
        // Snapshot the slot's ts + len once so a concurrent writer overwriting
        // this exact slot (only possible if we're lagging by ~27 s of frames)
        // can't tear the len/ts pair we send.
        int64_t slot_ts = s_ring[idx].ts_us;
        uint8_t slot_len = s_ring[idx].len;
        if (slot_len == 0 || slot_len > SLCAN_MAX_LINE_BYTES) continue;
        if (has_since && slot_ts <= since) continue;
        if (httpd_resp_send_chunk(req, s_ring[idx].buf, slot_len) != ESP_OK) {
            // Client disconnected mid-stream — bail cleanly.
            return ESP_FAIL;
        }
    }
    return httpd_resp_send_chunk(req, NULL, 0);
}

// -----------------------------------------------------------------------------
// POST /mark?label=<text> — M7a. Inserts `# MARK <label>` into the ring at the
// current position; also broadcast on /stream so live viewers see it live.
// -----------------------------------------------------------------------------

static esp_err_t mark_handler(httpd_req_t *req) {
    size_t qlen = httpd_req_get_url_query_len(req);
    if (qlen == 0) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                                   "missing ?label= query param");
    }
    char qbuf[128];
    if (qlen >= sizeof(qbuf)) qlen = sizeof(qbuf) - 1;
    if (httpd_req_get_url_query_str(req, qbuf, sizeof(qbuf)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad query");
    }
    char label[64];
    if (httpd_query_key_value(qbuf, "label", label, sizeof(label)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "label missing");
    }
    // Trim; reject empty. Keep control chars out — the mark ends up in a plain
    // text log line eventually.
    size_t len = strlen(label);
    while (len > 0 && (label[len - 1] == ' ' || label[len - 1] == '\t')) {
        label[--len] = '\0';
    }
    if (len == 0) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "empty label");
    }
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)label[i];
        if (c < 0x20 || c == 0x7f) label[i] = '?';
    }

    // Build the line. `# MARK ` is prefix-compatible with the capture.py hotkey
    // mark convention so downstream (# MARK / # GAP) shares one skip branch.
    char line[SLCAN_MAX_LINE_BYTES];
    int n = snprintf(line, sizeof(line), "# MARK %s\r", label);
    if (n <= 0 || n >= (int)sizeof(line)) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   "line too long");
    }

    int64_t ts_us = esp_timer_get_time();
    ring_write(ts_us, line, (size_t)n);

    // Also fan out on /stream so live viewers see the mark in real time.
    ws_item_t slot;
    slot.ts_us = ts_us;
    slot.len   = (uint8_t)n;
    memcpy(slot.buf, line, (size_t)n);
    xQueueSendToBack(ws_tx_q, &slot, 0);

    httpd_resp_set_type(req, "application/json");
    char body[96];
    int bn = snprintf(body, sizeof(body),
        "{\"ok\":true,\"ts_us\":%lld,\"label\":\"%s\"}",
        (long long)ts_us, label);
    if (bn < 0) return httpd_resp_send_500(req);
    return httpd_resp_send(req, body, bn);
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

// Phantom-fd reap: track per-fd send success/failure. When a WS peer's TCP
// socket stops draining — iOS Chrome swiped away is the canonical case, since
// the OS kernel keeps ACKing keepalives even after the app is gone — every
// httpd_ws_send_frame_async returns ESP_ERR (queue full behind a stalled
// control-thread send). We reap by force-closing (httpd_sess_trigger_close),
// which stops the WiFi task from drowning core 0 in retransmits.
//
// Trigger is time-based, not count-based. Sends fail in *bursts* — the httpd
// async work queue fills and drains at ~400 fps, so a healthy client can hit
// 100+ consecutive failures during a bad moment without anything actually
// being wrong. What separates a phantom from a healthy client isn't "how many
// failures in a row" but "how long has it been since anything got through."
// Only reap if the fd has attempted enough sends to have earned an opinion
// (fails ≥ FAIL_FLOOR) AND hasn't had a success in NO_SUCCESS_MS.
//
// -1 sentinel because fd=0 can be a valid LWIP socket. `last_ok_tick` is
// seeded at fd-tracking time so a freshly-added fd gets a grace period.
#define WS_TX_FAIL_TRACKED       8      // ≥ max_open_sockets
#define WS_TX_FAIL_FLOOR         30     // ~75 ms of failures at 400 fps
#define WS_TX_NO_SUCCESS_MS      3000   // 3 s dry spell → phantom
static struct {
    int         fd;
    uint16_t    fails;
    TickType_t  last_ok_tick;
} s_ws_tx_fails[WS_TX_FAIL_TRACKED];

// Drains ws_tx_q and fans each frame out to every active WS client tracked by
// the framework. Runs at priority +3 so it sits above status_task (+1) and
// below the httpd task (+5) — drains quickly, never starves the HTTP server.
// httpd_ws_send_frame_async is blocking on the socket send (bounded by
// cfg.send_wait_timeout, which we set to 1 s in http_server_start), so a
// stuck client can stall the sender for at most 1 s per stuck send call.
// Consecutive-failure tracking + trigger_close reaps half-open fds that
// keepalive can't catch (see s_ws_tx_fails above).
static void ws_tx_task(void *arg) {
    (void)arg;
    for (int j = 0; j < WS_TX_FAIL_TRACKED; j++) s_ws_tx_fails[j].fd = -1;

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
            bool ok = (httpd_ws_send_frame_async(s_server, fds[i], &f) == ESP_OK);
            if (ok) any_sent = true;

            TickType_t now = xTaskGetTickCount();
            int slot = -1, free_slot = -1;
            for (int j = 0; j < WS_TX_FAIL_TRACKED; j++) {
                if (s_ws_tx_fails[j].fd == fds[i]) { slot = j; break; }
                if (s_ws_tx_fails[j].fd == -1 && free_slot < 0) free_slot = j;
            }
            if (slot < 0 && free_slot >= 0) {
                slot = free_slot;
                s_ws_tx_fails[slot].fd           = fds[i];
                s_ws_tx_fails[slot].fails        = 0;
                s_ws_tx_fails[slot].last_ok_tick = now;  // grace period
            }
            if (slot < 0) continue;

            if (ok) {
                s_ws_tx_fails[slot].fails        = 0;
                s_ws_tx_fails[slot].last_ok_tick = now;
            } else if (++s_ws_tx_fails[slot].fails >= WS_TX_FAIL_FLOOR &&
                       (now - s_ws_tx_fails[slot].last_ok_tick) >=
                           pdMS_TO_TICKS(WS_TX_NO_SUCCESS_MS)) {
                httpd_sess_trigger_close(s_server, fds[i]);
                s_ws_tx_fails[slot].fd    = -1;
                s_ws_tx_fails[slot].fails = 0;
            }
        }
        if (any_sent) {
            atomic_fetch_add_explicit(&frames_ws_sent, 1, memory_order_relaxed);
        }

        // Sweep: forget any tracked fd that wasn't in this iteration's client
        // list (framework already reaped it, or trigger_close above did).
        for (int j = 0; j < WS_TX_FAIL_TRACKED; j++) {
            if (s_ws_tx_fails[j].fd == -1) continue;
            bool present = false;
            for (size_t i = 0; i < nfds; i++) {
                if (fds[i] == s_ws_tx_fails[j].fd) { present = true; break; }
            }
            if (!present) {
                s_ws_tx_fails[j].fd    = -1;
                s_ws_tx_fails[j].fails = 0;
            }
        }
    }
}

static void http_server_start(void) {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    // Headroom for one WS subscriber + occasional /health hits + rare /ota
    // and room for a second WS client (phone + laptop). httpd caps this at
    // LWIP_MAX_SOCKETS (10) minus 3 it reserves internally = 7.
    cfg.max_open_sockets = 7;
    // Bound the ws_tx_task stall if a WS peer's TCP send blocks. Field is
    // seconds; 1 is the floor.
    cfg.send_wait_timeout = 1;
    // Aggressive TCP keepalive so an ungracefully-closed WS peer (iOS Chrome
    // swiped away — no FIN) gets reaped in ~5 s instead of the LWIP default
    // (minutes). Without this the phantom fd stays in the client list and
    // ws_tx_task keeps queuing sends to it, congesting the httpd control
    // thread and making a fresh reconnect stagger behind the dead-fd timeouts.
    cfg.keep_alive_enable   = true;
    cfg.keep_alive_idle     = 2;   // seconds before first probe
    cfg.keep_alive_interval = 1;   // seconds between probes
    cfg.keep_alive_count    = 3;   // probes before giving up → ~5 s total
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

    static const httpd_uri_t capture_uri = {
        .uri = "/capture",
        .method = HTTP_GET,
        .handler = capture_handler,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &capture_uri));

    static const httpd_uri_t mark_uri = {
        .uri = "/mark",
        .method = HTTP_POST,
        .handler = mark_handler,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &mark_uri));
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

// TWAI RX drain. Pinned to core 1 so a busy WiFi task on core 0 (e.g. TCP
// retransmit storm to a half-open iOS peer) can never starve it. Previously
// this loop lived inline in app_main and inherited the main task's core-0 /
// priority-1 slot, which lost catastrophically to WiFi (priority 23) when a
// phantom fd triggered retransmits — RX rate dropped from ~420 fps to ~27 fps
// and rx_missed climbed at ~490/s. The pinning is the real fix; the phantom
// cleanup in ws_tx_task complements it.
static void rx_task(void *arg) {
    (void)arg;
    char line[SLCAN_MAX_LINE_BYTES];
    twai_message_t msg;
    while (true) {
        if (twai_lib_receive(&msg, portMAX_DELAY)) {
            // On-device timestamp per ADR 0018. `esp_timer_get_time()` is µs
            // since boot, monotonic — same clock /health uptime uses.
            int64_t ts_us = esp_timer_get_time();
            int prefix_n = snprintf(
                line, SLCAN_TS_PREFIX_MAX + 1, "(%lld.%06lld) ",
                (long long)(ts_us / 1000000), (long long)(ts_us % 1000000));
            if (prefix_n < 0 || prefix_n >= (int)SLCAN_TS_PREFIX_MAX) {
                prefix_n = 0;  // pathological — emit unprefixed rather than corrupt
            }
            size_t frame_n = slcan_format_frame(&msg, line + prefix_n);
            size_t n = (size_t)prefix_n + frame_n;

            write_locked(line, n);
            atomic_fetch_add_explicit(&frames_seen, 1, memory_order_relaxed);
            status_led_pulse_rx();

            // Ring first: the ring is the durable(-ish) side, WS is
            // opportunistic. If the queue drop-newest fires we still have
            // the frame in the ring for /capture?since=.
            ring_write(ts_us, line, n);

            // Fan out to WS clients via the sender task. Drop-newest on queue
            // full — bumps frames_ws_dropped for the "capture degraded"
            // signal on /health.
            ws_item_t slot;
            slot.ts_us = ts_us;
            slot.len   = (uint8_t)n;
            memcpy(slot.buf, line, n);
            if (xQueueSendToBack(ws_tx_q, &slot, 0) != pdPASS) {
                atomic_fetch_add_explicit(&frames_ws_dropped, 1,
                                         memory_order_relaxed);
            }
        }
    }
}

// -----------------------------------------------------------------------------

void app_main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    stdout_mutex = xSemaphoreCreateMutex();
    ws_tx_q = xQueueCreate(WS_TX_QUEUE_DEPTH, sizeof(ws_item_t));

    // Allocate the ring in PSRAM (ADR 0018 § Storage architecture). Before
    // TWAI + WiFi come up so any cold-boot frame lands in the ring. If the
    // allocation fails we log and continue — the WS + USB paths still work,
    // /capture just responds empty (X-Bike-Gap-Ms covers the gap).
    s_ring = (ring_slot_t *)heap_caps_malloc(
        (size_t)RING_SLOTS * sizeof(ring_slot_t),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (s_ring != NULL) {
        // Zero-init so a snapshot before the first write reads ts=0, not
        // uninitialised PSRAM. Cheap at boot (~512 KB memset over PSRAM).
        memset(s_ring, 0, (size_t)RING_SLOTS * sizeof(ring_slot_t));
    }

    // Yellow means "we booted, nothing else is up yet." Colors flip as each
    // surface comes online: green (TWAI up, no wifi yet) → blue (AP up, no
    // client) → cyan (client joined). Red is BUS_OFF or AP_STOP.
    ESP_ERROR_CHECK(status_led_init(LED_GPIO));
    status_led_set(STATUS_LED_BOOT);

    derive_ap_ssid();
    print_boot_header();
    printf("# ring_bytes=%u slots=%u alloc=%s\r\n",
           (unsigned)((size_t)RING_SLOTS * sizeof(ring_slot_t)),
           (unsigned)RING_SLOTS,
           s_ring != NULL ? "ok" : "FAILED");

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

    // RX drain runs on core 1, isolated from WiFi/httpd on core 0. See rx_task.
    xTaskCreatePinnedToCore(rx_task, "twai_rx", 4096,
                            NULL, tskIDLE_PRIORITY + 5, NULL, 1);
}
