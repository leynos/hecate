"""Behavioural test steps for the architecture-check CLI.

The package exists so the step module can import the fixture definitions
beside it by name. Everything here drives the real CLI: the steps declare
what a scenario does, and ``architecture_fixtures`` declares what a
scenario is -- the package tree, the import under test, and the policy
that judges it.
"""
