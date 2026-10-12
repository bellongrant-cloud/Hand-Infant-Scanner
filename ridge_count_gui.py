#!/usr/bin/env python3
"""
Dermatoglyphic ridge-count tool — point-and-click GUI.

No command line needed after the one-time install. Open a scan image,
click to mark the core and delta points directly on the picture (or
skip marking and let auto-detection guess), click "Count Ridges", and
see the ridge count plus an annotated image showing exactly which
ridges were counted.

Setup (one time, in a terminal):
    pip install numpy opencv-python-headless

Run:
    python ridge_count_gui.py

This file must sit next to ridge_count_standalone.py (it reuses that
file's image-processing code instead of duplicating it).
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np

from ridge_count_standalone import (
    RidgeCountResult,
    build_annotation_overlay,
    run_ridge_count,
)

MAX_DISPLAY_SIZE = 620


class RidgeCountApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Ridge Count")
        root.geometry("760x720")

        self.image_path: str | None = None
        self.original_bgr: np.ndarray | None = None
        self.display_scale = 1.0
        self.core_point: tuple[int, int] | None = None
        self.delta_point: tuple[int, int] | None = None
        self.mark_mode: str | None = None  # "core" | "delta" | None
        self.last_result: RidgeCountResult | None = None
        self.tk_photo = None  # keep a reference so Tk doesn't garbage-collect it

        self._build_widgets()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        top = tk.Frame(self.root, padx=8, pady=8)
        top.pack(side="top", fill="x")

        tk.Button(top, text="Open Scan Image…", command=self.open_image).pack(side="left", padx=4)
        self.mark_core_btn = tk.Button(top, text="Mark Core", command=lambda: self.set_mark_mode("core"))
        self.mark_core_btn.pack(side="left", padx=4)
        self.mark_delta_btn = tk.Button(top, text="Mark Delta", command=lambda: self.set_mark_mode("delta"))
        self.mark_delta_btn.pack(side="left", padx=4)
        tk.Button(top, text="Clear Points", command=self.clear_points).pack(side="left", padx=4)
        tk.Button(top, text="Count Ridges", command=self.count_ridges,
                  bg="#2e7d32", fg="white").pack(side="left", padx=12)
        tk.Button(top, text="Save Results…", command=self.save_results).pack(side="left", padx=4)

        self.result_var = tk.StringVar(value="Ridge count: —")
        tk.Label(self.root, textvariable=self.result_var, font=("TkDefaultFont", 16, "bold")).pack(pady=(0, 4))

        self.canvas = tk.Canvas(self.root, width=MAX_DISPLAY_SIZE, height=MAX_DISPLAY_SIZE,
                                 bg="#222222", highlightthickness=1, highlightbackground="#888888")
        self.canvas.pack(padx=8, pady=4)
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        self.status_var = tk.StringVar(
            value="Open a scan image to begin. Mark Core/Delta is optional — "
                  "leave both unmarked to let auto-detection guess (then verify!)."
        )
        tk.Label(self.root, textvariable=self.status_var, anchor="w", justify="left",
                 wraplength=740, fg="#444444").pack(fill="x", padx=8, pady=(4, 8))

    # ------------------------------------------------------------------
    # Image loading / display
    # ------------------------------------------------------------------
    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a scanner image",
            filetypes=[("Images", "*.png *.bmp *.tif *.tiff *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if not path:
            return
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            messagebox.showerror("Could not open image", f"Couldn't read:\n{path}")
            return

        self.image_path = path
        self.original_bgr = image
        self.core_point = None
        self.delta_point = None
        self.last_result = None
        self.mark_mode = None
        self.result_var.set("Ridge count: —")
        self._render(image)
        self.status_var.set(
            f"Loaded {os.path.basename(path)} ({image.shape[1]}x{image.shape[0]}px). "
            "Click 'Mark Core' or 'Mark Delta' then click on the image, or just press "
            "'Count Ridges' to auto-detect."
        )

    def _render(self, bgr_image: np.ndarray) -> None:
        h, w = bgr_image.shape[:2]
        scale = min(MAX_DISPLAY_SIZE / w, MAX_DISPLAY_SIZE / h, 1.0)
        self.display_scale = scale
        disp = cv2.resize(bgr_image, (max(int(w * scale), 1), max(int(h * scale), 1))) if scale < 1.0 else bgr_image
        ok, buf = cv2.imencode(".png", disp)
        self.tk_photo = tk.PhotoImage(data=buf.tobytes())
        self.canvas.config(width=disp.shape[1], height=disp.shape[0])
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_photo)
        self._draw_markers()

    def _draw_markers(self) -> None:
        self.canvas.delete("marker")
        if self.core_point:
            self._draw_marker(self.core_point, "red", "core")
        if self.delta_point:
            self._draw_marker(self.delta_point, "magenta", "delta")

    def _draw_marker(self, point: tuple[int, int], color: str, label: str) -> None:
        x, y = point[0] * self.display_scale, point[1] * self.display_scale
        self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline=color, width=2, tags="marker")
        self.canvas.create_text(x + 8, y - 8, text=label, fill=color, anchor="w", tags="marker")

    # ------------------------------------------------------------------
    # Marking core / delta by clicking
    # ------------------------------------------------------------------
    def set_mark_mode(self, mode: str) -> None:
        if self.original_bgr is None:
            messagebox.showinfo("No image", "Open a scan image first.")
            return
        self.mark_mode = mode
        self.status_var.set(f"Click on the image to place the {mode} point.")

    def clear_points(self) -> None:
        self.core_point = None
        self.delta_point = None
        self.mark_mode = None
        if self.original_bgr is not None:
            self._render(self.original_bgr)
        self.status_var.set("Points cleared.")

    def on_canvas_click(self, event: tk.Event) -> None:
        if self.original_bgr is None or self.mark_mode is None:
            return
        orig_x = int(round(event.x / self.display_scale))
        orig_y = int(round(event.y / self.display_scale))
        h, w = self.original_bgr.shape[:2]
        orig_x = max(0, min(orig_x, w - 1))
        orig_y = max(0, min(orig_y, h - 1))

        if self.mark_mode == "core":
            self.core_point = (orig_x, orig_y)
        else:
            self.delta_point = (orig_x, orig_y)

        placed = self.mark_mode
        self.mark_mode = None
        self._draw_markers()
        self.status_var.set(f"{placed.capitalize()} point placed at ({orig_x}, {orig_y}).")

    # ------------------------------------------------------------------
    # Running the pipeline
    # ------------------------------------------------------------------
    def count_ridges(self) -> None:
        if self.image_path is None:
            messagebox.showinfo("No image", "Open a scan image first.")
            return

        try:
            result = run_ridge_count(
                self.image_path,
                core=self.core_point,
                delta=self.delta_point,
            )
        except ValueError as exc:
            messagebox.showerror(
                "Couldn't auto-detect core/delta",
                f"{exc}\n\nUse 'Mark Core' and 'Mark Delta' to place them yourself.",
            )
            return
        except FileNotFoundError as exc:
            messagebox.showerror("Error", str(exc))
            return

        self.last_result = result
        self.core_point = result.core
        self.delta_point = result.delta

        overlay = build_annotation_overlay(self.original_bgr, result)
        self._render(overlay)
        self.result_var.set(f"Ridge count: {result.count}")

        msg = f"Counted {result.count} ridges between delta and core."
        if result.warnings:
            msg += " " + " ".join(result.warnings)
            msg += " Check the marked points on the image before trusting this count."
        self.status_var.set(msg)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def save_results(self) -> None:
        if self.last_result is None or self.image_path is None:
            messagebox.showinfo("Nothing to save", "Run 'Count Ridges' first.")
            return
        out_dir = filedialog.askdirectory(title="Choose a folder to save results into")
        if not out_dir:
            return

        overlay = build_annotation_overlay(self.original_bgr, self.last_result)
        annotated_path = os.path.join(out_dir, "annotated.png")
        cv2.imwrite(annotated_path, overlay)

        report = {
            "ridge_count": self.last_result.count,
            "core": self.last_result.core,
            "delta": self.last_result.delta,
            "core_confidence": self.last_result.core_confidence,
            "delta_confidence": self.last_result.delta_confidence,
            "crossings": self.last_result.crossings,
        }
        report_path = os.path.join(out_dir, "report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        messagebox.showinfo("Saved", f"Saved:\n{annotated_path}\n{report_path}")


def main() -> None:
    root = tk.Tk()
    RidgeCountApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
