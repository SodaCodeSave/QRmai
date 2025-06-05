# QRmai 打包说明

本文档详细说明了如何使用提供的脚本将QRmai打包为Windows可执行文件。

## 准备工作

QRmai使用pyzbar库进行二维码识别，在Windows系统上需要额外的DLL文件才能正常工作：

1. 下载以下两个DLL文件：
   - `libiconv.dll`
   - `libzbar-64.dll` (64位系统) 或 `libzbar-32.dll` (32位系统)

2. 将这些文件放置在 `packaging` 目录中

如果没有这些DLL文件，打包后的程序将无法正常运行二维码识别功能。

有关如何获取和安装这些DLL文件的详细说明，请参阅 [DLL_INSTALLATION.md](DLL_INSTALLATION.md) 文档。

## 打包步骤

### 方法一：使用Python脚本（推荐）

1. 确保已安装所有依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 运行打包脚本：
   ```bash
   python build_exe.py
   ```

3. 脚本将自动执行以下操作：
   - 检查必要的依赖
   - 使用PyInstaller打包程序
   - 保留控制台窗口
   - 应用最大化压缩选项
   - 处理所有依赖项和资源文件
   - 生成可执行文件到 `dist` 目录

### 方法二：使用批处理脚本

在Windows系统上，可以直接双击运行 `build.bat` 文件，该脚本会自动检查环境并执行打包过程。

## 生成的文件

打包完成后，会在 `dist` 目录中生成 `QRmai.exe` 文件，该文件包含了运行QRmai所需的所有组件。

如果提供了DLL文件，它们也会被包含在生成的可执行文件中，确保二维码识别功能正常工作。

## 运行打包后的程序

直接运行 `dist/QRmai.exe` 即可启动程序。程序会读取同目录下的 `config.json` 配置文件。

## 常见问题

### 1. 打包过程中出现错误

确保已正确安装所有依赖：
```bash
pip install -r requirements.txt
```

### 2. 打包后的程序无法运行

检查是否缺少必要的运行库，可能需要安装：
- Microsoft Visual C++ Redistributable
- .NET Framework（如果需要）

## 自定义打包参数

如果需要修改打包参数，可以直接编辑 `build_exe.py` 文件中的 `build_executable()` 函数，调整PyInstaller命令行参数。