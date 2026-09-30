# -*- coding: utf-8 -*-
"""打包成免安装的 Windows 程序。

    python tools/build_exe.py

产出 dist/模拟炒股/ 整个文件夹, 里面的「模拟炒股.exe」双击即开:

* 不需要装 Python, 不需要 pip, 不需要联网装任何东西
* --windowed 所以不会弹出黑色的 cmd 窗口
* 账户数据写在 exe 同级的 data/ 里 —— 整个文件夹拷走就把账户带走了

打包必须在 Windows 上跑 (PyInstaller 不能跨平台交叉编译)。
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "模拟炒股"


def sh(args):
    print(">", " ".join(args))
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        sys.exit("失败: {}".format(" ".join(args)))


def size_of(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _rescue_data():
    """把 dist/<名字>/data 抢救到一边, 打完包再放回去。

    2026-09-14 的教训: 下面那个 rmtree('dist') 会把用户的账户、成交记录、
    备份全部删掉, 而且一声不吭。打包脚本**绝对不能碰用户数据**。
    现在冻结运行时数据已经改放 %LOCALAPPDATA%\\模拟炒股\\ (见 config._app_dir),
    这里是给老版本留下的数据兜底。
    """
    src = os.path.join(ROOT, "dist", NAME, "data")
    if not os.path.isdir(src):
        return None
    safe = os.path.join(ROOT, "build_data_rescue")
    shutil.rmtree(safe, ignore_errors=True)
    shutil.copytree(src, safe)
    n = sum(len(f) for _, _, f in os.walk(safe))
    print("  已抢救 dist 里的用户数据 (%d 个文件) -> %s" % (n, safe))
    return safe


def _restore_data(safe):
    if not safe or not os.path.isdir(safe):
        return
    dst = os.path.join(ROOT, "dist", NAME, "data")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(safe, dst)
    shutil.rmtree(safe, ignore_errors=True)
    print("  用户数据已放回 %s" % dst)


def main():
    t0 = time.time()
    safe = _rescue_data()
    for d in ("build", "dist"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir",                 # 单文件夹: 启动比单文件快得多
        "--windowed",               # 关键: 不弹黑色 cmd 窗口
        "--name", NAME,
        "--distpath", "dist", "--workpath", "build", "--specpath", "build",
        # 这些是明确用不到的, 排掉能小不少
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
        "--exclude-module", "test",
        "--exclude-module", "PyQt6.QtWebEngineCore",
        "--exclude-module", "PyQt6.QtWebEngineWidgets",
        "--exclude-module", "PyQt6.QtMultimedia",
        "--exclude-module", "PyQt6.QtQml",
        "--exclude-module", "PyQt6.QtQuick",
        "--exclude-module", "PyQt6.Qt3DCore",
        "--exclude-module", "PyQt6.QtBluetooth",
        "--exclude-module", "PyQt6.QtNetworkAuth",
        "--exclude-module", "PyQt6.QtPositioning",
        "--exclude-module", "PyQt6.QtSerialPort",
        "--exclude-module", "PyQt6.QtDesigner",
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "IPython",
        "--exclude-module", "reportlab",
    ]
    icon = os.path.join(ROOT, "tools", "app.ico")
    if os.path.exists(icon):
        args += ["--icon", icon]
    args.append("main.py")
    sh(args)

    out = os.path.join(ROOT, "dist", NAME)
    exe = os.path.join(out, NAME + ".exe")
    if not os.path.exists(exe):
        sys.exit("没有生成 exe")

    # 把使用说明一起放进去。
    # 注意: 不能把标题和分隔线写成两个相邻的字符串再乘 40 —— Python 先把相邻的
    # 字面量拼成一个再算 * 40, 结果是整个标题重复 40 遍 (以前发出去的版本就是这样)。
    # 所以逐行放进列表, 最后统一 join + format。
    sep = "=" * 40
    lines = [
        "模拟炒股 —— 免安装版", sep, "",
        "怎么用",
        "  双击「{name}.exe」就能打开, 不需要装任何东西。", "",
        "打开是英文怎么办",
        "  界面默认是英文。切成中文:",
        "    点最上面一排的「Settings」-> 第一栏「Language / 语言」",
        "    -> 选「中文」-> 点最下面的「Save Settings」-> 问要不要重启时点「Yes」",
        "  以后再打开就一直是中文了。", "",
        "这是什么",
        "  用虚拟资金练习美股交易。股价是真实的、实时的,",
        "  但账户里的钱是假的, 不涉及任何真实资金和券商。", "",
        "需要联网",
        "  行情来自网络。如果打开后价格一直是 0 或者提示加载失败,",
        "  先运行「行情连通性自检.exe」看看网络能不能访问行情源。", "",
        "我的账户存在哪",
        "  %LOCALAPPDATA%\\模拟炒股\\data\\",
        "  (在文件管理器地址栏粘贴这一行就能打开)", "",
        "  故意不放在这个文件夹里 —— 放这儿的话, 你解压新版本",
        "  覆盖旧文件夹, 账户就没了。放在上面那个位置, 换多少次",
        "  版本都不受影响。", "",
        "  程序每 20 分钟自动存一份快照到 data\\backups\\, 最近",
        "  48 小时的全留着, 更早的每天留一份。账户出问题时用",
        "  「账户管理… -> 备份」找回来。", "",
        "杀毒软件报警怎么办",
        "  PyInstaller 打包的程序有时会被误报。这个程序不联任何",
        "  除行情之外的网, 也不修改系统设置。加信任即可。", "",
        sep, "",
        "Paper Trader (portable build)", "",
        "  Double-click \"{name}.exe\" to start. Nothing to install.",
        "  Practice US stock trading with virtual money: prices are real and",
        "  live, the money is not. No real broker, no real funds.", "",
        "  Language: English by default. Settings -> Language / 语言.",
        "  Your accounts: %LOCALAPPDATA%\\模拟炒股\\data\\  (kept outside this",
        "  folder so a new version never overwrites them; snapshots every",
        "  20 minutes, restore from Accounts... -> Backups)",
    ]
    readme = os.path.join(out, "使用说明.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).format(name=NAME) + "\n")

    # 自检工具也拷一份进去
    nc = os.path.join(ROOT, "dist_netcheck", "行情连通性自检.exe")
    if os.path.exists(nc):
        shutil.copy2(nc, os.path.join(out, "行情连通性自检.exe"))

    _restore_data(safe)

    mb = size_of(out) / 1024 / 1024
    print()
    print("=" * 56)
    print("  打包完成, 用时 {:.0f} 秒".format(time.time() - t0))
    print("  目录: {}".format(out))
    print("  体积: {:.0f} MB".format(mb))
    print("  入口: {}.exe  (双击即开, 无黑窗口)".format(NAME))
    print("=" * 56)
    print("  发给别人: 把整个「{}」文件夹压缩成 zip 发过去,".format(NAME))
    print("           对方解压后双击 exe 即可。")


if __name__ == "__main__":
    main()
