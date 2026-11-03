# Inspection of the two supplied archives

Verified with the actual supplied files. Raw archives, extracted experiments,
normalized sessions and any private-data browser artifacts are excluded from Git.
This report records structural/scientific findings, not experimental traces.

## Archive contents

`4 Testdata.zip`: 45 entries, 21,938,237 compressed bytes,
35,818,212 total uncompressed bytes. Internal structure:

```text
4/
  acqu, acqus, acqu2, acqu2s          acquisition parameters
  ser                              33,554,432-byte raw pseudo-2D data
  audita.txt                       acquisition audit trail
  adcInfo_TRX3.xml, scon2           acquisition configuration
  format.ased, format.temp
  lists/
    form/plot_acqu.form
    pp/ATM_zg_2D, Avance.incl       pulse program and include
  pdata/
    1/
      2rr, 2ii                    each 1,048,576 bytes
      proc, procs, proc2, proc2s   processing parameters
      title, auditp.txt
      assocs, clevels, curdat2, outd, thumb.png
    999/
      1r, 1i                      each 16,384 bytes
      proc, procs, used_from, auditp.txt, outd
  shimvalues, specpar, uxnmr.info, uxnmr.par, vtc_pid_settings
```

`NMC EC data for NMR.zip`: four entries, 1,432,943 compressed bytes,
4,900,356 total uncompressed bytes:

```text
NMC NMR/
  NMC811 vs Graphite 02.07.2025.mps               3,722 bytes
  NMC811 vs Graphite 02.07.2025_C01.mpr           4,896,394 bytes
  NMC811 vs Graphite 02.07.2025_DUSB-4025_C01.sta    240 bytes
```

There is **no `.mpt` export**. `.mps` is a text protocol; `.mpr` is the completed
binary measurement; `.sta` is an ancillary binary status file, not interpreted
as scientific measurement data.

## Bruker acquisition and processing

- Audit identifies **TopSpin 4.5.0**, an Avance 400 WB acquisition, and a genuine
  **pseudo-2D** series (`ATM_zg_2D`, also explicitly named in the title).
- Observed nucleus: **7Li**; acquisition `SFO1 = 155.6378883633 MHz`;
  `SW_h = 250000 Hz`; direct `TD = 65536`, indirect `TD = 64`;
  `NS = 1024`, `DS = 2`, `D[1] = 1 s`, `P[1] = 3 µs`.
- Raw `ser` uses `DTYPA = 2`, `BYTORDA = 0`: little-endian float64;
  its size agrees with 64 × 65536 × 8 bytes. Raw FIDs are preserved and are not
  reprocessed by this prototype.
- Processed `pdata/1/2rr` is **64 × 4096** little-endian int32,
  `XDIM = (64, 4096)` and `NC_proc = 6`. Displayed intensities are stored
  integers multiplied by **64**, matching nmrglue's documented TopSpin scaling.
- Direct chemical shift uses **processing** `SF = 155.591211 MHz`,
  `SW_p = 250000 Hz`, `OFFSET = 1103.38728130348 ppm`, `SI = 4096`.
  Axis: `OFFSET - i × SW_p / (SF × SI)`, decreasing from approximately
  1103.3873 to −502.9950 ppm. Acquisition SFO1 is not substituted for processing SF.
- `pdata/999/1r` is an extracted row from the main series. `used_from`/`auditp`
  identify **row 51** and the complete 4096-point intensity vector is identical
  to row 51 of `2rr`, including scaling. It is **not a 65th acquisition**.
  Loading the experiment chooses the main matrix; explicitly loading procno 999
  opens the extracted 1D result with unknown row acquisition time.

Acquisition timing is supported by both epochs and audit records:

| Quantity | Value |
|---|---|
| `DATE_START = 1751447391` | 2025-07-02 09:09:51 UTC |
| `DATE = 1751521788` | 2025-07-03 05:49:48 UTC |
| Total acquisition interval | 74,397 seconds (20 h 39 min 57 s) |
| Final processed matrix audit | 2025-08-15 11:24:06 +02:00 |
| Extracted row processing audit | 2025-10-06 10:32:16 +02:00 |

