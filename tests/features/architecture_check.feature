Feature: Hexagonal architecture checking

  Scenario Outline: Fixture package architecture result
    Given the "<fixture>" fixture package
    When I run Hecate against the fixture
    Then the exit code is "<exit_code>"
    And the diagnostics contain "<diagnostic>"

    Examples:
      | fixture                                      | exit_code | diagnostic                      |
      | clean_package                                | 0         | architecture check passed       |
      | domain_imports_adapter                       | 1         | sample.domain.model             |
      | application_imports_adapter                  | 1         | sample.application.service      |
      | application_imports_domain_port              | 0         | architecture check passed       |
      | composition_root_wires_adapters              | 0         | architecture check passed       |
      | inbound_cli_imports_config                   | 0         | architecture check passed       |
      | inbound_cli_imports_outbound_adapter         | 1         | sample.cli                      |
      | application_imports_reexported_adapter       | 1         | sample.adapters.outbound.db     |
      | application_imports_star_reexported_adapter  | 1         | sample.adapters.outbound.db     |
      | domain_imports_external_infrastructure       | 1         | sqlalchemy                      |
      | application_imports_all_hidden_adapter       | 1         | sample.adapters.outbound.db     |
      | application_imports_wildcard_consumer        | 1         | sample.adapters.outbound.db     |
      | application_imports_relative_barrel_adapter  | 1         | sample.adapters.outbound.db     |
      | application_imports_unclassified_subtree     | 0         | architecture check passed       |

  Scenario: An unclassified internal subtree is surfaced, not silently skipped
    Given the "application_imports_unclassified_subtree" fixture package
    When I run Hecate against the fixture with JSON output
    Then the exit code is "0"
    And the coverage report contains "unclassified"

  Scenario: Strict mode fails a check that a non-strict run passes
    Given the "application_imports_unclassified_subtree" fixture package
    When I run Hecate against the fixture in strict mode
    Then the exit code is "1"
    And the diagnostics contain "unclassified"

  Scenario: Strict mode fails an unresolved internal import
    Given the "application_imports_unresolved_symbol" fixture package
    When I run Hecate against the fixture in strict mode
    Then the exit code is "1"
    And the diagnostics contain "unresolved"

  Scenario: A wildcard over an empty __all__ binds no symbols to its consumer
    Given the "application_imports_empty_all_wildcard" fixture package
    When I run Hecate against the fixture
    Then the exit code is "1"
    And the diagnostics contain "sample.adapters"
    And the diagnostics omit "sample.adapters.outbound"

  Scenario: Custom TOML config is loaded from pyproject
    Given the "clean_package" fixture package
    When I run Hecate with default config discovery
    Then the exit code is "0"
    And the diagnostics contain "architecture check passed"

  Scenario: Explicit config overrides default discovery
    Given the "domain_imports_adapter" fixture package
    And an override config that permits every fixture group
    When I run Hecate with the override config
    Then the exit code is "0"
    And the diagnostics contain "architecture check passed"

  Scenario: Invalid config exits with code 2
    Given an invalid Hecate config
    When I run Hecate against the fixture
    Then the exit code is "2"
    And stderr contains "undeclared groups"
