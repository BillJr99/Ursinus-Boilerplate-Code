# code-viz runner "python" (runners/python/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 15 Where things run and safety.
# Python 3.12 with numpy, pandas, scikit-learn, matplotlib (Agg) and requests, for viz=env (pytrace.py),
# viz=lambda (lambdatrace.py) and plain Python examples.
#
# How it is used: code-viz builds this image as code-viz-python:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.1.3 pandas==2.2.3 scikit-learn==1.5.2 matplotlib==3.9.2 requests==2.32.3
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
