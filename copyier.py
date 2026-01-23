#!/usr/bin/env python3
"""
项目文件复制器 - 自动遍历目录生成Markdown文档
用于快速复制项目代码给AI分析

核心改进：
1. 单击即可切换文件选中状态
2. 动态显示预估Token数
3. 生成完整目录结构（不含copy.py）
4. 深度美化的现代UI
"""

import os
import threading
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Set, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


@dataclass
class FileInfo:
    """文件信息"""
    path: Path
    relative_path: str
    size: int
    extension: str
    is_selected: tk.BooleanVar = None
    
    @property
    def size_display(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        else:
            return f"{self.size / 1024 / 1024:.1f} MB"
    
    @property
    def token_estimate(self) -> int:
        """估算token数（约2.5字符/token）"""
        return int(self.size / 2.5)


class ProjectCopier:
    """项目文件复制器"""
    
    DEFAULT_IGNORE_DIRS = {
        '__pycache__', '.git', '.svn', '.hg', 'node_modules',
        'venv', 'env', '.venv', '.env', '.idea', '.vscode',
        'dist', 'build', 'egg-info', '.eggs', '.tox',
        'cache', 'logs', 'tmp', 'temp', '.pytest_cache'
    }
    
    DEFAULT_IGNORE_FILES = {
        '.DS_Store', 'Thumbs.db', '.gitignore', '.gitattributes',
        '*.pyc', '*.pyo', '*.exe', '*.dll', '*.so', '*.dylib',
        '*.jpg', '*.jpeg', '*.png', '*.gif', '*.ico', '*.bmp',
        '*.mp3', '*.mp4', '*.avi', '*.mov', '*.zip', '*.rar',
        '*.7z', '*.tar', '*.gz', '*.pdf', '*.doc', '*.docx',
        '*.woff', '*.woff2', '*.ttf', '*.eot'
    }
    
    SELF_FILENAME = 'copy.py'
    
    EXTENSION_LANG_MAP = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx', '.html': 'html', '.css': 'css',
        '.scss': 'scss', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
        '.md': 'markdown', '.sql': 'sql', '.sh': 'bash', '.bat': 'batch',
        '.ps1': 'powershell', '.xml': 'xml', '.toml': 'toml', '.ini': 'ini',
        '.cfg': 'ini', '.txt': 'text', '.go': 'go', '.rs': 'rust',
        '.java': 'java', '.kt': 'kotlin', '.c': 'c', '.cpp': 'cpp',
        '.h': 'c', '.hpp': 'cpp', '.vue': 'vue', '.svelte': 'svelte',
    }
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("📋 项目文件复制器")
        self.root.geometry("1050x780")
        self.root.minsize(850, 650)
        
        # 现代深色配色 (Catppuccin Mocha)
        self.colors = {
            'bg': '#11111b',
            'surface': '#1e1e2e',
            'surface_alt': '#313244',
            'overlay': '#45475a',
            'border': '#585b70',
            'text': '#cdd6f4',
            'subtext': '#a6adc8',
            'accent': '#cba6f7',
            'accent_alt': '#b4befe',
            'success': '#a6e3a1',
            'warning': '#f9e2af',
            'error': '#f38ba8',
            'info': '#89dceb',
        }
        
        self.root.configure(bg=self.colors['bg'])
        
        self.base_dir: Optional[Path] = None
        self.files: Dict[str, FileInfo] = {}
        self.all_scanned_files: Dict[str, FileInfo] = {}
        self.tree_items: Dict[str, str] = {}
        
        self._setup_styles()
        self._setup_ui()
        self._auto_detect_directory()
    
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure("Custom.Treeview",
            background=self.colors['surface'],
            foreground=self.colors['text'],
            fieldbackground=self.colors['surface'],
            borderwidth=0, rowheight=30,
            font=('Cascadia Code', 10))
        
        style.configure("Custom.Treeview.Heading",
            background=self.colors['surface_alt'],
            foreground=self.colors['text'],
            borderwidth=0, relief='flat',
            font=('Segoe UI', 10, 'bold'))
        
        style.map("Custom.Treeview",
            background=[('selected', self.colors['overlay'])],
            foreground=[('selected', self.colors['accent'])])
        
        style.configure("Custom.Vertical.TScrollbar",
            background=self.colors['overlay'],
            troughcolor=self.colors['surface'],
            borderwidth=0, arrowsize=0, width=8)
        
        style.configure("Accent.Horizontal.TProgressbar",
            background=self.colors['accent'],
            troughcolor=self.colors['surface_alt'],
            borderwidth=0, lightcolor=self.colors['accent'],
            darkcolor=self.colors['accent'])
    
    def _create_button(self, parent, text, command, variant='secondary', **kwargs):
        """创建风格统一的按钮"""
        variants = {
            'primary': (self.colors['accent'], '#000000', self.colors['accent_alt']),
            'secondary': (self.colors['surface_alt'], self.colors['text'], self.colors['overlay']),
            'success': (self.colors['success'], '#000000', '#b8f0b0'),
            'ghost': (self.colors['surface'], self.colors['subtext'], self.colors['surface_alt']),
        }
        bg, fg, hover = variants.get(variant, variants['secondary'])
        
        btn = tk.Button(parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
            relief=tk.FLAT, cursor='hand2', bd=0, highlightthickness=0,
            font=kwargs.pop('font', ('Segoe UI', 10)),
            padx=kwargs.pop('padx', 16), pady=kwargs.pop('pady', 8), **kwargs)
        
        btn.bind('<Enter>', lambda e: btn.config(bg=hover))
        btn.bind('<Leave>', lambda e: btn.config(bg=bg))
        return btn
    
    def _setup_ui(self):
        main = tk.Frame(self.root, bg=self.colors['bg'])
        main.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
        
        # === 标题区 ===
        header = tk.Frame(main, bg=self.colors['bg'])
        header.pack(fill=tk.X, pady=(0, 16))
        
        tk.Label(header, text="📋 项目文件复制器",
            bg=self.colors['bg'], fg=self.colors['text'],
            font=('Segoe UI', 20, 'bold')).pack(side=tk.LEFT)
        
        tk.Label(header, text="  快速复制项目代码给AI分析",
            bg=self.colors['bg'], fg=self.colors['subtext'],
            font=('Segoe UI', 11)).pack(side=tk.LEFT, pady=(6, 0))
        
        # === 目录选择卡片 ===
        dir_card = tk.Frame(main, bg=self.colors['surface'])
        dir_card.pack(fill=tk.X, pady=(0, 12), ipady=12, ipadx=16)
        
        tk.Label(dir_card, text="📁 项目目录",
            bg=self.colors['surface'], fg=self.colors['subtext'],
            font=('Segoe UI', 9)).pack(anchor='w', padx=4)
        
        dir_row = tk.Frame(dir_card, bg=self.colors['surface'])
        dir_row.pack(fill=tk.X, pady=(6, 0))
        
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(dir_row, textvariable=self.path_var,
            bg=self.colors['surface_alt'], fg=self.colors['text'],
            insertbackground=self.colors['text'], font=('Cascadia Code', 11),
            relief=tk.FLAT, highlightthickness=2,
            highlightbackground=self.colors['border'],
            highlightcolor=self.colors['accent'])
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        self.path_entry.bind('<Return>', lambda e: self._scan_directory())
        
        btn_box = tk.Frame(dir_row, bg=self.colors['surface'])
        btn_box.pack(side=tk.RIGHT, padx=(12, 0))
        
        self._create_button(btn_box, "📂 浏览", self._browse_directory
            ).pack(side=tk.LEFT, padx=(0, 8))
        self.btn_scan = self._create_button(btn_box, "🔍 扫描目录",
            self._scan_directory, 'primary')
        self.btn_scan.pack(side=tk.LEFT)
        
        # === 工具栏 ===
        toolbar = tk.Frame(main, bg=self.colors['bg'])
        toolbar.pack(fill=tk.X, pady=(0, 8))
        
        left_bar = tk.Frame(toolbar, bg=self.colors['bg'])
        left_bar.pack(side=tk.LEFT)
        
        quick_btns = [
            ("☑ 全选", lambda: self._select_all(True), self.colors['success']),
            ("☐ 取消全选", lambda: self._select_all(False), self.colors['subtext']),
            ("🐍 仅.py", lambda: self._select_by_ext({'.py'}), self.colors['warning']),
            ("📝 代码文件", lambda: self._select_by_ext(set(self.EXTENSION_LANG_MAP.keys())), self.colors['info']),
        ]
        for txt, cmd, clr in quick_btns:
            b = tk.Button(left_bar, text=txt, command=cmd,
                bg=self.colors['surface'], fg=clr,
                activebackground=self.colors['surface_alt'], activeforeground=clr,
                relief=tk.FLAT, cursor='hand2', font=('Segoe UI', 9), padx=10, pady=5, bd=0)
            b.pack(side=tk.LEFT, padx=2)
            b.bind('<Enter>', lambda e, btn=b: btn.config(bg=self.colors['surface_alt']))
            b.bind('<Leave>', lambda e, btn=b: btn.config(bg=self.colors['surface']))
        
        tk.Label(toolbar, text="💡 单击切换选中 | 空格键批量切换",
            bg=self.colors['bg'], fg=self.colors['subtext'],
            font=('Segoe UI', 9)).pack(side=tk.RIGHT)
        
        # === 文件树卡片 ===
        tree_card = tk.Frame(main, bg=self.colors['surface'])
        tree_card.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        
        tree_header = tk.Frame(tree_card, bg=self.colors['surface_alt'], height=42)
        tree_header.pack(fill=tk.X)
        tree_header.pack_propagate(False)
        
        tk.Label(tree_header, text="📂 文件列表",
            bg=self.colors['surface_alt'], fg=self.colors['text'],
            font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=16, pady=10)
        
        self.lbl_file_count = tk.Label(tree_header, text="",
            bg=self.colors['surface_alt'], fg=self.colors['subtext'],
            font=('Segoe UI', 9))
        self.lbl_file_count.pack(side=tk.RIGHT, padx=16)
        
        tree_box = tk.Frame(tree_card, bg=self.colors['surface'])
        tree_box.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        cols = ('size', 'tokens', 'status')
        self.tree = ttk.Treeview(tree_box, columns=cols, show='tree headings',
            style='Custom.Treeview', selectmode='extended')
        
        self.tree.heading('#0', text='文件名', anchor='w')
        self.tree.heading('size', text='大小', anchor='e')
        self.tree.heading('tokens', text='预估Token', anchor='e')
        self.tree.heading('status', text='选中', anchor='center')
        
        self.tree.column('#0', width=480, minwidth=280)
        self.tree.column('size', width=90, minwidth=70, anchor='e')
        self.tree.column('tokens', width=100, minwidth=80, anchor='e')
        self.tree.column('status', width=65, minwidth=55, anchor='center')
        
        vsb = ttk.Scrollbar(tree_box, orient=tk.VERTICAL, command=self.tree.yview,
            style='Custom.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 核心改进：单击切换
        self.tree.bind('<ButtonRelease-1>', self._on_single_click)
        self.tree.bind('<space>', self._on_space_key)
        self.tree.bind('<Return>', self._on_space_key)
        
        self.tree.tag_configure('selected', foreground=self.colors['success'])
        self.tree.tag_configure('unselected', foreground=self.colors['subtext'])
        self.tree.tag_configure('dir', foreground=self.colors['text'])
        
        # === 底部统计栏 ===
        bottom = tk.Frame(main, bg=self.colors['surface'])
        bottom.pack(fill=tk.X, ipady=14, ipadx=20)
        
        stats = tk.Frame(bottom, bg=self.colors['surface'])
        stats.pack(side=tk.LEFT, fill=tk.Y)
        
        token_row = tk.Frame(stats, bg=self.colors['surface'])
        token_row.pack(anchor='w')
        
        self.lbl_tokens = tk.Label(token_row, text="0",
            bg=self.colors['surface'], fg=self.colors['accent'],
            font=('Segoe UI', 32, 'bold'))
        self.lbl_tokens.pack(side=tk.LEFT)
        
        tk.Label(token_row, text=" 预估 Tokens",
            bg=self.colors['surface'], fg=self.colors['subtext'],
            font=('Segoe UI', 12)).pack(side=tk.LEFT, pady=(12, 0))
        
        self.lbl_details = tk.Label(stats,
            text="选中 0 个文件 · 0 B · ~0 字符",
            bg=self.colors['surface'], fg=self.colors['subtext'],
            font=('Segoe UI', 10))
        self.lbl_details.pack(anchor='w', pady=(4, 0))
        
        self.progress = ttk.Progressbar(stats, length=380, mode='determinate',
            style='Accent.Horizontal.TProgressbar')
        self.progress.pack(anchor='w', pady=(10, 0))
        
        self.lbl_progress = tk.Label(stats, text="",
            bg=self.colors['surface'], fg=self.colors['subtext'],
            font=('Segoe UI', 9))
        self.lbl_progress.pack(anchor='w', pady=(4, 0))
        
        btn_col = tk.Frame(bottom, bg=self.colors['surface'])
        btn_col.pack(side=tk.RIGHT)
        
        self.btn_copy = self._create_button(btn_col, "📋 复制到剪贴板",
            self._copy_to_clipboard, 'success',
            font=('Segoe UI', 12, 'bold'), padx=28, pady=14)
        self.btn_copy.pack(pady=(0, 10))
        
        self._create_button(btn_col, "💾 保存为文件",
            self._save_to_file).pack()
    
    def _auto_detect_directory(self):
        self.path_var.set(str(Path.cwd()))
    
    def _browse_directory(self):
        path = filedialog.askdirectory(title="选择项目目录",
            initialdir=self.path_var.get() or str(Path.cwd()))
        if path:
            self.path_var.set(path)
            self._scan_directory()
    
    def _scan_directory(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("警告", "请先选择目录")
            return
        
        self.base_dir = Path(path)
        if not self.base_dir.exists():
            messagebox.showerror("错误", f"目录不存在: {path}")
            return
        
        self.files.clear()
        self.all_scanned_files.clear()
        self.tree_items.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.btn_scan.config(state=tk.DISABLED)
        self.progress['value'] = 0
        threading.Thread(target=self._do_scan, daemon=True).start()
    
    def _do_scan(self):
        try:
            files = []
            for root, dirs, filenames in os.walk(self.base_dir):
                dirs[:] = [d for d in dirs if d not in self.DEFAULT_IGNORE_DIRS]
                for fn in filenames:
                    if fn == self.SELF_FILENAME or self._should_ignore(fn):
                        continue
                    fp = Path(root) / fn
                    try:
                        sz = fp.stat().st_size
                        rel = str(fp.relative_to(self.base_dir))
                        files.append(FileInfo(fp, rel, sz, fp.suffix.lower(),
                            tk.BooleanVar(value=True)))
                    except: pass
            self.root.after(0, lambda: self._populate_tree(files))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("扫描错误", str(e)))
        finally:
            self.root.after(0, lambda: self.btn_scan.config(state=tk.NORMAL))
    
    def _should_ignore(self, fn: str) -> bool:
        if fn in self.DEFAULT_IGNORE_FILES:
            return True
        for p in self.DEFAULT_IGNORE_FILES:
            if p.startswith('*') and fn.endswith(p[1:]):
                return True
        return False
    
    def _populate_tree(self, files: List[FileInfo]):
        dirs = {}
        root_id = self.tree.insert('', 'end', text=f"📁 {self.base_dir.name}",
            open=True, tags=('dir',))
        dirs[''] = root_id
        
        files.sort(key=lambda f: f.relative_path.lower())
        
        for fi in files:
            self.files[fi.relative_path] = fi
            self.all_scanned_files[fi.relative_path] = fi
            
            parts = Path(fi.relative_path).parts
            cur = ''
            parent = root_id
            
            for i, part in enumerate(parts[:-1]):
                cur = str(Path(cur) / part) if cur else part
                if cur not in dirs:
                    dirs[cur] = self.tree.insert(parent, 'end',
                        text=f"📂 {part}", open=True, tags=('dir',))
                parent = dirs[cur]
            
            icon = self._icon(fi.extension)
            iid = self.tree.insert(parent, 'end',
                text=f"{icon} {parts[-1]}",
                values=(fi.size_display, f"~{fi.token_estimate:,}", '☑'),
                tags=('file', 'selected'))
            self.tree_items[fi.relative_path] = iid
        
        self.lbl_file_count.config(text=f"共 {len(files)} 个文件")
        self._update_stats()
    
    def _icon(self, ext: str) -> str:
        icons = {'.py':'🐍','.js':'📜','.ts':'📘','.json':'📋','.md':'📝',
            '.txt':'📄','.html':'🌐','.css':'🎨','.yaml':'⚙️','.yml':'⚙️',
            '.toml':'⚙️','.sh':'🔧','.sql':'🗃️','.vue':'💚','.go':'🔵'}
        return icons.get(ext, '📄')
    
    # === 核心改进：单击切换 ===
    def _on_single_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        for path, iid in self.tree_items.items():
            if iid == item:
                self._toggle(iid, path)
                break
    
    def _on_space_key(self, event=None):
        for item in self.tree.selection():
            for path, iid in self.tree_items.items():
                if iid == item:
                    self._toggle(iid, path)
                    break
    
    def _toggle(self, iid: str, path: str):
        fi = self.files[path]
        new = not fi.is_selected.get()
        fi.is_selected.set(new)
        if new:
            self.tree.item(iid, tags=('file', 'selected'))
            self.tree.set(iid, 'status', '☑')
        else:
            self.tree.item(iid, tags=('file', 'unselected'))
            self.tree.set(iid, 'status', '☐')
        self._update_stats()
    
    def _select_all(self, sel: bool):
        for path, fi in self.files.items():
            fi.is_selected.set(sel)
            iid = self.tree_items[path]
            self.tree.item(iid, tags=('file', 'selected' if sel else 'unselected'))
            self.tree.set(iid, 'status', '☑' if sel else '☐')
        self._update_stats()
    
    def _select_by_ext(self, exts: Set[str]):
        for path, fi in self.files.items():
            sel = fi.extension in exts
            fi.is_selected.set(sel)
            iid = self.tree_items[path]
            self.tree.item(iid, tags=('file', 'selected' if sel else 'unselected'))
            self.tree.set(iid, 'status', '☑' if sel else '☐')
        self._update_stats()
    
    def _update_stats(self):
        sel = [f for f in self.files.values() if f.is_selected.get()]
        cnt = len(sel)
        chars = sum(f.size for f in sel)
        tokens = sum(f.token_estimate for f in sel)
        sz = sum(f.size for f in sel)
        
        sz_str = f"{sz} B" if sz < 1024 else (
            f"{sz/1024:.1f} KB" if sz < 1024**2 else f"{sz/1024**2:.1f} MB")
        
        self.lbl_tokens.config(text=f"{tokens:,}")
        self.lbl_details.config(text=f"选中 {cnt} 个文件 · {sz_str} · ~{chars:,} 字符")
        
        limit = 128000
        pct = min(100, tokens / limit * 100)
        self.progress['value'] = pct
        
        if tokens > limit:
            self.lbl_progress.config(text="⚠️ 超出128K Token限制", fg=self.colors['error'])
            self.lbl_tokens.config(fg=self.colors['error'])
        elif tokens > limit * 0.8:
            self.lbl_progress.config(text=f"⚡ 接近限制 ({pct:.0f}%)", fg=self.colors['warning'])
            self.lbl_tokens.config(fg=self.colors['warning'])
        else:
            self.lbl_progress.config(text=f"✅ Token用量 {pct:.0f}%", fg=self.colors['success'])
            self.lbl_tokens.config(fg=self.colors['accent'])
    
    def _generate_content(self) -> str:
        lines = [f"# {self.base_dir.name} - 项目源码", "",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
            "## 项目结构", "", "```text"]
        lines.extend(self._gen_tree())
        lines.extend(["```", ""])
        
        sel = sorted([(p, f) for p, f in self.files.items() if f.is_selected.get()],
            key=lambda x: x[0].lower())
        
        for path, fi in sel:
            lang = self.EXTENSION_LANG_MAP.get(fi.extension, 'text')
            lines.extend([f"## 📄 {path}", "", f"```{lang}"])
            try:
                txt = fi.path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                try: txt = fi.path.read_text(encoding='gbk')
                except: txt = "# 无法读取"
            except: txt = "# 读取错误"
            lines.extend([txt.rstrip(), "```", "", "---", ""])
        
        return '\n'.join(lines)
    
    def _gen_tree(self) -> List[str]:
        """生成完整目录结构（不含copy.py）"""
        lines = [f"{self.base_dir.name}/"]
        paths = set(self.all_scanned_files.keys())
        
        dirs = {}
        for p in paths:
            parts = Path(p).parts
            for i in range(len(parts)):
                dp = '/'.join(parts[:i]) if i else ''
                if dp not in dirs:
                    dirs[dp] = set()
                dirs[dp].add((parts[i], i == len(parts) - 1))
        
        def walk(dp: str, pfx: str):
            if dp not in dirs:
                return
            items = sorted(dirs[dp], key=lambda x: (x[1], x[0].lower()))
            for i, (name, is_file) in enumerate(items):
                last = i == len(items) - 1
                conn = "└── " if last else "├── "
                lines.append(f"{pfx}{conn}{name}{'/' if not is_file else ''}")
                if not is_file:
                    walk(f"{dp}/{name}" if dp else name,
                        pfx + ("    " if last else "│   "))
        
        walk('', '')
        return lines
    
    def _copy_to_clipboard(self):
        if not self.files:
            messagebox.showwarning("警告", "请先扫描目录")
            return
        cnt = sum(1 for f in self.files.values() if f.is_selected.get())
        if not cnt:
            messagebox.showwarning("警告", "请至少选择一个文件")
            return
        
        try:
            content = self._generate_content()
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update()
            
            tokens = int(len(content) / 2.5)
            messagebox.showinfo("✅ 复制成功",
                f"已复制到剪贴板!\n\n"
                f"📁 {cnt} 个文件\n"
                f"📝 {len(content):,} 字符\n"
                f"🎯 ~{tokens:,} Tokens")
        except Exception as e:
            messagebox.showerror("错误", f"复制失败: {e}")
    
    def _save_to_file(self):
        if not self.files:
            messagebox.showwarning("警告", "请先扫描目录")
            return
        cnt = sum(1 for f in self.files.values() if f.is_selected.get())
        if not cnt:
            messagebox.showwarning("警告", "请至少选择一个文件")
            return
        
        fp = filedialog.asksaveasfilename(title="保存Markdown文件",
            defaultextension=".md", initialfile=f"{self.base_dir.name}_source.md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All", "*.*")])
        if not fp:
            return
        
        try:
            content = self._generate_content()
            Path(fp).write_text(content, encoding='utf-8')
            tokens = int(len(content) / 2.5)
            messagebox.showinfo("✅ 保存成功",
                f"已保存到:\n{fp}\n\n"
                f"📁 {cnt} 个文件\n"
                f"📝 {len(content):,} 字符\n"
                f"🎯 ~{tokens:,} Tokens")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    ProjectCopier(root)
    root.mainloop()


if __name__ == "__main__":
    main()