import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Run workflow1-4 end-to-end in an isolated run directory.")
    parser.add_argument(
        "--product",
        default=str(Path("inputs") / "product_context.md"),
        help="Path to the product context Markdown file (utf-8).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id (default: timestamp like 20251220_165233).",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Runs output directory (default: runs).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    product_arg_path = Path(args.product)
    product_path = (repo_root / product_arg_path).resolve() if not product_arg_path.is_absolute() else product_arg_path

    if not product_path.is_file():
        raise FileNotFoundError(f"Product context file not found: {product_path}")

    run_id = args.run_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = repo_root / args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    run_product_path = run_dir / "product_context.md"
    shutil.copyfile(product_path, run_product_path)

    env = os.environ.copy()
    env["PRODUCT_CONTEXT_FILE"] = str(run_product_path)

    scripts = ["workflow1.py", "workflow2.py", "workflow3.py", "workflow4.py"]
    for script in scripts:
        script_path = repo_root / script
        if not script_path.is_file():
            raise FileNotFoundError(f"Missing script: {script_path}")
        subprocess.run([sys.executable, str(script_path)], cwd=str(run_dir), env=env, check=True)

    print(f"\n[Done] Run completed: {run_dir}")


if __name__ == "__main__":
    main()

