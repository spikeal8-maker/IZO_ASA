"""Framework-free ownership error shared by API orchestration and executor IPC."""


class GenerationClaimLost(RuntimeError):
    """The durable owner or active state no longer permits an execution effect."""
