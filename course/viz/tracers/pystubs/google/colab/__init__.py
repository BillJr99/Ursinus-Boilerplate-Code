"""code-viz stand-in for google.colab: drive.mount() does nothing (no Google Drive in a container),
files.upload() and files.download() raise, so a cell that needs them fails and is not labeled.
Full manual: the header of code-viz, section 4 (Notebooks)."""


class _Drive:
    def mount(self, *a, **k):
        print("(code-viz: Google Drive is not available here; drive.mount() did nothing)")

    def flush_and_unmount(self, *a, **k):
        pass


class _Files:
    def upload(self, *a, **k):
        raise RuntimeError("google.colab.files.upload is not available in code-viz")

    def download(self, *a, **k):
        raise RuntimeError("google.colab.files.download is not available in code-viz")


drive = _Drive()
files = _Files()
