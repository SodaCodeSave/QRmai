# GitHub Actions 自动发布说明

## 概述

本项目配置了GitHub Actions工作流，用于自动构建和发布新版本的QRmai Windows可执行文件。

## 工作流触发条件

- 当`version.txt`文件被更新并推送到`main`分支时，工作流将自动触发。

## 工作流功能

1. 检测`version.txt`文件中的版本号
2. 验证版本格式
3. 检查必需的DLL文件（如果不存在则创建占位符）
4. 运行`packaging/build_exe.py`构建Windows可执行文件
5. 将生成的`QRmai.exe`重命名为`QRmai-pyinstaller-windows-{version}.exe`
6. 获取自上次发布以来的提交历史
7. 创建一个新的GitHub Release，包含：
   - 以版本号为标签和名称
   - 发布说明包含提交历史
   - 附带重命名后的可执行文件
   - 如果版本包含`-alpha`或`-beta`后缀，则作为预发布版本

## 版本格式

支持的版本格式：
- `v1.2.3` - 正式版本
- `v1.2.3-alpha` - 预发布版本（alpha）
- `v1.2.3-beta` - 预发布版本（beta）

## 注意事项

1. 此工作流假设必需的DLL文件（`libiconv.dll`和`libzbar-64.dll`）位于`packaging`目录中
2. 如果DLL文件缺失，工作流将创建占位符文件，但生成的可执行文件可能无法正常工作
3. 请确保这些DLL文件已正确获取并存放在正确的目录中

## 手动触发发布

如需手动触发发布，只需修改`version.txt`文件中的版本号并推送到`main`分支：

```
v2.1.3
```

或

```
v2.1.3-alpha
```

然后提交并推送更改：

```bash
git add version.txt
git commit -m "Update version to v2.1.3"
git push origin main
```