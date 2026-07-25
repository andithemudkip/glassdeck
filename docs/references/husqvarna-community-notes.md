# Husqvarna community notes

Snippets from forum / Reddit / Discord conversations between Husqvarna owners about CAN signals on the 401 platform (and close relatives). Each snippet is a **hypothesis** to verify against our own captures — not a finding. When confirmed, promote to `docs/findings/can/` and cite the entry here.

One section per snippet. Lead with the source URL and date so links can be re-fetched if Reddit / forum threads disappear.

---

## Gear position on ID 129, first byte low nibble

- **Source:** <https://www.reddit.com/r/Husqvarna/comments/18zklgg/comment/lfe5om6/>
- **Author:** u/wifestalksthisuser (OP of the thread, working on their own Husqvarna dashboard)
- **Date seen:** 2026-06-16 (comment is ~2 years old per Reddit's relative timestamp, so written ~2024)

Verbatim exchange:

> **rayark9:** No problem. Is the gear position sent to the dash via canbus.
>
> **wifestalksthisuser (OP):** Yes it is on ID 129, first byte (second half of the byte)
>
> **rayark9:** Thanks

### Claim

Gear position is carried on **CAN ID 129, first byte (D0), low nibble** ("second half of the byte").

### Ambiguities to resolve when we capture

1. **Hex vs decimal.** "129" is ambiguous:
   - If **hex** `0x129` (= 297 dec): matches the ID blalor documented for gear on the KTM 690 ([ktm-can-library](ktm-can-library.md), `0x129` row). Strong prior — same KTM 390/690 family ECU lineage makes ID reuse plausible.
   - If **decimal** 129 (= `0x81`): a different ID entirely; we should still check it but it has no corroborating evidence.
   - The author doesn't say `0x` and forum/Reddit posters often write CAN IDs as bare decimal. Capture-time evidence will disambiguate (which ID actually changes nibble in sync with the gear lever).

2. **Nibble (high vs low).** blalor's 690 decoder puts gear on D0 **high** nibble; this commenter says **low** ("second half"). Two ways this can be reconciled:
   - Husqvarna's 401 ECU genuinely uses the low nibble while the KTM 690 uses the high nibble (firmware difference between platforms).
   - The commenter is reading the byte in the opposite endianness from blalor's convention and is actually describing the same nibble.
   - Easiest decider: at capture time, log D0 across gear changes, print as binary, see which 4 bits move.

3. **Neutral encoding.** blalor: `0` = neutral on 690. No info here for the 401. Worth checking whether neutral is `0` or some other value, and what values 1–6 map to (1-up vs 1-down etc.).

### What this does *not* tell us

- Nothing about clutch state (blalor put `clutch_in` on `0x129` D0 bit 3 on the 690 — separate hypothesis to test on our bike).
- No frame rate / period.
- No confirmation about other bytes of the message.
- No info on whether the dash *uses* this byte or just receives it.

### Verification plan when we get there

Capture session with: engine running, bike on stand or rolling slowly with rider, deliberate sequence N → 1 → 2 → 3 → 4 → 5 → 6 → N. Decode both `0x81` and `0x129` D0, splitting high vs low nibble. Whichever combination tracks the lever is the answer. Document in `docs/experiments/`, promote to `docs/findings/can/<id>-gear.md`.

---

## Self-test at power-on involves un-sniffed dash↔ECU traffic

- **Source:** <https://www.reddit.com/r/Husqvarna/comments/1eei5m3/update_8_custom_dashboard_project/> — "Update 8: Custom Dashboard Project" post by u/wifestalksthisuser
- **Date seen:** 2026-06-16

Verbatim:

> We started countless experiments and had dozens of data logging runs to try and understand what the OEM dash is communicating when the bike is turned on. There's a process called a self-test (or -check), where the bike checks if all systems are clear - basically - and it is precisely here where ABS, TC and the quick shifter get initiated. The OEM dash communicates SOMETHING to or from the ECU (or other components) that we have not managed to "sniff" out yet. This is a major road block that takes time and commitment which is hard because both of us work fulltime on our jobs or own other businesses.

### Claims worth treating as hypotheses

1. **There is a power-on self-test sequence** during which ABS, TC, and quick shifter get initialized.
2. **The OEM dash participates in that exchange** — it sends or receives something the ECU needs before those systems come online.
3. **At least one community team with extensive logging has not isolated that exchange.** Implication: it may not be plain broadcast CAN — could be a UDS / ISO-TP request-response sequence, a low-frequency frame, a frame only sent once per power cycle, or traffic on a bus we are not yet tapping (e.g. K-Line, LIN, or a separate CAN segment).

### Why this matters for us

This is direct evidence on `docs/research.md` open question **#2 — "Does the ECU expect messages from the dashboard?"** Tentative answer: **yes, at least during boot, and removing the dash is likely to leave ABS / TC / QS uninitialized.** This in turn pressures open question **#1 — "Can the OEM dashboard be completely disconnected?"** — answer is leaning toward "not without consequences."

This is still hypothesis-grade until we observe it ourselves, but it's strong enough to shape our capture plan: our **very first power-on capture must start before key-on and run continuously through the full self-test**, not just steady-state idle. If we miss the self-test window, we miss exactly the exchange that's been hard for others to find.

### What this does *not* say

- *Which* IDs are involved.
- Whether the un-sniffed traffic is on the same CAN bus the diagnostic connector exposes, or on a different physical layer.
- Whether the dash is the initiator or the responder.
- Whether the self-test runs every key-on or only after a reset / battery disconnect.

### Open follow-ups

- Watch for further posts from the same authors describing what they *did* sniff (would narrow the search space for what's missing).
- Once we have captures: compare bus traffic with OEM dash connected vs. disconnected during the self-test window. If ABS/TC/QS warning lamps stay lit or the bike refuses to start with the dash unplugged, that confirms the dash is on the critical path.

### Later update from the same author — problem is solvable

In a subsequent post (URL pending), u/wifestalksthisuser reports that they fixed all the outstanding issues and the bike runs with no problem on their custom dashboard. They are not disclosing the solution because they intend to commercialize the dash.

What this changes for us:

- **Existence proof.** The self-test exchange is reproducible by a third party — the bike's ECU is not doing anything that requires OEM-proprietary keys or signed firmware on the dash side. Whatever it expects is something a custom MCU can emit on the wire.
- **Risk model shifts** from "this may be unsolvable without OEM cooperation" to "this is hard but proven solvable; budget the time for the discovery phase rather than design around the limitation."
- **Method we likely need.** Since they did it but the broadcast traffic was insufficient, the most likely answer is one of: (a) the dash sends a frame *at the right moment in the boot sequence* that they originally missed because their capture started too late, (b) a UDS / ISO-TP request-response handshake that only shows up if you look for paired request+response IDs, or (c) traffic on a non-CAN bus (K-Line / LIN) that they instrumented separately. Our capture rig should be designed to not rule any of these out.
- **What it does *not* give us.** No technical details — the solution is being kept private. We get encouragement, not shortcuts.

---

## ABS / TC disable: ECU wants 5s of sustained signal; custom dash fakes the hold

- **Source:** <https://www.reddit.com/r/Husqvarna/> — comment by u/dominicht on "[Update 10] Custom Dashboard Project", reply to u/These-Economics-384
- **Date seen:** 2026-07-24 (comment marked "3 mo. ago", so written ~2026-04)

Verbatim:

> The ABS and TC can be disabled with this dashboard too, but it needs to wait 5 seconds as well. It's a simple toggle press you don't need to hold. The 5sec is what the ECU expects to turn these off.
>
> Currently, you'd need to disable again at every ignition, but I'll see if there's a way it could be done automatically in a secure and smooth way. I'm not sure turning on the ignition and having to wait 2x5 seconds with a loading animation is the best user experience

### Claims worth treating as hypotheses

1. **The ECU expects 5 seconds of sustained signal to disable ABS or TC.** On the OEM bike the rider provides that by holding the mode button; on the custom dash the rider short-presses and the dash itself sustains the signal for 5s (the "loading animation" the author references is that dwell playing out). This reading matches OEM UX — the stock 401 dash requires a press-and-hold, so the ECU-side requirement is almost certainly unchanged and the custom dash is abstracting the hold.
   - Less-likely alternative: the frame is a single discrete command and the 5s is a post-command ECU timer that the OEM dash coincidentally masks behind the hold. Possible but weaker prior given how the stock dash behaves.
2. **Each system has its own 5s dwell** (hence "2x5 seconds" if disabling both) — ABS and TC are separately gated, not a single combined command.
3. **Disable does not persist across ignition cycles** — the ECU re-enables both on every key-on, so whatever the dash sends must be re-issued each time.
4. **Author suggests auto-re-disable on key-on is achievable** ("if there's a way it could be done automatically in a secure and smooth way"), implying no cryptographic / rolling-code gate — the barrier is UX, not authentication.

### Why this matters for us

Directly relevant to `docs/research.md` open question **#2 — "Does the ECU expect messages from the dashboard?"**: yes, at least for rider-initiated mode changes like ABS/TC disable. Adds a second confirmed dash→ECU exchange beyond the boot self-test.

Also constrains a future TX ADR: if we ever transmit an ABS/TC disable, we likely need to *sustain* the disable frame(s) for the full 5s window rather than fire-and-forget. Verify frame period and total dwell against the OEM dash before authorizing any TX.

### What this does *not* tell us

- The CAN ID(s) or byte layout of whatever the dash sends.
- Whether the sustained signal is a repeating frame at some period or a single frame with a "button held" bit set for the duration.
- Whether ABS-off and TC-off are separate messages or a shared "rider mode" message with bits per system.
- What happens if the disable is sent before the boot self-test completes.

### Verification plan when we get there

Capture OEM dash traffic across a key-on → hold-mode-button-to-disable-ABS (or TC) sequence. Look for a frame or bit that stays asserted from press-start until the ECU acknowledges (dash lamp changes). Diff against a baseline where the rider doesn't touch the mode button. Repeat with ignition cycled to confirm the re-enable behavior. Cross-reference any candidate IDs against blalor's KTM 690 decoder and our own findings index.

### 2026-07-24 update — partially verified against our 401

Ran the capture. Findings in [[signal-ride-mode]]. Reconciliation vs the claims above:

1. **"Sustained signal" claim — partially reinterpreted.** On our 401, no *separate* "button held" bit fires during the 3 s SET-hold. The "sustained signal" the ECU wants is the *state bit itself persisting at its new value*: cluster (or ABS ECU) publishes `12A` D2 b1 / `450` D4 b7 at 50 ms period, and once the new value has been on the bus long enough (~3 s on the 401, matching the manual's 3–5 s), the ABS ECU commits. The commenter's "5 s dwell" likely refers to the same mechanism on their bike, just with a longer gate.
2. **"Each system has its own dwell" — untested here.** We only exercised ABS mode. TC on the 401 would need its own capture.
3. **"Does not persist across ignition cycles" — untested here.** Would fall out of a key-cycle capture with the bike left in SUPERMOTO before key-off.
4. **"No cryptographic gate" — supported by our data.** The two mirror bits are plain state broadcasts, no rolling counter or checksum-of-checksum protecting them. A replacement dash spoofing `450` D4 b7 = 1 for ≥ 3 s ought to work — pending the TX-probe experiment (deferred, needs an ADR).

The **CAN ID / byte layout** question the original plan couldn't answer is now answered: `12A` D2 b1 primary, `450` D4 b7 mirror. Direction between them (which module is the command publisher and which is the confirming mirror) is still open — see [[signal-ride-mode]] Open.
