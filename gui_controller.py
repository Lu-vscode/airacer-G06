#!/usr/bin/env python3
"""AI Racer 图形化控制程序

一个完整的 GUI 应用，封装 sdk/run_local.py 的所有功能：
- 单车和多车模式
- 控制器文件选择
- 赛道和车位选择
- 队伍ID配置
- 高级选项（快速模式、最小化、批量）
- 实时日志显示
- 启动/停止仿真
- 配置保存/加载
- 一键测试预设
"""

import sys
import os
import json
import pathlib
import subprocess
import threading
import tkinter as tk
from tkinter import Tk, ttk, filedialog, messagebox, scrolledtext, Listbox
from tkinter import BOTH, LEFT, RIGHT, TOP, BOTTOM, X, Y, END

# 添加 SDK 到 Python 路径
SDK_DIR = pathlib.Path(__file__).resolve().parent / "sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from worlds import WORLDS, DEFAULT_WORLD_KEY


class CarEntry:
    """表示一个车辆配置"""
    def __init__(self, controller_path: str, slot: str = "car_1", team: str = "local_team"):
        # 存储相对路径，如果已经是相对路径就直接使用
        path_obj = pathlib.Path(controller_path)
        if path_obj.is_absolute():
            # 如果是绝对路径，尝试转换为相对路径
            try:
                self.controller_path = str(path_obj.relative_to(pathlib.Path.cwd()))
            except ValueError:
                # 无法转换为相对路径，保持绝对路径
                self.controller_path = str(path_obj)
        else:
            # 已经是相对路径，直接使用
            self.controller_path = str(path_obj)
        self.slot = slot
        self.team = team

    def to_spec(self) -> str:
        """转换为 --car 格式: 相对路径:slot:team"""
        return f"{self.controller_path}:{self.slot}:{self.team}"

    def __repr__(self):
        filename = pathlib.Path(self.controller_path).name
        return f"{filename} ({self.slot}/{self.team})"


class ConfigManager:
    """配置管理器"""
    CONFIG_DIR = pathlib.Path.cwd() / ".gui_configs"
    
    @classmethod
    def init(cls):
        """初始化配置目录"""
        cls.CONFIG_DIR.mkdir(exist_ok=True)
    
    @classmethod
    def save_config(cls, name: str, config: dict) -> bool:
        """保存配置"""
        try:
            config_file = cls.CONFIG_DIR / f"{name}.json"
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False
    
    @classmethod
    def load_config(cls, name: str) -> dict:
        """加载配置"""
        try:
            config_file = cls.CONFIG_DIR / f"{name}.json"
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
        return None
    
    @classmethod
    def list_configs(cls) -> list:
        """列出所有配置"""
        if not cls.CONFIG_DIR.exists():
            return []
        configs = [f.stem for f in cls.CONFIG_DIR.glob("*.json")]
        return sorted(configs)
    
    @classmethod
    def delete_config(cls, name: str) -> bool:
        """删除配置"""
        try:
            config_file = cls.CONFIG_DIR / f"{name}.json"
            if config_file.exists():
                config_file.unlink()
            return True
        except Exception as e:
            print(f"删除配置失败: {e}")
            return False


class AiRacerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Racer 图形化控制程序")
        self.root.geometry("1000x750")
        
        # 初始化配置管理器
        ConfigManager.init()
        
        # 状态
        self.process = None
        self.cars = []  # 车辆列表
        self.selected_world = DEFAULT_WORLD_KEY
        
        # 初始化所有 UI 组件变量
        self.world_var = None
        self.world_desc_label = None
        self.slots_label = None
        self.mode_var = None
        self.code_path_var = None
        self.slot_combo = None
        self.car_slot_var = None
        self.team_id_var = None
        self.cars_listbox = None
        self.fast_var = None
        self.minimize_var = None
        self.batch_var = None
        self.validate_only_var = None
        self.skip_validate_var = None
        self.webots_var = None
        self.log_text = None
        self.start_button = None
        self.stop_button = None
        self.single_frame = None
        self.multi_frame = None
        self.config_name_var = None
        self.config_listbox = None
        
        self._build_ui()
        self._load_config_list()
    
    def _build_ui(self):
        """构建用户界面"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=BOTH, expand=True)
        
        # 左侧配置区 - 使用 Canvas 实现可滚动
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        
        # 创建 Canvas 和 Scrollbar
        canvas = tk.Canvas(left_frame, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", tags="scrollable_window")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("scrollable_window", width=e.width))
        
        # 鼠标滚轮支持
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        # 在可滚动框架中构建所有配置面板
        self._build_preset_panel(scrollable_frame)
        self._build_config_panel(scrollable_frame)
        
        # 右侧日志区
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=RIGHT, fill=BOTH, expand=True)
        
        self._build_log_panel(right_frame)
    
    def _build_preset_panel(self, parent):
        """构建预设和配置管理面板"""
        preset_frame = ttk.LabelFrame(parent, text="测试预设", padding="10")
        preset_frame.pack(fill=BOTH, expand=False, padx=5, pady=5)
        
        # 配置名称输入
        ttk.Label(preset_frame, text="配置名:").grid(row=0, column=0, sticky="w", pady=5)
        self.config_name_var = tk.StringVar()
        ttk.Entry(preset_frame, textvariable=self.config_name_var, width=28).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=5
        )
        
        # 保存和加载按钮
        button_frame1 = ttk.Frame(preset_frame)
        button_frame1.grid(row=1, column=0, columnspan=3, sticky="ew", pady=5)
        
        ttk.Button(
            button_frame1, text="保存配置", width=12,
            command=self._save_preset
        ).pack(side=LEFT, padx=2, fill=X, expand=True)
        
        ttk.Button(
            button_frame1, text="删除配置", width=12,
            command=self._delete_preset
        ).pack(side=LEFT, padx=2, fill=X, expand=True)
        
        # 配置列表
        ttk.Label(preset_frame, text="已保存的配置:").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 5))
        
        scrollbar = ttk.Scrollbar(preset_frame)
        scrollbar.grid(row=3, column=2, sticky="ns", padx=(0, 5), pady=5)
        
        self.config_listbox = Listbox(preset_frame, yscrollcommand=scrollbar.set, height=6, width=33)
        self.config_listbox.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.config_listbox.bind('<<ListboxSelect>>', self._on_config_selected)
        scrollbar.config(command=self.config_listbox.yview)
        
        # 一键启动按钮
        ttk.Button(
            preset_frame, text="一键启动选中配置", width=32,
            command=self._quick_start_preset
        ).grid(row=4, column=0, columnspan=3, sticky="ew", padx=5, pady=10)
        
        preset_frame.columnconfigure(1, weight=1)
    
    def _build_config_panel(self, parent):
        """构建配置区"""
        config_frame = ttk.LabelFrame(parent, text="仿真配置", padding="10")
        config_frame.pack(fill=BOTH, expand=False, padx=5, pady=5)
        
        # 赛道选择
        ttk.Label(config_frame, text="赛道:").grid(row=0, column=0, sticky="w", pady=5)
        self.world_var = ttk.Combobox(
            config_frame,
            values=list(WORLDS.keys()),
            state="readonly",
            width=30
        )
        self.world_var.set(DEFAULT_WORLD_KEY)
        self.world_var.grid(row=0, column=1, sticky="ew", pady=5)
        self.world_var.bind("<<ComboboxSelected>>", self._on_world_changed)
        
        # 赛道描述
        self.world_desc_label = ttk.Label(config_frame, text="", wraplength=280, justify="left")
        self.world_desc_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        
        # 车位显示
        ttk.Label(config_frame, text="可用车位:").grid(row=2, column=0, sticky="nw", pady=5)
        self.slots_label = ttk.Label(config_frame, text="", justify="left")
        self.slots_label.grid(row=2, column=1, sticky="w", pady=5)
        
        # 初始化世界信息
        self._update_world_info()
        
        # 分隔线
        ttk.Separator(config_frame, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=10
        )
        
        # 单车/多车模式切换
        ttk.Label(config_frame, text="模式:").grid(row=4, column=0, sticky="w", pady=5)
        self.mode_var = tk.StringVar(value="single")
        mode_frame = ttk.Frame(config_frame)
        mode_frame.grid(row=4, column=1, sticky="w", pady=5)
        ttk.Radiobutton(
            mode_frame, text="单车模式", variable=self.mode_var, value="single",
            command=self._on_mode_changed
        ).pack(side=LEFT, padx=5)
        ttk.Radiobutton(
            mode_frame, text="多车模式", variable=self.mode_var, value="multi",
            command=self._on_mode_changed
        ).pack(side=LEFT, padx=5)
        
        # 分隔线
        ttk.Separator(config_frame, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=10
        )
        
        # 单车模式配置
        self.single_frame = ttk.LabelFrame(config_frame, text="单车配置", padding="5")
        self.single_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=5)
        
        # 控制器文件
        ttk.Label(self.single_frame, text="控制器:").grid(row=0, column=0, sticky="w", pady=5)
        self.code_path_var = tk.StringVar()
        code_path_entry = ttk.Entry(self.single_frame, textvariable=self.code_path_var, width=25)
        code_path_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(
            self.single_frame, text="浏览",
            command=self._browse_controller
        ).grid(row=0, column=2, padx=5, pady=5)
        
        # 车位选择
        ttk.Label(self.single_frame, text="车位:").grid(row=1, column=0, sticky="w", pady=5)
        self.car_slot_var = tk.StringVar(value="car_1")
        self.slot_combo = ttk.Combobox(
            self.single_frame,
            textvariable=self.car_slot_var,
            width=25,
            state="readonly"
        )
        self.slot_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        self._update_slot_combo()
        
        # 队伍ID
        ttk.Label(self.single_frame, text="队伍ID:").grid(row=2, column=0, sticky="w", pady=5)
        self.team_id_var = tk.StringVar(value="local_team")
        ttk.Entry(self.single_frame, textvariable=self.team_id_var, width=25).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=5
        )
        
        # 多车模式配置
        self.multi_frame = ttk.LabelFrame(config_frame, text="多车配置", padding="5")
        self.multi_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=5)
        
        # 车辆列表
        list_frame = ttk.Frame(self.multi_frame)
        list_frame.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        ttk.Label(list_frame, text="车辆列表:").pack(anchor="w")
        
        # 列表框
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        self.cars_listbox = Listbox(list_frame, yscrollcommand=scrollbar.set, height=5)
        self.cars_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.config(command=self.cars_listbox.yview)
        
        # 添加/删除按钮
        button_frame = ttk.Frame(self.multi_frame)
        button_frame.pack(fill=X, padx=5, pady=5)
        
        ttk.Button(
            button_frame, text="添加车辆",
            command=self._add_car
        ).pack(side=LEFT, padx=2)
        
        ttk.Button(
            button_frame, text="删除选中",
            command=self._remove_car
        ).pack(side=LEFT, padx=2)
        
        # 初始隐藏多车模式
        self.multi_frame.grid_remove()
        
        # 分隔线
        ttk.Separator(config_frame, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=10
        )
        
        # 高级选项
        advanced_frame = ttk.LabelFrame(config_frame, text="高级选项", padding="5")
        advanced_frame.grid(row=9, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.fast_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame, text="快速模式 (--mode=fast)",
            variable=self.fast_var
        ).pack(anchor="w", pady=2)
        
        self.minimize_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame, text="最小化窗口",
            variable=self.minimize_var
        ).pack(anchor="w", pady=2)
        
        self.batch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame, text="批量模式 (--batch)",
            variable=self.batch_var
        ).pack(anchor="w", pady=2)
        
        self.validate_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame, text="仅校验代码",
            variable=self.validate_only_var
        ).pack(anchor="w", pady=2)
        
        self.skip_validate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame, text="跳过校验",
            variable=self.skip_validate_var
        ).pack(anchor="w", pady=2)
        
        # Webots 路径
        ttk.Label(advanced_frame, text="Webots 路径:").pack(anchor="w", pady=5)
        self.webots_var = tk.StringVar()
        webots_entry = ttk.Entry(advanced_frame, textvariable=self.webots_var, width=25)
        webots_entry.pack(fill=X, padx=5, pady=2)
        ttk.Button(
            advanced_frame, text="浏览",
            command=self._browse_webots
        ).pack(anchor="w", padx=5, pady=2)
        
        # 分隔线
        ttk.Separator(config_frame, orient="horizontal").grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=10
        )
        
        # 启动/停止按钮
        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=11, column=0, columnspan=2, sticky="ew", pady=10)
        
        self.start_button = ttk.Button(
            button_frame, text="启动仿真",
            command=self._start_simulation
        )
        self.start_button.pack(side=LEFT, padx=5, fill=X, expand=True)
        
        self.stop_button = ttk.Button(
            button_frame, text="停止仿真",
            command=self._stop_simulation,
            state="disabled"
        )
        self.stop_button.pack(side=LEFT, padx=5, fill=X, expand=True)
        
        # 配置栅栏布局权重
        config_frame.columnconfigure(1, weight=1)
        self.single_frame.columnconfigure(1, weight=1)
    
    def _build_log_panel(self, parent):
        """构建日志区"""
        log_frame = ttk.LabelFrame(parent, text="执行日志", padding="5")
        log_frame.pack(fill=BOTH, expand=True)
        
        # 日志文本框
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=30,
            width=50,
            state="normal"
        )
        self.log_text.pack(fill=BOTH, expand=True)
    
    def _log(self, message: str):
        """添加日志"""
        self.log_text.config(state="normal")
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.log_text.config(state="disabled")
        self.root.update()
    
    def _on_world_changed(self, event=None):
        """赛道改变时的回调"""
        self.selected_world = self.world_var.get()
        self._update_world_info()
        self._update_slot_combo()
    
    def _update_world_info(self):
        """更新赛道信息"""
        if self.world_desc_label is None or self.slots_label is None:
            return
        
        world = WORLDS.get(self.selected_world)
        if world:
            desc = f"{world.title}\n{world.description}"
            self.world_desc_label.config(text=desc)
            self._update_slots_info()
    
    def _update_slots_info(self):
        """更新车位信息"""
        if self.slots_label is None:
            return
        
        world = WORLDS.get(self.selected_world)
        if world:
            entries = [f"{slot}: {model.label()}" for slot, model in world.cars.items()]
            if len(entries) <= 2:
                slots_text = "，".join(entries)
            else:
                mid = (len(entries) + 1) // 2
                slots_text = "，".join(entries[:mid]) + "\n" + "，".join(entries[mid:])
            self.slots_label.config(text=slots_text)
    
    def _update_slot_combo(self):
        """更新车位下拉菜单"""
        if self.slot_combo is None:
            return
        
        world = WORLDS.get(self.selected_world)
        if world:
            slots = list(world.cars.keys())
            self.slot_combo.config(values=slots)
            if self.car_slot_var.get() not in slots:
                self.car_slot_var.set(slots[0] if slots else "car_1")
    
    def _on_mode_changed(self):
        """模式改变时的回调"""
        if self.mode_var.get() == "single":
            self.single_frame.grid()
            self.multi_frame.grid_remove()
        else:
            self.single_frame.grid_remove()
            self.multi_frame.grid()
    
    def _browse_controller(self):
        """浏览控制器文件"""
        filename = filedialog.askopenfilename(
            title="选择控制器文件",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
            initialdir=str(pathlib.Path.cwd() / "controllers")
        )
        if filename:
            # 转换为相对路径显示
            try:
                rel_path = pathlib.Path(filename).relative_to(pathlib.Path.cwd())
                display_path = str(rel_path)
            except ValueError:
                display_path = filename
            self.code_path_var.set(display_path)
    
    def _browse_webots(self):
        """浏览 Webots 可执行文件"""
        filename = filedialog.askopenfilename(
            title="选择 Webots 可执行文件",
            filetypes=[
                ("Executables", "*.exe" if sys.platform == "win32" else "*"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.webots_var.set(filename)
    
    def _add_car(self):
        """添加车辆"""
        # 创建添加车辆对话框 - 使用 Toplevel 而不是 Tk
        add_window = tk.Toplevel(self.root)
        add_window.title("添加车辆")
        add_window.geometry("450x280")
        add_window.resizable(False, False)
        
        frame = ttk.Frame(add_window, padding="15")
        frame.pack(fill=BOTH, expand=True)
        
        # 控制器
        ttk.Label(frame, text="控制器文件:").grid(row=0, column=0, sticky="w", pady=8)
        controller_var = tk.StringVar()
        controller_entry = ttk.Entry(frame, textvariable=controller_var, width=35)
        controller_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=8)
        
        def browse_controller():
            """浏览并选择控制器文件"""
            filename = filedialog.askopenfilename(
                parent=add_window,
                title="选择控制器文件",
                filetypes=[("Python files", "*.py"), ("All files", "*.*")],
                initialdir=str(pathlib.Path.cwd() / "controllers")
            )
            if filename:
                # 转换为相对路径显示
                try:
                    rel_path = pathlib.Path(filename).relative_to(pathlib.Path.cwd())
                    display_path = str(rel_path)
                except ValueError:
                    display_path = filename
                controller_var.set(display_path)
                controller_entry.xview_moveto(len(display_path))  # 滚动到末尾显示文件名
        
        ttk.Button(frame, text="浏览...", command=browse_controller, width=10).grid(
            row=0, column=2, padx=5, pady=8
        )
        
        # 车位
        ttk.Label(frame, text="车位:").grid(row=1, column=0, sticky="w", pady=8)
        world = WORLDS.get(self.selected_world)
        slots = list(world.cars.keys()) if world else ["car_1", "car_2", "car_3", "car_4", "car_5", "car_6"]
        slot_var = tk.StringVar(value=slots[0] if slots else "car_1")
        slot_combo = ttk.Combobox(frame, textvariable=slot_var, values=slots, state="readonly", width=33)
        slot_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=8)
        
        # 队伍ID
        ttk.Label(frame, text="队伍ID:").grid(row=2, column=0, sticky="w", pady=8)
        team_var = tk.StringVar(value="local_team")
        ttk.Entry(frame, textvariable=team_var, width=35).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=8
        )
        
        def add():
            """添加车辆"""
            controller = controller_var.get().strip()
            slot = slot_var.get()
            team = team_var.get().strip()
            
            if not controller:
                messagebox.showerror("错误", "请选择控制器文件", parent=add_window)
                return
            
            if not pathlib.Path(controller).is_file():
                messagebox.showerror("错误", f"控制器文件不存在:\n{controller}", parent=add_window)
                return
            
            # 检查车位是否已被使用
            for car in self.cars:
                if car.slot == slot:
                    messagebox.showerror("错误", f"车位 {slot} 已被使用", parent=add_window)
                    return
            
            # 转换为相对路径显示
            try:
                rel_path = pathlib.Path(controller).relative_to(pathlib.Path.cwd())
                display_path = str(rel_path)
            except ValueError:
                display_path = controller
            
            self.cars.append(CarEntry(controller, slot, team))
            self._update_cars_listbox()
            self._log(f"已添加车辆: {display_path} 到 {slot}")
            add_window.destroy()
        
        # 分隔线
        ttk.Separator(frame, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=15
        )
        
        # 按钮
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=10)
        
        ttk.Button(button_frame, text="确定", command=add, width=15).pack(side=LEFT, padx=5, fill=X, expand=True)
        ttk.Button(button_frame, text="取消", command=add_window.destroy, width=15).pack(side=LEFT, padx=5, fill=X, expand=True)
        
        frame.columnconfigure(1, weight=1)
        
        # 使窗口始终在主窗口前面
        add_window.transient(self.root)
        add_window.grab_set()
    
    def _remove_car(self):
        """删除选中的车辆"""
        selection = self.cars_listbox.curselection()
        if selection:
            self.cars.pop(selection[0])
            self._update_cars_listbox()
    
    def _update_cars_listbox(self):
        """更新车辆列表框"""
        self.cars_listbox.delete(0, END)
        for car in self.cars:
            self.cars_listbox.insert(END, str(car))
    
    def _start_simulation(self):
        """启动仿真"""
        if self.process:
            messagebox.showwarning("警告", "仿真已在运行")
            return
        
        # 构建命令行参数
        cmd = [sys.executable, str(SDK_DIR / "run_local.py")]
        
        # 添加赛道
        cmd += ["--world", self.selected_world]
        
        # 添加模式特定的参数
        if self.mode_var.get() == "single":
            code_path = self.code_path_var.get()
            if not code_path:
                messagebox.showerror("错误", "请选择控制器文件")
                return
            
            # 验证文件存在性（支持相对路径）
            abs_path = pathlib.Path(code_path).resolve()
            if not abs_path.is_file():
                messagebox.showerror("错误", f"控制器文件不存在: {code_path}")
                return
            
            # 使用相对路径传递给 run_local.py
            cmd += ["--code-path", code_path]
            cmd += ["--team-id", self.team_id_var.get()]
            cmd += ["--car-slot", self.car_slot_var.get()]
        else:
            if not self.cars:
                messagebox.showerror("错误", "多车模式下请至少添加一辆车")
                return
            
            for car in self.cars:
                cmd += ["--car", car.to_spec()]
        
        # 添加高级选项
        if self.fast_var.get():
            cmd.append("--fast")
        
        if self.minimize_var.get():
            cmd.append("--minimize")
        
        if self.batch_var.get():
            cmd.append("--batch")
        
        if self.validate_only_var.get():
            cmd.append("--validate-only")
        
        if self.skip_validate_var.get():
            cmd.append("--skip-validate")
        
        if self.webots_var.get():
            cmd += ["--webots", self.webots_var.get()]
        
        # 记录日志
        self._log(f"命令行: {' '.join(cmd)}")
        self._log("-" * 80)
        
        # 启动进程
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        
        # 在后台线程中运行
        thread = threading.Thread(target=self._run_process, args=(cmd,))
        thread.daemon = True
        thread.start()
    
    def _run_process(self, cmd):
        """在后台运行进程"""
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                cwd=str(SDK_DIR.parent)
            )
            
            # 读取输出 - 使用 bytes 模式，手动解码
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                
                # 尝试用多种编码解码
                try:
                    # 首先尝试 UTF-8
                    text = line.decode('utf-8', errors='ignore')
                except Exception:
                    try:
                        # 如果失败，尝试 GBK（Windows 默认）
                        text = line.decode('gbk', errors='ignore')
                    except Exception:
                        # 最后使用 latin-1（总是成功）
                        text = line.decode('latin-1', errors='replace')
                
                if text.strip():
                    self._log(text.rstrip())
            
            # 等待进程结束
            self.process.wait()
            exit_code = self.process.returncode
            
            self._log("-" * 80)
            self._log(f"进程已退出，退出码: {exit_code}")
            
        except Exception as e:
            self._log(f"错误: {e}")
        finally:
            self.process = None
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")
    
    def _stop_simulation(self):
        """停止仿真"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception as e:
                self._log(f"错误: {e}")
            finally:
                self.process = None
                self.start_button.config(state="normal")
                self.stop_button.config(state="disabled")
    
    def _collect_config(self) -> dict:
        """收集当前配置"""
        config = {
            "mode": self.mode_var.get(),
            "world": self.selected_world,
            "fast": self.fast_var.get(),
            "minimize": self.minimize_var.get(),
            "batch": self.batch_var.get(),
            "validate_only": self.validate_only_var.get(),
            "skip_validate": self.skip_validate_var.get(),
            "webots": self.webots_var.get(),
        }
        
        if config["mode"] == "single":
            config["code_path"] = self.code_path_var.get()
            config["car_slot"] = self.car_slot_var.get()
            config["team_id"] = self.team_id_var.get()
        else:
            config["cars"] = [
                {
                    "path": car.controller_path,
                    "slot": car.slot,
                    "team": car.team
                }
                for car in self.cars
            ]
        
        return config
    
    def _apply_config(self, config: dict) -> bool:
        """应用配置"""
        try:
            # 基本设置
            self.selected_world = config.get("world", DEFAULT_WORLD_KEY)
            self.world_var.set(self.selected_world)
            self._update_world_info()
            self._update_slot_combo()
            
            # 高级选项
            self.fast_var.set(config.get("fast", False))
            self.minimize_var.set(config.get("minimize", False))
            self.batch_var.set(config.get("batch", False))
            self.validate_only_var.set(config.get("validate_only", False))
            self.skip_validate_var.set(config.get("skip_validate", False))
            self.webots_var.set(config.get("webots", ""))
            
            # 模式特定配置
            mode = config.get("mode", "single")
            self.mode_var.set(mode)
            self._on_mode_changed()
            
            if mode == "single":
                self.code_path_var.set(config.get("code_path", ""))
                self.car_slot_var.set(config.get("car_slot", "car_1"))
                self.team_id_var.set(config.get("team_id", "local_team"))
            else:
                self.cars.clear()
                for car_config in config.get("cars", []):
                    self.cars.append(CarEntry(
                        car_config.get("path", ""),
                        car_config.get("slot", "car_1"),
                        car_config.get("team", "local_team")
                    ))
                self._update_cars_listbox()
            
            return True
        except Exception as e:
            messagebox.showerror("错误", f"应用配置失败: {e}")
            return False
    
    def _save_preset(self):
        """保存预设"""
        name = self.config_name_var.get().strip()
        if not name:
            messagebox.showwarning("警告", "请输入配置名称")
            return
        
        # 检查名称是否重复
        if name in ConfigManager.list_configs():
            if messagebox.askyesno("确认", f"配置 '{name}' 已存在，是否覆盖?"):
                pass
            else:
                return
        
        config = self._collect_config()
        if ConfigManager.save_config(name, config):
            messagebox.showinfo("成功", f"配置 '{name}' 已保存")
            self._load_config_list()
            self.config_name_var.set("")
        else:
            messagebox.showerror("错误", "保存配置失败")
    
    def _delete_preset(self):
        """删除预设"""
        selection = self.config_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请选择要删除的配置")
            return
        
        name = self.config_listbox.get(selection[0])
        if messagebox.askyesno("确认", f"确定删除配置 '{name}' 吗?"):
            if ConfigManager.delete_config(name):
                messagebox.showinfo("成功", f"配置 '{name}' 已删除")
                self._load_config_list()
            else:
                messagebox.showerror("错误", "删除配置失败")
    
    def _load_config_list(self):
        """加载配置列表"""
        self.config_listbox.delete(0, END)
        for config_name in ConfigManager.list_configs():
            self.config_listbox.insert(END, config_name)
    
    def _on_config_selected(self, event=None):
        """配置选中时的回调"""
        selection = self.config_listbox.curselection()
        if selection:
            name = self.config_listbox.get(selection[0])
            self.config_name_var.set(name)
    
    def _quick_start_preset(self):
        """一键启动选中的预设"""
        selection = self.config_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请选择要启动的配置")
            return
        
        name = self.config_listbox.get(selection[0])
        config = ConfigManager.load_config(name)
        if config:
            if self._apply_config(config):
                self._log(f"已加载配置: {name}")
                # 立即启动仿真
                self.root.after(500, self._start_simulation)
        else:
            messagebox.showerror("错误", f"加载配置 '{name}' 失败")


def main():
    root = Tk()
    app = AiRacerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
