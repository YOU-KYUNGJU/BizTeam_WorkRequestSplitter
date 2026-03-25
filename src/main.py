import os
import re
import sys
import time
import shutil
import threading
import configparser
import gc
from datetime import datetime
from collections import deque
from threading import Lock

from pdf2image import convert_from_path
import pytesseract
from PIL import ImageOps, ImageFilter

def configure_tk_environment():
    candidates = []

    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidates.extend([
            os.path.join(base_dir, "tcl", "tcl8.6"),
            os.path.join(base_dir, "lib", "tcl8.6"),
        ])
        tk_candidates = [
            os.path.join(base_dir, "tcl", "tk8.6"),
            os.path.join(base_dir, "lib", "tk8.6"),
        ]
    else:
        base_prefix = getattr(sys, "base_prefix", sys.prefix)
        candidates.extend([
            os.path.join(base_prefix, "tcl", "tcl8.6"),
            os.path.join(base_prefix, "lib", "tcl8.6"),
        ])
        tk_candidates = [
            os.path.join(base_prefix, "tcl", "tk8.6"),
            os.path.join(base_prefix, "lib", "tk8.6"),
        ]

    if "TCL_LIBRARY" not in os.environ:
        for path in candidates:
            if os.path.exists(os.path.join(path, "init.tcl")):
                os.environ["TCL_LIBRARY"] = path
                break

    if "TK_LIBRARY" not in os.environ:
        for path in tk_candidates:
            if os.path.exists(os.path.join(path, "tk.tcl")):
                os.environ["TK_LIBRARY"] = path
                break


configure_tk_environment()

import tkinterx as tk
from tkinterx import ttk, messagebox, simpledialog

# exe 파일만들기(권장)
# pyinstaller --onefile --windowed --name FITI_PDF_RequestSplitter main.py
# pyinstaller FITI_PDF_RequestSplitter.spec

__version__ = "4.0.0"

