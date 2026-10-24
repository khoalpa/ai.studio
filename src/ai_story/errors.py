class WorkflowError(Exception):
    """Base error for workflow contract violations."""


class ConfigurationError(WorkflowError):
    pass


class TransitionError(WorkflowError):
    pass


class ArtifactError(WorkflowError):
    pass


class PackageError(WorkflowError):
    pass


class RuntimeErrorBase(WorkflowError):
    """Base error for local model runtime failures."""


class RuntimeUnavailableError(RuntimeErrorBase):
    pass


class RuntimeRequestTooLargeError(RuntimeErrorBase):
    """A deterministic request-shape failure that retrying cannot resolve."""


class RuntimeTimeoutError(RuntimeErrorBase):
    pass


class RuntimeCancelledError(RuntimeErrorBase):
    pass


class RuntimeCapabilityError(RuntimeErrorBase):
    pass


class CircuitOpenError(RuntimeErrorBase):
    pass
