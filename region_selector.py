"""Interactive Screen Region Selector for Custom Area Recording."""
import tkinter as tk
import ctypes


class RegionSelector:
    """Semi-transparent full-screen overlay for selecting a recording region."""

    def __init__(self, on_selected_callback):
        self.on_selected = on_selected_callback
        self.root = None
        self.canvas = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.label_id = None

    def start(self):
        u32 = ctypes.windll.user32
        # Support virtual screen across multi-monitors if applicable
        vx = u32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = u32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = u32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = u32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

        if vw <= 0 or vh <= 0:
            vx, vy = 0, 0
            vw = u32.GetSystemMetrics(0)
            vh = u32.GetSystemMetrics(1)

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.root.attributes("-alpha", 0.35)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="crosshair")

        self.canvas = tk.Canvas(self.root, bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Instruction text in center
        cx = vw // 2
        cy = 50
        self.canvas.create_text(
            cx, cy,
            text="KÉO CHUỘT ĐỂ CHỌN VÙNG QUAY  |  Nhấn ESC để hủy",
            fill="#ffffff",
            font=("Segoe UI", 14, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self._cancel())

        self.root.focus_force()
        self.root.mainloop()

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.label_id:
            self.canvas.delete(self.label_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#38bdf8", width=3, fill="#0284c7"
        )
        self.label_id = self.canvas.create_text(
            self.start_x + 50, self.start_y - 15,
            text="0 x 0", fill="#38bdf8", font=("Segoe UI", 11, "bold")
        )

    def _on_drag(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)
        w = abs(cur_x - self.start_x)
        h = abs(cur_y - self.start_y)
        self.canvas.coords(self.label_id, max(self.start_x, cur_x), min(self.start_y, cur_y) - 15)
        self.canvas.itemconfig(self.label_id, text=f"{w} x {h}")

    def _on_release(self, event):
        end_x, end_y = event.x, event.y
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)

        self.root.destroy()
        self.root = None

        if width >= 50 and height >= 50:
            if self.on_selected:
                self.on_selected((left, top, width, height))
        else:
            if self.on_selected:
                self.on_selected(None)

    def _cancel(self):
        if self.root:
            self.root.destroy()
            self.root = None
        if self.on_selected:
            self.on_selected(None)
