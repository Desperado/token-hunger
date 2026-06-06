"""costbench — benchmark LLM targets by cost per successful outcome.

The unit of comparison is a *target* (a raw model, an HTTP endpoint, a local
command) and the headline metric is **cost per success**: total cost divided by
the number of correct outputs, not cost per token. A model that is cheap per
call but fails more often is not actually cheap.

Nothing in this package is provider-specific or vendor-specific: every target
runs the same cases through the same correctness check, and cost is computed
from a transparent, auditable pricing table committed in this repo.
"""

__version__ = "0.1.0"
