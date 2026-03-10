import argparse
import subprocess
import sys
import shutil
from pathlib import Path

# 导入同目录下的 upload 模块
import upload

def run_shell_command(cmd, ignore_error=False):
    """辅助函数：运行 shell 命令"""
    print(f"执行命令: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        if ignore_error:
            print(f"[提示] 命令未成功返回，但已设置为忽略 (可能仓库或相关配置已存在)。")
            return False
        else:
            print(f"\n[致命错误] 命令执行失败: {cmd}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="多媒体转换与自动分批部署脚手架")
    parser.add_argument("-s", "--source", required=True, help="目标文件夹目录 (需要转换的原始文件所在路径)")
    parser.add_argument("-w", "--workspace", required=True, help="临时处理文件夹目录 (工作区路径)")
    parser.add_argument("-p", "--project-name", required=True, help="远端 Cloudflare Pages 的项目/仓库名称")

    # 新增的可选参数：网页标题
    parser.add_argument("-t", "--title", help="自定义网页标题 (可选，例如: 某科学的超电磁炮)")

    # 可选参数，默认使用 512MB 阈值
    parser.add_argument("--threshold", type=int, default=512, help="单次上传阈值(MB)，默认 512")
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    workspace_dir = Path(args.workspace).resolve()

    if not source_dir.exists():
        print(f"[错误] 源目录不存在: {source_dir}")
        sys.exit(1)

    # 临时目录里的两个文件夹
    dist_dir = workspace_dir / "dist"  # 1. 转换兼上传的文件夹
    tmp_dir = workspace_dir / "tmp"    # 2. 用于中转的 tmp 文件夹

    # 确保目录结构存在
    dist_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*50)
    print("🚀 第一阶段：格式转换与压缩 (调用 convert.py)")
    print("="*50)

    # 调用 convert.py
    convert_cmd = f'"{sys.executable}" convert.py "{source_dir}" "{dist_dir}"'
    run_shell_command(convert_cmd)

    print("\n" + "="*50)
    print("🚀 附加阶段：复制静态资源并设置网页标题")
    print("="*50)

    # 获取 static 文件夹路径（假设它与 main.py 在同级目录下）
    static_dir = Path(__file__).parent / "static"
    if not static_dir.exists():
        print(f"[警告] 找不到 static 目录: {static_dir}，跳过静态资源复制。")
    else:
        print(f"正在复制 {static_dir} 下的所有文件到 {dist_dir} ...")
        # 复制 static 目录下的所有内容到 dist_dir (dirs_exist_ok=True 允许覆盖写入)
        shutil.copytree(static_dir, dist_dir, dirs_exist_ok=True)
        print("静态资源复制完成。")

        # 如果传入了自定义标题参数，则处理 index.html
        if args.title:
            index_html_path = dist_dir / "index.html"
            if index_html_path.exists():
                print(f"正在修改网页标题为: {args.title} - MediaPages")
                try:
                    with open(index_html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()

                    old_title_tag = "<title>MediaPages</title>"
                    new_title_tag = f"<title>{args.title} - MediaPages</title>"

                    if old_title_tag in html_content:
                        html_content = html_content.replace(old_title_tag, new_title_tag)
                        with open(index_html_path, "w", encoding="utf-8") as f:
                            f.write(html_content)
                        print("✅ 标题修改成功！")
                    else:
                        print(f"[警告] 在 index.html 中未找到特定的 `{old_title_tag}` 标签，标题替换失败。")
                except Exception as e:
                    print(f"[错误] 修改 index.html 失败: {e}")
            else:
                print(f"[警告] 找不到 {index_html_path}，无法修改标题。")
        else:
            print("未提供自定义标题参数 (-t)，保留默认标题。")

    print("\n" + "="*50)
    print(f"🚀 第二阶段：创建远端仓库 [{args.project_name}]")
    print("="*50)

    # 创建 Cloudflare Pages 项目
    create_cmd = f"npx wrangler pages project create {args.project_name} --production-branch main"
    run_shell_command(create_cmd, ignore_error=True)

    print("\n" + "="*50)
    print("🚀 第三阶段：分批上传与部署 (调用 upload.py)")
    print("="*50)

    # 动态组装部署命令
    deploy_cmd = f"npx wrangler pages deploy {dist_dir} --project-name {args.project_name}"
    threshold_bytes = args.threshold * 1024 * 1024

    print(f"转换输出目录: {dist_dir}")
    print(f"中转缓存目录: {tmp_dir}")
    print(f"部署命令: {deploy_cmd}")

    # 调用修改后的 upload.py 主函数
    upload.run_deploy(
        target_dir=dist_dir,
        cache_dir=tmp_dir,
        bash_cmd=deploy_cmd,
        threshold=threshold_bytes
    )

    print("\n" + "="*50)
    print("🧹 第四阶段：清理临时工作区")
    print("="*50)

    # 直接将整个 tmp_dir 连带里面的所有空文件夹结构一起销毁
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
        print(f"已彻底删除中转临时目录: {tmp_dir}")

    print("\n🎉 全部流程执行完毕！")

if __name__ == "__main__":
    main()
