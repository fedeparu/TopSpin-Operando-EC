# Entirely synthetic examples

Generate standard-format data after installing the application dependencies:

```powershell
python scripts/generate_examples.py
```

This creates `examples/synthetic/synthetic.mpt` and six small Bruker processed 1D
experiments under `examples/synthetic/bruker/`. The generator uses analytic peaks
and a triangular potential; **no uploaded experimental data are copied**.
`PROVENANCE.txt` records the synthetic ground truth. The generated dataset is
small enough to inspect, regenerate and use in tests.

Launch directly from the repository:

```powershell
python -m ecnmr --ec examples/synthetic/synthetic.mpt --nmr examples/synthetic/bruker
```

Or launch the app normally, then use its import controls to upload the EC `.mpt`
and `work/synthetic-bruker.zip`. The ZIP is generated outside the tracked
examples and is ignored by Git. Open processed 1D directories directly through
the CLI; ZIP is convenient for browser uploads.

Ground truth: EC and NMR start together at the synthetic epoch
`2025-01-01T00:00:00Z`. NMR starts at 0, 120, 240, 360, 480 and 600 seconds;
each acquisition lasts 90 seconds. Choose a **manual offset of 0 s** to align
these independently imported files. The MPT's timestamp text is preserved as
text because real MPT exports may have ambiguous date formats/timezones.
No manual cadence is required for these individual 1D acquisitions: their
acquisition epochs are present in `acqus`.
