// slcan — SLCAN (Lawicel ASCII) wire-format encoder.
//
// One classic-CAN frame per output line:
//
//   t<3-hex id><1-hex dlc><2-hex per data byte>\r       (11-bit data frame)
//   T<8-hex id><1-hex dlc><2-hex per data byte>\r       (29-bit data frame)
//   r / R                                                (remote-request)
//
// python-can's SLCAN parser (and scripts/capture.py's inline parser) consume
// this format directly. Consumers own their write path — this lib formats only.

#pragma once

#include "twai_lib.h"   // for twai_message_t

#include <stddef.h>

// Longest classic-CAN SLCAN line:
//   T + 8-hex id + 1-hex dlc + 16 hex data + \r  =  27 bytes.
// 32 gives a comfortable round-number ceiling for callers' local buffers.
#define SLCAN_MAX_FRAME_BYTES 32

// Format one TWAI frame as SLCAN into `out`. Returns bytes written.
// `out` must be at least SLCAN_MAX_FRAME_BYTES.
size_t slcan_format_frame(const twai_message_t *msg, char *out);
