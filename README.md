# QRmai

**qq交流群：1058589509 密码：SodaCodeSave/QRmai**

> 帮您在只有基本联网安卓设备（如：手表、翻盖手机）的情况下也能轻松出勤！

在服务端中获取二维码并将图片返回到客户端，灵感来源于[MaimaiHelper](https://github.com/SomeUtils/MaimaiHelper)

## 为什么使用QRmai

1. 具有更多的自定义选项
2. 兼容MaimaiHelper APP

## 下载

[123云盘](https://www.123865.com/s/4FlLVv-yI48d)

[Github Release](https://github.com/SodaCodeSave/QRmai/releases/latest)

## 使用教程

> QRMai使用微信最新版进行测试，不保证微信2可用，请尽可能使用微信最新版

1. 安装[Python3](https://www.python.org/downloads/)
2. 安装依赖

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

3. 运行main.py

```bash
python main.py
```

4. 访问http://127.0.0.1:5000/qrmai?token={你在配置文件中设置的token}

## 皮肤

将你下载好的皮肤放在程序同目录，并重命名为skin.png

制作好的皮肤可以在这里下载：[123云盘](https://www.123865.com/s/4FlLVv-yI48d)

## 配置文件

```
{
  "p1": [1087, 799], // 舞萌 | 中二服务号生成二维码按钮的位置
  "p2": [945, 682], // 生成后的二维码的消息的位置
  "token": "qrmai", // 访问二维码的token
  "host": "127.0.0.1", // 服务器地址 设置成0.0.0.0即可内网访问
  "port": 5000, // 服务器端口
  "cache_duration": 60, // 二维码缓存时间（秒），默认60秒
  "standalone_mode": false, // "舞萌丨中二"公众号是否为使用独立窗口显示
  "decode": { // 解码重试次数及时间 每次重试的时间为 time除以retry_count
    "time": 10,  // 超时时间
    "retry_count": 10  // 重试次数
  }
  "skin_format": "new", // 皮肤格式 new为新版皮肤 二维码居中 old为旧版皮肤 二维码靠下
  "dev_mode": false, // 是否开启开发模式 开启后修改代码时无需重启服务器
  "version": "259e1c35e495e4945bbfa47118aef4d2" // 版本号 用于安全检查验证
}
```

## 打包为可执行文件

本项目提供了PyInstaller打包脚本，可以将QRmai打包为独立的Windows可执行文件。

### 使用方法

1. 安装PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. 获取二维码识别所需的DLL文件:
   - 下载 `libiconv.dll` 和 `libzbar-64.dll` 文件
   - 将这些文件放置在 `packaging` 目录中

3. 进入packaging目录并运行打包脚本:
   ```bash
   cd packaging
   python build_exe.py
   ```

   或者在Windows上双击运行 `packaging/build.bat` 文件。

4. 生成的可执行文件将位于项目根目录的 `dist` 目录中。

有关详细的打包说明，请参阅 [PACKAGING.md](PACKAGING.md) 文档。