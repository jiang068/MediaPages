import argparse
import json
import os
import subprocess
import sys
import shutil
import urllib.request
import urllib.error
from pathlib import Path

# 导入同目录下的 upload 模块
import upload
import config

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

def apply_site_config(dist_dir, title_override):
    """从 config.ini 应用 site 配置（标题、图标）。"""
    from pathlib import Path
    index_html_path = dist_dir / "index.html"
    if not index_html_path.exists():
        return

    with open(index_html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 标题：CLI 参数 > config.ini > 默认 "MediaPages"
    title = title_override or config.str_("site", "title", "MediaPages")
    if title:
        old_tag = "<title>MediaPages</title>"
        new_tag = f"<title>{title}</title>"
        if old_tag in html:
            html = html.replace(old_tag, new_tag, 1)
            print(f"✅ 网页标题已设置为: {title}")

    # 网站图标：本地路径复制到 dist，URL 直接替换 href
    favicon = config.str_("site", "favicon", "")
    if favicon:
        favicon_path = Path(favicon)
        if favicon_path.is_absolute():
            # 绝对路径：复制到 dist
            dist_favicon = dist_dir / favicon_path.name
            shutil.copy2(favicon_path, dist_favicon)
            html = html.replace(
                'href="./favicon.png"',
                f'href="./{favicon_path.name}"',
            )
            print(f"✅ 网站图标已复制并设置: {favicon_path.name}")
        elif favicon.startswith("http://") or favicon.startswith("https://"):
            # URL：直接替换 href
            html = html.replace('href="./favicon.png"', f'href="{favicon}"')
            print(f"✅ 网站图标已设置为远程 URL: {favicon}")
        else:
            # 相对路径：直接替换 href
            html = html.replace('href="./favicon.png"', f'href="{favicon}"')
            print(f"✅ 网站图标已设置为: {favicon}")

    with open(index_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 鉴权：如果启用了密码，注入 auth 脚本
    auth = config.generate_auth(dist_dir)
    if auth["enabled"]:
        with open(index_html_path, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("<body>", f"<body>\n{auth['script_before']}")
        html = html.replace("</body>", f"\n{auth['script_after']}\n</body>")
        with open(index_html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ 网页密码鉴权已启用")


def export_cloudflare_credentials():
    """从 config.ini 或环境变量读取 CF 凭证，设置环境变量供 wrangler 使用。"""
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or config.str_("cloudflare", "api_token", "")
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or config.str_("cloudflare", "account_id", "")
    if token:
        os.environ["CLOUDFLARE_API_TOKEN"] = token
    if acct:
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = acct


def main():
    parser = argparse.ArgumentParser(description="多媒体转换与自动分批部署脚手架")
    parser.add_argument("-s", "--source", help="原始媒体库目录，不传则使用 config.ini [main] → source")
    parser.add_argument("-w", "--workspace", help="临时工作区目录，不传则使用 config.ini [main] → workspace")
    parser.add_argument("-p", "--project-name", help="Cloudflare Pages 远端项目名称，不传则使用 config.ini [main] → project_name")
    parser.add_argument("-t", "--title", help="网页标题，不传则使用 config.ini [site] → title")
    parser.add_argument("--threshold", type=int, default=0, help="单次上传阈值(MB)，不传则使用 config.ini [cloudflare] → upload_threshold_mb")
    args = parser.parse_args()

    # 优先级：CLI 参数 > config.ini > 报错（source/workspace/project_name 必须有值）
    source_str = args.source or config.str_("main", "source", "")
    workspace_str = args.workspace or config.str_("main", "workspace", "")
    project_name = args.project_name or config.str_("main", "project_name", "")

    missing = []
    if not source_str: missing.append("-s / [main].source")
    if not workspace_str: missing.append("-w / [main].workspace")
    if not project_name: missing.append("-p / [main].project_name")
    if missing:
        print(f"[错误] 以下必要参数未设置：{', '.join(missing)}")
        print("  请通过 CLI 参数传入，或在 config.ini 的 [main] 节中配置。")
        sys.exit(1)

    threshold = args.threshold or config.int_("cloudflare", "upload_threshold_mb", 512)

    source_dir = Path(source_str).resolve()
    workspace_dir = Path(workspace_str).resolve()

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

        # 应用 site 配置（标题、图标）到 index.html
        apply_site_config(dist_dir, args.title)

        # 根据配置生成 _headers 文件（CORS/安全头）
        config.generate_headers(dist_dir)
        headers_path = dist_dir / "_headers"
        if headers_path.exists():
            print(f"已生成 CORS 配置文件: {headers_path}")
        else:
            print("CORS 配置未启用，跳过 _headers 文件生成。")

    # 从 config.ini 或环境变量导出 CF 凭证
    export_cloudflare_credentials()

    print("\n" + "="*50)
    print(f"🚀 第二阶段：创建远端仓库 [{project_name}]")
    print("="*50)

    # 通过 Cloudflare API 检查项目是否已存在，避免盲目创建报错
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or config.str_("cloudflare", "account_id", "")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN") or config.str_("cloudflare", "api_token", "")
    project_exists = False
    if account_id and api_token:
        try:
            req = urllib.request.Request(
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project_name}",
                headers={"Authorization": f"Bearer {api_token}"}
            )
            with urllib.request.urlopen(req) as resp:
                if resp.status == 200:
                    project_exists = True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"[警告] 查询项目状态失败 (HTTP {e.code})，将尝试直接创建")

    if project_exists:
        print(f"✅ 项目 [{project_name}] 已存在，直接覆盖部署更新。")
    else:
        create_cmd = f"npx wrangler pages project create {project_name} --production-branch main"
        run_shell_command(create_cmd)

    print("\n" + "="*50)
    print("🚀 第三阶段：分批上传与部署 (调用 upload.py)")
    print("="*50)

    # 动态组装部署命令
    deploy_cmd = f"npx wrangler pages deploy {dist_dir} --project-name {project_name}"
    threshold_bytes = threshold * 1024 * 1024

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
