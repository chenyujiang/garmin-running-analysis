"""Summarise a FIT file: message counts, unknown (private) messages, developer fields."""

import sys
from collections import Counter

import fitdecode


def summarise(path: str) -> dict:
    msgs, unknown, dev = Counter(), Counter(), set()
    with fitdecode.FitReader(path) as fit:
        for frame in fit:
            if isinstance(frame, fitdecode.FitDataMessage):
                msgs[frame.name] += 1
                if frame.name.startswith("unknown"):
                    unknown[frame.global_mesg_num] += 1
                for f in frame.fields:
                    if getattr(f, "is_dev", False) or f.field_def is not None and getattr(f.field_def, "dev_data_index", None) is not None:
                        dev.add((frame.name, f.name))
    return {"msgs": msgs, "unknown": unknown, "dev": dev}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        s = summarise(path)
        print(path)
        print("  records:", s["msgs"].get("record"), " total msgs:", sum(s["msgs"].values()))
        print("  msg types:", dict(s["msgs"].most_common()))
        print("  unknown global nums:", dict(s["unknown"]))
        print("  dev fields:", sorted(s["dev"]))
