import base64, mimetypes, pathlib
import sys

def as_data_uri(path: str, write_txt: bool = True) -> str:
    p = pathlib.Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    uri = f"data:{mime};base64,{data}"
    if write_txt:
        out_path = p.parent / (p.name + ".txt")   # exactly “path + .txt”
        out_path.write_text(uri, encoding="utf-8")
    return uri

uri = as_data_uri(sys.argv[1])