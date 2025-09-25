import sys
import os
import re
import traceback
import webbrowser
from typing import Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception as e:
    print(f"[startup.tkimport] {e}")
    traceback.print_exc()
    raise

try:
    import yaml
except Exception as e:
    print(f"[startup.yamlimport] {e}")
    traceback.print_exc()
    print("Please install PyYAML: pip install pyyaml")
    sys.exit(1)

# =========================================================
# File I/O: Markdown front-matter aware loader/saver
# =========================================================

FM_BOUNDARY = re.compile(r"^---\s*$")

def read_markdown_with_front_matter(path: str) -> Tuple[Optional[dict], str]:
    """
    If file begins with '---', treat as Markdown with YAML front matter.
    Return (front_matter_dict, markdown_body_text).
    If not front-matter, return (None, entire_file_text).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[read_markdown_with_front_matter] {e}")
        traceback.print_exc()
        raise

    if not lines or not FM_BOUNDARY.match(lines[0].rstrip("\n")):
        return None, "".join(lines)

    # Find the closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if FM_BOUNDARY.match(lines[i].rstrip("\n")):
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("Front matter start found but closing '---' not found.")

    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx+1:])

    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception as e:
        print(f"[read_markdown_with_front_matter.safe_load] {e}")
        traceback.print_exc()
        raise
    if not isinstance(fm, dict):
        raise ValueError("Front matter is not a YAML mapping (dict).")

    return fm, body


def _quote_scalar(v) -> str:
    """Render a scalar as a YAML literal/string, keeping booleans unquoted.

    Rules:
      - None  -> false   (bare)
      - False -> false   (bare)
      - True  -> true    (bare)
      - All other values are double-quoted, with internal quotes escaped.
    """
    if v is None:
        return 'false'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    s = str(v)
    s = s.replace('"', '\\"')
    return f'"{s}"'


def _emit_kv_block(pairs: List[Tuple[str, Optional[str]]], base_indent: int) -> str:
    """
    Emit a YAML list item with one key per line.
    Example (base_indent=4):
        "    - rtitle: \"...\"\n"
        "      rlink: \"...\"\n"
        "      points: \"100\"\n"
    The first line starts with '- ' and each subsequent line aligns under it.
    Only include pairs whose value is not None.
    """
    pad0 = " " * base_indent
    pad1 = " " * (base_indent + 2)  # align under '- '
    lines = []
    first = True
    for k, v in pairs:
        if v is None:
            continue
        if first:
            lines.append(f"{pad0}- {k}: {v}")
            first = False
        else:
            lines.append(f"{pad1}{k}: {v}")
    if not lines:
        lines.append(f"{pad0}- {{}}")
    return "\n".join(lines)


def _dump_schedule_one_day(day: dict, indent_spaces: int = 2) -> str:
    """Custom emitter for a single day under schedule: renders readings/deliverables entries multi-line, one key per line."""
    pad = " " * indent_spaces
    pad2 = " " * (indent_spaces * 2)

    out = []
    out.append(f"{pad}- week: {_quote_scalar(day.get('week', ''))}")
    out.append(f"{pad}  date: {_quote_scalar(day.get('slot', ''))}")

    title = day.get("lectures", [])[:1]
    if title:
        t = title[0].get("title", "")
        if t:
            out.append(f"{pad}  title: {_quote_scalar(t)}")
        lnk = title[0].get("link")
        if lnk:
            out.append(f"{pad}  link: {_quote_scalar(lnk)}")

    # readings
    rlist = day.get("readings") or []
    if rlist:
        out.append(f"{pad}  readings:")
        for r in rlist:
            rtitle = _quote_scalar(r.get("title", ""))
            rlink = r.get("link", None)
            # pass False (boolean), not "false" (string)
            rlink_q = _quote_scalar(rlink if rlink else False)
            # carry extras
            extra_pairs = []
            for ek, ev in (r.get("_extra") or {}).items():
                extra_pairs.append((ek, _quote_scalar(ev)))
            pairs = [("rtitle", rtitle), ("rlink", rlink_q)] + extra_pairs
            out.append(_emit_kv_block(pairs, base_indent=indent_spaces * 2))

    # deliverables
    dlist = day.get("deliverables") or []
    if dlist:
        out.append(f"{pad}  deliverables:")
        for d in dlist:
            dtitle = _quote_scalar(d.get("title", ""))
            dlink = d.get("link", None)
            # pass False (boolean), not "false" (string)
            dlink_q = _quote_scalar(dlink if dlink else False)
            points = d.get("_extra", {}).get("points", d.get("points"))
            subs = d.get("_extra", {}).get("submission_types", d.get("submission_types"))
            rubric = d.get("_extra", {}).get("rubricpath", d.get("rubricpath"))

            pairs = [("dtitle", dtitle), ("dlink", dlink_q)]
            if points is not None:
                pairs.append(("points", _quote_scalar(points)))
            if subs is not None:
                pairs.append(("submission_types", _quote_scalar(subs)))
            if rubric is not None:
                pairs.append(("rubricpath", _quote_scalar(rubric)))

            used = {"points", "submission_types", "rubricpath"}
            for ek, ev in (d.get("_extra") or {}).items():
                if ek not in used:
                    pairs.append((ek, _quote_scalar(ev)))

            out.append(_emit_kv_block(pairs, base_indent=indent_spaces * 2))

    return "\n".join(out)


def write_markdown_with_front_matter(path: str, fm: dict, body: str):
    """
    Write Markdown with YAML front matter using our in-place schedule emitter.
    Guarantees:
      - No top-level keys other than 'schedule' are modified or introduced.
      - The ordering of top-level keys, including 'schedule', is preserved.
    """
    try:
        # Shallow copy so we can safely remove ephemeral keys before writing
        fm_to_write = dict(fm)
        fm_to_write.pop("_schedule_is_internal_shape__", None)

        # Optional regression guard: uncomment to catch unexpected key changes.
        # original_keys = [k for k in fm.keys() if k != "_schedule_is_internal_shape__"]
        # to_write_keys = list(fm_to_write.keys())
        # if set(to_write_keys) != set(original_keys):
        #     raise ValueError("Top-level key set changed outside of 'schedule'")

        with open(path, "w", encoding="utf-8") as f:
            f.write("---\n")
            if isinstance(fm_to_write.get("schedule"), list) and all(
                (
                    isinstance(d, dict)
                    and "lectures" in d
                    and "readings" in d
                    and "deliverables" in d
                )
                for d in fm_to_write.get("schedule", [])
            ):
                f.write(dump_front_matter_with_multiline_schedule(fm_to_write))
            else:
                # Fallback: standard YAML emission (still preserves order with sort_keys=False).
                yaml.safe_dump(fm_to_write, f, sort_keys=False, allow_unicode=True)
            f.write("---\n")
            f.write(body if body is not None else "")
    except Exception as e:
        print(f"[write_markdown_with_front_matter] {e}")
        traceback.print_exc()
        raise


# =========================================================
# Data model helpers (schema adapter)
# =========================================================

def serialize_schedule_to_front_matter(days: List[dict], fm: dict) -> dict:
    """
    Write internal days back to fm['schedule'] in our internal shape.
    IMPORTANT: Do not add or modify any top-level keys other than 'schedule'.
    """
    try:
        out_sched = []
        for d in days:
            week = d.get("week", "")
            slot = d.get("slot", "")

            lectures = d.get("lectures", []) or []
            if lectures:
                lec_title = lectures[0].get("title", "")
                lec_link = lectures[0].get("link", None)
            else:
                lec_title, lec_link = "", None

            day_out = {
                "week": week,
                "slot": slot,
                "lectures": lectures,
                "readings": d.get("readings", []),
                "deliverables": d.get("deliverables", []),
            }
            if lec_title:
                day_out["title"] = lec_title
            if lec_link:
                day_out["link"] = lec_link

            out_sched.append(day_out)

        # Copy fm verbatim and replace ONLY the 'schedule' key.
        new_fm = dict(fm)
        new_fm["schedule"] = out_sched
        return new_fm
    except Exception as e:
        print(f"[serialize_schedule_to_front_matter] {e}")
        traceback.print_exc()
        raise

def normalize_schedule_from_front_matter(fm: dict) -> List[dict]:
    """
    Convert front matter schedule into internal list of day dicts:
      day = {
        "week": any, "slot": any,
        "readings": [{"title","link", "_extra", "_kind"="reading"}, ...],
        "deliverables": [{"title","link","_extra","_kind"="deliverable"}],
        "lectures": [{"title","link","_extra","_kind"="lecture"}]  # usually 0..1
      }
    Preserves extra fields inside "_extra".
    """
    try:
        raw = fm.get("schedule", []) or []
        days = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            week = entry.get("week", "")
            slot = entry.get("date", "")

            lecture_title = (entry.get("title") or "").strip()
            lecture_link = entry.get("link", None)
            if isinstance(lecture_link, bool):
                lecture_link = None

            lectures = []
            if lecture_title:
                lectures.append({"title": lecture_title, "link": lecture_link, "_extra": {}, "_kind": "lecture"})

            readings = []
            for r in (entry.get("readings") or []):
                if not isinstance(r, dict):
                    r = {"rtitle": str(r)}
                title = str(r.get("rtitle", r.get("title", ""))).strip()
                link = r.get("rlink", r.get("link", None))
                link = (None if (link is False or link in (None, "")) else str(link).strip())
                extra = {k: v for k, v in r.items() if k not in ("rtitle", "rlink", "title", "link")}
                readings.append({"title": title, "link": link, "_extra": extra, "_kind": "reading"})

            deliverables = []
            for d in (entry.get("deliverables") or []):
                if not isinstance(d, dict):
                    d = {"dtitle": str(d)}
                title = str(d.get("dtitle", d.get("title", ""))).strip()
                link = d.get("dlink", d.get("link", None))
                link = (None if (link is False or link in (None, "")) else str(link).strip())
                extra = {k: v for k, v in d.items() if k not in ("dtitle", "dlink", "title", "link")}
                deliverables.append({"title": title, "link": link, "_extra": extra, "_kind": "deliverable"})

            days.append({
                "week": week,
                "slot": slot,
                "readings": readings,
                "deliverables": deliverables,
                "lectures": lectures,
            })
        return days
    except Exception as e:
        print(f"[normalize_schedule_from_front_matter] {e}")
        traceback.print_exc()
        raise


def dump_front_matter_with_multiline_schedule(fm: dict) -> str:
    """
    Return a YAML string with keys emitted in the original order of `fm`.
    The 'schedule' key is rendered with a custom multi-line emitter in-place,
    preserving its original position. Ephemeral helper keys are not emitted.
    """
    # Add any top-level ephemeral keys to skip here:
    skip_keys = {"_schedule_is_internal_shape__"}

    lines = []
    for key, value in fm.items():
        if key in skip_keys:
            continue

        if key == "schedule":
            # Custom, multi-line schedule emission at the original position.
            lines.append("schedule:")
            schedule = value or []
            for day in schedule:
                lines.append(_dump_schedule_one_day(day, indent_spaces=2))
        else:
            # Emit this single key as YAML while preserving nested order.
            # safe_dump on a one-key dict yields "key: value\n" without '---'.
            snippet = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True)
            lines.append(snippet.rstrip("\n"))

    return "\n".join(lines) + "\n"


# =========================================================
# Main Application — Treeview + basic editing
# =========================================================

class ScheduleBoard(tk.Tk):
    CATS = ("readings", "deliverables", "lectures")
    CAT_LABEL = {"readings": "Readings", "deliverables": "Deliverables", "lectures": "Lectures"}

    def __init__(self):
        super().__init__()
        self.title("Schedule Board (Tree)")
        self.geometry("900x720")

        self.days: List[dict] = []
        self.current_path: Optional[str] = None
        self._opened_as_front_matter = False
        self._front_matter: Optional[dict] = None
        self._md_body: Optional[str] = None

        self._node_meta: Dict[str, Tuple] = {}

        self._drag_toplevel = None
        self._drag_source = None
        self._drag_text = ""

        self._make_menu()
        self._make_tree()

        self.after(50, self.open_yaml_or_markdown_dialog)

    # ---------- UI ----------

    def _make_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open…", command=self.open_yaml_or_markdown_dialog, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As…", command=self.save_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)

        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

        self.bind_all("<Control-o>", lambda e: self.open_yaml_or_markdown_dialog())
        self.bind_all("<Control-s>", lambda e: self.save())
        self.bind_all("<Control-Shift-S>", lambda e: self.save_as())

    def _make_tree(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        try:
            self.tree.tag_configure("conflict", foreground="red")
        except Exception:
            pass

        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_context_menu)
        self.tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release, add="+")

    def open_yaml_or_markdown_dialog(self):
        try:
            path = filedialog.askopenfilename(
                filetypes=[
                    ("Markdown or YAML", "*.md *.markdown *.mdown *.mkd *.yaml *.yml"),
                    ("All files", "*.*"),
                ]
            )
            if not path:
                return

            self.current_path = path
            self._opened_as_front_matter = False
            self._front_matter, self._md_body = None, None

            fm, body = read_markdown_with_front_matter(path)
            if fm is not None:
                self._opened_as_front_matter = True
                self._front_matter = fm
                self._md_body = body
                self.days = normalize_schedule_from_front_matter(fm)
            else:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if "schedule" not in data:
                    raise ValueError("YAML file does not contain a top-level 'schedule' key.")
                self._front_matter = data
                self._md_body = None
                self.days = normalize_schedule_from_front_matter(data)

            try:
                self.days.sort(key=lambda d: (int(d.get("week", 0)), int(d.get("slot", 0))))
            except Exception:
                pass

            self._rebuild_tree()
            self._status(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            print(f"[open_yaml_or_markdown_dialog] {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def save(self):
        try:
            if not self.current_path:
                return self.save_as()
            if self._front_matter is None:
                raise RuntimeError("Nothing loaded to save.")

            new_fm = serialize_schedule_to_front_matter(self.days, self._front_matter)

            if self._opened_as_front_matter:
                write_markdown_with_front_matter(self.current_path, new_fm, self._md_body or "")
            else:
                with open(self.current_path, "w", encoding="utf-8") as f:
                    rendered = dump_front_matter_with_multiline_schedule(new_fm)
                    f.write(rendered)
            self._status(f"Saved: {os.path.basename(self.current_path)}")
        except Exception as e:
            print(f"[save] {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def save_as(self):
        try:
            path = filedialog.asksaveasfilename(
                defaultextension=(".md" if self._opened_as_front_matter else ".yaml"),
                filetypes=[
                    ("Markdown", "*.md"),
                    ("YAML", "*.yaml *.yml"),
                    ("All files", "*.*"),
                ]
            )
            if not path:
                return
            self.current_path = path
            self.save()
        except Exception as e:
            print(f"[save_as] {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to save as:\n{e}")

    # ---------- Tree building ----------

    def _rebuild_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._node_meta.clear()

        try:
            self._recompute_conflicts()
        except Exception:
            pass

        for day_idx, day in enumerate(self.days):
            wk = str(day.get("week", ""))
            sl = str(day.get("slot", ""))
            day_label = f"Week {wk} — Slot {sl}"
            day_id = self.tree.insert("", "end", text=day_label, open=True)
            self._node_meta[day_id] = ("day", day_idx)

            for cat in self.CATS:
                cat_label = self.CAT_LABEL[cat]
                cat_id = self.tree.insert(day_id, "end", text=cat_label, open=True)
                self._node_meta[cat_id] = ("cat", (day_idx, cat))

                items = day.get(cat, [])
                for item_idx, it in enumerate(items):
                    text = self._display_text(it)
                    tags = self._item_tags_for(day_idx, cat, item_idx)
                    itm_id = self.tree.insert(cat_id, "end", text=text, open=False, tags=tags)
                    self._node_meta[itm_id] = ("item", (day_idx, cat, item_idx))

    def _display_text(self, item: dict) -> str:
        base = item.get("title", "").strip()
        return base + (" [link]" if item.get("link") else "")

    def _status(self, msg: str):
        self.title(f"Schedule Board (Tree) — {msg}")

    # ---------- Interaction: open link / context menu ----------

    def _on_double_click(self, event):
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                return
            day_idx, cat, item_idx = meta[1]
            link = self.days[day_idx][cat][item_idx].get("link")
            if link:
                webbrowser.open(link)
        except Exception as e:
            print(f"[on_double_click] {e}")
            traceback.print_exc()

    def _on_context_menu(self, event):
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            self.tree.selection_set(iid)
            meta = self._node_meta.get(iid)
            if not meta:
                return

            menu = tk.Menu(self, tearoff=False)
            if meta[0] == "item":
                menu.add_command(label="Edit title…", command=lambda: self._edit_title(iid))
                menu.add_command(label="Edit link…", command=lambda: self._edit_link(iid))
                menu.add_separator()
                menu.add_command(label="Delete", command=lambda: self._delete_item(iid))
            elif meta[0] == "cat":
                menu.add_command(label="Add new…", command=lambda: self._add_item_under_category(iid))
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            print(f"[on_context_menu] {e}")
            traceback.print_exc()

    def _prompt(self, title: str, label: str, initial: str = "") -> Optional[str]:
        top = tk.Toplevel(self)
        top.title(title)
        top.transient(self)
        top.grab_set()

        ttk.Label(top, text=label).pack(padx=12, pady=(12, 4), anchor="w")
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(top, textvariable=var, width=60)
        entry.pack(padx=12, pady=4)
        entry.focus_set()
        entry.icursor("end")

        out = {"value": None}

        btns = ttk.Frame(top)
        btns.pack(padx=12, pady=(8, 12), fill="x")

        def ok():
            out["value"] = var.get()
            top.destroy()

        def cancel():
            out["value"] = None
            top.destroy()

        ttk.Button(btns, text="OK", command=ok).pack(side="right", padx=4)
        ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=4)

        self.wait_window(top)
        return out["value"]

    def _edit_title(self, iid: str):
        try:
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                return
            day_idx, cat, item_idx = meta[1]
            item = self.days[day_idx][cat][item_idx]
            new = self._prompt("Edit title", "Title:", item.get("title", ""))
            if new is None:
                return
            item["title"] = new.strip()
            self._refresh_category_branch(day_idx, cat)
        except Exception as e:
            print(f"[edit_title] {e}")
            traceback.print_exc()

    def _edit_link(self, iid: str):
        try:
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                return
            day_idx, cat, item_idx = meta[1]
            item = self.days[day_idx][cat][item_idx]
            current = item.get("link", "") or ""
            new = self._prompt("Edit link", "URL (optional):", current)
            if new is None:
                return
            new = new.strip()
            if new == "":
                item.pop("link", None)
            else:
                item["link"] = new
            self.tree.item(iid, text=self._display_text(item))
        except Exception as e:
            print(f"[edit_link] {e}")
            traceback.print_exc()

    def _delete_item(self, iid: str):
        try:
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                return
            if not messagebox.askyesno("Delete", "Remove this item?"):
                return
            day_idx, cat, item_idx = meta[1]
            self.days[day_idx][cat].pop(item_idx)
            parent = self.tree.parent(iid)
            self.tree.delete(iid)
            self._refresh_category_branch(day_idx, cat)
        except Exception as e:
            print(f"[delete_item] {e}")
            traceback.print_exc()

    def _add_item_under_category(self, cat_iid: str):
        try:
            meta = self._node_meta.get(cat_iid)
            if not meta or meta[0] != "cat":
                return
            (day_idx, cat) = meta[1]
            title = self._prompt("Add item", "Title:", "")
            if title is None or title.strip() == "":
                return
            new_item = {"title": title.strip(), "_extra": {}, "_kind": cat[:-1] if cat.endswith('s') else cat}
            self.days[day_idx][cat].append(new_item)
            self._refresh_category_branch(day_idx, cat)
        except Exception as e:
            print(f"[add_item_under_category] {e}")
            traceback.print_exc()

    def _reindex_children(self, cat_iid: str, day_idx: int, cat: str):
        try:
            for idx, child in enumerate(self.tree.get_children(cat_iid)):
                self._node_meta[child] = ("item", (day_idx, cat, idx))
        except Exception as e:
            print(f"[reindex_children] {e}")
            traceback.print_exc()

    # ---------- Drag & Drop ----------

    def _on_drag_start(self, event):
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                return
            self._drag_source = meta
            self._drag_text = self.tree.item(iid, "text")

            if self._drag_toplevel is None:
                self._drag_toplevel = tk.Toplevel(self)
                self._drag_toplevel.overrideredirect(True)
                self._drag_toplevel.attributes("-topmost", True)
                lbl = tk.Label(self._drag_toplevel, text=self._drag_text, bg="#ffffe0", relief="solid", bd=1)
                lbl.pack(ipadx=4, ipady=2)
            self._move_drag_label(event)
        except Exception as e:
            print(f"[dnd._on_drag_start] {e}")
            traceback.print_exc()

    def _on_drag_motion(self, event):
        if self._drag_toplevel is not None:
            self._move_drag_label(event)

    def _move_drag_label(self, event):
        try:
            x = self.winfo_pointerx() + 12
            y = self.winfo_pointery() + 12
            self._drag_toplevel.geometry(f"+{x}+{y}")
        except Exception as e:
            print(f"[dnd._move_drag_label] {e}")
            traceback.print_exc()

    def _on_drag_release(self, event):
        try:
            if not self._drag_source:
                return

            target_iid = self.tree.identify_row(event.y)
            if not target_iid:
                self._clear_drag()
                return

            tmeta = self._node_meta.get(target_iid)
            smeta = self._drag_source
            if not tmeta:
                self._clear_drag()
                return

            if tmeta[0] == "item":
                tgt_day_idx, tgt_cat, tgt_item_idx = tmeta[1]
            elif tmeta[0] == "cat":
                tgt_day_idx, tgt_cat = tmeta[1]
                tgt_item_idx = None
            else:
                day_idx = tmeta[1]
                tgt_day_idx, tgt_cat, tgt_item_idx = day_idx, None, None

            src_day_idx, src_cat, src_item_idx = smeta[1]

            if tmeta[0] == "day":
                tgt_cat = src_cat
                cat_iid = self._find_category_iid(tmeta, src_cat)
                if not cat_iid:
                    self._clear_drag()
                    return
                target_iid = cat_iid
                tgt_item_idx = None

            if tgt_cat != src_cat:
                self._clear_drag()
                return

            item = self.days[src_day_idx][src_cat].pop(src_item_idx)

            if tgt_item_idx is None:
                insert_pos = len(self.days[tgt_day_idx][tgt_cat])
            else:
                bbox = self.tree.bbox(target_iid)
                insert_pos = tgt_item_idx
                if bbox:
                    row_mid = bbox[1] + bbox[3] / 2
                    if event.y > row_mid:
                        insert_pos = tgt_item_idx + 1

                if src_day_idx == tgt_day_idx and src_cat == tgt_cat and src_item_idx < insert_pos:
                    insert_pos -= 1

            self.days[tgt_day_idx][tgt_cat].insert(insert_pos, item)

            self._refresh_category_branch(src_day_idx, src_cat)
            if (tgt_day_idx, tgt_cat) != (src_day_idx, src_cat):
                self._refresh_category_branch(tgt_day_idx, tgt_cat)
        except Exception as e:
            print(f"[dnd._on_drag_release] {e}")
            traceback.print_exc()
        finally:
            self._clear_drag()

    def _clear_drag(self):
        self._drag_source = None
        self._drag_text = ""
        if self._drag_toplevel is not None:
            self._drag_toplevel.destroy()
            self._drag_toplevel = None

    def _find_category_iid(self, day_meta: Tuple, cat: str) -> Optional[str]:
        try:
            if day_meta[0] != "day":
                return None
            day_idx = day_meta[1]
            for child in self.tree.get_children(""):
                m = self._node_meta.get(child)
                if m and m[0] == "day" and m[1] == day_idx:
                    for cc in self.tree.get_children(child):
                        m2 = self._node_meta.get(cc)
                        if m2 and m2[0] == "cat" and m2[1] == (day_idx, cat):
                            return cc
            return None
        except Exception as e:
            print(f"[find_category_iid] {e}")
            traceback.print_exc()
            return None

    def _refresh_category_branch(self, day_idx: int, cat: str):
        try:
            try:
                self._recompute_conflicts()
            except Exception:
                pass

            cat_iid = None
            for d_iid in self.tree.get_children(""):
                m = self._node_meta.get(d_iid)
                if m and m[0] == "day" and m[1] == day_idx:
                    for c_iid in self.tree.get_children(d_iid):
                        m2 = self._node_meta.get(c_iid)
                        if m2 and m2[0] == "cat" and m2[1] == (day_idx, cat):
                            cat_iid = c_iid
                            break
            if not cat_iid:
                return

            for child in self.tree.get_children(cat_iid):
                self._node_meta.pop(child, None)
                self.tree.delete(child)

            items = self.days[day_idx][cat]
            for idx, it in enumerate(items):
                text = self._display_text(it)
                tags = self._item_tags_for(day_idx, cat, idx)
                iid = self.tree.insert(cat_iid, "end", text=text, tags=tags)
                self._node_meta[iid] = ("item", (day_idx, cat, idx))
        except Exception as e:
            print(f"[refresh_category_branch] {e}")
            traceback.print_exc()

    def _date_key(self, day_idx: int) -> tuple:
        d = self.days[day_idx]
        try:
            w = int(d.get("week", 0))
        except Exception:
            w = 0
        try:
            s = int(d.get("slot", 0))
        except Exception:
            s = 0
        return (w, s)

    def _normalize_deliverable_base(self, title: str):
        t = (title or "").strip()
        if t.endswith("[link]"):
            t = t[:-6].rstrip()
        low = t.lower()
        for suff in ("handed out", "due"):
            if low.endswith(suff):
                base = t[: -len(suff)].rstrip(" -–:•\u2013")
                return base.strip(), "Handed Out" if suff == "handed out" else "Due"
        return t, None

    def _recompute_conflicts(self):
        self._conflict_items = set()

        # Lecture collisions (unchanged): more than one lecture on a day
        for di, day in enumerate(self.days):
            lecs = (day.get("lectures") or [])
            if len(lecs) > 1:
                for li in range(1, len(lecs)):
                    self._conflict_items.add((di, "lectures", li))

        # Deliverable ordering/same-day checks
        # Build an index by deliverable "base" name (title without "Handed Out"/"Due")
        index = {}
        for di, day in enumerate(self.days):
            for ii, it in enumerate((day.get("deliverables") or [])):
                base, suff = self._normalize_deliverable_base(it.get("title", ""))
                if base not in index:
                    index[base] = {"Handed Out": [], "Due": []}
                if suff in ("Handed Out", "Due"):
                    index[base][suff].append((di, ii, self._date_key(di)))  # store (day_idx, item_idx, date_key)

        for base, parts in index.items():
            handed = parts.get("Handed Out", [])
            due = parts.get("Due", [])

            if not handed or not due:
                # If we don't have both parts, there's no ordering constraint to enforce.
                continue

            # 1) Flag any "Due" that occurs before the earliest "Handed Out"
            min_handed_date = min(dk for (_di, _ii, dk) in handed)
            for (di_due, ii_due, dk_due) in due:
                if dk_due < min_handed_date:
                    self._conflict_items.add((di_due, "deliverables", ii_due))

            # 2) Same-day conflicts: mark BOTH "Handed Out" and "Due" that share the same date
            handed_by_date = {}
            for (di_h, ii_h, dk_h) in handed:
                handed_by_date.setdefault(dk_h, []).append((di_h, ii_h))

            for (di_due, ii_due, dk_due) in due:
                if dk_due in handed_by_date:
                    # Mark the due and all handouts on that same day as conflicts
                    self._conflict_items.add((di_due, "deliverables", ii_due))
                    for (di_h, ii_h) in handed_by_date[dk_due]:
                        self._conflict_items.add((di_h, "deliverables", ii_h))

    def _item_tags_for(self, day_idx: int, cat: str, item_idx: int):
        return ("conflict",) if (day_idx, cat, item_idx) in getattr(self, "_conflict_items", set()) else ()


def main():
    try:
        app = ScheduleBoard()
        app.mainloop()
    except Exception as e:
        print(f"[main] {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
