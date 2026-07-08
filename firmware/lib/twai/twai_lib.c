#include "twai_lib.h"

esp_err_t twai_lib_start(const twai_lib_config_t *cfg) {
    if (cfg == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
        cfg->tx_pin, cfg->rx_pin, TWAI_MODE_LISTEN_ONLY);
    g_config.rx_queue_len = cfg->rx_queue_len;

    twai_timing_config_t t_config;
    switch (cfg->bitrate_kbps) {
        case 500: {
            twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS();
            t_config = t;
            break;
        }
        case 250: {
            twai_timing_config_t t = TWAI_TIMING_CONFIG_250KBITS();
            t_config = t;
            break;
        }
        default:
            return ESP_ERR_INVALID_ARG;
    }

    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t err = twai_driver_install(&g_config, &t_config, &f_config);
    if (err != ESP_OK) {
        return err;
    }
    return twai_start();
}

bool twai_lib_receive(twai_message_t *out, TickType_t timeout_ticks) {
    return twai_receive(out, timeout_ticks) == ESP_OK;
}

esp_err_t twai_lib_health(twai_lib_health_t *out) {
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    twai_status_info_t s;
    esp_err_t err = twai_get_status_info(&s);
    if (err != ESP_OK) {
        return err;
    }
    out->bus_error_count  = s.bus_error_count;
    out->rx_missed_count  = s.rx_missed_count;
    out->rx_overrun_count = s.rx_overrun_count;
    out->state            = s.state;
    return ESP_OK;
}

const char *twai_lib_state_str(twai_state_t s) {
    switch (s) {
        case TWAI_STATE_STOPPED:    return "stopped";
        case TWAI_STATE_RUNNING:    return "running";
        case TWAI_STATE_BUS_OFF:    return "bus_off";
        case TWAI_STATE_RECOVERING: return "recovering";
        default:                    return "unknown";
    }
}
