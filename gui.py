# -*- coding: utf-8 -*-
"""
AD RANK 자동화 GUI
- 체크박스로 작업 선택 후 실행
- 실시간 로그, 진행률, 결과 요약
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import sys
import os
import io
import json
import webbrowser
import time
import importlib
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 작업 목록 (모듈명, 표시명, 설명)
TASKS = [
    ("main", "순위 검색", "adrank 순위+점수 검색 → 결과 시트 기록"),
    ("pick_random_biz", "업체 추출", "후순위 업체 랜덤 추출 → 키워드 시트 기록"),
    ("sync_mid", "MID 동기화", "결과 시트 MID → 키워드 시트 동기화"),
    ("sync_traffic", "길찾기/유입", "키워드 시트 길찾기·유입 → 결과 시트 동기화"),
    ("group_rows", "행 그룹화", "결과 시트 4행 단위 그룹화"),
]


class LogRedirector(io.TextIOBase):
    """print 출력을 로그 창으로 리다이렉트"""

    def __init__(self, text_widget, app):
        self.text_widget = text_widget
        self.app = app

    def write(self, msg):
        if msg.strip() == "":
            return len(msg)
        self.text_widget.after(0, self._append, msg)
        return len(msg)

    def _append(self, msg):
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, msg)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")

        # 진행률 파싱: [3/17] 같은 패턴
        import re
        m = re.search(r'\[(\d+)/(\d+)\]', msg)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            pct = int(current / total * 100) if total > 0 else 0
            self.app.progress_var.set(pct)
            self.app.progress_label.config(text=f"{current}/{total}")

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("AD RANK 자동화")
        self.root.geometry("750x600")
        self.root.resizable(True, True)
        self.running = False
        self.stop_flag = False
        self.worker_thread = None
        self.scheduled_target_time = None
        self._enter_event = None

        self._build_ui()
        self._tick_clock()

    def _build_ui(self):
        # ─── 상단: 작업 선택 ───
        task_frame = ttk.LabelFrame(self.root, text="작업 선택", padding=10)
        task_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.task_vars = {}
        for i, (mod, name, desc) in enumerate(TASKS):
            var = tk.BooleanVar(value=False)
            self.task_vars[mod] = var
            cb = ttk.Checkbutton(task_frame, text=f"{name}", variable=var)
            cb.grid(row=i, column=0, sticky="w", padx=(0, 10))
            lbl = ttk.Label(task_frame, text=desc, foreground="gray")
            lbl.grid(row=i, column=1, sticky="w")

        # ─── 중단: 버튼 + 진행률 ───
        ctrl_frame = ttk.Frame(self.root, padding=5)
        ctrl_frame.pack(fill="x", padx=10, pady=5)

        self.start_btn = ttk.Button(ctrl_frame, text="▶ 즉시 시작", command=self.start, width=12)
        self.start_btn.pack(side="left", padx=(0, 5))

        self.stop_btn = ttk.Button(ctrl_frame, text="긴급중지", command=self.stop, width=12, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 5))

        ttk.Separator(ctrl_frame, orient="vertical").pack(side="left", fill="y", padx=10)

        # ─── 예약 실행 ───
        schedule_frame = ttk.LabelFrame(self.root, text="예약 실행", padding=10)
        schedule_frame.pack(fill="x", padx=10, pady=(0, 5))

        time_row = ttk.Frame(schedule_frame)
        time_row.pack(fill="x")

        ttk.Label(time_row, text="실행 시각:").pack(side="left", padx=(0, 5))

        self.hour_var = tk.StringVar(value=f"{datetime.now().hour:02d}")
        hour_spin = ttk.Spinbox(time_row, from_=0, to=23, width=3, format="%02.0f",
                                textvariable=self.hour_var, wrap=True)
        hour_spin.pack(side="left")

        ttk.Label(time_row, text=":").pack(side="left")

        self.minute_var = tk.StringVar(value="00")
        min_spin = ttk.Spinbox(time_row, from_=0, to=59, width=3, format="%02.0f",
                               textvariable=self.minute_var, wrap=True)
        min_spin.pack(side="left", padx=(0, 10))

        self.schedule_btn = ttk.Button(time_row, text="⏰ 예약", command=self.schedule_start, width=10)
        self.schedule_btn.pack(side="left", padx=(0, 5))

        self.cancel_schedule_btn = ttk.Button(time_row, text="예약 취소", command=self.cancel_schedule,
                                              width=10, state="disabled")
        self.cancel_schedule_btn.pack(side="left", padx=(0, 5))

        self.enter_btn = ttk.Button(time_row, text="Enter ▶", command=self.gui_enter,
                                    width=10, state="disabled")
        self.enter_btn.pack(side="left", padx=(0, 10))

        self.clock_label = ttk.Label(time_row, text="", foreground="gray")
        self.clock_label.pack(side="left", padx=(5, 0))

        self.schedule_status = ttk.Label(schedule_frame, text="", foreground="blue")
        self.schedule_status.pack(anchor="w", pady=(5, 0))

        # 시트 바로가기
        self.sheet_btn = ttk.Button(ctrl_frame, text="결과 시트 열기", command=self.open_result_sheet, width=14)
        self.sheet_btn.pack(side="left", padx=(0, 5))

        self.kw_sheet_btn = ttk.Button(ctrl_frame, text="키워드 시트 열기", command=self.open_keyword_sheet, width=16)
        self.kw_sheet_btn.pack(side="left", padx=(0, 5))

        # 설정 버튼
        self.config_btn = ttk.Button(ctrl_frame, text="설정", command=self.open_config, width=8)
        self.config_btn.pack(side="right")

        # 진행률
        prog_frame = ttk.Frame(self.root, padding=(10, 0))
        prog_frame.pack(fill="x", padx=10)

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.progress_label = ttk.Label(prog_frame, text="대기 중")
        self.progress_label.pack(side="right")

        # ─── 하단: 로그 ───
        log_frame = ttk.LabelFrame(self.root, text="로그", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="both", expand=True)

        # 로그 우클릭 메뉴
        self.log_menu = tk.Menu(self.log_text, tearoff=0)
        self.log_menu.add_command(label="로그 지우기", command=self.clear_log)
        self.log_text.bind("<Button-3>", lambda e: self.log_menu.tk_popup(e.x_root, e.y_root))

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _tick_clock(self):
        now = datetime.now()
        self.clock_label.config(text=f"현재: {now.strftime('%H:%M:%S')}")
        self.root.after(1000, self._tick_clock)

    def schedule_start(self):
        selected = [mod for mod, var in self.task_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning("선택 없음", "실행할 작업을 하나 이상 선택하세요.")
            return

        has_browser_task = any(mod in selected for mod in ("main", "pick_random_biz"))
        if not has_browser_task:
            messagebox.showwarning("알림", "예약 실행은 브라우저 작업(순위 검색 또는 업체 추출)이 포함되어야 합니다.")
            return

        try:
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
        except ValueError:
            messagebox.showerror("오류", "시간을 올바르게 입력하세요.")
            return

        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        self.scheduled_target_time = target
        delay_sec = (target - now).total_seconds()

        self.schedule_btn.config(state="disabled")
        self.cancel_schedule_btn.config(state="normal")
        self.start_btn.config(state="disabled")
        self.schedule_status.config(
            text=f"⏰ {target.strftime('%Y-%m-%d %H:%M')}에 검색 시작 예정 — 브라우저를 먼저 엽니다")
        self.log(f"[예약] {target.strftime('%Y-%m-%d %H:%M')}에 검색 시작 예약")
        self.log(f"[예약] 브라우저가 먼저 열립니다. 로그인을 완료해주세요.")
        self.log(f"[예약] 약 {int(delay_sec//3600)}시간 {int((delay_sec%3600)//60)}분 후 자동 시작")

        self.start(scheduled=True)

    def cancel_schedule(self):
        self.scheduled_target_time = None
        self.schedule_btn.config(state="normal")
        self.cancel_schedule_btn.config(state="disabled")
        self.start_btn.config(state="normal")
        self.schedule_status.config(text="")
        self.log("[예약] 예약이 취소되었습니다.")

    def gui_enter(self):
        if self._enter_event:
            self._enter_event.set()
            self.enter_btn.config(state="disabled")
            self.log("[Enter] 로그인 확인 — 검색을 시작합니다!")

    def start(self, scheduled=False):
        selected = [mod for mod, var in self.task_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning("선택 없음", "실행할 작업을 하나 이상 선택하세요.")
            return

        self.running = True
        self.stop_flag = False
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.progress_label.config(text="시작 중...")

        target_time = self.scheduled_target_time if scheduled else None
        self.worker_thread = threading.Thread(
            target=self._run_tasks, args=(selected, target_time), daemon=True)
        self.worker_thread.start()

    def stop(self):
        if self.running:
            self.stop_flag = True
            self.log("\n[긴급중지] 현재 작업 완료 후 중지됩니다...")
            self.stop_btn.config(state="disabled")

    def _run_tasks(self, selected, target_time=None):
        os.chdir(BASE_DIR)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirector = LogRedirector(self.log_text, self)
        sys.stdout = redirector
        sys.stderr = redirector

        results = {}
        total_tasks = len(selected)

        try:
            for i, mod_name in enumerate(selected):
                if self.stop_flag:
                    self.log(f"\n[중지됨] 남은 작업 스킵")
                    break

                task_label = next(name for m, name, _ in TASKS if m == mod_name)
                self.log(f"\n{'='*50}")
                self.log(f"  [{i+1}/{total_tasks}] {task_label} 시작")
                self.log(f"{'='*50}\n")

                try:
                    mod = importlib.import_module(mod_name)
                    importlib.reload(mod)
                    if mod_name in ("main", "pick_random_biz"):
                        if target_time:
                            mod.scheduled_start_time = target_time
                        else:
                            self._enter_event = threading.Event()
                            mod.gui_enter_event = self._enter_event
                            self.root.after(0, lambda: self.enter_btn.config(state="normal"))
                    mod.run()
                    if mod_name in ("main", "pick_random_biz"):
                        self._enter_event = None
                        self.root.after(0, lambda: self.enter_btn.config(state="disabled"))
                    results[task_label] = "완료"
                except KeyboardInterrupt:
                    results[task_label] = "중지"
                except Exception as e:
                    results[task_label] = f"오류: {e}"
                    self.log(f"\n[오류] {task_label}: {e}")

            # 결과 요약
            self.log(f"\n{'='*50}")
            self.log(f"  결과 요약")
            self.log(f"{'='*50}")
            for task, result in results.items():
                icon = "O" if result == "완료" else "X"
                self.log(f"  [{icon}] {task}: {result}")

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.root.after(0, self._finish)

    def _finish(self):
        self.running = False
        self._enter_event = None
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.enter_btn.config(state="disabled")
        self.schedule_btn.config(state="normal")
        self.cancel_schedule_btn.config(state="disabled")
        self.schedule_status.config(text="")
        self.scheduled_target_time = None
        self.progress_var.set(100)
        self.progress_label.config(text="완료")

    def open_result_sheet(self):
        try:
            config = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
            webbrowser.open(config["result_sheet_url"])
        except Exception as e:
            messagebox.showerror("오류", f"시트 URL을 열 수 없습니다:\n{e}")

    def open_keyword_sheet(self):
        try:
            config = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
            webbrowser.open(config["keyword_sheet_url"])
        except Exception as e:
            messagebox.showerror("오류", f"시트 URL을 열 수 없습니다:\n{e}")

    def open_config(self):
        ConfigWindow(self.root)


class ConfigWindow:
    """설정 편집 팝업"""

    LABELS = {
        "adrank_id": "AD RANK 아이디",
        "adrank_pw": "AD RANK 비밀번호",
        "google_credentials_file": "인증 파일",
        "keyword_sheet_url": "키워드 시트 URL",
        "keyword_sheet_name": "키워드 시트 이름",
        "result_sheet_url": "결과 시트 URL",
        "result_sheet_gid": "결과 시트 GID",
        "data_start_row": "데이터 시작 행",
        "row_interval": "행 간격",
        "date_start_column": "날짜 시작 열",
        "search_wait_seconds": "검색 대기(초)",
        "between_search_delay": "검색 간 대기(초)",
    }

    PASSWORD_FIELDS = {"adrank_pw"}

    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("설정 편집")
        self.win.geometry("550x400")
        self.win.grab_set()

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            messagebox.showerror("오류", f"config.json 로드 실패:\n{e}")
            self.win.destroy()
            return

        frame = ttk.Frame(self.win, padding=10)
        frame.pack(fill="both", expand=True)

        self.entries = {}
        for i, (key, val) in enumerate(self.config.items()):
            label_text = self.LABELS.get(key, key)
            ttk.Label(frame, text=label_text).grid(row=i, column=0, sticky="w", pady=2)
            if key in self.PASSWORD_FIELDS:
                entry = ttk.Entry(frame, width=50, show="*")
            else:
                entry = ttk.Entry(frame, width=50)
            entry.insert(0, str(val))
            entry.grid(row=i, column=1, sticky="ew", padx=(10, 0), pady=2)
            self.entries[key] = entry

        frame.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(self.win, padding=10)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="저장", command=self.save).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="취소", command=self.win.destroy).pack(side="right")

    def save(self):
        new_config = {}
        for key, entry in self.entries.items():
            val = entry.get().strip()
            old_val = self.config[key]
            if isinstance(old_val, int):
                try:
                    val = int(val)
                except ValueError:
                    pass
            new_config[key] = val

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=4, ensure_ascii=False)
            messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")
            self.win.destroy()
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
