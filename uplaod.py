import os
import shutil
import subprocess
from pathlib import Path

# ================= 配置区域 =================
# 需要执行的特定 Bash 命令
BASH_COMMAND = "npx wrangler pages deploy ./onimai-anime --project-name onimai-anime"

# 目标目录路径 (需要被清理的目录)
TARGET_DIR = Path("/run/media/chocola/3T-DATA02/Projects/Pages/onimai-anime")

# 缓存目录路径 (用于临时存放文件)
CACHE_DIR = Path("/run/media/chocola/3T-DATA02/Projects/Pages/tmp")

# 文件大小阈值 (单位: 字节) 例如 512MB
THRESHOLD_BYTES = 512 * 1024 * 1024  # 512 MB
# ===========================================


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


def main():
    target_dir = TARGET_DIR.resolve()
    cache_dir = CACHE_DIR.resolve()

    print(f"目标目录: {target_dir}")
    print(f"缓存目录: {cache_dir}")
    print(f"大小阈值: {THRESHOLD_BYTES / (1024**2):.2f} MB\n")

    cache_dir.mkdir(parents=True, exist_ok=True)

    # 第一阶段：将所有超出阈值的文件搬到缓存
    print("--- 阶段一：清空目标目录 ---")
    initial_size, initial_files = get_directory_size_and_files(target_dir)
    print(f"初始目录总大小: {initial_size / (1024**2):.2f} MB")

    if initial_size > THRESHOLD_BYTES:
        files_to_move_initially = []
        size_moved = 0
        min_size_to_free = initial_size - THRESHOLD_BYTES

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

        # 执行第一次命令（此时目标目录已清理，只有少量残留文件）
        print("\n[步骤] 执行首次部署命令...")
        success = run_bash_command(BASH_COMMAND)
        if not success:
            print("[错误] 首次命令执行失败，程序终止。")
            return
    else:
        print("初始大小已满足阈值要求，无需搬运。")
        print("\n[步骤] 执行初始部署命令...")
        success = run_bash_command(BASH_COMMAND)
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
            if size_to_return + size <= THRESHOLD_BYTES:
                files_to_return.append((rel_path, size, full_path))
                size_to_return += size
            else:
                # 如果第一个文件就超了阈值，我们仍需移动它，否则会卡住
                if len(files_to_return) == 0:
                    print(f"  -> 警告: 单个文件超过阈值，但仍将其取出。")
                    files_to_return.append((rel_path, size, full_path))
                    size_to_return = size
                break

        print(f"  -> 从缓存取回 {len(files_to_return)} 个文件，总大小 {size_to_return / (1024**2):.2f} MB")
        move_files_with_structure(files_to_return, cache_dir, target_dir)

        # 执行命令
        print(f"  -> 执行部署命令...")
        success = run_bash_command(BASH_COMMAND)
        if not success:
            print("[错误] 命令执行失败，程序终止。")
            return

        # 关键区别：执行完命令后，文件就留在目标目录了，不需要再移回去！

    # 第三阶段：当缓存为空时，执行最终命令
    print("\n--- 阶段三：完成任务 ---")
    print("\n[最终步骤] 执行最终部署命令，此时所有文件都已回到目标目录。")
    success = run_bash_command(BASH_COMMAND)
    if not success:
        print("[错误] 最终命令执行失败。")
        return

    print("\n任务完成！所有文件已处理并完成最终部署。")


if __name__ == "__main__":
    main()
