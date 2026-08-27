"""Evolvable scheduling policy. OpenEvolve modifies only the EVOLVE-BLOCK."""


def generate_schedule():
    """Return (memcached, schedule, dependencies) for the cluster."""
    # EVOLVE-BLOCK-START
    memcached = {"node": "node-b-4core", "cores": "0", "threads": 1}
    schedule = {
        "blackscholes":  {"node": "node-b-4core", "cores": "1-2", "threads": 2},
        "radix":         {"node": "node-a-8core", "cores": "0-1", "threads": 2},
        "barnes":        {"node": "node-a-8core", "cores": "2-3", "threads": 2},
        "vips":          {"node": "node-a-8core", "cores": "0-7", "threads": 8},
        "freqmine":      {"node": "node-a-8core", "cores": "0-3", "threads": 4},
        "canneal":       {"node": "node-a-8core", "cores": "4-7", "threads": 4},
        "streamcluster": {"node": "node-a-8core", "cores": "0-7", "threads": 8},
    }
    dependencies = {
        "vips": "radix",
        "freqmine": "vips",
        "canneal": "barnes",
        "streamcluster": "vips",
    }
    return memcached, schedule, dependencies
    # EVOLVE-BLOCK-END