"""Report what `llama-server` needs to know about a GGUF before it loads it.

Reads the header only, so it costs nothing on an 18 GB file.  Prints two
`key=value` lines for the launcher to read:

    chat_template=yes|no     whether the model carries its own Jinja template
    vision_tensors=<count>   tensors llama.cpp's text loader will not claim
"""

import struct
import sys

_SCALARS = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}


def main(path: str) -> int:
    with open(path, "rb") as handle:
        if handle.read(4) != b"GGUF":
            print(f"not a GGUF file: {path}", file=sys.stderr)
            return 1
        handle.read(4)  # version
        n_tensors, n_kv = struct.unpack("<QQ", handle.read(16))

        def read(fmt: str, size: int):
            return struct.unpack(fmt, handle.read(size))

        def read_string() -> str:
            length, = read("<Q", 8)
            return handle.read(length).decode("utf-8", "replace")

        def read_value(kind: int):
            if kind == 8:
                return read_string()
            if kind == 9:
                element_kind, = read("<I", 4)
                count, = read("<Q", 8)
                return [read_value(element_kind) for _ in range(count)]
            fmt, size = _SCALARS[kind]
            return read(fmt, size)[0]

        has_template = False
        for _ in range(n_kv):
            key = read_string()
            kind, = read("<I", 4)
            value = read_value(kind)
            if key == "tokenizer.chat_template" and value:
                has_template = True

        # A projector packed into the same file is the failure this exists to
        # catch: llama.cpp builds the text tensors, finds the count short of the
        # header's, and refuses the model with no mention of vision.
        vision = 0
        for _ in range(n_tensors):
            name = read_string()
            n_dims, = read("<I", 4)
            for _ in range(n_dims):
                read("<Q", 8)
            read("<I", 4)  # type
            read("<Q", 8)  # offset
            if name.startswith(("v.", "mm.")):
                vision += 1

    print(f"chat_template={'yes' if has_template else 'no'}")
    print(f"vision_tensors={vision}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
