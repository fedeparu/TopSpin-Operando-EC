# TopSpin-style companion window

The viewer now uses a desktop workbench shell rather than a dashboard layout.
The existing linked EC/NMR renderer, recorded data and timing assumptions remain
shared by the local service and downloadable standalone HTML.

The visual reference is the data browser, grouped display tools, dataset tabs and
command-line workflow shown in Bruker's [TopSpin application examples](https://www.bruker.com/it/products-and-solutions/mr/nmr-software/fragment-based-screening/_jcr_content/root/contentpar/linklist/contentpar-1/calltoaction.download-asset.pdf/links/item4/Bruker-Fragment-Based-Screening-Analysis-Suite.pdf).
Bruker's [TopSpin product page](https://www.bruker.com/en/products-and-solutions/magnetic-resonance/nmr-software/topspin.html)
also describes customizable displays and linked cursors. This implementation
uses original HTML/CSS/icons; no vendor assets or proprietary GUI code are bundled.

## Workbench controls

- **Data browser:** shows the EC quantities and available NMR acquisitions.
  Filter by acquisition number/name, then select a row to lock that spectrum.
  EXPNO/PROCNO, nucleus, scan count and processed point count come from the data.
- **Display ribbon:** peak region, full ppm range, reset, pan and box zoom operate
  on the existing linked plots. Integrate opens the secondary peak analysis.
- **Workspace tabs:** EC–NMR shows the linked experiment; 1D spectrum focuses
  the selected full-resolution trace. Parameters opens the data/timing settings.
- **Menus:** File, View, Display, Analysis, Window and Help invoke the same
  controls, without placeholder processing/acquisition actions.
- **Status strip:** shows the current acquisition, lock state and actual
  offline/replay status. It does not claim a connected spectrometer.

The window is sized so the main linked view and 1D detail are visible together
on a desktop. The browser can be collapsed; on narrow screens it opens as an
overlay. Maximize removes the surrounding application margin.

## Commands and shortcuts

The command line accepts viewer commands only:

```text
stack       contour       map
peak        full          reset
spectrum 12               gain 1.2
lock        unlock        pan        zoom
linked      detail        browser    help
```

`/` focuses the command line; Up/Down browse its history. `1` and `2` select the
linked or focused-1D workspace when not typing into a form. Home resets display
ranges; Ctrl+S/Cmd+S saves analysis; F1 opens Help. Bruker processing/acquisition
commands are not executed by this command line.

## Separate pop-out window

**Pop out** opens a separate browser companion window from a user click. The
standalone HTML passes the current measurements and analysis settings into the
new window without a server or external asset requests. The new window is an
offline snapshot; it does not launch a second acquisition/replay clock. A browser
that blocks pop-ups must allow the user-initiated window for this control.

This is still an external companion with a TopSpin-style interface. Native
TopSpin embedding and instrument control remain unimplemented/unverified as
described in [instrument integration](INSTRUMENT_INTEGRATION.md).
