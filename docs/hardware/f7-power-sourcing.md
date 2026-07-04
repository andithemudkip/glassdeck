# F7 power path — Romanian sourcing

## Order placed

**From [optimusdigital.ro](https://www.optimusdigital.ro):**
- [LM2596 buck, fixed 5V (pre-set)](https://www.optimusdigital.ro/ro/surse-coboratoare-de-5-v/13597-sursa-coboratoare-de-tensiune-lm2596-cu-iesire-fixa-de-5v.html) × 2 — one for the F7 adapter, one earmarked for the dashboard-side build ([ADR 0014](../decisions/0014-dashboard-bridge-firmware.md))
- [Zener diode kit, 10 types × 200 pcs](https://www.optimusdigital.ro/ro/kituri/5397-kit-diode-zener-10-tipuri-200-buc.html) × 1 — for the 1N4734A
- [24 AWG silicone wire kit, 6 colours × 9 m](https://www.optimusdigital.ro/ro/kituri/11950-set-de-fire-siliconice-24awg-6-culori-9m-fiecare-0721248989734.html) × 1 — 22 AWG was out of stock; 24 AWG silicone is acceptable substitute (carries 200 mA load trivially, silicone insulation gives the vibration tolerance)
- [470 µF / 50 V electrolytic](https://www.optimusdigital.ro/ro/componente-electronice-condensatoare/3008-condensator-electrolitic-de-470-uf-la-50-v.html) × 10 — primary + generous spares (electrolytic is the part most likely to need swap over the life of the build)
- 60 V / 10 A reverse-polarity protection module (2× SS56 Schottky in parallel), Optimus SKU 0104110000087508 × 3 — primary + two spares (one earmarked for the dashboard-side build). Replaces the planned 1N5819 axial: strict upgrade on reverse-voltage rating (60 V vs 40 V), lower Vf at the operating current (~200 mA split across two 5 A parts sits at ~0.2 V vs ~0.3 V for a lone 1N5819), and board-mounted form factor eliminates SMD soldering.

**From [emag.ro](https://www.emag.ro):** *(completed)*
- [Glass fuse kit 5×20 mm, 100 pcs (0.2 A–20 A) + 10 inline holders](https://www.emag.ro/set-sigurante-rapide-5x20mm-100-bucati-0-2a-20a-cu-10-suporturi-pentru-sigurante-qb-167/pd/D9V7183BM/) × 1

**Dropped from plan: Conexelectronic order.** The SS56 protection module (from Optimus) replaces the 1N5819 axial that was the primary reason for the Conex run. The 470 µF cap is now sourced from Optimus. Perfboard is already on hand. Net: three planned orders collapsed to two, one shipping fee saved, and no SMD soldering needed for the diode.

**Not in any cart (assumed already on hand or to be sourced separately):** soldering iron + solder, multimeter, wire strippers, heatshrink (verify inclusion in the 24 AWG wire kit — Plusivo 22 AWG kit includes it, 24 AWG variant may not), crimp connectors or solder splices for extending the existing 3-wire bike pigtail with the F7 line, perfboard.

*Hot glue / nail polish for buck pot locking is no longer needed — the fixed-output LM2596 has no user-adjustable pot.*

---



Direct product links for the [f7-power.md](f7-power.md) build, sourced from Romanian hobby shops (sigmanortec, optimusdigital, cleste, ardushop) in that order of preference. Where none of the four carries a part, an RO-friendly alternative is noted.

Prices are RON, recorded at sourcing time — treat as ballpark.

## Required parts

| Part | Shop | Link | Price | Notes |
|------|------|------|-------|-------|
| LM2596 adjustable buck | sigmanortec | [LM2596 4.5–40 V, 3 A](https://sigmanortec.ro/en/adjustable-step-down-module-lm2596-dc-dc-45-40v-3a) | ~8 | Classic blue module, 25-turn output trimmer. Backup: [optimusdigital](https://www.optimusdigital.ro/ro/surse-coboratoare-reglabile/150-modul-dc-dc-step-down-lm2596-albastru.html). |
| 1N5819 Schottky | sigmanortec | [SS14 SMD (1N5819 equivalent)](https://sigmanortec.ro/en/schottky-diode-1n5819-smd-ss14-40v) | 0.30 | **SMD only** — no DO-41 axial at any of the four shops. SS14 is the explicit substitute called out in the BOM. Backup: [ardushop](https://ardushop.ro/en/diode-smd/819-dioda-schottky-1n5819-smd-ss14-40v-6427854010667.html). Order TME.ro if you really need axial. |
| 470 µF / 50 V electrolytic | optimusdigital | [470 µF / 50 V radial](https://www.optimusdigital.ro/ro/componente-electronice-condensatoare/3008-condensator-electrolitic-de-470-uf-la-50-v.html) | ~1–2 | 63 V / 470 µF isn't stocked locally. 50 V meets the BOM's ≥50 V floor; headroom shrinks but is still adequate for a switched-12V automotive rail (peaks well under 50 V in normal operation, and a sustained over-voltage event blows the fuse before the cap is the limiting factor). |
| 500 mA (or 1 A) fuse + inline holder | Emag | [Glass 5×20 mm assortment, 100 fuses (0.2 A–20 A) + 10 inline holders](https://www.emag.ro/set-sigurante-rapide-5x20mm-100-bucati-0-2a-20a-cu-10-suporturi-pentru-sigurante-qb-167/pd/D9V7183BM/) | ~20 | Deviates from the BOM's ATO-mini-blade spec — none of the RO hobby shops stock 500 mA mini blades, they start at 2 A. Glass 5×20 is electrically equivalent and the assortment covers 0.5 A (primary) and 1 A (fallback if 0.5 A nuisance-trips). **Mount inside the enclosure** — glass is more vibration-fragile than blade in free air, fine when secured. Pure-blade alternatives in § Sourcing gaps. |
| Perfboard | optimusdigital | [50×70 mm, double-sided, plated through-holes](https://www.optimusdigital.ro/ro/prototipare-cablaje-de-test/723-placa-de-test-universala-verde-50x70-mm.html) | ~5 | Cut down to ~30×40 mm. Backup: [cleste 5×7](https://cleste.ro/placa-prototipare-5x7.html). |
| 22 AWG silicone hookup wire | optimusdigital | [Plusivo 22 AWG, 6 colours × 7 m + heatshrink](https://www.optimusdigital.ro/ro/kituri/9514-set-de-fire-siliconice-22awg-6-culori-7m-fiecare.html) | ~40 | Kit covers the full adapter build plus future projects. |

## Optional parts

| Part | Shop | Link | Price | Notes |
|------|------|------|-------|-------|
| 1N4734A 5.6 V / 1 W Zener | optimusdigital | [Zener kit, 10 values × 200 pcs](https://www.optimusdigital.ro/ro/kituri/5397-kit-diode-zener-10-tipuri-200-buc.html) | ~25 | Standalone DZ 5V6 is listed (~0.49 RON) but flagged out of stock; the kit reliably covers the 5.6 V value. Useful to have the assortment around regardless. |
| SPDT switch | sigmanortec | [MTS-102 mini SPDT toggle](https://sigmanortec.ro/en/switch-3a-250v-switch-mts-102) | ~3–4 | True slide form factor isn't stocked at the four. Toggle is functionally identical for the USB/F7 selector use case. If a slide is strongly preferred: [electronicmarket.ro mini SPDT slide](https://electronicmarket.ro/mini-spdt-slide-switch-on-on-3-pini). |
| P-channel MOSFET | optimusdigital | [IRFP9140N (P-channel, 100 V, 21 A, TO-247)](https://www.optimusdigital.ro/ro/componente-electronice-tranzistoare/11858-tranzistor-mosfet-irfp9140n-canal-p-20w-100v-21a.html) | 9.99 | TO-247, slightly bigger than the TO-220 the BOM names. Pin-compatible for hand-wired use. Vgs(th) is non-logic-level but irrelevant here — the gate sits at GND, driven by the 12 V rail. None of the four shops carry a true low-Vgs(th) P-FET (AO3401, IRLML6402) — order from TME.ro if needed. |

## Sourcing gaps

### Blade-form fuse holder (if glass isn't acceptable)

The Emag glass-fuse kit in the required-parts table is the picked path. If you'd rather stay with the BOM's original ATO-mini-blade spec (e.g. don't want glass inside the build, or want a fuse you can swap without opening the enclosure):

- [frize.ro — 19×13 mm ATO holder on 16 AWG pigtail](https://frize.ro/products/suport-siguranta-auto-19x13mm-pe-fir) — closest to the original BOM spec. Pair with a mini blade fuse from any auto-parts shop or Emag.
- roelectro.ro, leoauto.ro, cel.ro, or Emag also stock these — search "suport siguranță auto pe fir".

**Heads up on blade fuse ratings:** Romanian retailers don't reliably stock 500 mA or 1 A mini blade fuses — assortments typically start at 2 A. A 2 A fast-blow still trips on a hard short (the safety-critical scenario) and tolerates the ~200 mA normal load with margin; just gives up protection against slow partial faults. Acceptable tradeoff for a DIY build if blade is preferred over glass.

### Axial 1N5819 (DO-41)

Not available at the four. The SS14 SMD substitute is in spec per the BOM and solders to perfboard fine with short jumper wires. TME.ro if axial is mandatory. **Conexelectronic.ro also stocks the genuine DO-41 axial part** — see the single-source bundle section below.

### True low-Vgs(th) P-channel MOSFET

Not available at the four. The IRFP9140N listed above works for the F7 reverse-polarity use case because gate drive is the 12 V rail, not a 3.3 V GPIO. If a logic-level P-FET is needed for a future build (e.g. switching from an ESP GPIO), order AO3401 or IRLML6402 from TME.ro.

## Alternative: single-source bundle from conexelectronic.ro

Conexelectronic.ro is a serious electronics distributor (not a hobby-Arduino shop) that stocks named-brand parts (Panasonic, Nichicon caps; real DO-41 axial diodes). The whole build can plausibly come from a single cart there — fewer shipping fees, named-brand components, and the through-hole 1N5819 you'd otherwise have to substitute.

The tradeoff: hobby modules like the LM2596 board cost more here (~23 lei vs ~8 lei at sigmanortec) because the SKU comes with extras like a voltage display. For a single-shipping bundle the premium is usually less than the second shipping fee.

| Part | Link | Notes |
|------|------|-------|
| 1N5819 Schottky, DO-41 axial | [link](https://www.conexelectronic.ro/diode-schottky/14018-1N5819-40V-1A.html) | ~2 lei. Real through-hole part, no SMD soldering needed. Order 2–3 for spares. |
| LM2596 buck module (4–40 V in, 1.25–37 V out, 3 A, with display) | [link](https://www.conexelectronic.ro/ro/surse-de-alimentare/16394-MODUL-STEP-DOWN-DC-DC-4-40V-IN-1-25V-37V-OUT-CU-DISPLAY.html) | ~23 lei. Display is unnecessary feature; functionally identical to the sigmanortec ~8 lei module. |
| 470 µF / 50 V / 105°C low-ESR electrolytic (13×25 mm, 5 mm pitch) | [link](https://www.conexelectronic.ro/condensatori-electrolitici/9843-470-MF-50-V-105-GRD-13X25-MM-RM5-LOW.html) | Picked: 105°C rating is a meaningful lifetime upgrade for an automotive install vs the 85°C alternative, and low-ESR is the right characteristic for a switching-regulator input. 50 V is within BOM spec (≥50 V required); the missing headroom vs 63 V is a non-issue since any transient over 50 V also exceeds the LM2596's 40 V abs-max input. Alternative if this is out of stock: [470 µF / 63 V / 85°C Jamicon](https://www.conexelectronic.ro/condensatori-electrolitici/4798-470-MF-63-V-85-GRD-JAMICON.html). |
| Fuse assortment set (100 pcs, 5×20 mm, 0.2–20 A) | [link](https://www.conexelectronic.ro/sigurante-fuzibile/23372-SET-100-SIGURANTE-5X20MM-5949203911193.html) | Equivalent to the Emag pick. Confirm fast-blow vs slow-blow on the product page before ordering — want fast-blow ("rapide") for this build. |
| Glass fuse 1 A 5×20 fast-blow (single) | [link](https://www.conexelectronic.ro/sigurante-fuzibile/11318-SIGURANTA-RAPIDA-1A-5X20-MM.html) | Buy this if you don't need the whole assortment. Note: 0.5 A only appears as "temporizată" (slow-blow) at conex — fast-blow 0.5 A would need to come from the assortment kit or Emag. |
| Inline fuse holder 5×20 on wire (PTF80A) | [link](https://www.conexelectronic.ro/suporti-sigurante/2505-SUPORT-SIGURANTA-PE-FIR-5X20MM-PTF80A.html) | 0.3 m cable, nickel-plated brass contacts. Alternative without "PTF80A" branding: [link](https://www.conexelectronic.ro/suporti-sigurante/17745-SUPORT-SIGURANTA-PE-FIR-5X20-MM.html). |
| Perfboard 50×100 mm | [link](https://www.conexelectronic.ro/accesorii-pentru-cablaje-imprimate/14117-PLACA-TEST-50X100-PASTILE-PATRATE.html) | Single-sided, square pads, 1.5 mm paper substrate. Cut to size as needed. |
| BZX55C5V6 Zener (5.6 V, **0.5 W**, DO-35) | [link](https://www.conexelectronic.ro/235-diode-zener) | 1 leu. Browse the category page — direct product URL not stable. **Under BOM spec** (BOM calls for 1 W); acceptable substitute because the crowbar use case is a few-ms transient before the fuse blows, and 0.5 W parts typically fail short anyway (which is what the crowbar wants). If you want true 1 W spec, use the [optimusdigital 200-piece zener kit](https://www.optimusdigital.ro/ro/kituri/5397-kit-diode-zener-10-tipuri-200-buc.html) instead — small separate order. Optional part either way. |

**Not at conexelectronic (still need to source separately if going single-shipping):**
- 22 AWG silicone hookup wire kit — keep the [optimusdigital Plusivo kit](https://www.optimusdigital.ro/ro/kituri/9514-set-de-fire-siliconice-22awg-6-culori-7m-fiecare.html).

## Notes for the next BOM revision

While compiling this list, two things surfaced that the BOM in [bom.md](bom.md) and [f7-power.md](f7-power.md) might want to reflect:

- **50 V is the realistic local stock for the bulk cap.** The 63 V spec is preferred-but-not-available at RO hobby shops. The build doc says ≥50 V is required and that has been honoured; the picking guidance could note this explicitly so a future build doesn't waste time hunting for 63 V.
- **The Schottky is SMD in practice.** Axial 1N5819 isn't sourceable from the four; SS14 SMD is the working substitute. Already listed as an acceptable equivalent in the BOM — just worth flagging that it's the *only* RO-available option, not a fallback.
- **Optimus stocks a board-mounted reverse-polarity module (2× SS56 in parallel, 60 V / 10 A, SKU 0104110000087508) that is a strict upgrade over the 1N5819 for this build.** Higher reverse-voltage rating, lower Vf at the operating current (paralleled diodes share load), and no SMD soldering required (through-hole pads on the module). Worth naming as the primary Schottky pick in the BOM for future revisions, with the axial 1N5819 / SS14 falling back to the "alternative" column.
