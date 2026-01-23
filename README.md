# Yande.re Ultimate Viewer

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

一个现代化的、高性能的 Yande.re 桌面浏览客户端。基于 Python 和 PyQt6 构建，专为流畅的图片浏览和管理体验而设计。

![Screenshot](https://via.placeholder.com/800x450?text=Please+Add+A+Screenshot+Here)
*(建议在此处替换为软件实际运行截图)*

## ✨ 主要特性

*   **🚀 极致性能**：内置多级 LRU 缓存和智能预加载系统（TurboPreloader），浏览体验丝般顺滑。
*   **🎨 现代化 UI**：基于设计令牌（Design Tokens）的深色主题，提供舒适的视觉体验。
*   **🔍 强大的筛选**：支持按分数、评级（Safe/Questionable/Explicit）和标签进行实时筛选。
*   **📥 智能下载**：
    *   多线程并发下载。
    *   支持断点续传。
    *   自动按评级分类保存。
*   **💾 数据安全**：
    *   自动保存浏览历史和会话状态（续看模式）。
    *   内置备份与恢复功能，轻松迁移数据。
*   **⌨️ 键盘流操作**：全套快捷键支持，无需鼠标即可高效浏览。

## 🛠️ 安装指南

### 环境要求
*   Python 3.9 或更高版本

### 1. 克隆或下载项目
```bash
git clone https://github.com/你的用户名/yande_viewer.git
cd yande_viewer
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

## 🚀 使用方法

运行主程序：
```bash
python main.py
```

### ⌨️ 快捷键列表

| 按键 | 功能 |
| :--- | :--- |
| `→` / `←` | 下一张 / 上一张图片 |
| `Space` / `L` | ❤️ 收藏/取消收藏（并自动下载） |
| `F` | 切换全屏模式 |
| `S` | 切换浏览模式（最新 / 续看） |
| `P` | 打开设置 |
| `B` | 打开备份管理 |
| `1` - `5` | 快速设置最低分数筛选 |
| `F1` | 显示快捷键帮助 |

## ⚙️ 配置说明

软件首次运行后会在目录下生成 `config.json` 和 `user_settings.json`。
*   **基础路径**：默认下载目录为 `love/`，可在代码配置中修改。
*   **安全模式**：默认支持所有评级内容，请在设置中根据需要调整评级过滤器。

## 🤝 贡献

欢迎提交 Issue 或 Pull Request！

1. Fork 本仓库
2. 新建 Feat_xxx 分支
3. 提交代码
4. 新建 Pull Request

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源。

## ⚠️ 免责声明

本项目仅供学习交流使用。所有图片资源均来自 Yande.re，版权归原作者所有。请遵守当地法律法规使用。