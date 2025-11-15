#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本检查脚本
用于检查version.txt文件是否被更新，以便在GitHub Actions中使用
"""

import sys
from pathlib import Path


def get_version_from_file(version_file_path):
    """从文件中读取版本号"""
    try:
        with open(version_file_path, 'r', encoding='utf-8') as f:
            version = f.read().strip()
        return version
    except FileNotFoundError:
        print(f"错误: 找不到版本文件 {version_file_path}")
        return None
    except Exception as e:
        print(f"读取版本文件出错: {e}")
        return None


def main():
    """主函数"""
    project_root = Path(__file__).parent.parent
    version_file = project_root / "version.txt"
    
    version = get_version_from_file(version_file)
    if version:
        print(f"VERSION={version}")
        # 也输出到环境变量文件，以便GitHub Actions使用
        if 'GITHUB_ENV' in str(Path.cwd()):
            # 在GitHub Actions环境中
            with open('env.txt', 'a') as f:
                f.write(f"VERSION={version}\n")
        return version
    else:
        print("无法读取版本信息")
        sys.exit(1)


if __name__ == "__main__":
    main()