Processing and ZIP modification timestamps reflect later copies/reprocessing;
they are not acquisition timestamps. Most ZIP acquisition-file times are
2025-08-15; ZIP folder times also include September/October 2025. `DATE_START`
is rounded to integer seconds; the audit contains finer clock resolution but
does not establish synchronization accuracy with another instrument.

**No per-row timestamps are supplied.** The pulse program inserts automatic
tune/match between rows, so dividing total duration by 64 would manufacture
uniform timing. Import leaves every matrix row's `time_s` and `duration_s` null.
The viewer requires explicit operator-supplied timing assumptions before linking
them to EC. A manual uniform cadence is an analysis assumption and is recorded
as such, with offset/uncertainty. True 2D spectra without explicit pseudo-2D
identification are rejected rather than treated as time series.

## Electrochemical measurement

- Read with **galvani 0.5.0**, a third-party completed-file MPR reader. This is
  not a vendor live-data API, and no concurrent binary-file reading is claimed.
- **98,790 points**; `time/s` from 0 to **186,964.6980535169 s**
  (51 h 56 min 4.698 s), nondecreasing.
- Voltage is exported `Ewe/V`, approximately **2.4974334–4.5422616 V**.
- Exported fields include `Ns`, `dq/mA.h`, `(Q-Qo)/mA.h`,
  `control/V/mA`, `I Range`, `Q charge/discharge/mA.h`, `half cycle`, and flags.
- **There is no measured `I/mA` field.** The mixed-unit `control/V/mA` field
  switches meaning with control mode and is never relabelled as measured current.
  Current shown by the viewer is the **interval average** reconstructed as
  `3600 × dq[i] / (time[i] - time[i-1])` mA. First/zero-duration values are null.
  This is not an instantaneous current measurement and is labelled in metadata.
- Capacity shown is the exported **signed cumulative charge `(Q-Qo)/mA.h`**;
  its last value is approximately **0.924961603 mAh**. It is neither a
  mass-normalized capacity nor a per-cycle discharge capacity. Exported
  charge/discharge and half-cycle fields are preserved in metadata.
- Protocol reports **SP-150e**, EC-Lab **11.50**, GCPL with nominal ±0.200 mA,
  voltage limits 4.3/2.5 V and current/voltage recording conditions. Settings
  are context, never executed. The observed voltage maximum exceeds the nominal
  4.3 V setting; the importer preserves the measurement without clipping it.
- Protocol filenames/sample descriptions contain inconsistent copied context;
  filenames are not trusted as acquisition timestamps or chemical identification.

The MPR settings-module date is **2024-05-31**; LOG end date is **2024-06-02**;
LOG OLE timestamp is **2024-05-31 04:54:03.166**, with **no timezone supplied**.
ZIP member timestamps are 2024-06-02 (`.mps`, `.sta`) and 2024-07-28 (`.mpr`);
the containing folder ZIP timestamp is November 2026. These do not agree with the
filename's July 2025 label or with the NMR epoch/audit acquisition interval.

## Synchronization conclusion

The archives cannot establish a measured common timeline. The viewer must show
both datasets but **must not claim automatic synchronization**. Their dates
differ by over a year, the EC timezone is unknown, and NMR row timing is absent.
Only an operator-confirmed manual alignment (with cadence/offset, uncertainty,
and an explanatory note), or external timestamp evidence, can support linked
analysis. Demonstrations using assumed alignment must retain that label.

## Verification

`tests/test_importers.py` checks synthetic MPT decimal commas, units, signed
charge integration, current reconstruction, rejection of incomplete/reset-time
files, Bruker big-endian data, positive/negative scaling, tiled matrices,
chemical-shift axes, rejection of true 2D, and processing-variant deduplication.

With `ECNMR_REAL_DATA` pointing at the extracted uploads, two additional tests
verify the real point count/ranges/timestamp, reconstructed current, capacity,
64 × 4096 shape, complete binary-versus-imported scaling, ppm calibration,
unknown row timing, and exact extracted-row-51 identity. Raw data are never
copied into test fixtures or committed.
