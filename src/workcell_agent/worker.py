import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["convert_step", "check_interference", "query_features",
                                             "usd_brep_status", "install_usd_brep", "convert_step_brep"])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    from .brep import register_schema, sdk_status, convert_step_brep
    register_schema()
    from .geometry import convert_step, check_interference, query_features
    parameters = json.loads(args.input.read_text(encoding="utf-8"))
    if args.operation == "install_usd_brep":
        script = Path(__file__).resolve().parents[2] / "scripts/install_usd_brep.sh"
        subprocess.run(["bash", str(script)], check=True)
        result = sdk_status()
        if not result["installed"]:
            raise RuntimeError("USD BRep 安装没有通过验证")
    elif args.operation == "usd_brep_status":
        result = sdk_status()
    elif args.operation == "convert_step_brep":
        result = convert_step_brep(**parameters)
    elif args.operation == "convert_step":
        result = convert_step(Path(parameters["source"]), Path(parameters["output_directory"]))
    elif args.operation == "check_interference":
        result = check_interference(**parameters)
    else:
        result = query_features(**parameters)
    args.output.write_text(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
