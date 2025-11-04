# QRmai DLL文件安装说明

QRmai使用pyzbar库进行二维码识别，在Windows系统上需要额外的DLL文件才能正常工作。

## 必需的DLL文件

1. `libiconv.dll` - 字符编码转换库
2. `libzbar-64.dll` - 64位系统的二维码识别库 (如果您使用32位系统，则需要`libzbar-32.dll`)

## 获取DLL文件的方法

### 方法一：从Python安装目录复制（推荐）

如果您已经安装了pyzbar库，可以尝试从Python的site-packages目录中复制这些文件：

1. 找到pyzbar库的安装目录：
   ```bash
   python -c "import pyzbar; print(pyzbar.__file__)"
   ```

2. 在该目录或其父目录中查找DLL文件

### 方法二：从GitHub仓库下载

您可以从以下GitHub仓库下载这些DLL文件：

1. 访问 https://github.com/NaturalHistoryMuseum/pyzbar/tree/master/pyzbar
2. 下载对应的DLL文件

### 方法三：使用conda安装（如果您使用conda环境）

```bash
conda install -c conda-forge pyzbar
```

然后从conda环境的Lib/site-packages/pyzbar目录中复制DLL文件。

## 安装步骤

1. 下载所需的DLL文件
2. 将这些文件放置在QRmai项目的 `packaging` 目录中
3. 运行打包脚本时，这些文件将自动包含在生成的可执行文件中

## 验证安装

打包完成后，您可以检查生成的可执行文件目录中是否包含这些DLL文件：

```bash
dir dist\
```

您应该能看到QRmai.exe、libiconv.dll和libzbar-64.dll文件。

## 常见问题

### 1. 打包后程序无法识别二维码

确保DLL文件已正确放置在packaging目录中，并且打包脚本显示已包含这些文件。

### 2. 提示缺少MSVCR120.dll

这表示您的系统缺少Visual C++ Redistributable for Visual Studio 2013。请从微软官网下载并安装相应的运行库。

### 3. DLL文件版本不兼容

确保下载的DLL文件与您的系统架构（32位或64位）匹配。