def get_runtime_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# ================== 설정 파일 로드 ==================
def load_config():
    config = configparser.ConfigParser()

    base_dir = get_runtime_base_dir()
    source_dir = os.path.dirname(os.path.abspath(__file__))

    candidate_paths = [
        os.path.join(base_dir, "config", "config.ini"),
        os.path.join(base_dir, "config.ini"),
        os.path.join(source_dir, "config.ini"),
        os.path.join(os.path.dirname(source_dir), "config", "config.ini"),
    ]

    config_path = candidate_paths[1]
    for candidate in candidate_paths:
        if os.path.exists(candidate):
            config_path = candidate
            break

    defaults = {
        "PATHS": {
            "POPPLER_PATH": r"C:\poppler\Library\bin",
            "TESSERACT_EXE": r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        },
        "OCR": {
            "DPI": "500",
            "BATCH_SIZE": "10"
        },
        "WATCHER": {
            "SCAN_INTERVAL_SEC": "1.0",
            "STABLE_CHECK_SEC": "0.7",
            "STABLE_RETRY": "3"
        }
    }

    if not os.path.exists(config_path):
        config.read_dict(defaults)
        try:
            dir_name = os.path.dirname(config_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                config.write(f)
        except Exception:
            pass
    else:
        config.read(config_path, encoding="utf-8")

    return config


CONFIG = load_config()

# ================== 환경 설정 ==================
POPPLER_PATH = CONFIG["PATHS"].get("POPPLER_PATH", r"C:\poppler\Library\bin")
TESSERACT_EXE = CONFIG["PATHS"].get("TESSERACT_EXE", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
DPI = CONFIG["OCR"].getint("DPI", 500)
BATCH_SIZE = CONFIG["OCR"].getint("BATCH_SIZE", 10)

SCAN_INTERVAL_SEC = CONFIG["WATCHER"].getfloat("SCAN_INTERVAL_SEC", 1.0)
STABLE_CHECK_SEC = CONFIG["WATCHER"].getfloat("STABLE_CHECK_SEC", 0.7)
STABLE_RETRY = CONFIG["WATCHER"].getint("STABLE_RETRY", 3)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

# ---------- pypdf ----------
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pypdf"])
    from pypdf import PdfReader, PdfWriter

# ---------- 정규식 ----------
RE_REQUEST_RECEIPT = re.compile(r"N\d{3}\s*[-]?\s*\d{2}\s*[-]?\s*\d{5}", re.IGNORECASE)

# ---------- 전역 상태 ----------
stop_requested = False
paused_by_checkbox = False

queue_lock = threading.Lock()
pdf_queue = deque()            # 처리 대기 큐: [pdf_path, ...]
seen_files = set()             # 이미 큐에 넣었거나 처리한 파일들
currently_processing = None    # 현재 처리 중인 pdf 경로
last_done_filename = None      # 마지막 완료 파일명

# ================== 유틸 ==================
def now_ts():
    return datetime.now().strftime("%H:%M:%S")

def safe_filename(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s)

def norm_keep(s):
    return re.sub(r"\s+", "", s).upper()

def norm_code(s):
    s = re.sub(r"\s+", "", s)
    s = s.replace("O", "0").replace("o", "0")
    s = s.replace("I", "1").replace("l", "1").replace("L", "1")
    return s.upper()

def preprocess_gray_sharp(img):
    g = img.convert("L")
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = g.filter(ImageFilter.SHARPEN)
    return g

def binarize(img_gray, thr):
    return img_gray.point(lambda x, t=thr: 255 if x > t else 0)

def file_is_stable(path):
    """
    파일이 쓰기 중일 수 있으므로 size가 일정해질 때까지 짧게 확인
    """
    try:
        prev = os.path.getsize(path)
        for _ in range(STABLE_RETRY):
            time.sleep(STABLE_CHECK_SEC)
            cur = os.path.getsize(path)
            if cur != prev:
                prev = cur
            else:
                return True
        return False
    except Exception:
        return False

def normalize_request_receipt(s):
    """
    OCR 문자열에서 접수번호 추출
    예:
      N232-26-03706 -> N2322603706
      N2322603706   -> N2322603706
    """
    if not s:
        return None

    s = re.sub(r"\s+", "", s).upper()
    s = s.replace("O", "0").replace("I", "1").replace("L", "1")

    m = RE_REQUEST_RECEIPT.search(s)
    if m:
        v = re.sub(r"[^A-Z0-9]", "", m.group(0).upper())
        m2 = re.fullmatch(r"(N\d{3})(\d{2})(\d{5})", v)
        if m2:
            return "{0}{1}{2}".format(m2.group(1), m2.group(2), m2.group(3))

    raw = re.sub(r"[^A-Z0-9]", "", s)
    m3 = re.search(r"(N\d{3})(\d{2})(\d{5})", raw)
    if m3:
        return "{0}{1}{2}".format(m3.group(1), m3.group(2), m3.group(3))

    return None

def ocr_text(img, lang="kor+eng", psm=6, whitelist=None):
    cfg = "--oem 3 --psm {0}".format(psm)
    if whitelist:
        cfg += " -c tessedit_char_whitelist={0}".format(whitelist)

    try:
        return pytesseract.image_to_string(img, lang=lang, config=cfg)
    except Exception:
        try:
            return pytesseract.image_to_string(img, lang="eng", config=cfg)
        except Exception:
            return ""

# ================== 출력 폴더 ==================
RUN_DIR = get_runtime_base_dir()
SPLIT_OUTPUT_DIR = os.path.join(RUN_DIR, "split_output")
os.makedirs(SPLIT_OUTPUT_DIR, exist_ok=True)

# ================== 텍스트 로그 파일 ==================
LOG_DIR = os.path.join(RUN_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(LOG_DIR, "FITI_PDF_RequestSplitter_{0}.txt".format(datetime.now().strftime("%Y%m%d")))
log_file_lock = Lock()

def get_output_dir():
    """
    현재 버전은 로컬 split_output 고정
    """
    os.makedirs(SPLIT_OUTPUT_DIR, exist_ok=True)
    return SPLIT_OUTPUT_DIR

def ensure_dir_or_fallback(preferred_dir, log):
    """
    저장 폴더 생성/접근 실패 시 로컬 fallback
    """
    day = datetime.now().strftime("%Y%m%d")
    fallback_dir = os.path.join(SPLIT_OUTPUT_DIR, "_fallback_server_failed", day)
    os.makedirs(fallback_dir, exist_ok=True)

    try:
        os.makedirs(preferred_dir, exist_ok=True)

        test_path = os.path.join(preferred_dir, "__write_test__{0}.tmp".format(int(time.time())))
        with open(test_path, "wb") as f:
            f.write(b"")
        os.remove(test_path)

        return preferred_dir, False
    except Exception as e:
        log("⚠️ 저장 폴더 접근/생성 실패 → 로컬 fallback 저장")
        log("   원인: {0}".format(e))
        log("   로컬 저장 폴더: {0}".format(fallback_dir))
        return fallback_dir, True

# ================== 작업요청서 검출 ==================
def detect_work_request_page(img, page_num=None):
    """
    작업요청서 페이지 검출 + N 접수번호 추출
    반환:
      is_request_page: bool
      receipt_no: 예) N2322603706
    """
    w, h = img.size

    # 좌측 상단: 접수번호 영역
    left_top = img.crop((
        int(w * 0.03),
        int(h * 0.02),
        int(w * 0.55),
        int(h * 0.18)
    ))

    # 우측 상단: 작업요청서 문구 영역
    right_top = img.crop((
        int(w * 0.60),
        int(h * 0.02),
        int(w * 0.96),
        int(h * 0.16)
    ))

    # 상단 전체: 보조 OCR 영역
    top_band = img.crop((
        int(w * 0.02),
        int(h * 0.01),
        int(w * 0.98),
        int(h * 0.22)
    ))

    left_g = preprocess_gray_sharp(left_top)
    right_g = preprocess_gray_sharp(right_top)
    top_g = preprocess_gray_sharp(top_band)

    receipt_found = None
    request_keyword_hit = False

    # 1) 접수번호 검출
    for thr in [145, 160, 175, 190]:
        bw = binarize(left_g, thr)
        raw = ocr_text(
            bw,
            lang="eng",
            psm=6,
            whitelist="Nn0123456789-"
        )
        receipt_found = normalize_request_receipt(raw)
        if receipt_found:
            break

    if not receipt_found:
        for thr in [145, 160, 175, 190]:
            bw = binarize(top_g, thr)
            raw = ocr_text(
                bw,
                lang="eng",
                psm=6,
                whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
            )
            receipt_found = normalize_request_receipt(raw)
            if receipt_found:
                break

    # 2) "작업요청서" 문구 검출
    for thr in [145, 160, 175, 190]:
        bw = binarize(right_g, thr)
        raw = ocr_text(bw, lang="kor+eng", psm=7)
        raw_n = re.sub(r"\s+", "", raw)
        if "작업요청서" in raw_n:
            request_keyword_hit = True
            break

    # 판정:
    # - 기본: "작업요청서" 문구와 접수번호가 모두 있을 때만 첫장으로 인정
    # - 예외: PDF 첫 페이지는 OCR 품질 때문에 문구를 놓칠 수 있어, 접수번호만 있어도 허용
    is_first_page_fallback = (page_num == 1 and receipt_found is not None)
    is_request_page = (request_keyword_hit and receipt_found is not None) or is_first_page_fallback

    return is_request_page, receipt_found

# ================== 저장/이동 ==================
def split_by_request_and_save(pdf_path, out_dir, request_pages, request_receipts, log):
    """
    분할 규칙:
    - request_pages: 작업요청서 페이지 번호(1-based)
    - 각 작업요청서 페이지를 그룹 시작으로 간주
    - 저장 시 첫장(작업요청서)은 제외
    - 파일명: N2322603706.pdf
    """
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    used_names = set()

    for idx, start_page in enumerate(request_pages):
        receipt = request_receipts[idx]

        if idx + 1 < len(request_pages):
            end_page = request_pages[idx + 1] - 1
        else:
            end_page = total_pages

        # 첫 페이지(작업요청서)는 제외
        save_start = start_page + 1
        save_end = end_page

        if save_start > save_end:
            log("⚠️ 스킵: 페이지 {0} 그룹은 작업요청서 1장만 있어서 저장할 본문이 없습니다.".format(start_page))
            continue

        base = safe_filename(receipt if receipt else "UNKNOWN_{0:04d}".format(idx + 1))
        fname = "{0}.pdf".format(base)
        low = fname.lower()
        k = 2
        while low in used_names:
            fname = "{0}_{1}.pdf".format(base, k)
            low = fname.lower()
            k += 1
        used_names.add(low)

        out_path = os.path.join(out_dir, fname)

        writer = PdfWriter()
        for p in range(save_start - 1, save_end):
            writer.add_page(reader.pages[p])

        with open(out_path, "wb") as f:
            writer.write(f)

        log("✅ 저장: {0}  (원본 구간 {1}~{2}, 저장 구간 {3}~{4})".format(
            out_path, start_page, end_page, save_start, save_end
        ))

def move_original_to_done(pdf_path, split_output_dir, log):
    """
    원본 PDF는 split_output/_inbox_done 으로 이동
    """
    done_dir = os.path.join(split_output_dir, "_inbox_done")
    os.makedirs(done_dir, exist_ok=True)

    base = os.path.basename(pdf_path)
    name, ext = os.path.splitext(base)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(done_dir, "{0}_{1}{2}".format(safe_filename(name), ts, ext))

    try:
        shutil.move(pdf_path, dst)
        log("📦 원본 이동: {0}".format(dst))
    except Exception as e:
        log("❌ 원본 이동 실패: {0}".format(e))

# ================== UI ==================
root = tk.Tk()
root.title("FITI PDF Request Splitter (Folder Watch)")

status_var = tk.StringVar(value="대기 중...")
info_var = tk.StringVar(value="")
progress_var = tk.DoubleVar(value=0)
auto_next_var = tk.BooleanVar(value=True)   # 체크 ON: 자동 진행 + 로그 숨김

frm_top = tk.Frame(root)
frm_top.pack(fill="x", padx=10, pady=8)

lbl_status = tk.Label(frm_top, textvariable=status_var, font=("맑은 고딕", 11, "bold"))
lbl_status.grid(row=0, column=0, sticky="w")

lbl_info = tk.Label(frm_top, textvariable=info_var, font=("맑은 고딕", 9))
lbl_info.grid(row=1, column=0, sticky="w", pady=(2, 0))

pbar = ttk.Progressbar(frm_top, maximum=100, variable=progress_var)
pbar.grid(row=2, column=0, sticky="ew", pady=(6, 0))

frm_top.grid_columnconfigure(0, weight=1)

frm_mid = tk.Frame(root)
frm_mid.pack(fill="x", padx=10, pady=(0, 6))

auto_chk = tk.Checkbutton(
    frm_mid,
    text="자동 진행(로그 숨김)",
    variable=auto_next_var,
    onvalue=True,
    offvalue=False
)
auto_chk.pack(side="left")

txt = tk.Text(root, height=16, wrap="word")
txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))

frm_btn = tk.Frame(root)
frm_btn.pack(fill="x", padx=10, pady=(0, 10))

exit_btn = tk.Button(frm_btn, text="종료", width=10)
exit_btn.pack(side="right")

def append_log(s):
    try:
        with log_file_lock:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(s + "\n")
    except Exception:
        pass

    def _append():
        txt.insert("end", s + "\n")
        txt.see("end")
    root.after(0, _append)

def set_status(s):
    root.after(0, lambda: status_var.set(s))

def set_info(s):
    root.after(0, lambda: info_var.set(s))

def set_progress(pct):
    root.after(0, lambda: progress_var.set(pct))

def refresh_log_visibility():
    show = not auto_next_var.get()
    if show:
        txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    else:
        txt.pack_forget()

def on_auto_chk_toggle():
    global paused_by_checkbox
    refresh_log_visibility()
    paused_by_checkbox = (not auto_next_var.get())
    if paused_by_checkbox:
        append_log("[{0}] ⏸️ 자동 진행 OFF: 다음 작업은 대기합니다. (체크를 다시 켜면 재개)".format(now_ts()))
    else:
        append_log("[{0}] ▶️ 자동 진행 ON: 대기 중이면 다음 작업을 진행합니다.".format(now_ts()))

auto_next_var.trace_add("write", lambda *_: on_auto_chk_toggle())

def request_exit():
    global stop_requested
    stop_requested = True
    set_status("종료 중...")
    set_info("프로그램을 종료합니다.")
    append_log("[{0}] 🛑 종료 요청됨".format(now_ts()))
    root.after(300, root.destroy)

exit_btn.config(command=request_exit)

def on_window_close():
    if messagebox.askyesno("종료", "프로그램을 종료할까요?"):
        request_exit()

root.protocol("WM_DELETE_WINDOW", on_window_close)

# ================== 시작 로그/폴더 ==================
append_log("[{0}] 감시 폴더: {1}".format(now_ts(), RUN_DIR))
append_log("[{0}] 로컬 출력 폴더: {1}".format(now_ts(), SPLIT_OUTPUT_DIR))
refresh_log_visibility()

# ================== 폴더 감시 스레드 ==================
def scan_loop():
    """
    RUN_DIR 최상위 PDF 자동 처리
    - 작업 완료된 파일은 _inbox_done 으로 이동되므로 중복 처리 방지
    - split_output, logs 등 시스템 폴더는 제외
    """
    global stop_requested

    EXCLUDE_DIRS = {
        "split_output",
        "_inbox_done",
        "_fallback_server_failed",
        "__pycache__",
        "logs",
    }

    while not stop_requested:
        try:
            for name in os.listdir(RUN_DIR):
                if stop_requested:
                    break

                full = os.path.join(RUN_DIR, name)

                if os.path.isdir(full):
                    if name in EXCLUDE_DIRS:
                        continue
                    # 현재 버전은 하위 폴더 자동 스캔 안함
                    continue

                if not name.lower().endswith(".pdf"):
                    continue

                try:
                    if os.path.commonpath([full, SPLIT_OUTPUT_DIR]) == SPLIT_OUTPUT_DIR:
                        continue
                except Exception:
                    pass

                if full in seen_files:
                    continue

                if not file_is_stable(full):
                    continue

                with queue_lock:
                    pdf_queue.append(full)
                    seen_files.add(full)

                append_log("[{0}] 📥 새 PDF 감지: {1}".format(now_ts(), name))

        except Exception as e:
            append_log("[{0}] ❌ 스캔 오류: {1}".format(now_ts(), e))

        time.sleep(SCAN_INTERVAL_SEC)

# ================== 작업 처리 ==================
def process_one_pdf(pdf_path):
    """
    작업요청서 기준 분리:
    - '작업요청서'가 있는 페이지를 그룹 시작점으로 인식
    - 좌측 상단 N 접수번호 OCR
    - 결과 파일명: N2322603706.pdf
    - 저장 시 첫장(작업요청서)은 제외
    """
    set_status("📄 PDF 처리 중...")
    set_info(os.path.basename(pdf_path))

    def log(msg):
        append_log("[{0}] {1}".format(now_ts(), msg))

    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            log("❌ 페이지 0: {0}".format(pdf_path))
            return

        request_pages = []
        request_receipts = []

        set_status("작업요청서 OCR 추출 중...")

        for start_idx in range(1, total_pages + 1, BATCH_SIZE):
            if stop_requested:
                return

            end_idx = min(start_idx + BATCH_SIZE - 1, total_pages)

            images = convert_from_path(
                pdf_path,
                poppler_path=POPPLER_PATH,
                dpi=DPI,
                first_page=start_idx,
                last_page=end_idx
            )

            for i, img in enumerate(images):
                page_num = start_idx + i

                set_progress((page_num / float(total_pages)) * 85.0)
                set_info("{0} | OCR Page {1}/{2}".format(os.path.basename(pdf_path), page_num, total_pages))

                is_request, receipt = detect_work_request_page(img, page_num=page_num)

                if is_request:
                    request_pages.append(page_num)
                    request_receipts.append(receipt)
                    if page_num == 1 and receipt and page_num not in request_pages[:-1]:
                        log("Page {0}/{1} | 작업요청서 ✅ (첫 페이지 fallback) | Receipt: {2}".format(
                            page_num, total_pages, receipt
                        ))
                    else:
                        log("Page {0}/{1} | 작업요청서 ✅ | Receipt: {2}".format(
                            page_num, total_pages, receipt if receipt else "❌"
                        ))

            del images
            gc.collect()

        if not request_pages:
            log("❌ 작업요청서 페이지 미검출: {0}".format(os.path.basename(pdf_path)))
            return

        preferred = get_output_dir()
        out_dir, fallback_used = ensure_dir_or_fallback(preferred, log)

        if fallback_used:
            set_status("저장 중(로컬 fallback)...")
        else:
            set_status("저장 중...")

        set_info("{0} | 저장 폴더: {1}".format(os.path.basename(pdf_path), out_dir))
        set_progress(92.0)

        split_by_request_and_save(pdf_path, out_dir, request_pages, request_receipts, log)

        set_status("원본 이동 중...")
        set_info("{0} | 원본 이동".format(os.path.basename(pdf_path)))
        set_progress(98.0)

        move_original_to_done(pdf_path, SPLIT_OUTPUT_DIR, log)

        log("✅ 완료: {0}".format(os.path.basename(pdf_path)))
        set_progress(100.0)

        global last_done_filename
        last_done_filename = os.path.basename(pdf_path)
        set_status("✅ 처리 완료")
        set_info("{0} 완료".format(last_done_filename))

    except Exception as e:
        log("❌ 처리 오류: {0}".format(e))

def worker_loop():
    """
    큐에 들어온 PDF를 순차 처리
    체크박스 OFF이면 다음 파일로 넘어가기 전 대기
    """
    global currently_processing, paused_by_checkbox

    while not stop_requested:
        if paused_by_checkbox:
            set_status("대기 중(자동 진행 OFF)")
            set_info("체크를 다시 켜면 다음 작업 진행")
            time.sleep(0.2)
            continue

        pdf_path = None
        with queue_lock:
            if pdf_queue:
                pdf_path = pdf_queue.popleft()

        if not pdf_path:
            if last_done_filename:
                set_status("대기 중...")
                set_info("감시 폴더에 PDF가 생성되면 자동 처리합니다. | {0} 완료".format(last_done_filename))
            else:
                set_status("대기 중...")
                set_info("감시 폴더에 PDF가 생성되면 자동 처리합니다.")
            set_progress(0)
            time.sleep(0.2)
            continue

        currently_processing = pdf_path
        append_log("[{0}] ▶ 처리 시작: {1}".format(now_ts(), os.path.basename(pdf_path)))
        process_one_pdf(pdf_path)
        currently_processing = None

        if not auto_next_var.get():
            paused_by_checkbox = True

# ================== 시작 ==================
paused_by_checkbox = (not auto_next_var.get())
refresh_log_visibility()

threading.Thread(target=scan_loop, daemon=True).start()
threading.Thread(target=worker_loop, daemon=True).start()

root.mainloop()
