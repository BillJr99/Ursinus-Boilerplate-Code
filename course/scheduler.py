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


def write_markdown_with_front_matter(path: str, fm: dict, body: str):
    """Write back Markdown with YAML front matter and the given body."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\n")
            yaml.safe_dump(fm, f, sort_keys=False, allow_unicode=True)
            f.write("---\n")
            f.write(body if body is not None else "")
    except Exception as e:
        print(f"[write_markdown_with_front_matter] {e}")
        traceback.print_exc()
        raise


# =========================================================
# Data model helpers (schema adapter)
# =========================================================

def normalize_schedule_from_front_matter(fm: dict) -> List[dict]:
    """
    Convert front matter schedule into internal list of day dicts:
      day = {
        "week": any, "slot": any,
        "readings": [{"title","link", "_extra", "_kind"="reading"}, ...],
        "deliverables": [... "_kind"="deliverable"],
        "lectures": [... "_kind"="lecture"]   # usually 0..1
      }
    We preserve extra fields for readings/deliverables inside "_extra".
    """
    try:
        raw = fm.get("schedule", []) or []
        days = []

        for entry in raw:
            if not isinstance(entry, dict):
                continue
            week = entry.get("week", "")
            slot = entry.get("date", "")

            # Day-level lecture comes from title/link on the entry
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


def serialize_schedule_to_front_matter(days: List[dict], fm: dict) -> dict:
    """
    Write internal days back to fm['schedule'], preserving the original schema:
      - day.title/day.link from first lecture (if any)
      - readings: rtitle/rlink (+ extras)
      - deliverables: dtitle/dlink (+ extras)
    """
    try:
        out_sched = []
        for d in days:
            week = d.get("week", "")
            slot = d.get("slot", "")

            # title/link from first lecture
            lectures = d.get("lectures", []) or []
            if lectures:
                lec_title = lectures[0].get("title", "")
                lec_link = lectures[0].get("link", None)
            else:
                lec_title, lec_link = "", None

            readings_out = []
            for it in d.get("readings", []):
                rv = {"rtitle": it.get("title", "")}
                link = it.get("link", None)
                rv["rlink"] = (False if not link else link)
                extra = it.get("_extra", {}) or {}
                rv.update(extra)
                readings_out.append(rv)

            deliverables_out = []
            for it in d.get("deliverables", []):
                dv = {"dtitle": it.get("title", "")}
                link = it.get("link", None)
                dv["dlink"] = (False if not link else link)
                extra = it.get("_extra", {}) or {}
                dv.update(extra)
                deliverables_out.append(dv)

            day_out = {"week": week, "date": slot}
            if lec_title:
                day_out["title"] = lec_title
            if lec_link:
                day_out["link"] = lec_link
            if readings_out:
                day_out["readings"] = readings_out
            if deliverables_out:
                day_out["deliverables"] = deliverables_out

            out_sched.append(day_out)

        new_fm = dict(fm)
        new_fm["schedule"] = out_sched
        return new_fm
    except Exception as e:
        print(f"[serialize_schedule_to_front_matter] {e}")
        traceback.print_exc()
        raise


# =========================================================
# Main Application — Treeview with Drag & Drop
# =========================================================

class ScheduleBoard(tk.Tk):
    CATS = ("readings", "deliverables", "lectures")
    CAT_LABEL = {"readings": "Readings", "deliverables": "Deliverables", "lectures": "Lectures"}

    def __init__(self):
        super().__init__()
        self.title("Schedule Board (Tree)")
        self.geometry("900x720")

        # Model
        self.days: List[dict] = []
        self.current_path: Optional[str] = None
        self._opened_as_front_matter = False
        self._front_matter: Optional[dict] = None
        self._md_body: Optional[str] = None

        # Tree bookkeeping: map Tree item id -> (type, payload)
        # type ∈ {"day","cat","item"}
        #   - day payload: day_index
        #   - cat payload: (day_index, category)
        #   - item payload: (day_index, category, item_index)
        self._node_meta: Dict[str, Tuple] = {}

        # Drag state
        self._drag_toplevel = None
        self._drag_source = None  # ("item", (src_day_idx, src_cat, src_item_idx))
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
        self.bind_all("<Control-S>", lambda e: self.save_as())


    def _make_tree(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        # conflict tag
        try:
            self.tree.tag_configure("conflict", foreground="red")
        except Exception:
            pass

        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")

        # events
        self.tree.bind("<Double-Button-1>", self._on_double_click)
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
                    yaml.safe_dump(new_fm, f, sort_keys=False, allow_unicode=True)
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

        # recompute conflicts
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
        return base + ("  [link]" if item.get("link") else "")

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
            # refresh to update conflict tags
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
            # refresh to update conflict tags
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
            # refresh to update conflict tags
            self._refresh_category_branch(day_idx, cat)
        except Exception as e:
            print(f"[add_item_under_category] {e}")
            traceback.print_exc()    
            
    def _reindex_children(self, cat_iid: str, day_idx: int, cat: str):
        """Refresh metadata indices under a category node after mutation."""
        try:
            for idx, child in enumerate(self.tree.get_children(cat_iid)):
                # only leaf items here
                self._node_meta[child] = ("item", (day_idx, cat, idx))
        except Exception as e:
            print(f"[reindex_children] {e}")
            traceback.print_exc()

    # ---------- Drag & Drop over Treeview ----------
    def _on_drag_start(self, event):
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            meta = self._node_meta.get(iid)
            if not meta or meta[0] != "item":
                # only drag leaf items
                return
            self._drag_source = meta  # ("item", (day_idx, cat, item_idx))
            self._drag_text = self.tree.item(iid, "text")

            # floating label
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
            smeta = self._drag_source  # ("item", (src_day_idx, src_cat, src_item_idx))
            if not tmeta:
                self._clear_drag()
                return

            # Allowed moves: item -> (same-category item) or item -> category node (same category)
            if tmeta[0] == "item":
                tgt_day_idx, tgt_cat, tgt_item_idx = tmeta[1]
            elif tmeta[0] == "cat":
                tgt_day_idx, tgt_cat = tmeta[1]
                tgt_item_idx = None
            else:
                # dropped on a day node — place into first child category of same type if possible
                day_idx = tmeta[1]
                tgt_day_idx, tgt_cat, tgt_item_idx = day_idx, None, None

            src_day_idx, src_cat, src_item_idx = smeta[1]

            # Derive target category if dropped on a day node: no cross-category moves per your rule
            if tmeta[0] == "day":
                # We need a category node of same type under that day — ask user which category is intended?
                # Instead, we restrict to same category: reuse src_cat.
                tgt_cat = src_cat
                # find the category node under day
                cat_iid = self._find_category_iid(tmeta, src_cat)
                if not cat_iid:
                    self._clear_drag()
                    return
                target_iid = cat_iid
                tgt_item_idx = None

            # Only same-category moves:
            if tgt_cat != src_cat:
                self._clear_drag()
                return

            # Move in model
            item = self.days[src_day_idx][src_cat].pop(src_item_idx)

            if tgt_item_idx is None:
                # append to end of target category list
                insert_pos = len(self.days[tgt_day_idx][tgt_cat])
            else:
                # decide insert before/after based on pointer y vs target row bbox center
                bbox = self.tree.bbox(target_iid)
                insert_pos = tgt_item_idx
                if bbox:
                    row_mid = bbox[1] + bbox[3] / 2
                    if event.y > row_mid:
                        insert_pos = tgt_item_idx + 1
                # if source and target are same list and removing earlier element shifts indices:
                if src_day_idx == tgt_day_idx and src_cat == tgt_cat and src_item_idx < insert_pos:
                    insert_pos -= 1

            self.days[tgt_day_idx][tgt_cat].insert(insert_pos, item)

            # Rebuild only the two affected category branches
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
        """Find the Tree iid of a category under a given day meta ('day', day_idx)."""
        try:
            if day_meta[0] != "day":
                return None
            day_idx = day_meta[1]
            # find the specific day node by matching meta
            for child in self.tree.get_children(""):
                m = self._node_meta.get(child)
                if m and m[0] == "day" and m[1] == day_idx:
                    # scan its children for requested category
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
            # recompute conflicts
            try:
                self._recompute_conflicts()
            except Exception:
                pass

            # find the category node
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

            # clear items
            for child in self.tree.get_children(cat_iid):
                self._node_meta.pop(child, None)
                self.tree.delete(child)

            # repopulate with tags
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

        # Lecture collisions: mark any lecture after the first on the same day
        for di, day in enumerate(self.days):
            lecs = (day.get("lectures") or [])
            if len(lecs) > 1:
                for li in range(1, len(lecs)):
                    self._conflict_items.add((di, "lectures", li))

        # Deliverable mis-order: Due before Handed Out
        index = {}
        for di, day in enumerate(self.days):
            for ii, it in enumerate((day.get("deliverables") or [])):
                base, suff = self._normalize_deliverable_base(it.get("title", ""))
                if base not in index:
                    index[base] = {"Handed Out": [], "Due": []}
                if suff in ("Handed Out", "Due"):
                    index[base][suff].append((di, ii))

        for base, parts in index.items():
            handed = parts.get("Handed Out", [])
            due = parts.get("Due", [])
            if not handed or not due:
                continue
            min_handed_date = None
            for (di, _ii) in handed:
                dk = self._date_key(di)
                if (min_handed_date is None) or (dk < min_handed_date):
                    min_handed_date = dk
            for (di_due, ii_due) in due:
                if self._date_key(di_due) < min_handed_date:
                    self._conflict_items.add((di_due, "deliverables", ii_due))
                    for (di_h, ii_h) in handed:
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
