# 0004 — Logger wire format: SLCAN (Lawicel ASCII) over USB-CDC

**Date:** 2026-06-16
**Status:** Accepted

## Context

The `can-logger` firmware reads CAN frames from the TWAI peripheral and needs to ship them somewhere. For Phase 0 / Phase 1, "somewhere" is a host laptop over the ESP32-S3's USB-CDC serial. The on-wire format between firmware and laptop determines what the laptop-side capture script looks like and what off-the-shelf tools (SavvyCAN, can-utils, Wireshark, `python-can`) can ingest the data.

Options considered:

- **SLCAN (Lawicel ASCII)** — `t<id><len><data>\r` for 11-bit frames, `T<id><len><data>\r` for 29-bit extended. Line-based text.
- **candump-style text** — human-readable, `(timestamp) can0 12345678#DEADBEEF`. No live-stream parser in `python-can`.
- **Custom binary** — most compact, but every consumer needs custom parsing. Premature for this phase.

Throughput sanity check: worst-case CAN at 500 kbps is ~4000 frames/sec; SLCAN encoding is ~30 bytes/frame → ~120 kB/s. USB-CDC handles this comfortably.

## Decision

- **Format:** SLCAN (Lawicel ASCII), emitted line-by-line over USB-CDC serial.
- **Frame types:** both `t...` (11-bit standard) and `T...` (29-bit extended) emitted as received. Remote-request frames (`r` / `R`) emitted if observed but not expected on this bus.
- **Direction:** firmware → host only. The host→adapter half of the SLCAN protocol (channel open/close, bitrate set, etc.) is **not** implemented — the logger is fixed-purpose, configured at compile time. Standard `python-can` SLCAN backend tolerates a passive adapter.
- **Timestamps:** added by the host-side capture script using the host clock, not by the firmware. Frames are emitted in arrival order; jitter from USB-CDC buffering is acceptable for Phase 0 / Phase 1 analysis. (Revisit if signal timing analysis ever needs sub-ms accuracy.)

## Consequences

- Laptop-side capture script is short — `python-can` opens the serial port as an `slcan` bus and iterates `bus.recv()`.
- Captured `.log` files load directly into SavvyCAN, can-utils, and Wireshark without conversion.
- Bring-up debugging is trivial: `screen /dev/tty.usbmodem... 115200` shows raw frames as they arrive.
- Deviation from the SLCAN spec (no command channel) is documented here so future readers don't waste time wondering why `O` / `C` / `Sxx` aren't supported.
- If timestamp jitter ever matters, the firmware can add `Z<msb><lsb>` timestamp extensions (also SLCAN-standard) — supersede this ADR if so.
