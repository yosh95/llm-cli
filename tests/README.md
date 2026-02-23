# Test Suite for llm-cli

This directory contains the test suite for the llm-cli project.

## Running Tests

### Install test dependencies

```bash
pip install -e ".[test]"
```

### Run all tests

```bash
pytest
```

Or using the command shortcut:

```bash
llm-test
```

Or directly with Python:

```bash
python -m pytest
```

### Run tests with coverage

```bash
pytest --cov=llm_cli --cov-report=html
```

### Run specific test files

```bash
pytest tests/test_base_client.py
pytest tests/test_pdf_processing.py
```

### Run specific test classes or functions

```bash
pytest tests/test_base_client.py::TestBaseLlmClient
pytest tests/test_base_client.py::TestBaseLlmClient::test_initialization
```

### Run tests with verbose output

```bash
pytest -v
```

### Run tests in parallel (requires pytest-xdist)

```bash
pip install pytest-xdist
pytest -n auto
```

## Test Structure

- `conftest.py`: Shared fixtures and test configuration
- `test_base_client.py`: Tests for BaseLlmClient base class
- `test_pdf_processing.py`: Tests for PDF processing across providers
- `test_providers.py`: Tests for provider-specific implementations

## Test Categories

### Unit Tests
Tests that verify individual components in isolation using mocks.

### Integration Tests
Tests that verify interactions between components (marked with `@pytest.mark.integration`).

## Writing New Tests

1. Create test files with the `test_` prefix
2. Use fixtures from `conftest.py` for common setup
3. Follow the Arrange-Act-Assert pattern
4. Use descriptive test names that explain what is being tested

Example:

```python
def test_feature_does_something(mock_config, temp_file):
    # Arrange
    client = SomeClient(stdout=True)

    # Act
    result = client.some_method(temp_file)

    # Assert
    assert result is not None
    assert result['key'] == expected_value
```

## Mocking API Calls

All API calls are mocked in tests to avoid hitting real APIs. Use the fixtures from `conftest.py`:

- `mock_config`: Mocks configuration loading
- `mock_requests_success`: Mocks successful HTTP requests
- `mock_curl_requests`: Mocks curl_cffi for URL fetching
