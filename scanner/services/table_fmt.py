"""Fixed-width table rendering for the Slack / terminal reports.

Column widths are derived from the rendered cells, floored at a per-column
minimum. A value that is wider than the usual width therefore widens that
column for every row instead of pushing the rest of the row to the right and
breaking the alignment with the header.

Numeric columns are rendered at one shared width so their decimals stay in a
vertical line; every cell in such a column has the same length.

`slack_table_block` renders the same cells as a native Slack Block Kit table.
Slack only keeps a fenced code block monospaced inside the message bubble —
in notifications, search results and channel previews the same text is shown
as proportional type and every column collapses. A native table grid stays
aligned in all of those places.
"""

import math
from typing import Iterable, List, Optional, Sequence, Tuple

# (title, align, min_width) — align is 'l' or 'r'.
Column = Tuple[str, str, int]

_SLACK_ALIGN = {'l': 'left', 'r': 'right', 'c': 'center'}


def is_missing(value: Optional[float]) -> bool:
    """True when a value has no usable number (None or NaN)."""
    if value is None:
        return True
    try:
        return math.isnan(value)
    except TypeError:
        return False


def cell_matrix(columns: Sequence[Column],
                rows: Iterable[Sequence[object]]) -> List[List[str]]:
    """Normalise rows into one list of strings per row, one cell per column."""
    body = []
    for row in rows:
        cells = [str(cell) for cell in row]
        if len(cells) < len(columns):
            cells += [''] * (len(columns) - len(cells))
        body.append(cells[:len(columns)])
    return body


def render_table(columns: Sequence[Column],
                 rows: Iterable[Sequence[object]]) -> List[str]:
    """Render a header line, a separator line and one line per row.

    `columns` is a sequence of (title, align, min_width); `rows` is a sequence
    of cell sequences, one cell per column.
    """
    body = cell_matrix(columns, rows)

    widths = []
    for idx, (title, _align, min_width) in enumerate(columns):
        width = max(min_width, len(title))
        for row in body:
            if idx < len(row):
                width = max(width, len(row[idx]))
        widths.append(width)

    def format_line(cells: Sequence[str]) -> str:
        parts = []
        for idx, cell in enumerate(cells):
            if columns[idx][1] == 'l':
                parts.append(cell.ljust(widths[idx]))
            else:
                parts.append(cell.rjust(widths[idx]))
        return ' '.join(parts)

    lines = [format_line([col[0] for col in columns])]
    lines.append(' '.join('-' * width for width in widths))
    for row in body:
        lines.append(format_line(row))
    return lines


def _raw_text(text: str) -> dict:
    return {'type': 'raw_text', 'text': text}


def slack_table_block(columns: Sequence[Column],
                      rows: Iterable[Sequence[object]]) -> dict:
    """Build a Slack Block Kit `table` block from the same cells.

    The first row of the block is the header row. Per-column alignment comes
    from the column spec, so numeric columns stay right-aligned exactly like
    the fixed-width renderer.

    Slack rejects the whole block when any cell is empty (HTTP 400
    `invalid_blocks`), so blank cells are replaced with a dash.
    """
    body = cell_matrix(columns, rows)
    table_rows = [[_raw_text(col[0]) for col in columns]]
    table_rows.extend(
        [_raw_text(cell if cell.strip() else '-') for cell in row] for row in body
    )
    return {
        'type': 'table',
        'column_settings': [
            {'align': _SLACK_ALIGN.get(col[1], 'left')} for col in columns
        ],
        'rows': table_rows,
    }


def numeric_cells(values: Iterable[Optional[float]], decimals: int = 4,
                  prefix: str = '') -> List[str]:
    """Format a numeric column at one shared width so the decimals line up."""
    nums = [value for value in values if not is_missing(value)]
    width = max((len(f'{value:.{decimals}f}') for value in nums), default=0)
    cells = []
    for value in values:
        if is_missing(value):
            cells.append('n/a'.rjust(width + len(prefix)))
        else:
            cells.append(f'{prefix}{value:>{width}.{decimals}f}')
    return cells
