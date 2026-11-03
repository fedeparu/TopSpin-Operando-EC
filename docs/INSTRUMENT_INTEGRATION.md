# Instrument integration and validation

The delivered application runs Offline and Simulation without TopSpin, EC-Lab,
Windows COM or an instrument. Real acquisition is **disabled**, including when
connection settings and operator authorization have been supplied. The real
adapter classes are explicit integration boundaries, not operational drivers.

## Evidence reviewed on 3 November 2026

The following official pages were retrieved through the web research tool. The
execution environment's shell network policy denied these vendor domains; that
restriction did not prevent reviewing their public documentation.

| Official source | Verified capability | Limit of evidence |
| --- | --- | --- |
| [Bruker TopSpin Python interface](https://www.bruker.com/en/products-and-solutions/mr/nmr-software/topspin/topspin-python-interface.html) | An external Python 3.9+ interface can execute TopSpin commands and access parameters and 1D/2D data through TopSpin's embedded web service. TopSpin 4.3 on Windows includes Python 3.10. Jython 2.7 remains supported. | Installed version, package names, connection setup, acquisition-status methods and concurrent acquisition behavior require the installed API manual and tests. The page does not establish a native browser-panel embedding API. |
| [BioLogic integration packages](https://www.biologic.net/softwares/ec-lab-oem-development-package/) | OEM and SDK packages provide instrument/channel control and experimental data retrieval. The current table differentiates board families and operating systems; OEM covers Essential SP-series hardware in principle. | Exact SP-150e serial/board/firmware compatibility and developer-package version must be confirmed by BioLogic. Public descriptions do not supply enough detail to implement and validate a driver. |
| [BioLogic OLE-COM](https://www.biologic.net/softwares/ole-com-for-ec-lab/) | Remote execution of preset EC-Lab protocols is documented. OLE-COM mode must be activated within EC-Lab. | This page does not establish continuous numerical measurement access, exact ProgID/method signatures, bitness constraints or reconnection semantics. No guessed COM calls are shipped. |
| [BioLogic external-device synchronization](https://www.biologic.net/topics/ec-lab-solutions-for-coupling-with-external-devices/) | EC-Lab has external-device techniques and trigger input/output for coupling instruments. | Specific Bruker trigger ports, wiring, isolation, polarity, pulse width and electrical compatibility require both instrument manuals and laboratory approval. No wiring prescription is supplied. |

The BioLogic external-device article was marked updated 28 September 2026 when
reviewed. Website descriptions are capability evidence, not proof that a
particular installed instrument is compatible.

## Selected architecture

Use a local external Python service and browser viewer launched from TopSpin.
This avoids depending on an undocumented embedded HTML panel. Offline Bruker
reading is independent of the TopSpin acquisition API. The same experiment model
and charts display offline and progressively arriving simulated measurements.

For real experiments, prefer OLE-COM for running an existing approved EC-Lab
protocol **if the installed API confirms the required operations**. Validate
numerical live data access separately. If OLE-COM does not expose it, use a
vendor-supported OEM/SDK retrieval path only after compatibility testing. Do not
assume an EC-Lab `.mps` protocol can be loaded unchanged by an OEM driver: the
public OEM workflow describes constructing technique parameter structures.

Do not repeatedly open an actively written binary `.mpr`. Completed `.mpt`
exports or a supported numerical API are the fallback. If neither is available,
continue running the experiment in vendor software and import completed files
for offline analysis; this is not a validated live-monitoring implementation.

## TopSpin launcher

`topspin/ecnmr_launcher.py` is a Jython user-script integration candidate. It:

1. Obtains TopSpin's conventional `CURDATA()` result.
2. Resolves the current experiment directory from dataset name, experiment number
   and data-root directory.
3. Starts the installed external Python with explicit argv arguments, passes
   `--nmr <current experiment>` and opens the browser.
4. Writes subprocess output to `work/topspin-launch.log`.

The path-resolution helper is tested under Python; invocation inside TopSpin is
**unverified**. Consult the installed TopSpin Jython manual for `CURDATA`, `MSG`,
the user script directory and script command. The script intentionally uses no
acquisition commands, vendor parameter changes or hidden system installation.

After running the Windows assistant, set `ECNMR_HOME` to the repository directory
before launching TopSpin. Set `ECNMR_PYTHON` if the project's `.venv` interpreter
is elsewhere. For example, in a shell used to start TopSpin:

```powershell
$env:ECNMR_HOME = 'C:\Research\TopSpin-Operando-EC'
$env:ECNMR_PYTHON = 'C:\Research\TopSpin-Operando-EC\.venv\Scripts\python.exe'
```

Copy the launcher to the documented **user** script directory, or explicitly ask
the installation assistant to copy it with
`-TopSpinUserScriptDirectory 'C:\your\documented\user\script\directory'`.
The assistant asks before copying and refuses to overwrite a launcher. Invoke
that user script through your installed TopSpin's documented script command. Do
not place it in a proprietary installation directory on a guess. The browser
workflow is also available directly through `scripts\launch_windows.cmd`.

## Conservative completed-spectrum discovery

`CompletedSpectrumWatcher` is a tested integration helper for **processed 1D**
results. It requires:

- `1r` and `procs` with supported integer parameters and a binary length matching
  `SI`, data type and permitted 1D padding;
- a producer-created `ecnmr.complete` marker newer than both files;
- unchanged file signatures across at least two polls.

An installed vendor-side acquisition/processing integration must write the
marker only after successful completion. File stability alone cannot establish
that an acquisition or processing operation succeeded. The helper never invokes
processing or interrupts acquisition. It emits each completed version once and
allows a later complete version to be discovered. It is not wired to instrument
control in this release. Live pseudo2D incremental row publication remains
unsupported until the producer can certify each row's completion and timestamps.

## Windows installation and diagnostics

The PowerShell assistant checks Python 3.10–3.13, creates `.venv`, installs project
dependencies and runs `scripts/diagnose.py`. It does not install Python, TopSpin,
EC-Lab, COM servers or vendor DLLs. It requires no administrator privileges.

Diagnostics report possible vendor installation folders, package availability
and matching COM registration names. An exact vendor-documented ProgID can also
be checked with `--ole-progid`. Registry presence is **not** an accessibility
test. Diagnostics intentionally do not instantiate a COM object or connect to a
spectrometer. Follow the EC-Lab version's documented procedure to activate
OLE-COM; never silently register or activate vendor components.

## Required real-instrument acceptance procedure

1. Record Windows, TopSpin, EC-Lab, Python and vendor-package versions, bitness,
   SP-150e serial number, board type and firmware. Obtain the relevant supported
   API manuals, examples and licensing/redistribution permissions from vendors.
2. Confirm a vendor example can connect to the intended channel without starting
   an experiment. Verify status, disconnect/reconnect and error reporting.
3. Use an approved dummy cell and protocol. The operator must approve endpoint,
   channel, protocol and voltage/current limits. Prove stop/abort behavior through
   vendor controls and the laboratory's independent hardware safety procedure.
4. Validate preset protocol start/stop independently from numerical measurement
   retrieval. Compare reported potential, current, step and time against EC-Lab.
   Verify bounded polling, sample deduplication and recovery after disconnection.
5. Validate TopSpin command execution, current-dataset resolution, acquisition
   status, completion, processing, and parameter/data readout against its installed
   examples. Prove that viewing completed data does not interrupt acquisition.
6. Create completion markers only after successful processing. Confirm truncated
   files, processing errors and absent timestamps are excluded and reported.
7. Record EC start time, each NMR acquisition start/end, clock timezone and clock
   offset. Measure software start-command latency and drift. Compare acquisition
   intervals with a common independent time reference. Retain unknown uncertainty
   until it is measured. Sequential starts are not simultaneous hardware triggers.
8. Test loss of one connection, partial writes, restart, duplicate delivery and
   interrupted processing. Preserve existing measurements and flag gaps; never
   backfill invented synchronized samples.
9. If hardware triggering is required, have both vendors approve ports, isolation,
   levels, timing and wiring. Measure timing on approved test equipment before
   connecting experimental samples. Keep trigger events in the experiment log.
10. Only then replace the fail-closed adapter boundary and enable Live mode after
    an operator readiness check. Retain the offline/simulation tests as regression
    coverage. Software stop is not a hardware safety system.
