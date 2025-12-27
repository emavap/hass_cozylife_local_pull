# Testing Guide for CozyLife Local Integration

This document describes how to run tests for the CozyLife Local Home Assistant integration using Docker.

## Prerequisites

- Docker installed on your system
- Docker Compose installed (usually comes with Docker Desktop)

## Quick Start

### Run All Tests

```bash
docker-compose -f docker-compose.test.yml up --build
```

This will:
1. Build the test Docker image
2. Run all tests with pytest
3. Generate coverage reports
4. Display results in the terminal

### Run Tests in Watch Mode

To run tests and keep the container running for development:

```bash
docker-compose -f docker-compose.test.yml run --rm test bash
```

Then inside the container:

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_tcp_client.py

# Run specific test
pytest tests/test_tcp_client.py::TestTCPClient::test_connect_success

# Run with verbose output
pytest -v

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration
```

## Test Structure

```
tests/
├── __init__.py                 # Test package initialization
├── conftest.py                 # Shared fixtures and configuration
├── test_udp_discover.py        # UDP discovery tests
├── test_tcp_client.py          # TCP client tests
├── test_light.py               # Light entity tests
├── test_switch.py              # Switch entity tests
├── test_discovery.py           # Hostname discovery tests
└── test_init.py                # Integration setup tests
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
- Test individual components in isolation
- Use mocks for external dependencies
- Fast execution
- Examples: TCP client, UDP discovery, entity logic

### Integration Tests (`@pytest.mark.integration`)
- Test component interactions
- Test full setup flow
- May use real Home Assistant core
- Examples: Config entry setup, discovery flow

## Coverage Reports

After running tests, coverage reports are generated:

### Terminal Report
Displayed automatically after test execution showing:
- Line coverage percentage
- Missing lines for each file

### HTML Report
Generated in `htmlcov/` directory:

```bash
# View HTML coverage report (macOS)
open htmlcov/index.html

# View HTML coverage report (Linux)
xdg-open htmlcov/index.html

# View HTML coverage report (Windows)
start htmlcov/index.html
```

## Running Specific Test Suites

### UDP Discovery Tests
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest tests/test_udp_discover.py -v
```

### TCP Client Tests
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest tests/test_tcp_client.py -v
```

### Entity Tests (Light & Switch)
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest tests/test_light.py tests/test_switch.py -v
```

### Integration Tests
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest -m integration -v
```

## Debugging Tests

### Run with Debug Output
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest -v -s
```

The `-s` flag disables output capturing, showing print statements and logs.

### Run Single Test with Debug
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest tests/test_tcp_client.py::TestTCPClient::test_connect_success -v -s
```

### Interactive Debugging
Add breakpoints in your test code:

```python
import pdb; pdb.set_trace()
```

Then run:
```bash
docker-compose -f docker-compose.test.yml run --rm test pytest tests/test_tcp_client.py -v -s
```

## Continuous Integration

The test suite is designed to run in CI/CD pipelines. Example GitHub Actions workflow:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: docker-compose -f docker-compose.test.yml up --abort-on-container-exit
```

## Test Fixtures

Common fixtures available in `conftest.py`:

- `hass` - Mock Home Assistant instance
- `mock_config_entry` - Mock configuration entry
- `mock_tcp_connection` - Mock TCP reader/writer
- `mock_udp_socket` - Mock UDP socket
- `mock_device_info_response` - Mock device info JSON
- `mock_query_response` - Mock query response JSON
- `mock_pid_list` - Mock product ID list
- `mock_async_get_pid_list` - Patched PID list function
- `mock_get_sn` - Patched serial number function

## Writing New Tests

### Example Unit Test

```python
import pytest
from unittest.mock import MagicMock

@pytest.mark.unit
@pytest.mark.asyncio
async def test_my_feature(mock_tcp_client):
    """Test description."""
    # Arrange
    mock_tcp_client.query = AsyncMock(return_value={'1': 255})
    
    # Act
    result = await my_function(mock_tcp_client)
    
    # Assert
    assert result is True
```

### Example Integration Test

```python
import pytest
from homeassistant.core import HomeAssistant

@pytest.mark.integration
@pytest.mark.asyncio
async def test_setup_flow(hass: HomeAssistant, mock_config_entry):
    """Test integration setup."""
    result = await async_setup_entry(hass, mock_config_entry)
    assert result is True
```

## Troubleshooting

### Tests Fail to Start
- Ensure Docker is running
- Check Docker Compose version: `docker-compose --version`
- Rebuild the image: `docker-compose -f docker-compose.test.yml build --no-cache`

### Import Errors
- Verify PYTHONPATH is set correctly in docker-compose.test.yml
- Check that all files are being copied in Dockerfile.test

### Coverage Not Generated
- Ensure pytest-cov is installed (check requirements_test.txt)
- Verify htmlcov directory is mounted in docker-compose.test.yml

## Clean Up

Remove test containers and images:

```bash
docker-compose -f docker-compose.test.yml down
docker system prune -f
```

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [Home Assistant testing documentation](https://developers.home-assistant.io/docs/development_testing)

