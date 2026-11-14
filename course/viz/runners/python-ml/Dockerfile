# code-viz runner "python-ml" (runners/python-ml/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 7 Figures, 15 Where things run and safety.
# The python runner plus PyTorch and torchvision, CPU-only wheels (no CUDA), for examples labeled
# runner=python-ml (label suggests it for blocks that import torch or torchvision, with viz=plain and
# timeout=120). Only output and figures are recorded: stepping through tensor code is not useful and
# would be slow. TensorFlow is not installed (too large for what the course examples need); its
# examples are not labeled.
#
# How it is used: exactly like the python runner (built as code-viz-python-ml:<hash of this file>,
# run with --network none, --cpus 1, --memory 1g, removed afterwards unless --keep-images).
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.1.3 pandas==2.2.3 scikit-learn==1.5.2 matplotlib==3.9.2 scipy==1.14.1 \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
