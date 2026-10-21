"""Nullable actual usage; neither an execution permission nor a paid-use estimate."""

from typing import Annotated

from pydantic import Field, model_validator

from app.ai.operations_support_contract import StrictModel

Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class OperationsUsage(StrictModel):
    input_tokens: Count | None
    output_tokens: Count | None
    complete: bool
    model_call_attempted: bool | None

    @model_validator(mode="after")
    def faithful_counts(self):
        if self.complete != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Complete usage requires two actual counts")
        if self.model_call_attempted is False and (self.input_tokens, self.output_tokens) != (0, 0):
            raise ValueError("A proven unattempted request has exact zero counts")
        if self.model_call_attempted is None and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("An interrupted attempt cannot manufacture known counts")
        return self


def usage(inputs=None, outputs=None, attempted=None):
    return OperationsUsage(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted).model_dump(mode="json")
