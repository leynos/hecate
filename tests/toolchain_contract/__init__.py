"""Contracts keeping the CI tool caches in agreement with their pins.

The readers here extract the CI cache steps as plain text. The rule tests in
``test_provisioning.py`` apply them to the real workflow; the cases in
``test_readers.py`` apply them to text this repository does not contain, so a
reader that only happens to work on the current spelling is caught.
"""
