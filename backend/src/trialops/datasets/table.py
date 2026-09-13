"""Safe named access to positional Dataset-JSON rows."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from trialops.datasets.dataset_json import DatasetJsonDocument, DatasetJsonValue


class MissingRequiredColumnsError(ValueError):
    """Raised when a dataset lacks columns required by an importer."""

    def __init__(self, dataset_name: str, missing_columns: tuple[str, ...]) -> None:
        columns = ", ".join(missing_columns)
        super().__init__(f"Dataset {dataset_name} is missing required columns: {columns}")
        self.dataset_name = dataset_name
        self.missing_columns = missing_columns


@dataclass(frozen=True, slots=True)
class NamedDatasetRow:
    """One source row paired with its column names and one-based position."""

    record_number: int
    values: Mapping[str, DatasetJsonValue]


def require_columns(
    document: DatasetJsonDocument,
    required_columns: Iterable[str],
) -> None:
    """Ensure a document contains every exact column name an importer needs."""
    available_columns = {column.name for column in document.columns}
    missing_columns = tuple(sorted(set(required_columns) - available_columns))
    if missing_columns:
        raise MissingRequiredColumnsError(document.name, missing_columns)


def iter_named_rows(document: DatasetJsonDocument) -> Iterator[NamedDatasetRow]:
    """Yield rows whose positional values are safely paired with column names."""
    column_names = tuple(column.name for column in document.columns)
    for record_number, row in enumerate(document.rows, start=1):
        values = MappingProxyType(dict(zip(column_names, row, strict=True)))
        yield NamedDatasetRow(record_number=record_number, values=values)
