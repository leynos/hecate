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
