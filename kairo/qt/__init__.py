"""The Qt frontend.

A second frontend over the same backend, not a fork of it. Everything under
``kairo/`` outside this package is untouched and shared: providers, artwork
sources, the ledger, migration, adoption, matching, the launcher writers and
their tests behave identically whichever shell is running.

Two things Qt gives that Tk could not. Per-pixel alpha, so a translucent panel
can carry fully opaque text - Tk offers only whole-window opacity. And a real
surface handle, which is what lets the compositor be asked for blur.
"""
