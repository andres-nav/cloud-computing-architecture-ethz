from dataclasses import dataclass
from typing import Literal
from enum import Enum

class Job(Enum):
    BARNES = "barnes"
    BLACKSCHOLES = "blackscholes"
    CANNEAL = "canneal"
    FREQMINE = "freqmine"
    RADIX = "radix"
    STREAMCLUSTER = "streamcluster"
    VIPS = "vips"

@dataclass
class NodeA:
    cores: set[Literal[0, 1, 2, 3, 4, 5, 6, 7]]
    kind: Literal["A"] = "A"

@dataclass
class NodeB:
    cores: set[Literal[0, 1, 2, 3]]
    kind: Literal["B"] = "B"

ParsecThreadCount = Literal[1, 2, 3, 4, 5, 6, 7, 8]

@dataclass
class ParsecJob:
    node: NodeA | NodeB
    threads: ParsecThreadCount
    after: Job | None

# splash job threads must be power of 2
SplashThreadCount = Literal[1, 2, 4, 8]

@dataclass
class SplashJob:
    node: NodeA | NodeB
    threads: SplashThreadCount
    after: Job | None

@dataclass
class Policy:
    blackscholes: ParsecJob
    canneal: ParsecJob
    freqmine: ParsecJob
    streamcluster: ParsecJob
    vips: ParsecJob
    barnes: SplashJob
    radix: SplashJob

def get_policy() -> Policy:
    """Returns the scheduling policy discovered by evolution."""
    # EVOLVE-BLOCK-START
    policy: Policy = Policy(
        blackscholes = ParsecJob(node = NodeB(cores = {1, 2, 3}), threads = 3, after = None),
        canneal = ParsecJob(node = NodeA(cores = {0, 1, 2, 3}), threads = 4, after = Job.STREAMCLUSTER),
        freqmine = ParsecJob(node = NodeA(cores = {4, 5, 6, 7}), threads = 4, after = Job.STREAMCLUSTER),
        streamcluster = ParsecJob(node = NodeA(cores = {0, 1, 2, 3}), threads = 4, after = None),
        vips = ParsecJob(node = NodeA(cores = {0, 1, 2, 3}), threads = 4, after = Job.CANNEAL),
        barnes = SplashJob(node = NodeA(cores = {4, 5, 6, 7}), threads = 4, after = Job.FREQMINE),
        radix = SplashJob(node = NodeA(cores = {4, 5, 6, 7}), threads = 4, after = Job.BARNES)
    )
    # EVOLVE-BLOCK-END
    return policy
