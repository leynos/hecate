"""Contracts keeping the Makefile, CI, and detector pin in agreement.

The pin for the ``nose`` duplication detector is written in three places that
nothing at runtime compares: the Makefile installs it, the CI workflow
installs it again through ``cargo-binstall``, and the gate verifies the
installed binary against ``[tool.nose]``. A drift between any two of those
produces a gate that passes locally and fails in CI, or reuses a detector
version the gate then refuses.

The readers here extract those pins, and the provisioning facts underneath
them, as plain text. The rule tests in ``test_toolchain_pins.py`` and
``test_provisioning.py`` apply the readers to the real files; the cases in
``test_readers.py`` apply them to text this repository does not contain, so a
reader that only happens to work on the current spelling is caught.
"""
