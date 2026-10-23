"""STL reader (binary and ASCII) returning a compact flat float array."""
import re
import struct
from array import array

_HEADER_BYTES = 84
_RECORD = struct.Struct("<12fH")
_ASCII_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


class StlError(ValueError):
    """The file is not a readable STL mesh."""


def read_triangles(path):
    # type: (str) -> array
    """Return vertex coordinates, 9 floats (3 vertices x xyz) per triangle."""
    with open(path, "rb") as stream:
        payload = stream.read()
    # Binary files may start with "solid", so trust the size, not the header.
    if len(payload) >= _HEADER_BYTES:
        declared = struct.unpack_from("<I", payload, 80)[0]
        if _HEADER_BYTES + _RECORD.size * declared == len(payload):
            return _read_binary(payload, declared)
    return _read_ascii(payload)


def _read_binary(payload, triangle_count):
    # type: (bytes, int) -> array
    coordinates = array("f")
    body = memoryview(payload)[_HEADER_BYTES:]
    for record in _RECORD.iter_unpack(body):
        coordinates.extend(record[3:12])
    if len(coordinates) != 9 * triangle_count:
        raise StlError("binary STL record count mismatch")
    return coordinates


def _read_ascii(payload):
    # type: (bytes) -> array
    values = [float(value) for match in _ASCII_VERTEX.finditer(payload) for value in match.groups()]
    if not values or len(values) % 9 != 0:
        raise StlError("not a valid STL file: no complete triangles found")
    return array("f", values)
