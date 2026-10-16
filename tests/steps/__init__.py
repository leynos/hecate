"""pytest-bdd steps and the fixture authoring they drive.

The step definitions read as prose over a small vocabulary of fixtures; the
fixtures themselves are data tables in `fixture_setup`, which is a package
sibling so the steps can import it without depending on how pytest arranges
`sys.path`.
"""
