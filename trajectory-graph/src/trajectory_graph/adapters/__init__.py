"""Versioned input adapters for supported trajectory corpora."""

from . import terminal_bench_2_0, terminal_bench_4_0


ADAPTERS = {
    terminal_bench_2_0.NAME: terminal_bench_2_0,
    terminal_bench_4_0.NAME: terminal_bench_4_0,
}


def get_adapter(name):
    """Return a configured adapter module by its stable CLI name."""
    try:
        return ADAPTERS[name]
    except KeyError:
        choices = ', '.join(sorted(ADAPTERS))
        raise ValueError(f'Unsupported adapter {name!r}; choose one of: {choices}') from None
