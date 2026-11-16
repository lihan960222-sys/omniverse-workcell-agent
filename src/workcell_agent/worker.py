import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["convert_step", "check_interference", "query_features"])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    from .geometry import convert_step, check_interference, query_features
    parameters = json.loads(args.input.read_text(encoding="utf-8"))
    if args.operation == "convert_step":
        result = convert_step(Path(parameters["source"]), Path(parameters["output_directory"]))
    elif args.operation == "check_interference":
        result = check_interference(**parameters)
    else:
        result = query_features(**parameters)
    args.output.write_text(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
