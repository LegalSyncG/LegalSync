import shutil
import pytest
from pathlib import Path

UPLOADS_DIR = Path(__file__).parent / "uploads"

@pytest.fixture(scope="session", autouse=True)
def cleanup_uploads_after_tests():
    """
    Remove uploads directory after all tests finish.
    """
    yield
    if UPLOADS_DIR.exists():
        shutil.rmtree(UPLOADS_DIR)
