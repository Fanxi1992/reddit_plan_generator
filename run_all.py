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
    # `repo_root` 是这个仓库的根目录（也就是 run_all.py 所在目录）。
    # 后面我们会用它来定位 workflow1~4 的脚本路径，以及 runs/ 输出目录。
    repo_root = Path(__file__).resolve().parent

    # 用户传入的 `--product` 可能是相对路径（相对于仓库根目录），也可能是绝对路径。
    # 这里统一把它解析为一个绝对路径，确保后续读取文件稳定可靠。
    product_arg_path = Path(args.product)
    product_path = (repo_root / product_arg_path).resolve() if not product_arg_path.is_absolute() else product_arg_path

    # 如果找不到产品信息文件，就直接报错中止；
    # 因为 workflow1 需要这个输入，缺失的话后面运行没有意义。
    if not product_path.is_file():
        raise FileNotFoundError(f"Product context file not found: {product_path}")

    # 为本次运行生成一个 run_id：
    # - 你可以手动传 `--run-id xxx`（比如用客户名）
    # - 不传的话就用时间戳，保证每次运行都是唯一目录，避免串数据
    run_id = args.run_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 本次运行的所有中间文件/输出文件都会写到 `runs/<run_id>/` 中，
    # 这样仓库根目录不会被大量产物污染，也不会发生 “get_latest_file() 选到上一次运行文件” 的问题。
    run_dir = repo_root / args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    # 把产品输入复制到 run 目录里，形成一次“输入快照”，便于复盘和交付。
    # 注意：后续 workflow1 会优先读取这个 run 目录里的 product_context.md。
    run_product_path = run_dir / "product_context.md"
    shutil.copyfile(product_path, run_product_path)

    # 把当前系统环境变量拷贝一份，并注入 `PRODUCT_CONTEXT_FILE`：
    # workflow1.py 里会优先读取这个环境变量指向的文件来作为 PRODUCT_CONTEXT。
    # 这样你不需要每次改 workflow1.py 里的硬编码内容，只要换输入 md 文件即可。
    env = os.environ.copy()
    env["PRODUCT_CONTEXT_FILE"] = str(run_product_path)

    # 固定按顺序执行四个阶段脚本（多米诺骨牌）：
    # - workflow2/3/4 会用 glob + “latest file” 的方式找上一阶段产物
    # - 我们把 cwd 切到 run_dir，所以它们只会在当前 run 目录里找文件，不会串到历史运行
    scripts = ["workflow1.py", "workflow2.py", "workflow3.py", "workflow4.py"]
    for script in scripts:
        # 每个脚本文件都从仓库根目录定位（不是从 run_dir 里找）
        script_path = repo_root / script
        if not script_path.is_file():
            raise FileNotFoundError(f"Missing script: {script_path}")

        # 关键点：
        # - `cwd=str(run_dir)`：让脚本把所有输出文件写到 run_dir，并且读“latest 文件”也只在 run_dir 范围内生效
        # - `env=env`：把 PRODUCT_CONTEXT_FILE 传给 workflow1
        # - `check=True`：任何一个阶段失败都会立刻抛异常并停止后续阶段（方便你定位是哪一段出错）
        subprocess.run([sys.executable, str(script_path)], cwd=str(run_dir), env=env, check=True)

    # 所有阶段都成功时，给出最终 run 目录位置，方便你打开查看产物。
    print(f"\n[Done] Run completed: {run_dir}")


if __name__ == "__main__":
    main()
