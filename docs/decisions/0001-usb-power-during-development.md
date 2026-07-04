# 0001 — USB-power the adapter during development; 12V only for test rides

**Date:** 2026-06-15
**Status:** Superseded by [ADR 0015](0015-f7-12v-power-path.md) (2026-06-25)

## Context

The bike's diagnostic connector exposes a switched 12V line on pin 4 (F7). Feeding 12V into the ESP32-S3 directly would destroy it, so any 12V use requires a buck converter (or LDO) sized for the load, plus protection (reverse polarity, transients, fuse).

For the majority of Phase 0 / Phase 1 work — bench logging, idle captures, indicator/mode-switch captures with the bike stationary — a USB cable from a laptop is sufficient and avoids the power-conditioning rabbit hole.

Test rides are the case where USB power isn't practical.

## Decision

- Development sessions are USB-powered from a laptop or USB battery. Pin 4 (F7) is left unconnected.
- For mounted test rides, switch to a 12V → 5V buck converter fed from F7, sized appropriately and with basic protection.
- The "test ride" power path is a separate, deferred sub-project — do not design it speculatively. Spec it when the first test ride is actually on the calendar.

## Consequences

- First adapter build can skip all 12V conditioning. Faster path to first CAN capture.
- Logging sessions are tethered — fine on the bench, fine for short stationary tests, not for ride captures. Ride captures will require either the 12V path or a USB battery on the bike.
- F7 cannot be used as a key-on detect under this decision (it isn't wired). Bus activity itself is a serviceable proxy for "key is on" — re-evaluate only if a real need appears.
- When the 12V harness gets built, it gets its own ADR (supersede this one if anything here changes).
