# code-viz runner "qr" (runners/qr/Dockerfile).
# segno (pure Python) for code-viz qr: writes SVG and PNG QR codes of student links. No network.
#
# How it is used: code-viz builds this image as code-viz-qr:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN pip install --no-cache-dir segno==1.6.1
WORKDIR /out
