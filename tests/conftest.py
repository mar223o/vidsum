import pytest


@pytest.fixture(autouse=True)
def _procs_not_closing():
    """Test zamykania ustawia globalne „program się zamyka” — kolejne testy zaczynają od czystego stanu."""
    from vidsum import procs
    procs.closing.clear()
    yield
    procs.closing.clear()
