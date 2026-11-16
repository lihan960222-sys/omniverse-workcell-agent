import argparse
from pathlib import Path

from workcell_agent.example import create_example


def main():
    parser = argparse.ArgumentParser(description="创建包含滑台、夹具和障碍物的 USD 示例。")
    parser.add_argument("output", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".work/example/workcell.usda")
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists():
        raise FileExistsError(f"输出文件已经存在：{destination}")
    print(create_example(destination))


if __name__ == "__main__":
    main()
