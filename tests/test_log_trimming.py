from llm_cli.apps.gemini import GeminiClient


def test_trim_log_file(tmp_path, mock_config):
    """Test that log files are trimmed to max_lines."""
    client = GeminiClient(stdout=True)

    # Create a test log file with 100 lines
    log_file = tmp_path / "test.log"
    lines = [f"Line {i}\n" for i in range(100)]
    log_file.write_text("".join(lines))

    # Trim to 10 lines
    client._trim_log_file(log_file, max_lines=10)

    # Check that only the last 10 lines remain
    result = log_file.read_text().splitlines(keepends=True)
    assert len(result) == 10
    assert result[0] == "Line 90\n"
    assert result[-1] == "Line 99\n"


def test_trim_log_file_no_trim_needed(tmp_path, mock_config):
    """Test that log files are not trimmed if under max_lines."""
    client = GeminiClient(stdout=True)

    # Create a test log file with 5 lines
    log_file = tmp_path / "test.log"
    lines = [f"Line {i}\n" for i in range(5)]
    log_file.write_text("".join(lines))

    # Trim to 10 lines
    client._trim_log_file(log_file, max_lines=10)

    # Check that all 5 lines remain
    result = log_file.read_text().splitlines(keepends=True)
    assert len(result) == 5


def test_trim_log_file_nonexistent(tmp_path, mock_config):
    """Test that trimming a nonexistent file doesn't raise an error."""
    client = GeminiClient(stdout=True)

    log_file = tmp_path / "nonexistent.log"
    # Should not raise an error
    client._trim_log_file(log_file, max_lines=10)
