import os
import shutil
import subprocess
import argparse
from pathlib import Path

def get_directory_size_and_files(directory: Path):
    """
    计算目录下所有文件的总大小，并返回文件列表及其大小信息。
    """
    total_size = 0
    file_list = []
    for root, dirs, files in os.walk(directory):
        for name in files:
            filepath = Path(root) / name
            try:
                size = filepath.stat().st_size
                total_size += size
                rel_path = filepath.relative_to(directory)
                file_list.append((rel_path, size, filepath))
            except OSError as e:
                print(f"无法获取文件大小 {filepath}: {e}")
    # 按文件大小降序排列
    file_list.sort(key=lambda x: x[1], reverse=True)
    return total_size, file_list


def move_files_with_structure(file_list, source_base: Path, dest_base: Path):
    """
    将文件列表中的文件连同其目录结构一起移动到新位置。
    """
    for i, (rel_path, size, _) in enumerate(file_list):
        src_file = source_base / rel_path
        dest_file = dest_base / rel_path

        if src_file.exists():
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(src_file), str(dest_file))
                if (i + 1) % 500 == 0 or (i + 1) == len(file_list):
                    print(f"  -> 已移动 {i + 1}/{len(file_list)} 个文件...")
            except Exception as e:
                print(f"[移动失败] {src_file}: {e}")
    print(f"  -> 文件移动操作完成。")


def run_bash_command(cmd):
    """执行 Bash 命令并返回是否成功"""
    print(f"\n[执行命令] {cmd}")
    print("  -> 命令开始执行...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True)
        print("  -> 命令执行完毕。")
        print("[命令输出]:", result.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        print(f"[命令失败]: {e}")
        if e.stderr:
            print("[错误信息]:", e.stderr.strip())
        return False


def run_deploy(target_dir, cache_dir, bash_cmd, threshold, resume=False):
    """
    接收外部传入的路径和参数执行部署逻辑
    """
    print(f"目标目录: {target_dir}")
    print(f"缓存目录: {cache_dir}")
    print(f"大小阈值: {threshold / (1024**2):.2f} MB")
    print(f"断点续传: {'开启' if resume else '关闭'}\n")

    if resume:
        # 断点续传模式：直接对目标文件夹当前的内容重试部署，跳过清空阶段
        print("--- 恢复模式：尝试重新部署当前目标目录中的文件 ---")
        success = run_bash_command(bash_cmd)
        if not success:
            print("[错误] 恢复模式下部署重试失败，程序终止。请检查网络或重新运行。")
            return
        print("  -> 恢复部署成功，直接进入阶段二，继续从缓存搬运文件...")
    else:
        # 第一阶段：正常模式，将所有超出阈值的文件搬到缓存
        print("--- 阶段一：清空目标目录 ---")
        initial_size, initial_files = get_directory_size_and_files(target_dir)
        print(f"初始目录总大小: {initial_size / (1024**2):.2f} MB")

        if initial_size > threshold:
            files_to_move_initially = []
            size_moved = 0
            min_size_to_free = initial_size - threshold

            print(f"需要释放至少 {min_size_to_free / (1024**2):.2f} MB 的空间")

            for rel_path, size, full_path in initial_files:
                if size_moved < min_size_to_free:
                    files_to_move_initially.append((rel_path, size, full_path))
                    size_moved += size
                else:
                    break

            print(f"准备搬运 {len(files_to_move_initially)} 个文件到缓存")
            move_files_with_structure(files_to_move_initially, target_dir, cache_dir)

            remaining_size_after_initial_move, _ = get_directory_size_and_files(target_dir)
            print(f"搬运后，目标目录剩余大小: {remaining_size_after_initial_move / (1024**2):.2f} MB")

            # 执行第一次命令
            print("\n[步骤] 执行首次部署命令...")
            success = run_bash_command(bash_cmd)
            if not success:
                print("[错误] 首次命令执行失败，程序终止。")
                return
        else:
            print("初始大小已满足阈值要求，无需搬运。")
            print("\n[步骤] 执行初始部署命令...")
            success = run_bash_command(bash_cmd)
            if not success:
                print("[错误] 初始命令执行失败，程序终止。")
                return

    # 第二阶段：从缓存分批取回文件并执行命令
    print("\n--- 阶段二：从缓存取回文件并部署 ---")
    loop_count = 0
    while True:
        loop_count += 1
        print(f"\n--- 取回循环 #{loop_count} ---")

        # 检查缓存是否还有文件
        cached_size, cached_files = get_directory_size_and_files(cache_dir)
        if cached_size == 0:
            print("缓存目录已空，进入最终步骤。")
            break

        # 从缓存中选取不超过阈值的文件
        files_to_return = []
        size_to_return = 0
        for rel_path, size, full_path in cached_files:
            if size_to_return + size <= threshold:
                files_to_return.append((rel_path, size, full_path))
                size_to_return += size
            else:
                if len(files_to_return) == 0:
                    print(f"  -> 警告: 单个文件超过阈值，但仍将其取出。")
                    files_to_return.append((rel_path, size, full_path))
                    size_to_return = size
                break

        print(f"  -> 从缓存取回 {len(files_to_return)} 个文件，总大小 {size_to_return / (1024**2):.2f} MB")
        move_files_with_structure(files_to_return, cache_dir, target_dir)

        # 执行命令
        print(f"  -> 执行部署命令...")
        success = run_bash_command(bash_cmd)
        if not success:
            print("[错误] 命令执行失败，程序终止。如果是因为网络波动，可以加上 -r 参数重新运行来续传。")
            return

    # 第三阶段：当缓存为空时，执行最终命令
    print("\n--- 阶段三：完成任务 ---")
    print("\n[最终步骤] 执行最终部署命令，此时所有文件都已回到目标目录。")
    success = run_bash_command(bash_cmd)
    if not success:
        print("[错误] 最终命令执行失败。")
        return

    print("\n任务完成！所有文件已处理并完成最终部署。")


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Pages 分批上传部署工具")
    parser.add_argument("-t", "--target", required=True, help="目标文件夹目录 (需要部署的内容所在路径)")
    parser.add_argument("-c", "--cache", required=True, help="缓存文件夹目录 (用于上传过程中的中转存放)")
    parser.add_argument("-p", "--project", required=True, help="远端 Cloudflare Pages 项目名称")
    parser.add_argument("--threshold", type=int, default=512, help="单次上传阈值(MB)，默认 512")

    # 新增的断点续传参数
    parser.add_argument("-r", "--resume", action="store_true", help="启用断点续传：优先上传当前目标文件夹内剩余的文件，再继续从缓存搬运")

    args = parser.parse_args()

    target_dir = Path(args.target).resolve()
    cache_dir = Path(args.cache).resolve()

    if not target_dir.exists():
        print(f"[错误] 目标目录不存在: {target_dir}")
        sys.exit(1)

    # 确保缓存目录存在
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 动态拼接 wrangler 部署命令
    bash_cmd = f"npx wrangler pages deploy {target_dir} --project-name {args.project}"
    threshold_bytes = args.threshold * 1024 * 1024

    print(f"--- 启动独立部署脚本 ---")
    print(f"远端项目: {args.project}")

    run_deploy(target_dir, cache_dir, bash_cmd, threshold_bytes, resume=args.resume)


if __name__ == "__main__":
    main()
