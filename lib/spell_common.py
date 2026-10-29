"""Spell policy constants, domain errors and binary/serialization
primitives.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import NoReturn


POLICY = 'spell-state-v18'
LEARN, SKILL, SKILL_STEP, DUAL_WIELD = 36, 118, 44, 40
PASSIVE, HIDDEN = 0x40, 0x80


class Unsupported(ValueError):
    """Unsupported spell state with a stable compatibility reason code."""

    reason: str

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class MetadataQueryError(RuntimeError):
    """Database access failed before spell compatibility could be
    established.
    """

    detail: str
    label: str

    def __init__(self, label: str, detail: str) -> None:
        super().__init__(f'{label}: {detail}')
        self.label, self.detail = label, detail


def reject(reason: str, detail: str) -> NoReturn:
    raise Unsupported(reason, detail)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators= (',', ':')).encode()


def sql_text(value: object) -> str:
    return 'CONVERT(0x' + str(value).encode().hex() + ' USING utf8mb4)'


def read_dbc(path: Path, fmt: str) -> tuple[dict[int, list[int]], str]:
    data = path.read_bytes()
    if len(data) < 20:
        reject('INVALID_DBC', f'{path.name}: truncated header')
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    if (magic != b'WDBC' or fields != len(fmt) or size != 4 * fields or len(
        data) != 20 + count * size + strings):
        reject('INVALID_DBC', f'{path.name}: incompatible WDBC layout')
    records = {}
    string_start = 20 + count * size
    string_fields = [index for index, field in enumerate(fmt) if field == 's']
    for offset in range(20, 20 + count * size, size):
        record = list(struct.unpack_from('<' + 'I' * fields, data, offset))
        if not record[0] or record[0] in records:
            reject('INVALID_DBC',
                f'{path.name}: duplicate/zero ID {record[0]}')
        for index in string_fields:
            if (record[index] >= strings or data.find(b'\0', string_start
                + record[index]) < 0):
                reject('INVALID_DBC',
                    f'{path.name}: invalid string offset for ID '
                    f'{record[0]}')
        records[record[0]] = record
    return records, digest(data)


def signed(value: int) -> int:
    return value - 2 ** 32 if value >= 2 ** 31 else value


SPELL_READER_FILES = (
    'lib/spells.py',
    'lib/spell_common.py',
    'lib/spell_metadata.py',
    'lib/spell_rules.py',
    'lib/spell_reconstruction.py',
    'lib/cleanup_types.py',
)


def reader_hashes(root: Path) -> dict[str, str]:
    """Keep captured metadata tied to every extracted spell-reader
    dependency.
    """
    return ({name: digest((root / name).read_bytes()) for name
        in SPELL_READER_FILES})
