#include "slcan.h"

#include <stdint.h>

static const char HEX[] = "0123456789ABCDEF";

size_t slcan_format_frame(const twai_message_t *msg, char *out) {
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
